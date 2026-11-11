"""How far the similar-photo service has got with analysing the library."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .similarity import SimilarityError

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    lib = hass.data[DOMAIN]
    if lib.similarity is None:
        return
    client = lib.similarity

    async def _update() -> dict:
        try:
            return await client.async_status()
        except SimilarityError as err:
            raise UpdateFailed(str(err)) from err

    coordinator = DataUpdateCoordinator(
        hass, _LOGGER, config_entry=entry, name="similar photos", update_method=_update,
        update_interval=timedelta(minutes=1),
    )
    await coordinator.async_refresh()
    async_add_entities([SimilarityIndexSensor(coordinator, entry)])


class SimilarityIndexSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "similarity_index"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:image-search"

    def __init__(self, coordinator: DataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_similarity_index"

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data or {}
        total, indexed = data.get("total"), data.get("indexed") or 0
        if not total:
            return None if total is None else 100.0
        done = indexed + (data.get("failed") or 0)
        return round(min(100.0, 100.0 * done / total), 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        return {key: data.get(key) for key in ("indexed", "failed", "total", "pending", "scanning", "model")}
