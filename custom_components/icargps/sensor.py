"""Sensors for the ICAR collar."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfSpeed
from homeassistant.core import HomeAssistant
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
    async_add_entities(
        [
            ICarBatterySensor(coordinator),
            ICarSpeedSensor(coordinator),
            ICarStatusSensor(coordinator),
            ICarLastAlarmSensor(coordinator),
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


class ICarBatterySensor(CoordinatorEntity[ICarCoordinator], SensorEntity):
    """Battery percentage (from the dataContext field)."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: ICarCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.api.sn}_battery"
        self._attr_name = f"{coordinator.api.device_name} Battery"
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.get("battery")


class ICarSpeedSensor(CoordinatorEntity[ICarCoordinator], SensorEntity):
    """Speed in km/h as reported by the platform."""

    _attr_device_class = SensorDeviceClass.SPEED
    _attr_native_unit_of_measurement = UnitOfSpeed.KILOMETERS_PER_HOUR
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:run-fast"

    def __init__(self, coordinator: ICarCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.api.sn}_speed"
        self._attr_name = f"{coordinator.api.device_name} Speed"
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> float | None:
        try:
            return float(self.coordinator.data.get("device", {}).get("speed"))
        except (TypeError, ValueError):
            return None


class ICarStatusSensor(CoordinatorEntity[ICarCoordinator], SensorEntity):
    """Movement status (Stop/Moving) with stop duration."""

    _attr_icon = "mdi:dog-side"

    def __init__(self, coordinator: ICarCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.api.sn}_status"
        self._attr_name = f"{coordinator.api.device_name} Status"
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> str | None:
        return self.coordinator.data.get("device", {}).get("status")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        device = self.coordinator.data.get("device", {})
        return {
            "is_stop": device.get("isStop"),
            "stop_time_minute": device.get("stopTimeMinute"),
            "offline_flag": device.get("ofl"),
            "device_utc_date": device.get("deviceUtcDate"),
        }


class ICarLastAlarmSensor(CoordinatorEntity[ICarCoordinator], SensorEntity):
    """The most recent alarm (geofence in/out, etc.)."""

    _attr_icon = "mdi:alert"

    def __init__(self, coordinator: ICarCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.api.sn}_last_alarm"
        self._attr_name = f"{coordinator.api.device_name} Last Alarm"
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> str | None:
        alarm = self.coordinator.data.get("last_alarm")
        if not alarm:
            return None
        label = ALARM_TYPE_MAP.get(_type(alarm), "unknown")
        note = (alarm.get("note") or "").strip()
        return f"{label} {note}".strip()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        alarm = self.coordinator.data.get("last_alarm") or {}
        return {
            "type": ALARM_TYPE_MAP.get(_type(alarm), "unknown"),
            "raw_type": alarm.get("notificationType"),
            "note": alarm.get("note"),
            "device_date": alarm.get("deviceDate"),
            "create_date": alarm.get("createDate"),
            "id": alarm.get("id"),
        }


def _type(alarm: dict[str, Any]) -> int | None:
    try:
        return int(alarm.get("notificationType"))
    except (TypeError, ValueError):
        return None
