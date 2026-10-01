"""Exercise the real TCP client without requiring Home Assistant."""

import asyncio
import importlib.util
import sys
import types
import unittest
from contextlib import suppress
from pathlib import Path
from unittest.mock import patch

# Load the standalone client without executing the HA integration entry point.
ROOT = Path(__file__).resolve().parents[2] / "custom_components" / "intesisbox"
PACKAGE = "intesisbox_protocol_tests"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package
spec = importlib.util.spec_from_file_location(
    f"{PACKAGE}.intesisbox", ROOT / "intesisbox.py"
)
client = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = client
spec.loader.exec_module(client)

IDENTITY = "ID:IS-IR-WMP-1,001DC9A2C911,192.0.2.1,ASCII,v1,-44\r\n"
LIMITS = (
    "LIMITS:SETPTEMP,[160,300]\r\nLIMITS:FANSP,[AUTO,1,2,3,4]\r\n"
    "LIMITS:MODE,[AUTO,HEAT,COOL,FAN,DRY]\r\n"
    "LIMITS:VANEUD,[AUTO,SWING]\r\nLIMITS:VANELR,[]\r\n"
)
STATE = "CHN,1:ONOFF,ON\r\nCHN,1:MODE,COOL\r\nCHN,1:AMBTEMP,215\r\nCHN,1:SETPTEMP,230\r\nCHN,1:FANSP,AUTO\r\n"


class Device(asyncio.Protocol):
    """A WMP peer which deliberately fragments its identity response."""

    def __init__(self, peers, commands, respond=True):
        self.peers, self.commands, self.respond = peers, commands, respond
        self.buffer = b""

    def connection_made(self, transport):
        self.transport = transport
        self.peers.append(self)

    def data_received(self, data):
        self.buffer += data
        while b"\r" in self.buffer:
            line, self.buffer = self.buffer.split(b"\r", 1)
            self.commands.append(line.decode())
            if not self.respond:
                continue
            if line == b"ID":
                self.transport.write(IDENTITY[:15].encode())
                asyncio.get_running_loop().call_soon(
                    self.transport.write, IDENTITY[15:].encode()
                )
            elif line == b"LIMITS:SETPTEMP":
                self.transport.write(LIMITS.encode())
            elif line == b"GET,1:*":
                self.transport.write(STATE.encode())


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.patches = [
            patch.object(client, name, value)
            for name, value in (
                ("COMMAND_INTERVAL", 0.001),
                ("CONNECT_TIMEOUT", 0.15),
                ("RECONNECT_DELAY", 0.01),
                ("MAX_RECONNECT_DELAY", 0.02),
                ("KEEPALIVE_INTERVAL", 0.02),
                ("POLL_INTERVAL", 0.03),
            )
        ]
        for item in self.patches:
            item.start()
        self.peers, self.commands = [], []
        self.server = await asyncio.get_running_loop().create_server(
            lambda: Device(self.peers, self.commands), "127.0.0.1", 0
        )
        self.box = client.IntesisBox(
            "127.0.0.1", self.server.sockets[0].getsockname()[1]
        )
        self.runner = None

    async def asyncTearDown(self):
        if self.runner:
            self.runner.cancel()
            with suppress(asyncio.CancelledError):
                await self.runner
        await self.box.async_close()
        for peer in self.peers:
            peer.transport.close()
        self.server.close()
        await self.server.wait_closed()
        for item in reversed(self.patches):
            item.stop()

    async def until(self, predicate):
        async with asyncio.timeout(1):
            while not predicate():
                await asyncio.sleep(0.001)

    async def test_full_handshake_and_command_wire_format(self):
        await self.box.async_connect()
        self.assertTrue(self.box.is_connected)
        self.assertEqual(self.box.device_mac_address, "001DC9A2C911")
        self.assertEqual(self.box.ambient_temperature, 21.5)
        self.box.set_temperature(22.5)
        self.box.set_power_off()
        await self.until(lambda: "SET,1:ONOFF,OFF" in self.commands)
        self.assertIn("SET,1:SETPTEMP,225", self.commands)

    async def test_fragmented_coalesced_and_invalid_frames(self):
        await self.box.async_connect()
        calls = []
        unsubscribe = self.box.add_update_callback(
            lambda: calls.append(self.box.ambient_temperature)
        )
        for data in (b"CHN,1:AMB", b"TEMP,2", b"45\r\nCHN,1:SETPTEMP,210\r"):
            self.box.data_received(data)
        self.assertEqual(calls, [24.5])
        self.box.data_received(
            b"\xff\rCHN,1:AMBTEMP,NaN\rCHN,1:bad\rLIMITS:SETPTEMP,[x,3]\r"
        )
        self.assertEqual(self.box.ambient_temperature, 24.5)
        self.box.data_received(
            b"x" * (client.MAX_LINE_LENGTH + 5) + b"\rCHN,1:AMBTEMP,200\n"
        )
        self.assertEqual(self.box.ambient_temperature, 20)
        unsubscribe()
        self.box.data_received(b"CHN,1:AMBTEMP,210\r")
        self.assertEqual(calls, [24.5, 20])

    async def test_null_and_unknown_values(self):
        await self.box.async_connect()
        self.box.data_received(b"CHN,1:AMBTEMP,-32768\rCHN,1:FANSP,32768\r")
        self.assertIsNone(self.box.ambient_temperature)
        self.assertIsNone(self.box.fan_speed)
        self.box.data_received(b"CHN,1:AMBTEMP,0\r")
        self.assertEqual(self.box.ambient_temperature, 0)

    async def test_disconnect_reconnect_and_maintenance(self):
        await self.box.async_connect()
        availability = []
        self.box.add_update_callback(lambda: availability.append(self.box.is_connected))
        self.runner = asyncio.create_task(self.box.async_run())
        self.peers[0].transport.close()
        await self.until(lambda: len(self.peers) == 2 and self.box.is_connected)
        self.assertIn(False, availability)
        self.assertTrue(availability[-1])
        await self.until(
            lambda: "PING" in self.commands and self.commands.count("GET,1:*") >= 3
        )

    async def test_timeout_closes_reader_and_socket(self):
        with patch.object(Device, "data_received", lambda *_: None):
            with self.assertRaises(TimeoutError):
                await self.box.async_connect()
        self.assertFalse(self.box.is_connected)
        self.assertIsNone(self.box._reader_task)
        self.assertIsNone(self.box._writer)

    async def test_identity_alone_is_not_ready(self):
        original = Device.data_received

        def identity_only(peer, data):
            if b"ID" in data:
                original(peer, data)

        with patch.object(Device, "data_received", identity_only):
            with self.assertRaises(TimeoutError):
                await self.box.async_connect()

    async def test_refused_connection_can_be_retried(self):
        port = self.server.sockets[0].getsockname()[1]
        self.server.close()
        await self.server.wait_closed()
        with self.assertRaises(OSError):
            await self.box.async_connect()
        self.server = await asyncio.get_running_loop().create_server(
            lambda: Device(self.peers, self.commands), "127.0.0.1", port
        )
        await self.box.async_connect()
        self.assertTrue(self.box.is_connected)

    async def test_cancel_setup_and_repeated_close(self):
        with patch.object(Device, "data_received", lambda *_: None):
            task = asyncio.create_task(self.box.async_connect())
            await self.until(lambda: bool(self.peers))
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        await self.box.async_close()
        await self.box.async_close()
        self.assertIsNone(self.box._reader_task)
        with self.assertRaises(ConnectionError):
            self.box.set_power_on()

    async def test_repeated_identity_does_not_spawn_tasks(self):
        await self.box.async_connect()
        reader = self.box._reader_task
        self.box.data_received((IDENTITY * 5).encode())
        self.assertIs(self.box._reader_task, reader)
        self.assertEqual(self.commands.count("GET,1:*"), 1)

    async def test_reconnection_rejects_different_device(self):
        await self.box.async_connect()
        with patch(
            __name__ + ".IDENTITY", IDENTITY.replace("001DC9A2C911", "001DC9A2C922")
        ):
            with self.assertRaises(ConnectionError):
                await self.box.async_connect()
        self.assertFalse(self.box.is_connected)


if __name__ == "__main__":
    unittest.main()
