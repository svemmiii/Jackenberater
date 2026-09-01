"""Authenticated WebSocket API used by the JackenBerater card."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
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


def _can_use_shared_profiles(connection: websocket_api.ActiveConnection, entry: ConfigEntry) -> bool:
    own_id = str(connection.user.id)
    allowed = entry.data.get(CONF_SHARED_USER_IDS, [])
    return bool(connection.user.is_admin) or (isinstance(allowed, list) and own_id in allowed)


async def _profile(
    connection: websocket_api.ActiveConnection,
    manager: ProfileManager,
    requested_id: str | None,
    entry: ConfigEntry,
) -> tuple[str, Any]:
    own_id = str(connection.user.id)
    own_name = str(connection.user.name or "Home-Assistant-Nutzer")
    await manager.async_ensure_profile(own_id, own_name)
    if requested_id and requested_id != own_id:
        if not _can_use_shared_profiles(connection, entry):
            raise ValueError("shared_profile_access_denied")
        if requested_id not in manager.profile_ids:
            raise ValueError("profile_not_found")
        return requested_id, manager.get_model(requested_id)
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
    work_start: datetime | None = None
    active_work_context = False
    work_entity = entry.data.get(CONF_WORK_WEATHER)
    if isinstance(work_entity, str) and work_entity:
        windows = await _cached_work_windows(hass, entry, runtime)
        work_forecast = list((coordinator.data or {}).get("work_forecast", []))
        if windows:
            work_start = windows[0][0]
            work_points = [
                point
                for point in work_forecast
                if any(start <= point.dt <= end for start, end in windows)
            ]
            # Always remove home forecast points inside probable work windows.
            # If work has no hourly forecast, a gap is more honest than silently
            # showing the weather from the wrong location.
            forecast = merge_location_timeline(forecast, work_forecast, windows)

        # When a shift is active right now, use the work weather as the current
        # context. This is explicitly a calendar/shift inference, not tracking.
        now = dt_util.now()
        if windows and any(start <= now <= end for start, end in windows):
            work_current = current_weather(hass, work_entity)
            if work_current is not None:
                current = work_current
                active_work_context = True
                # A selected living-room sensor is not representative at work.
                indoor = float(
                    entry.data.get(CONF_FALLBACK_INDOOR_TEMP, DEFAULT_FALLBACK_INDOOR_TEMP)
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
        work_name=work_name,
        calendar_context=context_horizon is not None,
        activity_context_c=activity,
        activity_context_fn=lambda when: activity_context_c(when, model.evening_answer),
    )
    recommendation.source = "work" if active_work_context else "home"
    if active_work_context and not recommendation.work_context:
        recommendation.work_context = True
        recommendation.work_jacket = recommendation.jacket_now
        recommendation.work_name = work_name
    return recommendation


async def _cached_work_windows(
    hass: HomeAssistant,
    entry: ConfigEntry,
    runtime: dict[str, Any],
) -> list[tuple[datetime, datetime]]:
    now = dt_util.now()
    cache = runtime.setdefault("context_cache", {})
    updated = cache.get("updated")
    if isinstance(updated, datetime) and now - updated < timedelta(minutes=15):
        return list(cache.get("work_windows", []))
    windows = await work_windows(hass, entry, now)
    cache["updated"] = now
    cache["work_windows"] = windows
    return windows


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
    if isinstance(updated, datetime) and now - updated < timedelta(minutes=15):
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
        "temperature_c": rec.current_temperature_c,
        "wind_kmh": _effective_wind(rec.current_wind_kmh, rec.current_gust_kmh),
        "condition": rec.current_condition,
        "effective_c": rec.effective_now_c,
        "transition_penalty_c": rec.transition_penalty_c,
    }
    later = {
        "jacket": rec.jacket_later,
        "temperature_c": rec.later_temperature_c,
        "wind_kmh": _effective_wind(rec.later_wind_kmh, rec.later_gust_kmh),
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
        profile_id, model = await _profile(connection, manager, msg.get("profile_id"), entry)
        rec = await _recommendation(hass, entry, runtime, model)
        connection.send_result(
            msg["id"],
            {
                "entry_id": entry.entry_id,
                "profile": manager.get_profile_summary(profile_id),
                "recommendation": rec.as_dict(),
                "feedback": manager.feedback_candidates(profile_id),
                "latest_session": manager.latest_session(profile_id),
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
    summaries = (
        manager.summaries()
        if _can_use_shared_profiles(connection, entry)
        else [manager.get_profile_summary(own_id)] if own_id in manager.profile_ids else []
    )
    connection.send_result(
        msg["id"],
        {
            "current_user_id": own_id,
            "shared_access": _can_use_shared_profiles(connection, entry),
            "profiles": summaries,
        },
    )
