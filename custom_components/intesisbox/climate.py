"""Climate entity for the local IntesisBox WMP interface."""

from collections.abc import Callable
from typing import Any

import voluptuous as vol
from homeassistant.components.climate import (
    PLATFORM_SCHEMA,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.components.climate.const import ATTR_HVAC_MODE
from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_HOST,
    CONF_NAME,
    CONF_UNIQUE_ID,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import (
    HomeAssistantError,
    PlatformNotReady,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IntesisBoxConfigEntry, IntesisBoxRuntimeData
from .const import DOMAIN
from .intesisbox import IntesisBox

PARALLEL_UPDATES = 1
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_NAME, default="Intesisbox"): cv.string,
        vol.Optional(CONF_UNIQUE_ID): cv.string,
    }
)
MAP_OPERATION_MODE_TO_HA = {
    "AUTO": HVACMode.HEAT_COOL,
    "FAN": HVACMode.FAN_ONLY,
    "HEAT": HVACMode.HEAT,
    "DRY": HVACMode.DRY,
    "COOL": HVACMode.COOL,
    "OFF": HVACMode.OFF,
}
MAP_OPERATION_MODE_TO_IB = {v: k for k, v in MAP_OPERATION_MODE_TO_HA.items()}
FAN_MODE_I_TO_E = {"AUTO": "auto", "1": "low", "2": "medium", "3": "high"}
FAN_MODE_E_TO_I = {v: k for k, v in FAN_MODE_I_TO_E.items()}
# Keep existing service values so swing automations remain valid.
SWING_LIST_STOP = "Auto"
SWING_LIST_HORIZONTAL = "Horizontal"
SWING_LIST_VERTICAL = "Vertical"
SWING_LIST_BOTH = "Both"
MAP_STATE_ICONS = {
    HVACMode.HEAT: "mdi:white-balance-sunny",
    HVACMode.HEAT_COOL: "mdi:cached",
    HVACMode.COOL: "mdi:snowflake",
    HVACMode.DRY: "mdi:water-off",
    HVACMode.FAN_ONLY: "mdi:fan",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IntesisBoxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([IntesisBoxAC(entry.runtime_data.controller)])


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Retain legacy YAML support without changing existing unique IDs."""
    controller = IntesisBox(config[CONF_HOST])
    try:
        await controller.async_connect()
    except (OSError, TimeoutError) as err:
        raise PlatformNotReady("Cannot initialize IntesisBox") from err
    runtime = IntesisBoxRuntimeData(controller)
    entity = IntesisBoxAC(
        controller, config.get(CONF_NAME), config.get(CONF_UNIQUE_ID), runtime
    )
    async_add_entities([entity])


class IntesisBoxAC(ClimateEntity):
    """Publish acknowledged device state immediately without HA polling."""

    _attr_should_poll = False
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        controller: IntesisBox,
        name: str | None = None,
        unique_id: str | None = None,
        owned_runtime: IntesisBoxRuntimeData | None = None,
    ) -> None:
        self._controller = controller
        self._owned_runtime = owned_runtime
        self._attr_unique_id = unique_id or controller.device_mac_address
        self._attr_name = name or controller.device_mac_address
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            name=self._attr_name,
            manufacturer="Intesis",
            model=controller.device_model,
            sw_version=controller.firmware_version,
        )
        self._refresh_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._controller.add_update_callback(self._handle_update))
        if self._owned_runtime is not None:
            self._owned_runtime.task = self.hass.async_create_background_task(
                self._controller.async_run(), "intesisbox YAML connection"
            )
        self._refresh_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._owned_runtime is not None:
            await self._owned_runtime.async_close()

    @callback
    def _handle_update(self) -> None:
        self._refresh_state()
        self.async_write_ha_state()

    @callback
    def _refresh_state(self) -> None:
        controller = self._controller
        self._attr_available = controller.is_connected
        self._attr_current_temperature = controller.ambient_temperature
        self._attr_target_temperature = controller.setpoint
        self._attr_min_temp = (
            controller.min_setpoint if controller.min_setpoint is not None else 7
        )
        self._attr_max_temp = (
            controller.max_setpoint if controller.max_setpoint is not None else 35
        )
        self._attr_hvac_mode = (
            MAP_OPERATION_MODE_TO_HA.get(controller.mode)
            if controller.is_on
            else HVACMode.OFF
        )
        self._attr_icon = MAP_STATE_ICONS.get(self._attr_hvac_mode)
        self._attr_hvac_modes = list(
            dict.fromkeys(
                [
                    HVACMode.OFF,
                    *(
                        MAP_OPERATION_MODE_TO_HA[m]
                        for m in controller.operation_list
                        if m in MAP_OPERATION_MODE_TO_HA
                    ),
                ]
            )
        )
        speed = controller.fan_speed
        self._attr_fan_mode = (
            FAN_MODE_I_TO_E.get(speed, speed.lower()) if speed else None
        )
        self._attr_fan_modes = [
            FAN_MODE_I_TO_E.get(s, s.lower()) for s in controller.fan_speed_list
        ]
        vertical = controller.vertical_swing == "SWING"
        horizontal = controller.horizontal_swing == "SWING"
        self._attr_swing_modes = [SWING_LIST_STOP]
        if "SWING" in controller.vane_horizontal_list:
            self._attr_swing_modes.append(SWING_LIST_HORIZONTAL)
        if "SWING" in controller.vane_vertical_list:
            self._attr_swing_modes.append(SWING_LIST_VERTICAL)
        if len(self._attr_swing_modes) == 3:
            self._attr_swing_modes.append(SWING_LIST_BOTH)
        self._attr_swing_mode = (
            SWING_LIST_BOTH
            if vertical and horizontal
            else SWING_LIST_VERTICAL
            if vertical
            else SWING_LIST_HORIZONTAL
            if horizontal
            else SWING_LIST_STOP
        )
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )
        if self._attr_fan_modes:
            self._attr_supported_features |= ClimateEntityFeature.FAN_MODE
        self._attr_extra_state_attributes = {
            "ha_update_type": "push" if controller.is_connected else "poll"
        }
        if len(self._attr_swing_modes) > 1:
            self._attr_supported_features |= ClimateEntityFeature.SWING_MODE
            self._attr_extra_state_attributes.update(
                vertical_swing=vertical, horizontal_swing=horizontal
            )

    def _command(self, method: Callable, *args: Any) -> None:
        """Report command failures to the caller instead of hiding them."""
        try:
            method(*args)
        except OSError as err:
            raise HomeAssistantError("Cannot send command to IntesisBox") from err

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
            await self.async_set_hvac_mode(mode)
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            self._command(self._controller.set_temperature, temperature)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode not in self.hvac_modes:
            raise ServiceValidationError("Unsupported HVAC mode")
        if hvac_mode == HVACMode.OFF:
            self._command(self._controller.set_power_off)
        else:
            self._command(
                self._controller.set_mode, MAP_OPERATION_MODE_TO_IB[hvac_mode]
            )
            if self.target_temperature is not None:
                self._command(self._controller.set_temperature, self.target_temperature)

    async def async_turn_on(self) -> None:
        self._command(self._controller.set_power_on)

    async def async_turn_off(self) -> None:
        self._command(self._controller.set_power_off)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        if fan_mode not in self.fan_modes:
            raise ServiceValidationError("Unsupported fan mode")
        self._command(
            self._controller.set_fan_speed,
            FAN_MODE_E_TO_I.get(fan_mode, fan_mode).upper(),
        )

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        if swing_mode not in self.swing_modes:
            raise ServiceValidationError("Unsupported swing mode")
        # Do not send vane commands for an axis unsupported by this model.
        for supported, setter, enabled in (
            (
                self._controller.vane_vertical_list,
                self._controller.set_vertical_vane,
                swing_mode in {SWING_LIST_VERTICAL, SWING_LIST_BOTH},
            ),
            (
                self._controller.vane_horizontal_list,
                self._controller.set_horizontal_vane,
                swing_mode in {SWING_LIST_HORIZONTAL, SWING_LIST_BOTH},
            ),
        ):
            if "SWING" in supported:
                self._command(setter, "SWING" if enabled else "AUTO")
