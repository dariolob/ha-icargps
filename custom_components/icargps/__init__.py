"""Support for ICAR GPS trackers (icargps.net)."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from .api import ICarApi, ICarApiError, ICarAuthError, SendResult
from .config_entry_data import ICarEntryData
from .const import (
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_SN,
    CONF_TZ,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TZ,
    DOMAIN,
    EVENT_COMMAND_RESULT,
)
from .coordinator import ICarCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.DEVICE_TRACKER,
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.EVENT,
]

SERVICE_SEND_COMMAND = "send_command"

SEND_COMMAND_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("command"): cv.string,
        vol.Optional("params", default="false"): cv.string,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the icargps integration from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    session = async_get_clientsession(hass)
    api = ICarApi(
        session,
        entry.data[CONF_SN],
        entry.data[CONF_PASSWORD],
        entry.options.get(CONF_TZ, entry.data.get(CONF_TZ, DEFAULT_TZ)),
    )

    try:
        await api.async_login()
    except ICarAuthError as exc:
        raise ConfigEntryAuthFailed(f"Login failed: {exc}") from exc
    except ICarApiError as exc:
        raise ConfigEntryNotReady(f"Platform error: {exc}") from exc

    coordinator = ICarCoordinator(hass, api, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = ICarEntryData(api=api, coordinator=coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _register_send_command_service(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options updates (interval / timezone / watermark persistence)."""
    data: ICarEntryData = hass.data[DOMAIN][entry.entry_id]
    coordinator = data.coordinator
    coordinator.update_interval = timedelta(
        seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )
    data.api.tz = entry.options.get(CONF_TZ, entry.data.get(CONF_TZ, DEFAULT_TZ))


def _register_send_command_service(hass: HomeAssistant) -> None:
    """Register the generic icargps.send_command service once."""

    async def _handle_send_command(call: ServiceCall) -> None:
        registry = er.async_get(hass)
        entity = registry.async_get(call.data["entity_id"])
        if entity is None or entity.config_entry_id is None:
            raise HomeAssistantError("Unknown entity")

        entry = hass.config_entries.async_get_entry(entity.config_entry_id)
        if entry is None or entry.entry_id not in hass.data.get(DOMAIN, {}):
            raise HomeAssistantError("Entity does not belong to an icargps config entry")

        data: ICarEntryData = hass.data[DOMAIN][entry.entry_id]
        try:
            result: SendResult = await data.api.async_send_command(
                call.data["command"], call.data["params"]
            )
        except ICarAuthError as exc:
            raise HomeAssistantError(f"Session error: {exc}") from exc
        _fire_command_result(hass, entry, result)

    if not hass.services.has_service(DOMAIN, SERVICE_SEND_COMMAND):
        hass.services.async_register(
            DOMAIN, SERVICE_SEND_COMMAND, _handle_send_command, SEND_COMMAND_SCHEMA
        )


def _fire_command_result(hass: HomeAssistant, entry: ConfigEntry, result: SendResult) -> None:
    """Fire an event summarising a command outcome."""
    hass.bus.async_fire(
        EVENT_COMMAND_RESULT,
        {
            "sn": entry.data[CONF_SN],
            "command": result.command,
            "code": result.code,
            "queued": result.queued,
            "saved": result.saved,
            "message": result.message,
            "response": result.response_text,
        },
    )
    if not result.queued and not result.saved:
        _LOGGER.warning("Command %s failed: %s", result.command, result.message)
