"""Shared JackenBerater profile entity base."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN, INTEGRATION_VERSION, SIGNAL_PROFILE_UPDATED
from .profiles import ProfileManager


class JackenProfileEntity(Entity):
    """Base entity attached to one personal comfort profile."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, manager: ProfileManager, profile_id: str) -> None:
        self.entry = entry
        self.manager = manager
        self.profile_id = profile_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="JackenBerater",
            model="Personal Comfort Advisor",
            sw_version=INTEGRATION_VERSION,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_PROFILE_UPDATED.format(entry_id=self.entry.entry_id),
                self._profile_updated,
            )
        )

    def _profile_updated(self, profile_id: str) -> None:
        if profile_id == self.profile_id:
            # Profile names can follow later Home Assistant user renames.
            # Refresh translation placeholders for already-created entities too.
            if getattr(self, "_attr_translation_key", None):
                self._attr_translation_placeholders = {
                    "name": self.manager.profile_name(self.profile_id)
                }
            self.async_write_ha_state()
