"""Typed container for per-entry runtime data."""

from __future__ import annotations

from dataclasses import dataclass

from .api import ICarApi
from .coordinator import ICarCoordinator


@dataclass
class ICarEntryData:
    """Runtime data for one config entry."""

    api: ICarApi
    coordinator: ICarCoordinator
