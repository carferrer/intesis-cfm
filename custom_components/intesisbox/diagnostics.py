"""Diagnostics without network addresses or device identifiers."""

from homeassistant.core import HomeAssistant

from . import IntesisBoxConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: IntesisBoxConfigEntry
) -> dict:
    controller = entry.runtime_data.controller
    return {
        "connected": controller.is_connected,
        "model": controller.device_model,
        "firmware": controller.firmware_version,
        "rssi": controller.rssi,
        "capabilities": {
            "modes": controller.operation_list,
            "fan_speeds": controller.fan_speed_list,
            "vertical_vane": controller.vane_vertical_list,
            "horizontal_vane": controller.vane_horizontal_list,
            "min_temperature": controller.min_setpoint,
            "max_temperature": controller.max_setpoint,
        },
    }
