"""Exercise setup, services and entity registry compatibility on HA 2026.9.2."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.intesisbox import async_unload_entry
from custom_components.intesisbox.diagnostics import async_get_config_entry_diagnostics

MAC = "001DC9A2C911"


async def setup_entry(hass, unique_id=MAC):
    entry = MockConfigEntry(
        domain="intesisbox",
        title="192.0.2.1",
        unique_id=unique_id,
        data={"host": "192.0.2.1"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_registry_and_push_updates(hass, mock_client):
    registry = er.async_get(hass)
    entry = MockConfigEntry(
        domain="intesisbox", unique_id=MAC, data={"host": "192.0.2.1"}
    )
    entry.add_to_hass(hass)
    old = registry.async_get_or_create(
        "climate", "intesisbox", MAC, suggested_object_id="salon", config_entry=entry
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(old.entity_id).state == "cool"
    assert hass.states.get(old.entity_id).attributes["fan_mode"] == "auto"
    mock_client.data_received(b"CHN,1:AMBTEMP,255\rCHN,1:ONOFF,OFF\r")
    assert hass.states.get(old.entity_id).state == "off"
    assert hass.states.get(old.entity_id).attributes["current_temperature"] == 25.5
    assert len(er.async_entries_for_config_entry(registry, entry.entry_id)) == 1
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not mock_client._callbacks
    mock_client.async_close.assert_awaited()


async def test_availability_and_missing_fan(hass, mock_client):
    await setup_entry(hass)
    entity_id = er.async_get(hass).async_get_entity_id("climate", "intesisbox", MAC)
    mock_client.data_received(b"CHN,1:FANSP,-32768\r")
    assert hass.states.get(entity_id).attributes.get("fan_mode") is None
    mock_client._connected = False
    mock_client._notify()
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE
    mock_client._connected = True
    mock_client._notify()
    assert hass.states.get(entity_id).state == "cool"


@pytest.mark.parametrize("error", [TimeoutError(), ConnectionRefusedError()])
async def test_offline_setup_retries(hass, mock_client, error):
    mock_client.async_connect.side_effect = error
    entry = MockConfigEntry(domain="intesisbox", data={"host": "192.0.2.1"})
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    mock_client.async_close.assert_awaited()


async def test_legacy_entry_gets_mac(hass, mock_client):
    entry = await setup_entry(hass, unique_id=None)
    assert entry.unique_id == MAC
    assert entry.version == 1


async def test_wrong_device_does_not_create_new_entities(hass, mock_client):
    entry = MockConfigEntry(
        domain="intesisbox", unique_id="001DC9A2C922", data={"host": "192.0.2.1"}
    )
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert not er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)


async def test_failed_unload_keeps_connection(hass, mock_client):
    entry = await setup_entry(hass)
    with patch.object(
        hass.config_entries, "async_unload_platforms", new=AsyncMock(return_value=False)
    ):
        assert not await async_unload_entry(hass, entry)
    mock_client.async_close.assert_not_awaited()


async def test_diagnostics_omit_network_identity(hass, mock_client):
    entry = await setup_entry(hass)
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["model"] == "IS-IR-WMP-1"
    assert "192.0.2.1" not in str(result)
    assert MAC not in str(result)


@pytest.mark.parametrize(
    ("service", "data", "commands"),
    [
        ("turn_on", {}, ["SET,1:ONOFF,ON"]),
        ("turn_off", {}, ["SET,1:ONOFF,OFF"]),
        ("set_temperature", {"temperature": 22.5}, ["SET,1:SETPTEMP,225"]),
        ("set_fan_mode", {"fan_mode": "low"}, ["SET,1:FANSP,1"]),
        ("set_swing_mode", {"swing_mode": "Vertical"}, ["SET,1:VANEUD,SWING"]),
        (
            "set_hvac_mode",
            {"hvac_mode": "heat"},
            ["SET,1:MODE,HEAT", "SET,1:SETPTEMP,230"],
        ),
    ],
)
async def test_services(hass, mock_client, service, data, commands):
    await setup_entry(hass)
    entity_id = er.async_get(hass).async_get_entity_id("climate", "intesisbox", MAC)
    with patch.object(mock_client, "_write") as write:
        await hass.services.async_call(
            "climate", service, {"entity_id": entity_id, **data}, blocking=True
        )
    assert [call.args[0] for call in write.call_args_list] == commands
