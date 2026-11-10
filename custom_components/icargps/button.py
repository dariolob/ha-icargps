"""Buttons for the ICAR collar (find / shock)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import ICarApiError, ICarAuthError, SendResult
from .const import (
    CMD_FIND,
    CMD_SHOCK,
    CONF_SHOCK_LEVEL,
    DEFAULT_SHOCK_LEVEL,
    DOMAIN,
    EVENT_COMMAND_RESULT,
)
from .coordinator import ICarCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ICarCoordinator = hass.data[DOMAIN][entry.entry_id].coordinator
    async_add_entities(
        [
            ICarFindButton(coordinator, entry),
            ICarShockButton(coordinator, entry),
        ]
    )


def _device_info(coordinator: ICarCoordinator) -> DeviceInfo:
    api = coordinator.api
    device = coordinator.data.get("device", {})
    return DeviceInfo(
        identifiers={(DOMAIN, api.sn)},
        name=api.device_name,
        manufacturer="ICAR (icargps.net)",
        model=str(device.get("modelName") or "ICAR GPS tracker"),
    )


def _fire_result(hass: HomeAssistant, entry: ConfigEntry, result: SendResult) -> None:
    hass.bus.async_fire(
        EVENT_COMMAND_RESULT,
        {
            "sn": entry.data["sn"],
            "command": result.command,
            "code": result.code,
            "queued": result.queued,
            "saved": result.saved,
            "message": result.message,
            "response": result.response_text,
        },
    )


class ICarBaseButton(CoordinatorEntity[ICarCoordinator], ButtonEntity):
    """Base class: sends a command and fires the result event."""

    def __init__(self, coordinator: ICarCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = _device_info(coordinator)

    async def _async_send(self, command: str, params: str) -> None:
        try:
            result = await self.coordinator.api.async_send_command(command, params)
        except ICarAuthError as exc:
            raise HomeAssistantError(f"Login/session error: {exc}") from exc
        except ICarApiError as exc:
            raise HomeAssistantError(f"Platform error: {exc}") from exc
        _fire_result(self.hass, self._entry, result)
        if result.queued:
            _LOGGER.info("Command %s delivered (id=%s)", command, result.command_id)
        elif result.saved:
            _LOGGER.info(
                "Command %s saved: the collar is sleeping and will run it when it "
                "wakes up and reconnects",
                command,
            )
        else:
            raise HomeAssistantError(
                f"Command {command} rejected: {result.message} (code {result.code})"
            )


class ICarFindButton(ICarBaseButton):
    """Make the collar beep and flash for ~1 minute (SLXKDM)."""

    _attr_icon = "mdi:bell-ring"
    _attr_has_entity_name = False

    def __init__(self, coordinator: ICarCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{coordinator.api.sn}_find"
        self._attr_name = f"{coordinator.api.device_name} Find"

    async def async_press(self) -> None:
        await self._async_send(CMD_FIND, "false")


class ICarShockButton(ICarBaseButton):
    """Vibration + e-shock (SLXKZDXG).

    EXPERIMENTAL: the command name and the numeric level parameter were read
    from the platform command history, but the level encoding has not been
    verified end-to-end. The entity is disabled by default: enable it in the
    entity registry only if you really need it, and start with level 1.
    """

    _attr_icon = "mdi:lightning-bolt"
    _attr_entity_registry_enabled_default = False
    _attr_has_entity_name = False

    def __init__(self, coordinator: ICarCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{coordinator.api.sn}_shock"
        self._attr_name = f"{coordinator.api.device_name} Shock"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "level": self._entry.options.get(CONF_SHOCK_LEVEL, DEFAULT_SHOCK_LEVEL),
            "warning": "Experimental: shock level encoding not verified",
        }

    async def async_press(self) -> None:
        level = str(self._entry.options.get(CONF_SHOCK_LEVEL, DEFAULT_SHOCK_LEVEL))
        await self._async_send(CMD_SHOCK, level)
