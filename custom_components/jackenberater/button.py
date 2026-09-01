"""Per-profile maintenance buttons."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
        async_add_entities([
            ResetLearningButton(entry, manager, profile_id),
            UndoFeedbackButton(entry, manager, profile_id),
        ])
    for profile_id in manager.profile_ids:
        add(profile_id)
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_PROFILE_CREATED.format(entry_id=entry.entry_id), add))


class ResetLearningButton(JackenProfileEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:restore"

    def __init__(self, entry, manager, profile_id) -> None:
        super().__init__(entry, manager, profile_id)
        self._attr_unique_id = f"{entry.entry_id}_{profile_id}_reset_learning"
        self._attr_translation_key = "reset_learning"
        self._attr_translation_placeholders = {"name": manager.profile_name(profile_id)}

    async def async_press(self) -> None:
        await self.manager.async_reset_learning(self.profile_id)


class UndoFeedbackButton(JackenProfileEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:undo"

    def __init__(self, entry, manager, profile_id) -> None:
        super().__init__(entry, manager, profile_id)
        self._attr_unique_id = f"{entry.entry_id}_{profile_id}_undo_feedback"
        self._attr_translation_key = "undo_feedback"
        self._attr_translation_placeholders = {"name": manager.profile_name(profile_id)}

    async def async_press(self) -> None:
        await self.manager.async_undo_last_feedback(self.profile_id)
