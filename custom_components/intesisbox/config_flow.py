"""Validate local connectivity and avoid duplicate IntesisBox entries."""

import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.helpers.selector import TextSelector

from .const import DOMAIN
from .intesisbox import IntesisBox

_LOGGER = logging.getLogger(__name__)


class IntesisboxFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Keep v1 entries and MAC identifiers compatible with existing installs."""

    VERSION = 1

    async def _validate(self, host: str) -> str:
        controller = IntesisBox(host)
        try:
            await controller.async_connect()
            return controller.device_mac_address
        finally:
            await controller.async_close()

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            self._async_abort_entries_match({CONF_HOST: host})
            try:
                mac = await self._validate(host)
            except (OSError, TimeoutError):
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error validating IntesisBox")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=host, data={CONF_HOST: host})
        return self._form("user", user_input, errors)

    async def async_step_reconfigure(self, user_input=None):
        entry = self._get_reconfigure_entry()
        errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            if host == entry.data[CONF_HOST]:
                return self.async_abort(reason="no_changes")
            try:
                mac = await self._validate(host)
            except (OSError, TimeoutError):
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error reconfiguring IntesisBox")
                errors["base"] = "unknown"
            else:
                if entry.unique_id is None or mac != entry.unique_id:
                    return self.async_abort(reason="wrong_device")
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_HOST: host}
                )
        return self._form("reconfigure", user_input or entry.data, errors)

    def _form(self, step, user_input, errors):
        return self.async_show_form(
            step_id=step,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST, default=(user_input or {}).get(CONF_HOST, "")
                    ): TextSelector()
                }
            ),
            errors=errors,
        )

    async def async_step_import(self, user_input=None):
        return await self.async_step_user(user_input)
