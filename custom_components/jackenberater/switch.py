"""Per-profile learning switch."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, SIGNAL_PROFILE_CREATED
from .entity import JackenProfileEntity
from .profiles import ProfileManager


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    manager: ProfileManager = hass.data[DOMAIN][entry.entry_id]["profiles"]
    known: set[str] = set()
    def add(profile_id: str) -> None:
        if profile_id in known:
            return
        known.add(profile_id)
        async_add_entities([LearningSwitch(entry, manager, profile_id)])
    for profile_id in manager.profile_ids:
        add(profile_id)
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_PROFILE_CREATED.format(entry_id=entry.entry_id), add))


class LearningSwitch(JackenProfileEntity, SwitchEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:school"

    def __init__(self, entry, manager, profile_id) -> None:
        super().__init__(entry, manager, profile_id)
        self._attr_unique_id = f"{entry.entry_id}_{profile_id}_learning_enabled"
        self._attr_translation_key = "learning_enabled"
        self._attr_translation_placeholders = {"name": manager.profile_name(profile_id)}

    @property
    def is_on(self) -> bool:
        return self.manager.get_model(self.profile_id).learning_enabled

    async def async_turn_on(self, **kwargs) -> None:
        await self.manager.async_set_learning(self.profile_id, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.manager.async_set_learning(self.profile_id, False)
