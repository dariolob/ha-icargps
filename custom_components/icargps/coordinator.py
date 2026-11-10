"""DataUpdateCoordinator for the iCar GPS integration."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ICarApi, ICarApiError, ICarAuthError
from .const import CONF_SCAN_INTERVAL, CONF_WATERMARK, DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


def parse_battery(data_context: str | None) -> int | None:
    """Extract battery percentage from the dataContext field.

    Observed format on the IK122T Pro: ``0-0-<battery %>-<other>``.
    """
    if not data_context:
        return None
    parts = data_context.split("-")
    if len(parts) >= 3 and parts[2].isdigit():
        return int(parts[2])
    return None


class ICarCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll the platform for device state and alarms."""

    def __init__(self, hass: HomeAssistant, api: ICarApi, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=api.sn,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.api = api
        self.entry = entry
        self.first_poll = True
        self.first_alarm_batch = True

    @property
    def watermark(self) -> str:
        """Alarm watermark (server-side UTC), persisted in entry options."""
        return self.entry.options.get(CONF_WATERMARK, self._default_watermark())

    @staticmethod
    def _default_watermark() -> str:
        # Last 24 h: enough to populate the last-alarm sensor without
        # replaying the whole history as events.
        ts = datetime.now(dt_timezone.utc) - timedelta(hours=24)
        return ts.strftime("%Y-%m-%d %H:%M:%S.000")

    async def _fetch_device(self, first: bool) -> dict[str, Any]:
        try:
            return await self.api.async_get_device(first=first)
        except ICarAuthError:
            _LOGGER.info("Session lost, logging in again")
            await self.api.async_login()
            return await self.api.async_get_device(first=True)

    async def _fetch_alarms(self) -> tuple[list[dict[str, Any]], str]:
        try:
            return await self.api.async_get_exceptions(self.watermark)
        except ICarAuthError:
            await self.api.async_login()
            return await self.api.async_get_exceptions(self.watermark)

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            device = await self._fetch_device(first=self.first_poll)
            alarms, new_watermark = await self._fetch_alarms()
        except ICarAuthError as exc:
            raise UpdateFailed(f"Authentication failed: {exc}") from exc
        except ICarApiError as exc:
            raise UpdateFailed(f"Platform error: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise UpdateFailed(f"Error communicating with platform: {exc}") from exc

        self.first_poll = False

        # Alarms come back newest-first; make them chronological.
        alarms = list(reversed(alarms))

        if self.first_alarm_batch:
            # Historical batch (first poll after restart): update the
            # sensor but do not replay old alarms as events.
            new_alarms: list[dict[str, Any]] = []
            self.first_alarm_batch = False
        else:
            new_alarms = alarms

        if new_watermark != self.entry.options.get(CONF_WATERMARK):
            self.hass.config_entries.async_update_entry(
                self.entry,
                options={**self.entry.options, CONF_WATERMARK: new_watermark},
            )

        last_alarm = alarms[-1] if alarms else (self.data or {}).get("last_alarm")

        return {
            "device": device,
            "battery": parse_battery(device.get("dataContext")),
            "new_alarms": new_alarms,
            "last_alarm": last_alarm,
        }
