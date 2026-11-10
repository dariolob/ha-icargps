"""Buttons for the ICAR collar (find / sound / vibration / light / shock)."""

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
    CMD_NIGHT_LIGHT,
    CMD_SHOCK,
    CMD_SOUND,
    CMD_VIBRATION,
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
            ICarSoundButton(coordinator, entry),
            ICarVibrationButton(coordinator, entry),
            ICarNightLightButton(coordinator, entry),
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


class _ICarSimpleButton(ICarBaseButton):
    """A button that sends a fixed command with no parameters."""

    _cmd: str = ""
    _attr_has_entity_name = False

    def __init__(self, coordinator: ICarCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)

    async def async_press(self) -> None:
        await self._async_send(self._cmd, "")


class ICarFindButton(_ICarSimpleButton):
    """Play the "find" tune and flash for ~1 minute (SLXKDM)."""

    _cmd = CMD_FIND
    _attr_icon = "mdi:bell-ring"

    def __init__(self, coordinator: ICarCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{coordinator.api.sn}_find"
        self._attr_name = f"{coordinator.api.device_name} Find"


class ICarSoundButton(_ICarSimpleButton):
    """Play the short training rhythm (SLXKLS).

    This is the "punitive" sound of the app (Sound rhythm to train dog),
    not the long find tune.
    """

    _cmd = CMD_SOUND
    _attr_icon = "mdi:volume-high"

    def __init__(self, coordinator: ICarCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{coordinator.api.sn}_sound"
        self._attr_name = f"{coordinator.api.device_name} Sound"


class ICarVibrationButton(_ICarSimpleButton):
    """Vibrate once to train the dog (SLXKBSD)."""

    _cmd = CMD_VIBRATION
    _attr_icon = "mdi:vibrate"

    def __init__(self, coordinator: ICarCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{coordinator.api.sn}_vibration"
        self._attr_name = f"{coordinator.api.device_name} Vibration"


class ICarNightLightButton(_ICarSimpleButton):
    """Turn on the night light to find the dog in the dark (SLXKZXZD)."""

    _cmd = CMD_NIGHT_LIGHT
    _attr_icon = "mdi:lightbulb-on"

    def __init__(self, coordinator: ICarCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{coordinator.api.sn}_night_light"
        self._attr_name = f"{coordinator.api.device_name} Night Light"


class ICarShockButton(ICarBaseButton):
    """Vibration + e-shock at the configured level (SLXKZDXG).

    The command and the 1-9 level parameter are the same the mobile app
    sends (verified: levels 1, 2, 3 and 6 ACKed "Success!" by the collar
    on 2026-11-10). The entity is disabled by default because an
    e-shock on a pet is something you should enable deliberately.
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
            "warning": "E-shock: enable deliberately and supervise your dog",
        }

    async def async_press(self) -> None:
        level = str(self._entry.options.get(CONF_SHOCK_LEVEL, DEFAULT_SHOCK_LEVEL))
        await self._async_send(CMD_SHOCK, level)
