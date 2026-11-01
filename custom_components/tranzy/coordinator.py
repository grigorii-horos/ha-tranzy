"""One coordinator per agency: static index once a day, vehicles every scan."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import TranzyApi, TranzyAuthError, TranzyError
from .const import (
    CONF_LAYOVER,
    CONF_MAX_AGE,
    CONF_SCAN_INTERVAL,
    CONF_SPEED,
    CONF_STOP_ID,
    DEFAULT_LAYOVER,
    DEFAULT_MAX_AGE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SPEED,
    HORIZON,
    LOGGER,
    STATIC_TTL,
    SUBENTRY_STOP,
)
from .model import Arrival, TransitIndex


class TranzyCoordinator(DataUpdateCoordinator[dict[int, list[Arrival]]]):
    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: TranzyApi) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=entry.title,
            update_interval=timedelta(seconds=interval),
        )
        self.api = api
        self.index: TransitIndex | None = None
        self._index_at: datetime | None = None

    @property
    def stop_ids(self) -> list[int]:
        return [
            int(sub.data[CONF_STOP_ID])
            for sub in self.config_entry.subentries.values()
            if sub.subentry_type == SUBENTRY_STOP
        ]

    async def async_load_index(self) -> TransitIndex:
        data = await self.api.static()
        index = await self.hass.async_add_executor_job(lambda: TransitIndex.build(**data))
        self.index, self._index_at = index, dt_util.utcnow()
        LOGGER.debug("static index: %s trips, %s served stops", len(index.trips), len(index.trips_by_stop))
        return index

    async def _async_update_data(self) -> dict[int, list[Arrival]]:
        now = dt_util.utcnow()
        try:
            if self.index is None or now - self._index_at > STATIC_TTL:
                try:
                    await self.async_load_index()
                except TranzyError:
                    if self.index is None:
                        raise
                    LOGGER.warning("static data refresh failed, keeping the previous index", exc_info=True)
            vehicles = await self.api.vehicles()
        except TranzyAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except TranzyError as err:
            raise UpdateFailed(str(err)) from err

        opts = self.config_entry.options
        index = self.index
        stop_ids = self.stop_ids

        def compute() -> dict[int, list[Arrival]]:
            positions = index.locate(vehicles, now, timedelta(minutes=opts.get(CONF_MAX_AGE, DEFAULT_MAX_AGE)))
            return {
                stop_id: index.arrivals(
                    stop_id,
                    positions,
                    now,
                    opts.get(CONF_SPEED, DEFAULT_SPEED),
                    timedelta(minutes=opts.get(CONF_LAYOVER, DEFAULT_LAYOVER)),
                    HORIZON,
                )
                for stop_id in stop_ids
            }

        return await self.hass.async_add_executor_job(compute)
