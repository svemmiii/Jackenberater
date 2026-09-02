"""Authenticated WebSocket API used by the JackenBerater card."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
import math
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import (
    CALENDAR_MAX_HOURS,
    CONF_CONTEXT_CALENDAR,
    CONF_FALLBACK_INDOOR_TEMP,
    CONF_INDOOR_TEMP,
    CONF_RAIN_ADVICE,
    CONF_SHARED_USER_IDS,
    CONF_WEATHER,
    CONF_WORK_WEATHER,
    CONF_WORK_ZONE,
    DEFAULT_FALLBACK_INDOOR_TEMP,
    DOMAIN,
    FEEDBACK_VALUES,
    MAX_FORECAST_HOURS,
    PHASE_VALUES,
)
from .context import activity_context_c, calendar_context_horizon, work_windows
from .engine import build_recommendation, merge_location_timeline
from .models import Recommendation, WeatherPoint
from .profiles import ProfileManager
from .weather import current_weather, indoor_temperature_c

_LOGGER = logging.getLogger(__name__)


def async_register_api(hass: HomeAssistant) -> None:
    """Register commands once per Home Assistant process."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("api_registered"):
        return
    websocket_api.async_register_command(hass, ws_preview)
    websocket_api.async_register_command(hass, ws_open_session)
    websocket_api.async_register_command(hass, ws_profile_setup)
    websocket_api.async_register_command(hass, ws_feedback)
    websocket_api.async_register_command(hass, ws_profiles)
    websocket_api.async_register_command(hass, ws_profile_export)
    websocket_api.async_register_command(hass, ws_profile_import)
    websocket_api.async_register_command(hass, ws_profile_maintenance)
    domain_data["api_registered"] = True


def _runtime(hass: HomeAssistant, entry_id: str | None) -> tuple[ConfigEntry, dict[str, Any]]:
    entries = hass.config_entries.async_entries(DOMAIN)
    if entry_id:
        entry = next((item for item in entries if item.entry_id == entry_id), None)
    elif len(entries) == 1:
        entry = entries[0]
    else:
        entry = None
    if entry is None:
        raise ValueError("JackenBerater config entry not found")
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not isinstance(runtime, dict):
        raise ValueError("JackenBerater is not loaded")
    return entry, runtime


def _is_shared_account(connection: websocket_api.ActiveConnection, entry: ConfigEntry) -> bool:
    """Return whether this HA login is explicitly configured as a shared device."""
    own_id = str(connection.user.id)
    allowed = entry.data.get(CONF_SHARED_USER_IDS, [])
    return isinstance(allowed, list) and own_id in allowed


def _can_use_shared_profiles(connection: websocket_api.ActiveConnection, entry: ConfigEntry) -> bool:
    return bool(connection.user.is_admin) or _is_shared_account(connection, entry)


def _read_only_profile_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """Expose only what a wall tablet needs to select and render a profile."""
    return {
        key: summary[key]
        for key in ("id", "name", "setup_complete")
        if key in summary
    }


async def _profile(
    connection: websocket_api.ActiveConnection,
    manager: ProfileManager,
    requested_id: str | None,
    entry: ConfigEntry,
    *,
    allow_shared_read: bool = False,
) -> tuple[str, Any]:
    own_id = str(connection.user.id)
    own_name = str(connection.user.name or "Home-Assistant-Nutzer")

    if requested_id and requested_id != own_id:
        if not connection.user.is_admin and not (
            allow_shared_read and _is_shared_account(connection, entry)
        ):
            raise ValueError("shared_profile_access_denied")
        if requested_id not in manager.profile_ids:
            raise ValueError("profile_not_found")
        return requested_id, manager.get_model(requested_id)

    # A configured wall-tablet/shared login is only a control surface. It must
    # never silently become its own thermal comfort profile.
    if _is_shared_account(connection, entry):
        raise ValueError("shared_profile_required")

    await manager.async_ensure_profile(own_id, own_name)
    return own_id, manager.get_model(own_id)


async def _recommendation(
    hass: HomeAssistant,
    entry: ConfigEntry,
    runtime: dict[str, Any],
    model,
) -> Recommendation:
    coordinator = runtime["coordinator"]
    weather_entity = str(entry.data[CONF_WEATHER])
    current = current_weather(hass, weather_entity)
    if current is None:
        raise ValueError("weather_unavailable")

    indoor = indoor_temperature_c(
        hass,
        entry.data.get(CONF_INDOOR_TEMP),
        float(entry.data.get(CONF_FALLBACK_INDOOR_TEMP, DEFAULT_FALLBACK_INDOOR_TEMP)),
    )
    forecast = list((coordinator.data or {}).get("home_forecast", []))
    activity = activity_context_c(dt_util.now(), model.evening_answer)
    context_horizon = await _cached_calendar_horizon(hass, entry, runtime)
    base_horizon = max(9, context_horizon or 0)
    max_horizon = max(MAX_FORECAST_HOURS, min(CALENDAR_MAX_HOURS, context_horizon or 0))

    work_points: list[WeatherPoint] = []
    work_weather_available = True
    work_start: datetime | None = None
    work_end: datetime | None = None
    active_work_context = False
    work_entity = entry.data.get(CONF_WORK_WEATHER)
    if isinstance(work_entity, str) and work_entity:
        actual_windows, planning_windows = await _cached_work_window_sets(
            hass, entry, runtime
        )
        work_forecast = list((coordinator.data or {}).get("work_forecast", []))
        now = dt_util.now()
        if planning_windows:
            chosen_window = (actual_windows or planning_windows)[0]
            work_start = chosen_window[0]
            work_end = chosen_window[1] if actual_windows else None
            work_points = [
                point
                for point in work_forecast
                if point.dt > current.dt
                and any(start <= point.dt <= end for start, end in planning_windows)
            ]
            if not work_points:
                work_weather_available = False
            # Planning relevance starts 30 minutes around the work period, but the
            # current location does not. Home forecast points are replaced only for
            # the planning timeline; current weather switches below using the actual
            # unbuffered work window.
            forecast = merge_location_timeline(
                forecast, work_forecast, planning_windows
            )

        # Only the unbuffered actual work window may replace the *current* weather.
        # The ±30 minute planning buffer is for “take it with you”, not a location
        # claim about where the user already is.
        if actual_windows and any(start <= now <= end for start, end in actual_windows):
            work_current = current_weather(hass, work_entity)
            if work_current is None:
                # During an actual work window, silently falling back to home
                # weather would claim conditions for the wrong location. Prefer
                # an explicit temporary gap until the work source is usable.
                raise ValueError("work_weather_unavailable")
            current = work_current
            active_work_context = True
            # A selected living-room sensor is not representative at work.
            indoor = float(
                entry.data.get(CONF_FALLBACK_INDOOR_TEMP, DEFAULT_FALLBACK_INDOOR_TEMP)
            )

    # If work planning extends the recommendation beyond the ordinary 12-hour
    # weather window, the home timeline must be evaluated to the same claimed
    # end time. Otherwise a home cold/rain event at e.g. +13 h could be skipped
    # while a work point at +14 h makes the card claim a 14-hour horizon.
    if work_points:
        latest_work = max(point.dt for point in work_points)
        work_horizon = math.ceil(
            max(0.0, (latest_work - current.dt).total_seconds()) / 3600.0
        )
        max_horizon = max(
            max_horizon,
            min(CALENDAR_MAX_HOURS, work_horizon),
        )

    work_name = None
    work_zone = entry.data.get(CONF_WORK_ZONE)
    if isinstance(work_zone, str) and work_zone:
        zone_state = hass.states.get(work_zone)
        if zone_state is not None:
            work_name = zone_state.name

    recommendation = build_recommendation(
        current,
        forecast,
        model,
        indoor_temperature_c=indoor,
        base_horizon_hours=base_horizon,
        max_horizon_hours=max_horizon,
        rain_advice=bool(entry.data.get(CONF_RAIN_ADVICE, True)),
        work_points=work_points,
        work_start=work_start,
        work_end=work_end,
        work_name=work_name,
        calendar_context=context_horizon is not None,
        activity_context_c=activity,
        activity_context_fn=lambda when: activity_context_c(when, model.evening_answer),
    )
    recommendation.source = "work" if active_work_context else "home"
    recommendation.work_weather_available = work_weather_available
    if active_work_context and not recommendation.work_context:
        recommendation.work_context = True
        recommendation.work_jacket = recommendation.jacket_now
        recommendation.work_name = work_name
    return recommendation


async def _cached_work_window_sets(
    hass: HomeAssistant,
    entry: ConfigEntry,
    runtime: dict[str, Any],
) -> tuple[list[tuple[datetime, datetime]], list[tuple[datetime, datetime]]]:
    now = dt_util.now()
    cache = runtime.setdefault("context_cache", {})
    updated = cache.get("updated")
    age = now - updated if isinstance(updated, datetime) else None
    if isinstance(age, timedelta) and timedelta(0) <= age < timedelta(minutes=15):
        return (
            list(cache.get("work_windows_actual", [])),
            list(cache.get("work_windows_planning", [])),
        )
    actual, planning = await work_windows(hass, entry, now, return_actual=True)
    cache["updated"] = now
    cache["work_windows_actual"] = actual
    cache["work_windows_planning"] = planning
    return actual, planning


async def _cached_calendar_horizon(
    hass: HomeAssistant,
    entry: ConfigEntry,
    runtime: dict[str, Any],
) -> int | None:
    if not entry.data.get(CONF_CONTEXT_CALENDAR):
        return None
    now = dt_util.now()
    cache = runtime.setdefault("context_cache", {})
    updated = cache.get("calendar_updated")
    age = now - updated if isinstance(updated, datetime) else None
    if isinstance(age, timedelta) and timedelta(0) <= age < timedelta(minutes=15):
        value = cache.get("calendar_horizon")
        return int(value) if isinstance(value, int) else None
    value = await calendar_context_horizon(hass, entry, now)
    cache["calendar_updated"] = now
    cache["calendar_horizon"] = value
    return value


def _effective_wind(wind_kmh: float | None, gust_kmh: float | None) -> float | None:
    values = [value for value in (wind_kmh, gust_kmh) if value is not None]
    return max(values) if values else None


def _weather_context(rec: Recommendation) -> dict[str, Any]:
    """Small display reminder for the historical feedback card."""
    return {
        "temperature_c": rec.current_temperature_c,
        "wind_kmh": _effective_wind(rec.current_wind_kmh, rec.current_gust_kmh),
        "condition": rec.current_condition,
        "effective_c": rec.effective_now_c,
    }


def _learning_contexts(rec: Recommendation) -> dict[str, dict[str, Any]]:
    """Store the actual start/later contexts used by feedback learning."""
    start = {
        "jacket": rec.jacket_now,
        "observed_at": dt_util.now().isoformat(),
        "temperature_c": rec.current_temperature_c,
        "wind_kmh": _effective_wind(rec.current_wind_kmh, rec.current_gust_kmh),
        "wind_penalty_c": rec.current_wind_penalty_c,
        "condition": rec.current_condition,
        "effective_c": rec.effective_now_c,
        "transition_penalty_c": rec.transition_penalty_c,
        "transient_override": rec.transient_override,
        "transient_direction": rec.transient_direction,
        "transient_burden": rec.transient_burden,
    }
    later = {
        "jacket": rec.jacket_later,
        "observed_at": rec.later_at.isoformat() if rec.later_at is not None else None,
        "temperature_c": rec.later_temperature_c,
        "wind_kmh": _effective_wind(rec.later_wind_kmh, rec.later_gust_kmh),
        "wind_penalty_c": rec.later_wind_penalty_c,
        "condition": rec.later_condition,
        "effective_c": rec.later_effective_c,
        # Indoor->outdoor transition belongs to the deliberate 'go out now'
        # moment, not automatically to a later forecast point.
        "transition_penalty_c": 0.0,
    }
    return {"start": start, "later": later}


@websocket_api.websocket_command(
    {
        vol.Required("type"): "jackenberater/preview",
        vol.Optional("entry_id"): str,
        vol.Optional("profile_id"): str,
    }
)
@websocket_api.async_response
async def ws_preview(hass, connection, msg) -> None:
    try:
        entry, runtime = _runtime(hass, msg.get("entry_id"))
        manager: ProfileManager = runtime["profiles"]
        profile_id, model = await _profile(
            connection,
            manager,
            msg.get("profile_id"),
            entry,
            allow_shared_read=True,
        )
        rec = await _recommendation(hass, entry, runtime, model)
        read_only_shared = _is_shared_account(connection, entry) and not connection.user.is_admin
        summary = manager.get_profile_summary(profile_id)
        connection.send_result(
            msg["id"],
            {
                "entry_id": entry.entry_id,
                "profile": _read_only_profile_summary(summary) if read_only_shared else summary,
                "recommendation": rec.as_dict(),
                "feedback": [] if read_only_shared else manager.feedback_candidates(profile_id),
                "latest_session": None if read_only_shared else manager.latest_session(profile_id),
            },
        )
    except ValueError as err:
        connection.send_error(msg["id"], "unavailable", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "jackenberater/open_session",
        vol.Optional("entry_id"): str,
        vol.Optional("profile_id"): str,
    }
)
@websocket_api.async_response
async def ws_open_session(hass, connection, msg) -> None:
    try:
        entry, runtime = _runtime(hass, msg.get("entry_id"))
        manager: ProfileManager = runtime["profiles"]
        profile_id, model = await _profile(connection, manager, msg.get("profile_id"), entry)
        rec = await _recommendation(hass, entry, runtime, model)
        session = await manager.async_open_session(
            profile_id,
            rec,
            weather_context=_weather_context(rec),
            learning_contexts=_learning_contexts(rec),
        )
        connection.send_result(
            msg["id"],
            {
                "profile": manager.get_profile_summary(profile_id),
                "recommendation": rec.as_dict(),
                "session": session,
                "feedback": manager.feedback_candidates(profile_id),
            },
        )
    except ValueError as err:
        connection.send_error(msg["id"], "unavailable", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "jackenberater/profile_setup",
        vol.Optional("entry_id"): str,
        vol.Optional("profile_id"): str,
        vol.Required("cold"): vol.All(int, vol.Range(min=1, max=5)),
        vol.Required("warm"): vol.All(int, vol.Range(min=1, max=5)),
        vol.Required("wind"): vol.All(int, vol.Range(min=1, max=5)),
        vol.Required("evening"): vol.All(int, vol.Range(min=1, max=5)),
    }
)
@websocket_api.async_response
async def ws_profile_setup(hass, connection, msg) -> None:
    try:
        entry, runtime = _runtime(hass, msg.get("entry_id"))
        manager: ProfileManager = runtime["profiles"]
        profile_id, _ = await _profile(connection, manager, msg.get("profile_id"), entry)
        await manager.async_setup_profile(
            profile_id,
            cold=msg["cold"],
            warm=msg["warm"],
            wind=msg["wind"],
            evening=msg["evening"],
        )
        connection.send_result(msg["id"], manager.get_profile_summary(profile_id))
    except ValueError as err:
        connection.send_error(msg["id"], "unavailable", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "jackenberater/feedback",
        vol.Optional("entry_id"): str,
        vol.Optional("profile_id"): str,
        vol.Required("session_id"): str,
        vol.Required("rating"): vol.In(FEEDBACK_VALUES),
        vol.Optional("phase"): vol.Any(None, vol.In(PHASE_VALUES)),
        vol.Optional("recommendation_used", default=True): vol.Any(None, bool),
        vol.Optional("unusual_day", default=False): bool,
        vol.Optional("voluntary", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_feedback(hass, connection, msg) -> None:
    try:
        entry, runtime = _runtime(hass, msg.get("entry_id"))
        manager: ProfileManager = runtime["profiles"]
        profile_id, _ = await _profile(connection, manager, msg.get("profile_id"), entry)
        session = await manager.async_feedback(
            profile_id,
            msg["session_id"],
            rating=msg["rating"],
            phase=msg.get("phase"),
            recommendation_used=msg.get("recommendation_used"),
            unusual_day=msg.get("unusual_day", False),
            voluntary=msg.get("voluntary", False),
        )
        connection.send_result(
            msg["id"],
            {
                "session": session,
                "profile": manager.get_profile_summary(profile_id),
            },
        )
    except (ValueError, KeyError) as err:
        connection.send_error(msg["id"], "invalid_feedback", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "jackenberater/profiles",
        vol.Optional("entry_id"): str,
        vol.Optional("profile_id"): str,
    }
)
@callback
def ws_profiles(hass, connection, msg) -> None:
    try:
        entry, runtime = _runtime(hass, msg.get("entry_id"))
    except ValueError as err:
        connection.send_error(msg["id"], "unavailable", str(err))
        return
    manager: ProfileManager = runtime["profiles"]
    own_id = str(connection.user.id)
    shared_account = _is_shared_account(connection, entry)
    if _can_use_shared_profiles(connection, entry):
        summaries = [
            summary
            for summary in manager.summaries()
            if not (shared_account and summary.get("id") == own_id)
        ]
        if shared_account and not connection.user.is_admin:
            summaries = [_read_only_profile_summary(summary) for summary in summaries]
    else:
        summaries = (
            [manager.get_profile_summary(own_id)] if own_id in manager.profile_ids else []
        )
    connection.send_result(
        msg["id"],
        {
            "entry_id": entry.entry_id,
            "current_user_id": own_id,
            "shared_access": _can_use_shared_profiles(connection, entry),
            "shared_account": shared_account,
            "is_admin": bool(connection.user.is_admin),
            "profiles": summaries,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "jackenberater/profile_export",
        vol.Optional("entry_id"): str,
        vol.Optional("profile_id"): str,
    }
)
@callback
def ws_profile_export(hass, connection, msg) -> None:
    """Export only compact personal learning state, never session/weather history."""
    try:
        entry, runtime = _runtime(hass, msg.get("entry_id"))
        manager: ProfileManager = runtime["profiles"]
        own_id = str(connection.user.id)
        requested = msg.get("profile_id")
        if requested and requested != own_id:
            if not connection.user.is_admin:
                raise ValueError("shared_profile_access_denied")
            if requested not in manager.profile_ids:
                raise ValueError("profile_not_found")
            profile_id = requested
        else:
            if _is_shared_account(connection, entry):
                raise ValueError("shared_profile_required")
            profile_id = own_id
            if profile_id not in manager.profile_ids:
                raise ValueError("profile_not_found")
        connection.send_result(msg["id"], manager.export_profile(profile_id))
    except (ValueError, KeyError) as err:
        connection.send_error(msg["id"], "profile_export_failed", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "jackenberater/profile_import",
        vol.Optional("entry_id"): str,
        vol.Optional("profile_id"): str,
        vol.Required("payload"): dict,
    }
)
@websocket_api.async_response
async def ws_profile_import(hass, connection, msg) -> None:
    """Restore a compact profile backup.

    A user may restore their own profile. Replacing somebody else's profile is
    reserved for HA administrators even when a shared wall-tablet login can read
    and use that profile for advice.
    """
    try:
        entry, runtime = _runtime(hass, msg.get("entry_id"))
        manager: ProfileManager = runtime["profiles"]
        own_id = str(connection.user.id)
        requested = msg.get("profile_id")
        if requested and requested != own_id:
            if not connection.user.is_admin:
                raise ValueError("profile_import_admin_required")
            if requested not in manager.profile_ids:
                raise ValueError("profile_not_found")
            profile_id = requested
        else:
            if _is_shared_account(connection, entry):
                raise ValueError("shared_profile_required")
            profile_id = own_id
            await manager.async_ensure_profile(
                profile_id, str(connection.user.name or "Home-Assistant-Nutzer")
            )
        model = await manager.async_import_profile(profile_id, msg["payload"])
        connection.send_result(
            msg["id"],
            {
                "profile": manager.get_profile_summary(profile_id),
                "setup_complete": model.setup_complete,
            },
        )
    except (ValueError, KeyError) as err:
        connection.send_error(msg["id"], "profile_import_failed", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "jackenberater/profile_maintenance",
        vol.Optional("entry_id"): str,
        vol.Optional("profile_id"): str,
        vol.Required("action"): vol.In({"learning_on", "learning_off", "reset", "undo"}),
    }
)
@websocket_api.async_response
async def ws_profile_maintenance(hass, connection, msg) -> None:
    """Run profile-changing maintenance only after authenticated profile checks."""
    try:
        entry, runtime = _runtime(hass, msg.get("entry_id"))
        manager: ProfileManager = runtime["profiles"]
        profile_id, _ = await _profile(connection, manager, msg.get("profile_id"), entry)
        action = msg["action"]
        result: bool | None = None
        if action in {"learning_on", "learning_off"}:
            await manager.async_set_learning(profile_id, action == "learning_on")
        elif action == "reset":
            await manager.async_reset_learning(profile_id)
        else:
            result = await manager.async_undo_last_feedback(profile_id)
        connection.send_result(
            msg["id"],
            {"profile": manager.get_profile_summary(profile_id), "result": result},
        )
    except (ValueError, KeyError) as err:
        connection.send_error(msg["id"], "profile_maintenance_failed", str(err))
