"""JackenBerater integration."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.const import LOVELACE_DATA, MODE_STORAGE
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

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


async def _async_register_frontend(hass: HomeAssistant) -> None:
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("frontend_registered"):
        return

    frontend_dir = Path(__file__).parent / "frontend"
    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(FRONTEND_URL, str(frontend_dir), False)]
        )
    except RuntimeError as err:
        # Reloads may legitimately hit an already-registered path, but keep
        # unexpected registration failures diagnosable without breaking setup.
        _LOGGER.debug(
            "Frontend static path already registered or unavailable: %s", err
        )

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
    wanted = f"{base}?v={INTEGRATION_VERSION}"
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
    await _async_register_frontend(hass)
    async_register_api(hass)

    manager = ProfileManager(hass, entry)
    await manager.async_load()
    coordinator = JackenWeatherCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "profiles": manager,
        "coordinator": coordinator,
        "context_cache": {},
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
