"""Diagnostic learning sensors."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, SIGNAL_PROFILE_CREATED
from .entity import JackenProfileEntity
from .profiles import ProfileManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    manager: ProfileManager = hass.data[DOMAIN][entry.entry_id]["profiles"]
    known: set[str] = set()

    def add(profile_id: str) -> None:
        if profile_id in known:
            return
        known.add(profile_id)
        async_add_entities([LearningStatusSensor(entry, manager, profile_id)])

    for profile_id in manager.profile_ids:
        add(profile_id)
    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            SIGNAL_PROFILE_CREATED.format(entry_id=entry.entry_id),
            add,
        )
    )


class LearningStatusSensor(JackenProfileEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:brain"

    def __init__(self, entry, manager, profile_id) -> None:
        super().__init__(entry, manager, profile_id)
        self._attr_unique_id = f"{entry.entry_id}_{profile_id}_learning_status"
        self._attr_translation_key = "learning_status"
        self._attr_translation_placeholders = {"name": manager.profile_name(profile_id)}

    @property
    def native_value(self):
        return self.manager.get_model(self.profile_id).total_feedback

    @property
    def extra_state_attributes(self):
        model = self.manager.get_model(self.profile_id)
        return {
            "confidence": round(model.confidence() * 100, 1),
            "learning_enabled": model.learning_enabled,
            "setup_complete": model.setup_complete,
            "general_offset_c": round(model.general_offset_c, 2),
            "wind_samples": model.wind_stat.samples,
            "transition_samples": model.transition_stat.samples,
            "light_boundary_samples": model.light_stat.samples,
            "warm_boundary_samples": model.warm_stat.samples,
            "winter_boundary_samples": model.winter_stat.samples,
        }
