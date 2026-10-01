"""Set up the local IntesisBox integration."""

import asyncio
from contextlib import suppress
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN
from .intesisbox import IntesisBox

PLATFORMS = [Platform.CLIMATE]


@dataclass
class IntesisBoxRuntimeData:
    """Objects owned by a loaded config entry."""

    controller: IntesisBox
    task: asyncio.Task | None = None

    async def async_close(self) -> None:
        if self.task is not None:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None
        await self.controller.async_close()


type IntesisBoxConfigEntry = ConfigEntry[IntesisBoxRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: IntesisBoxConfigEntry) -> bool:
    """Connect with a timeout and let HA retry an offline device."""
    controller = IntesisBox(entry.data[CONF_HOST])
    try:
        await controller.async_connect()
        if (
            entry.unique_id is not None
            and entry.unique_id != controller.device_mac_address
        ):
            raise ConnectionError("A different device answered at the configured host")
    except (OSError, TimeoutError) as err:
        await controller.async_close()
        raise ConfigEntryNotReady(
            "Cannot initialize IntesisBox; check its host and power"
        ) from err
    if entry.unique_id is None:
        hass.config_entries.async_update_entry(
            entry, unique_id=controller.device_mac_address
        )
    entry.runtime_data = runtime = IntesisBoxRuntimeData(controller)
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await runtime.async_close()
        raise
    runtime.task = hass.async_create_background_task(
        controller.async_run(), f"{DOMAIN} connection {entry.entry_id}"
    )

    async def async_stop(event: Event) -> None:
        await runtime.async_close()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_stop)
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: IntesisBoxConfigEntry) -> bool:
    """Only close the connection once the platform has unloaded."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.async_close()
    return True
