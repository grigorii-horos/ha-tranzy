"""One sensor per stop: minutes to the next vehicle, the whole board in attributes."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import TranzyConfigEntry
from .const import CONF_AGENCY_ID, CONF_STOP_ID, CONF_STOP_NAME, DOMAIN, MAX_ARRIVALS, SUBENTRY_STOP
from .coordinator import TranzyCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: TranzyConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    for sub in entry.subentries.values():
        if sub.subentry_type == SUBENTRY_STOP:
            async_add_entities([StopBoardSensor(coordinator, sub)], config_subentry_id=sub.subentry_id)


class StopBoardSensor(CoordinatorEntity[TranzyCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_icon = "mdi:bus-clock"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_suggested_display_precision = 0
    # the board changes every scan; keep it out of the database
    _unrecorded_attributes = frozenset({"arrivals", "updated"})

    def __init__(self, coordinator: TranzyCoordinator, sub: ConfigSubentry) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._stop_id = int(sub.data[CONF_STOP_ID])
        self._attr_unique_id = f"{entry.data[CONF_AGENCY_ID]}_{self._stop_id}"
        stop = coordinator.index.stops.get(self._stop_id) if coordinator.index else None
        self._stop_name = stop.name if stop else sub.data[CONF_STOP_NAME]
        self._stop_code = stop.code if stop else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            name=sub.title,
            manufacturer=entry.title,
            model="Stop",
            model_id=str(self._stop_id),
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _arrivals(self):
        return (self.coordinator.data or {}).get(self._stop_id, [])

    @property
    def native_value(self) -> int | None:
        arrivals = self._arrivals
        if not arrivals:
            return None
        now = dt_util.utcnow()
        return max(0, int((arrivals[0].arrival - now).total_seconds() // 60))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        now = dt_util.utcnow()
        return {
            "stop_id": self._stop_id,
            "stop_name": self._stop_name,
            "stop_code": self._stop_code,
            "updated": now.isoformat(),
            "arrivals": [a.as_dict(now) for a in self._arrivals[:MAX_ARRIVALS]],
        }
