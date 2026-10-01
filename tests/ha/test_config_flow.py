"""Validate the UI, duplicate detection and safe host changes."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

MAC = "001DC9A2C911"


async def test_user_flow(hass, mock_client):
    result = await hass.config_entries.flow.async_init(
        "intesisbox", context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    with patch(
        "custom_components.intesisbox.async_setup_entry",
        new=AsyncMock(return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": " 192.0.2.1 "}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == MAC
    assert result["data"] == {"host": "192.0.2.1"}
    mock_client.async_close.assert_awaited()


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TimeoutError(), "cannot_connect"),
        (ConnectionRefusedError(), "cannot_connect"),
        (RuntimeError(), "unknown"),
    ],
)
async def test_validation_failure(hass, mock_client, error, expected):
    mock_client.async_connect.side_effect = error
    result = await hass.config_entries.flow.async_init(
        "intesisbox", context={"source": SOURCE_USER}, data={"host": "192.0.2.1"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}
    mock_client.async_close.assert_awaited()


@pytest.mark.parametrize("host", ["192.0.2.1", "192.0.2.2"])
async def test_duplicate(hass, mock_client, host):
    entry = MockConfigEntry(
        domain="intesisbox", unique_id=MAC, data={"host": "192.0.2.1"}
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        "intesisbox", context={"source": SOURCE_USER}, data={"host": host}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.parametrize(
    ("mac", "reason"),
    [(MAC, "reconfigure_successful"), ("001DC9A2C922", "wrong_device")],
)
async def test_reconfigure(hass, mock_client, mac, reason):
    entry = MockConfigEntry(
        domain="intesisbox", unique_id=MAC, data={"host": "192.0.2.1"}
    )
    entry.add_to_hass(hass)
    mock_client._mac = mac
    with patch.object(
        hass.config_entries, "async_reload", new=AsyncMock(return_value=True)
    ):
        result = await hass.config_entries.flow.async_init(
            "intesisbox",
            context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
            data={"host": "192.0.2.2"},
        )
        await hass.async_block_till_done()
    assert result["reason"] == reason
    assert entry.data["host"] == ("192.0.2.2" if mac == MAC else "192.0.2.1")
    assert entry.unique_id == MAC
