"""Device tracker for the ICAR collar."""

from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ICarCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ICarCoordinator = hass.data[DOMAIN][entry.entry_id].coordinator
    async_add_entities([ICarTrackerEntity(coordinator)])


class ICarTrackerEntity(CoordinatorEntity[ICarCoordinator], TrackerEntity):
    """The collar position on the map."""

    _attr_has_entity_name = False

    def __init__(self, coordinator: ICarCoordinator) -> None:
        super().__init__(coordinator)
        api = coordinator.api
        self._attr_unique_id = f"{api.sn}_tracker"
        self._attr_name = api.device_name or f"ICAR {api.sn}"

    @property
    def device_info(self) -> DeviceInfo:
        api = self.coordinator.api
        device = self.coordinator.data.get("device", {})
        return DeviceInfo(
            identifiers={(DOMAIN, api.sn)},
            name=api.device_name,
            manufacturer="ICAR (icargps.net)",
            model=str(device.get("modelName") or "ICAR GPS tracker"),
            sw_version=None,
        )

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        device = self.coordinator.data.get("device", {})
        try:
            return float(device.get("latitude"))
        except (TypeError, ValueError):
            return None

    @property
    def longitude(self) -> float | None:
        device = self.coordinator.data.get("device", {})
        try:
            return float(device.get("longitude"))
        except (TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        device = self.coordinator.data.get("device", {})
        attrs: dict[str, Any] = {
            "speed": _float(device.get("speed")),
            "course": _int(device.get("course")),
            "status": device.get("status"),
            "is_stop": device.get("isStop"),
            "stop_time_minute": _int(device.get("stopTimeMinute")),
            "device_utc_date": device.get("deviceUtcDate"),
            "server_utc_date": device.get("serverUtcDate"),
            "data_context": device.get("dataContext"),
            "offline_flag": device.get("ofl"),
            "distance_km": _float(device.get("distance")),
            "battery": self.coordinator.data.get("battery"),
        }
        return {k: v for k, v in attrs.items() if v is not None}

    @property
    def location_accuracy(self) -> int | None:
        # The platform does not expose GPS accuracy.
        return None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
