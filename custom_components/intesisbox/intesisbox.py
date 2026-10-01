"""Asynchronous local WMP client. All methods run on the event loop."""

import asyncio
import logging
import re
from collections.abc import Callable
from contextlib import suppress

from .const import (
    COMMAND_INTERVAL,
    CONNECT_TIMEOUT,
    KEEPALIVE_INTERVAL,
    MAX_LINE_LENGTH,
    MAX_RECONNECT_DELAY,
    POLL_INTERVAL,
    RECONNECT_DELAY,
)

_LOGGER = logging.getLogger(__name__)
MODES = {"AUTO", "DRY", "FAN", "COOL", "HEAT"}
NULL_VALUES = {"-32768", "32768"}
REQUIRED_LIMITS = {"SETPTEMP", "MODE", "FANSP"}


class IntesisBox:
    """One connection, one reader and one optional maintenance task."""

    def __init__(self, ip: str, port: int = 3310) -> None:
        self._ip, self._port = ip, port
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task | None = None
        self._ready = asyncio.Event()
        self._disconnected = asyncio.Event()
        self._disconnected.set()
        self._callbacks: list[Callable[[], None]] = []
        self._connected = False
        self._buffer = bytearray()
        self._discard_line = False
        self._device: dict[str, str | None] = {}
        self._limits: dict[str, list[str]] = {}
        self._mac: str | None = None
        self._expected_mac: str | None = None
        self._model: str | None = None
        self._firmversion: str | None = None
        self._rssi: int | None = None
        self._minimum: float | None = None
        self._maximum: float | None = None

    async def async_connect(self) -> None:
        """Wait for identity, essential capabilities and initial power/mode."""
        await self.async_close()
        self._ready.clear()
        self._disconnected.clear()
        self._buffer.clear()
        self._discard_line = False
        self._device.clear()
        self._limits.clear()
        self._mac = None
        self._minimum = self._maximum = None
        try:
            async with asyncio.timeout(CONNECT_TIMEOUT):
                reader, self._writer = await asyncio.open_connection(
                    self._ip, self._port
                )
                self._reader_task = asyncio.create_task(self._read(reader))
                for cmd in (
                    "ID",
                    "LIMITS:SETPTEMP",
                    "LIMITS:FANSP",
                    "LIMITS:MODE",
                    "LIMITS:VANEUD",
                    "LIMITS:VANELR",
                ):
                    self._write(cmd)
                    await asyncio.sleep(COMMAND_INTERVAL)
                self._write("GET,1:*")
                await self._ready.wait()
                if not self._initial_state_complete() or self._disconnected.is_set():
                    raise ConnectionError("Device disconnected before initialization")
                if self._expected_mac is not None and self._mac != self._expected_mac:
                    raise ConnectionError(
                        "A different device answered at the configured host"
                    )
                self._expected_mac = self._mac
                self._connected = True
                self._notify()
        except BaseException:
            await self.async_close()
            raise

    async def async_run(self) -> None:
        """Keep alive, poll as a fallback, and reconnect with bounded backoff."""
        delay = RECONNECT_DELAY
        try:
            while True:
                if not self.is_connected:
                    await asyncio.sleep(delay)
                    try:
                        await self.async_connect()
                    except (OSError, TimeoutError):
                        _LOGGER.debug("IntesisBox reconnect failed", exc_info=True)
                        delay = min(delay * 2, MAX_RECONNECT_DELAY)
                        continue
                    delay = RECONNECT_DELAY
                loop = asyncio.get_running_loop()
                next_poll = loop.time() + POLL_INTERVAL
                while self.is_connected:
                    try:
                        async with asyncio.timeout(KEEPALIVE_INTERVAL):
                            await self._disconnected.wait()
                    except TimeoutError:
                        try:
                            self._write("PING")
                            if loop.time() >= next_poll:
                                self._write("GET,1:*")
                                next_poll = loop.time() + POLL_INTERVAL
                        except OSError:
                            await self.async_close()
        finally:
            await self.async_close()

    async def async_close(self) -> None:
        """Close and join the reader; safe before connection or when repeated."""
        self._connected = False
        self._disconnected.set()
        self._ready.set()
        if self._reader_task is not None:
            self._reader_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._reader_task
            self._reader_task = None
        if self._writer is not None:
            self._writer.close()
            with suppress(OSError, TimeoutError):
                async with asyncio.timeout(2):
                    await self._writer.wait_closed()
            self._writer = None

    async def _read(self, reader: asyncio.StreamReader) -> None:
        try:
            while chunk := await reader.read(4096):
                self.data_received(chunk)
        except OSError:
            _LOGGER.debug("IntesisBox connection lost", exc_info=True)
        finally:
            self._connected = False
            self._disconnected.set()
            self._ready.set()
            self._notify()

    def data_received(self, data: bytes) -> None:
        """Buffer fragments and accept CR, LF or CRLF terminated WMP lines."""
        changed = False
        for byte in data:
            if byte in (10, 13):
                if self._buffer and not self._discard_line:
                    try:
                        changed |= self._parse_line(self._buffer.decode("ascii"))
                    except (ValueError, IndexError):
                        _LOGGER.debug("Discarded malformed WMP line")
                self._buffer.clear()
                self._discard_line = False
            elif not self._discard_line:
                self._buffer.append(byte)
                if len(self._buffer) > MAX_LINE_LENGTH:
                    self._buffer.clear()
                    self._discard_line = True
                    _LOGGER.debug("Discarded oversized WMP line")
        if self._initial_state_complete():
            self._ready.set()
        if changed and self._connected:
            self._notify()

    def _parse_line(self, line: str) -> bool:
        command, separator, args = line.partition(":")
        if not separator:
            return False
        if command == "ID":
            fields = args.split(",")
            if len(fields) < 6 or not re.fullmatch(
                r"[0-9a-fA-F]{12}", fields[1].replace(":", "").replace("-", "")
            ):
                raise ValueError("Invalid identity")
            # Preserve MAC spelling: existing HA entity IDs depend on it.
            self._model, self._mac, self._firmversion = fields[0], fields[1], fields[4]
            try:
                self._rssi = int(fields[5])
            except ValueError:
                self._rssi = None
            return True
        if command == "CHN,1":
            function, separator, raw = args.partition(",")
            if not separator:
                raise ValueError("Missing value")
            value = None if raw in NULL_VALUES else raw
            if function in {"SETPTEMP", "AMBTEMP"} and value is not None:
                int(value)
            if function == "ONOFF" and value not in {"ON", "OFF", None}:
                raise ValueError("Invalid power state")
            changed = function not in self._device or self._device[function] != value
            self._device[function] = value
            return changed
        if command == "LIMITS":
            function, separator, raw = args.partition(",")
            if not separator or not raw.startswith("[") or not raw.endswith("]"):
                raise ValueError("Invalid limits")
            values = [v.strip() for v in raw[1:-1].split(",") if v.strip()]
            if function == "SETPTEMP":
                if len(values) != 2:
                    raise ValueError("Missing temperature limits")
                minimum, maximum = (int(v) / 10 for v in values)
                if minimum > maximum:
                    raise ValueError("Reversed limits")
                self._minimum, self._maximum = minimum, maximum
            if function == "MODE" and not MODES.intersection(values):
                raise ValueError("No supported HVAC modes")
            self._limits[function] = values
            return True
        return False

    def _initial_state_complete(self) -> bool:
        return bool(
            self._mac
            and REQUIRED_LIMITS <= self._limits.keys()
            and self._device.get("ONOFF") in {"ON", "OFF"}
            and self._device.get("MODE") in MODES
        )

    def _write(self, command: str) -> None:
        if (
            self._writer is None
            or self._writer.is_closing()
            or self._disconnected.is_set()
        ):
            raise ConnectionError("IntesisBox is disconnected")
        self._writer.write(f"{command}\r".encode("ascii"))

    def _set_value(self, function: str, value: str | int) -> None:
        if not self.is_connected:
            raise ConnectionError("IntesisBox is unavailable")
        self._write(f"SET,1:{function},{value}")

    def set_temperature(self, temperature: float) -> None:
        self._set_value("SETPTEMP", round(temperature * 10))

    def set_fan_speed(self, speed: str) -> None:
        self._set_value("FANSP", speed)

    def set_vertical_vane(self, vane: str) -> None:
        self._set_value("VANEUD", vane)

    def set_horizontal_vane(self, vane: str) -> None:
        self._set_value("VANELR", vane)

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError("Unsupported HVAC mode")
        if not self.is_on:
            self.set_power_on()
        self._set_value("MODE", mode)

    def set_power_on(self) -> None:
        self._set_value("ONOFF", "ON")

    def set_power_off(self) -> None:
        self._set_value("ONOFF", "OFF")

    def add_update_callback(self, callback: Callable[[], None]) -> Callable[[], None]:
        self._callbacks.append(callback)

        def unsubscribe() -> None:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

        return unsubscribe

    def _notify(self) -> None:
        for callback in tuple(self._callbacks):
            callback()

    @property
    def is_connected(self) -> bool:
        return self._connected and not self._disconnected.is_set()

    @property
    def device_mac_address(self) -> str | None:
        return self._mac

    @property
    def device_model(self) -> str | None:
        return self._model

    @property
    def firmware_version(self) -> str | None:
        return self._firmversion

    @property
    def rssi(self) -> int | None:
        return self._rssi

    @property
    def operation_list(self) -> list[str]:
        return self._limits.get("MODE", [])

    @property
    def fan_speed_list(self) -> list[str]:
        return self._limits.get("FANSP", [])

    @property
    def vane_horizontal_list(self) -> list[str]:
        return self._limits.get("VANELR", [])

    @property
    def vane_vertical_list(self) -> list[str]:
        return self._limits.get("VANEUD", [])

    @property
    def is_on(self) -> bool:
        return self._device.get("ONOFF") == "ON"

    @property
    def mode(self) -> str | None:
        return self._device.get("MODE")

    @property
    def fan_speed(self) -> str | None:
        return self._device.get("FANSP")

    @property
    def setpoint(self) -> float | None:
        value = self._device.get("SETPTEMP")
        return int(value) / 10 if value is not None else None

    @property
    def ambient_temperature(self) -> float | None:
        value = self._device.get("AMBTEMP")
        return int(value) / 10 if value is not None else None

    @property
    def min_setpoint(self) -> float | None:
        return self._minimum

    @property
    def max_setpoint(self) -> float | None:
        return self._maximum

    @property
    def vertical_swing(self) -> str | None:
        return self._device.get("VANEUD")

    @property
    def horizontal_swing(self) -> str | None:
        return self._device.get("VANELR")
