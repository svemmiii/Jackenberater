"""JackenBerater integration."""
from __future__ import annotations

import logging
from pathlib import Path
from datetime import timedelta

from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.const import LOVELACE_DATA, MODE_STORAGE
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_interval

from .api import async_register_api
from .const import (
    CONF_SHIFT_PATTERN,
    CONF_WORK_CALENDAR,
    CONF_WORK_MODE,
    CONF_WORKDAY_END,
    CONF_WORKDAY_START,
    DEFAULT_WORKDAY_END,
    DEFAULT_WORKDAY_START,
    DOMAIN,
    INTEGRATION_VERSION,
    PLATFORMS,
    WORK_MODE_SHIFT,
    WORK_MODE_WEEKDAY,
)
from .profiles import ProfileManager
from .weather import JackenWeatherCoordinator

_LOGGER = logging.getLogger(__name__)

FRONTEND_URL = "/jackenberater/frontend"
FRONTEND_FILE = "jackenberater-card.js"
# UI-only cache revision. The integration release stays 0.1.5 while Lovelace
# still receives a new resource URL for frontend-only fixes.
FRONTEND_CACHE_REVISION = "4"
LEGACY_PROFILE_ENTITY_SUFFIXES = (
    "_learning_enabled",
    "_reset_learning",
    "_undo_feedback",
    "_learning_status",
)


def _async_remove_legacy_profile_entities(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Remove registry leftovers from the retired global profile platforms."""
    entity_registry = er.async_get(hass)
    for entity in list(er.async_entries_for_config_entry(entity_registry, entry.entry_id)):
        if (
            entity.platform == DOMAIN
            and entity.entity_id.split(".", 1)[0] in {"button", "switch", "sensor"}
            and entity.unique_id.startswith(f"{entry.entry_id}_")
            and entity.unique_id.endswith(LEGACY_PROFILE_ENTITY_SUFFIXES)
        ):
            entity_registry.async_remove(entity.entity_id)

    # The old entities all shared one integration-owned device. Once their
    # registry entries are gone, remove that obsolete device card as well.
    device_registry = dr.async_get(hass)
    remaining_device_ids = {
        entity.device_id
        for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id)
        if entity.device_id is not None
    }
    for device in list(dr.async_entries_for_config_entry(device_registry, entry.entry_id)):
        if (
            (DOMAIN, entry.entry_id) in device.identifiers
            and device.id not in remaining_device_ids
        ):
            device_registry.async_remove_device(device.id)


def _async_remove_orphan_profile_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry, profile_ids: list[str]
) -> None:
    """Remove diagnostic registry entries for profiles pruned before sensors load."""
    entity_registry = er.async_get(hass)
    expected = {
        f"{entry.entry_id}_{profile_id}_profile_diagnostics"
        for profile_id in profile_ids
    }
    for entity in list(er.async_entries_for_config_entry(entity_registry, entry.entry_id)):
        if (
            entity.platform == DOMAIN
            and entity.entity_id.split(".", 1)[0] == "sensor"
            and entity.unique_id.startswith(f"{entry.entry_id}_")
            and entity.unique_id.endswith("_profile_diagnostics")
            and entity.unique_id not in expected
        ):
            entity_registry.async_remove(entity.entity_id)


async def _async_register_frontend(hass: HomeAssistant) -> None:
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("frontend_registered"):
        return

    frontend_dir = Path(__file__).parent / "frontend"
    if not domain_data.get("frontend_path_registered"):
        # Do not blanket-swallow RuntimeError here. A real registration failure
        # must fail setup visibly; successful path registration is remembered
        # separately so a later partial setup retry does not register it twice.
        await hass.http.async_register_static_paths(
            [StaticPathConfig(FRONTEND_URL, str(frontend_dir), False)]
        )
        domain_data["frontend_path_registered"] = True

    lovelace = hass.data.get(LOVELACE_DATA)
    if lovelace is None or lovelace.resource_mode != MODE_STORAGE:
        _LOGGER.info(
            "Lovelace storage resources unavailable; add %s/%s manually",
            FRONTEND_URL,
            FRONTEND_FILE,
        )
        domain_data["frontend_registered"] = True
        return
    resources = lovelace.resources
    await resources.async_get_info()
    base = f"{FRONTEND_URL}/{FRONTEND_FILE}"
    wanted = f"{base}?v={INTEGRATION_VERSION}&ui={FRONTEND_CACHE_REVISION}"
    existing = next(
        (
            item
            for item in resources.async_items()
            if str(item.get("url", "")).split("?", 1)[0] == base
        ),
        None,
    )
    if existing is None:
        await resources.async_create_item({"res_type": "module", "url": wanted})
    elif existing.get("url") != wanted or existing.get("type") != "module":
        await resources.async_update_item(
            existing["id"], {"res_type": "module", "url": wanted}
        )

    domain_data["frontend_registered"] = True


async def _async_remove_frontend_resource(hass: HomeAssistant) -> None:
    """Remove the storage-mode Lovelace resource owned by JackenBerater."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    lovelace = hass.data.get(LOVELACE_DATA)
    if lovelace is not None and lovelace.resource_mode == MODE_STORAGE:
        resources = lovelace.resources
        await resources.async_get_info()
        base = f"{FRONTEND_URL}/{FRONTEND_FILE}"
        for item in list(resources.async_items()):
            if str(item.get("url", "")).split("?", 1)[0] == base:
                await resources.async_delete_item(item["id"])
    # Keep the static-path marker: Home Assistant still owns that registration
    # for this process. A later re-add should recreate only the Lovelace item.
    domain_data["frontend_registered"] = False


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate the unreleased v0.1.0 work-context shape to v0.1.1."""
    if entry.version == 1 and entry.minor_version < 1:
        data = dict(entry.data)
        data.setdefault(
            CONF_WORK_MODE,
            WORK_MODE_SHIFT if data.get(CONF_SHIFT_PATTERN) else WORK_MODE_WEEKDAY,
        )
        data.setdefault(CONF_WORKDAY_START, DEFAULT_WORKDAY_START)
        data.setdefault(CONF_WORKDAY_END, DEFAULT_WORKDAY_END)
        # v0.1.1 no longer requires a calendar containing explicit work events.
        # Keep vacation/absence as an optional suppressor instead.
        data.pop(CONF_WORK_CALENDAR, None)
        hass.config_entries.async_update_entry(
            entry, data=data, version=1, minor_version=1
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _async_remove_legacy_profile_entities(hass, entry)
    await _async_register_frontend(hass)
    async_register_api(hass)

    manager = ProfileManager(hass, entry)
    await manager.async_load()
    # Keep stored profile names aligned with Home Assistant and remove profiles
    # whose HA user was actually deleted. Inactive-but-existing users are kept.
    manager.sync_user_directory(await hass.auth.async_get_users())
    # At startup PROFILE_DELETED listeners from the sensor platform do not exist
    # yet. Remove stale diagnostic registry entries directly after pruning users.
    _async_remove_orphan_profile_diagnostics(hass, entry, manager.profile_ids)

    async def _async_sync_user_directory(_now) -> None:
        manager.sync_user_directory(await hass.auth.async_get_users())

    entry.async_on_unload(
        async_track_time_interval(
            hass,
            _async_sync_user_directory,
            timedelta(minutes=30),
        )
    )
    coordinator = JackenWeatherCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    # DataUpdateCoordinator only schedules update_interval polling while at least
    # one listener is registered. JackenBerater consumes the coordinator directly
    # from its WebSocket API instead of through CoordinatorEntity, so keep one
    # integration-owned listener alive or the startup forecast would slowly age
    # away until only the final cached hour remained.
    entry.async_on_unload(coordinator.async_add_listener(lambda: None))

    entry.runtime_data = {
        "profiles": manager,
        "coordinator": coordinator,
        "context_cache": {},
        "simulations": {},
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Profile writes are intentionally delayed during normal operation. Force the
    # current in-memory state to disk before a reload can create a new manager.
    runtime = getattr(entry, "runtime_data", None)
    if isinstance(runtime, dict):
        manager = runtime.get("profiles")
        if isinstance(manager, ProfileManager):
            await manager.async_flush()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove integration-owned frontend and personal profile storage."""
    runtime = getattr(entry, "runtime_data", None)
    manager = runtime.get("profiles") if isinstance(runtime, dict) else None
    if not isinstance(manager, ProfileManager):
        manager = ProfileManager(hass, entry)
    await manager.async_remove_storage()
    await _async_remove_frontend_resource(hass)


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
