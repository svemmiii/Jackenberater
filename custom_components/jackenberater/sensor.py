"""Per-profile compact diagnostics with non-persistent test simulation."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, MATCH_ALL
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    DOMAIN,
    INTEGRATION_VERSION,
    SIGNAL_PROFILE_CREATED,
    SIGNAL_PROFILE_UPDATED,
)
from .diagnostics import model_diagnostics, simulation_from_state
from .profiles import ProfileManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create one compact diagnostic entity for every existing profile."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    manager: ProfileManager = runtime["profiles"]
    known: set[str] = set()

    @callback
    def add(profile_id: str) -> None:
        if profile_id in known:
            return
        known.add(profile_id)
        async_add_entities(
            [ProfileDiagnosticsSensor(entry, manager, runtime, profile_id)]
        )

    for profile_id in manager.profile_ids:
        add(profile_id)
    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            SIGNAL_PROFILE_CREATED.format(entry_id=entry.entry_id),
            add,
        )
    )


class ProfileDiagnosticsSensor(SensorEntity):
    """Expose the fixed-size profile and accept only volatile state simulations."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:brain"
    _attr_has_entity_name = True
    _attr_should_poll = False
    # Home Assistant permissions are entity-wide, not attribute/profile-wide.
    # Keep the full model out of the state machine until an administrator
    # explicitly enables this troubleshooting entity.
    _attr_entity_registry_enabled_default = False
    # The live attributes are useful for inspection and simulation, but keeping
    # a database copy of the complete model after every update would merely
    # recreate the growing history this integration deliberately avoids.
    _unrecorded_attributes = frozenset({MATCH_ALL})

    def __init__(
        self,
        entry: ConfigEntry,
        manager: ProfileManager,
        runtime: dict,
        profile_id: str,
    ) -> None:
        self.entry = entry
        self.manager = manager
        self.runtime = runtime
        self.profile_id = profile_id
        self._attr_unique_id = f"{entry.entry_id}_{profile_id}_profile_diagnostics"
        self._attr_translation_key = "profile_diagnostics"
        self._attr_translation_placeholders = {
            "name": manager.profile_name(profile_id)
        }
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="JackenBerater",
            model="Personal Comfort Advisor",
            sw_version=INTEGRATION_VERSION,
        )

    @property
    def _simulation(self):
        return self.runtime.setdefault("simulations", {}).get(self.profile_id)

    @property
    def native_value(self) -> int:
        model = self._simulation or self.manager.get_model(self.profile_id)
        return model.total_feedback

    @property
    def extra_state_attributes(self) -> dict:
        simulation = self._simulation
        model = simulation or self.manager.get_model(self.profile_id)
        return model_diagnostics(model, simulation_active=simulation is not None)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_PROFILE_UPDATED.format(entry_id=self.entry.entry_id),
                self._profile_updated,
            )
        )
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self.entity_id],
                self._state_changed,
            )
        )

    @callback
    def _state_changed(self, event) -> None:
        # Integration writes have no user context. Only an intentional user
        # action (for example Developer Tools -> States) starts simulation.
        if event.context.user_id is None:
            return
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        real_model = self.manager.get_model(self.profile_id)
        simulated = simulation_from_state(
            real_model,
            new_state.state,
            dict(new_state.attributes),
        )
        simulations = self.runtime.setdefault("simulations", {})
        if simulated is None:
            simulations.pop(self.profile_id, None)
        else:
            simulations[self.profile_id] = simulated
        # Re-publish sanitized volatile values and the simulation marker. This
        # never touches ProfileManager or its persistent Store.
        self.async_write_ha_state()

    @callback
    def _profile_updated(self, profile_id: str) -> None:
        if profile_id != self.profile_id:
            return
        self.runtime.setdefault("simulations", {}).pop(self.profile_id, None)
        self._attr_translation_placeholders = {
            "name": self.manager.profile_name(self.profile_id)
        }
        self.async_write_ha_state()
