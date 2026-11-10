"""Config flow for the iCar GPS (icargps.net) integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ICarApi, ICarApiError, ICarAuthError
from .const import (
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_SHOCK_LEVEL,
    CONF_SN,
    CONF_TZ,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SHOCK_LEVEL,
    DEFAULT_TZ,
    DOMAIN,
)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SN): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_TZ, default=DEFAULT_TZ): str,
        vol.Optional(
            CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
        ): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
    }
)


class ICarConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for one device (login is per device SN)."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            api = ICarApi(
                session,
                user_input[CONF_SN],
                user_input[CONF_PASSWORD],
                user_input.get(CONF_TZ, DEFAULT_TZ),
            )
            try:
                await api.async_login()
            except ICarAuthError:
                errors["base"] = "invalid_auth"
            except ICarApiError:
                errors["base"] = "cannot_connect"
            except TimeoutError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(user_input[CONF_SN])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=api.device_name or f"ICAR {user_input[CONF_SN]}",
                    data={
                        CONF_SN: user_input[CONF_SN],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_TZ: user_input.get(CONF_TZ, DEFAULT_TZ),
                        CONF_SCAN_INTERVAL: user_input.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: Any,
    ) -> ICarOptionsFlow:
        return ICarOptionsFlow(config_entry)


class ICarOptionsFlow(OptionsFlow):
    """Options: poll interval, timezone, shock level."""

    def __init__(self, config_entry: Any) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_SCAN_INTERVAL,
                            self.config_entry.data.get(
                                CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                            ),
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
                    vol.Optional(
                        CONF_TZ,
                        default=self.config_entry.options.get(
                            CONF_TZ, DEFAULT_TZ
                        ),
                    ): str,
                    vol.Optional(
                        CONF_SHOCK_LEVEL,
                        default=self.config_entry.options.get(
                            CONF_SHOCK_LEVEL, DEFAULT_SHOCK_LEVEL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=9)),
                }
            ),
        )
