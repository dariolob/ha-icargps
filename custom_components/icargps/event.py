"""Event entities for ICAR collar alarms (geofence, vibration, ...)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ALARM_TYPE_MAP, DOMAIN
from .coordinator import ICarCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ICarCoordinator = hass.data[DOMAIN][entry.entry_id].coordinator
    async_add_entities([ICarAlarmEvent(coordinator)])


def _type(alarm: dict[str, Any]) -> int | None:
    try:
        return int(alarm.get("notificationType"))
    except (TypeError, ValueError):
        return None


class ICarAlarmEvent(CoordinatorEntity[ICarCoordinator], EventEntity):
    """Fires one event per new alarm received from the platform."""

    _attr_event_types = [
        "geofence_exit",
        "geofence_enter",
        "alarm",
        "unknown",
    ]
    _attr_icon = "mdi:bell-alert"

    def __init__(self, coordinator: ICarCoordinator) -> None:
        super().__init__(coordinator)
        api = coordinator.api
        self._attr_unique_id = f"{api.sn}_alarms"
        self._attr_name = f"{api.device_name} Alarms"
        device = coordinator.data.get("device", {})
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, api.sn)},
            name=api.device_name,
            manufacturer="ICAR (icargps.net)",
            model=str(device.get("modelName") or "ICAR GPS tracker"),
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        alarms = (self.coordinator.data or {}).get("new_alarms") or []
        for alarm in alarms:
            event_type = ALARM_TYPE_MAP.get(_type(alarm), "unknown")
            self._trigger_event(
                event_type,
                {
                    "note": alarm.get("note"),
                    "device_date": alarm.get("deviceDate"),
                    "create_date": alarm.get("createDate"),
                    "raw_type": alarm.get("notificationType"),
                    "id": alarm.get("id"),
                },
            )
        self.async_write_ha_state()
