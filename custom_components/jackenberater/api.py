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
    CALENDAR_STATUS_AVAILABLE,
    CALENDAR_STATUS_NOT_APPLICABLE,
    CALENDAR_STATUS_NOT_CONFIGURED,
    CALENDAR_STATUS_UNAVAILABLE,
    CONF_CONTEXT_CALENDAR,
    CONF_FALLBACK_INDOOR_TEMP,
    CONF_INDOOR_TEMP,
    CONF_RAIN_ADVICE,
    CONF_SHARED_USER_IDS,
    CONF_VACATION_CALENDAR,
    CONF_WEATHER,
    CONF_WORK_WEATHER,
    CONF_WORK_ZONE,
    DEFAULT_FALLBACK_INDOOR_TEMP,
    DEFAULT_FORECAST_HOURS,
    DOMAIN,
    FORECAST_REFRESH,
    FEEDBACK_VALUES,
    MAX_FORECAST_HOURS,
    WORK_BUFFER,
    PHASE_VALUES,
    PROFILE_BACKUP_ENABLED,
)
from .context import activity_context_c, calendar_context_horizon, work_windows
from .diagnostics import model_diagnostics
from .engine import build_recommendation, merge_location_timeline
from .models import Recommendation, WeatherPoint
from .profiles import ProfileManager
from .time_utils import (
    elapsed,
    instant_key,
    is_after,
    is_before,
    is_between,
    is_between_half_open,
    real_add,
)
from .weather import current_weather, indoor_temperature_c

_LOGGER = logging.getLogger(__name__)

# Short shared cache: state events invalidate immediately when providers emit
# them; this TTL limits JackenBerater-owned staleness when calendar CRUD does not
# produce an entity-state change.
_CONTEXT_CACHE_TTL = timedelta(minutes=1)
_FORECAST_FAILURE_RETRY = timedelta(minutes=1)


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
    websocket_api.async_register_command(hass, ws_profile_revision)
    if PROFILE_BACKUP_ENABLED:
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
    has_runtime_data = hasattr(entry, "runtime_data")
    runtime = getattr(entry, "runtime_data", None)
    # Compatibility fallback for lightweight tests/older harnesses that do not
    # expose ConfigEntry.runtime_data at all. A real ConfigEntry with runtime_data
    # present but cleared/replaced must never fall back to stale hass.data.
    if not isinstance(runtime, dict) and not has_runtime_data:
        runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not isinstance(runtime, dict):
        raise ValueError("JackenBerater is not loaded")
    if runtime.get("unloading"):
        raise ValueError("integration_reloading")
    state = getattr(entry, "state", None)
    state_value = getattr(state, "value", state)
    if state is not None and state_value != "loaded":
        raise ValueError("integration_reloading")
    return entry, runtime


def _runtime_is_current(
    entry: ConfigEntry,
    runtime: dict[str, Any],
    manager: ProfileManager | None = None,
) -> bool:
    """Return whether an async request still owns the active entry runtime."""
    current = getattr(entry, "runtime_data", None)
    if hasattr(entry, "runtime_data") and current is not runtime:
        return False
    if runtime.get("unloading"):
        return False
    state = getattr(entry, "state", None)
    state_value = getattr(state, "value", state)
    if state is not None and state_value != "loaded":
        return False
    if manager is not None and runtime.get("profiles") is not manager:
        return False
    return True


def _ensure_runtime_current(
    entry: ConfigEntry,
    runtime: dict[str, Any],
    manager: ProfileManager | None = None,
) -> None:
    if not _runtime_is_current(entry, runtime, manager):
        raise ValueError("integration_reloading")


def _shared_control_ids(entry: ConfigEntry) -> set[str]:
    """Return HA user IDs currently configured as shared/control surfaces."""
    allowed = entry.data.get(CONF_SHARED_USER_IDS, [])
    if not isinstance(allowed, list):
        return set()
    return {str(user_id) for user_id in allowed if str(user_id)}


def _is_shared_account(connection: websocket_api.ActiveConnection, entry: ConfigEntry) -> bool:
    """Return whether this HA login is explicitly configured as a shared device."""
    return str(connection.user.id) in _shared_control_ids(entry)


def _can_use_shared_profiles(connection: websocket_api.ActiveConnection, entry: ConfigEntry) -> bool:
    return bool(connection.user.is_admin) or _is_shared_account(connection, entry)


def _read_only_profile_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """Expose only what a wall tablet needs to select and render a profile."""
    return {
        key: summary[key]
        for key in ("id", "name", "setup_complete")
        if key in summary
    }


def _profile_summary_for_connection(
    connection: websocket_api.ActiveConnection,
    entry: ConfigEntry,
    summary: dict[str, Any],
) -> dict[str, Any]:
    """Hide personal learning metadata on non-admin shared control surfaces."""
    if _is_shared_account(connection, entry) and not connection.user.is_admin:
        return _read_only_profile_summary(summary)
    return summary


def _revision_token_for_connection(
    connection: websocket_api.ActiveConnection,
    entry: ConfigEntry,
    manager: ProfileManager,
    requested_id: str | None,
) -> str:
    """Return only the revision scope relevant to this authenticated card."""
    own_id = str(connection.user.id)
    shared_account = _is_shared_account(connection, entry)

    if requested_id and requested_id != own_id:
        if not _can_use_shared_profiles(connection, entry):
            raise ValueError("shared_profile_access_denied")
        if requested_id not in manager.profile_ids:
            # A shared card may still poll with a just-deleted selection. Return
            # the directory token so it refreshes the profile list and clears
            # that stale selection instead of getting stuck until the fallback.
            return str(getattr(manager, "directory_revision_token", getattr(manager, "revision_token", "legacy:0")))
        # Shared/admin selectors need directory changes (rename/delete) plus the
        # selected person's model revision, but not unrelated model changes.
        token = getattr(manager, "card_revision_token", None)
        if callable(token):
            return token(requested_id, include_directory=True)
        return str(getattr(manager, "revision_token", "legacy:0"))

    if shared_account:
        # No selected person yet: only the selectable profile directory matters.
        return str(getattr(manager, "directory_revision_token", getattr(manager, "revision_token", "legacy:0")))

    token = getattr(manager, "card_revision_token", None)
    if callable(token):
        return token(own_id, include_directory=False)
    token = getattr(manager, "profile_revision_token", None)
    if callable(token):
        return token(own_id)
    return str(getattr(manager, "revision_token", "legacy:0"))


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
        # Accounts currently configured as wall-tablet/shared control surfaces
        # are not advice personas. Their old personal model may remain stored so
        # it can reappear if the account becomes normal again, but preview/session/
        # feedback must never target it while the control role is active.
        if allow_shared_read and requested_id in _shared_control_ids(entry):
            raise ValueError("shared_profile_is_control")
        if requested_id not in manager.profile_ids:
            raise ValueError("profile_not_found")
        return requested_id, manager.get_model(requested_id)

    # A configured wall-tablet/shared login is only a control surface. It must
    # never silently become its own thermal comfort profile.
    if _is_shared_account(connection, entry):
        raise ValueError("shared_profile_required")

    await manager.async_ensure_profile(own_id, own_name)
    return own_id, manager.get_model(own_id)


async def _ensure_forecast_fresh(
    coordinator, *, required_sources: set[str] | None = None
) -> bool:
    """Refresh stale/failed forecast data before a deliberate lookup.

    Provider failures are tracked per source. A broken work forecast must not
    force short-retry polling while no work planning window is relevant, while
    a failed source that is actually needed still gets the short retry/backoff.
    """
    refresh = getattr(coordinator, "async_refresh", None)
    if not callable(refresh):
        return True
    data = coordinator.data if isinstance(getattr(coordinator, "data", None), dict) else {}
    updated = data.get("updated")
    now = dt_util.now()
    age = elapsed(updated, now) if isinstance(updated, datetime) else None
    if required_sources is None:
        fetch_failed = bool(data.get("forecast_fetch_failed"))
    else:
        fetch_failed = any(
            data.get(f"{source}_forecast_success", True) is False
            for source in required_sources
        )
    if isinstance(age, timedelta) and timedelta(0) <= age < FORECAST_REFRESH:
        if not fetch_failed or age < _FORECAST_FAILURE_RETRY:
            return True
    try:
        await refresh()
    except Exception as err:
        _LOGGER.debug("Forced forecast refresh failed: %s", err)
        return False

    # A DataUpdateCoordinator can swallow provider failures and retain its old
    # data object. A finished refresh call therefore is not proof of fresh data.
    if getattr(coordinator, "last_update_success", True) is False:
        return False
    refreshed = (
        coordinator.data
        if isinstance(getattr(coordinator, "data", None), dict)
        else {}
    )
    refreshed_at = refreshed.get("updated")
    if not isinstance(refreshed_at, datetime):
        return False
    refreshed_age = elapsed(refreshed_at, dt_util.now())
    return timedelta(0) <= refreshed_age < FORECAST_REFRESH


def _profile_revision_marker(manager: ProfileManager, profile_id: str) -> str:
    """Return a reload-safe marker for exactly one profile model snapshot."""
    token = getattr(manager, "profile_revision_token", None)
    if callable(token):
        return str(token(profile_id))
    return f"legacy:{getattr(manager, 'revision', 0)}"


def _directory_revision_marker(manager: ProfileManager) -> str:
    return str(
        getattr(
            manager,
            "directory_revision_token",
            getattr(manager, "revision_token", "legacy:0"),
        )
    )


async def _stable_advice_snapshot(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    entry: ConfigEntry,
    runtime: dict[str, Any],
    manager: ProfileManager,
    profile_id: str,
    *,
    allow_simulation: bool,
) -> tuple[Any, Recommendation, bool, str, str]:
    """Build advice from one stable personal-model revision.

    A recommendation must never be labelled with a revision newer than the
    model copy that produced it. Cross-device feedback/simulation can change a
    profile while calendar/forecast awaits are in flight, so retry once when
    the profile revision changes and fail conservatively on a second race.
    """
    for attempt in range(2):
        _ensure_runtime_current(entry, runtime, manager)
        if profile_id not in manager.profile_ids:
            raise ValueError("profile_not_found")

        simulations = runtime.setdefault("simulations", {})
        if not allow_simulation and profile_id in simulations:
            # Session-producing advice must stay outside diagnostic simulation
            # for the entire operation, including retries after a concurrent
            # profile-revision change.
            raise ValueError("simulation_active")
        simulated_model = simulations.get(profile_id) if allow_simulation else None
        if simulated_model is None:
            active_model = manager.prepare_model_for_advice(profile_id, dt_util.now())
        else:
            # Simulation is runtime-only. If calendar time itself initializes a
            # simulated season, expose that volatile model change to open cards.
            if simulated_model.prepare_seasons_for(dt_util.now()):
                bump = getattr(manager, "bump_volatile_profile_revision", None)
                if callable(bump):
                    bump(profile_id)
            active_model = simulated_model

        advice_profile_revision = _profile_revision_marker(manager, profile_id)

        rec = await _recommendation(hass, entry, runtime, active_model)
        _ensure_runtime_current(entry, runtime, manager)
        if profile_id not in manager.profile_ids:
            raise ValueError("profile_not_found")
        if not allow_simulation and profile_id in runtime.setdefault("simulations", {}):
            raise ValueError("simulation_active")

        if _profile_revision_marker(manager, profile_id) == advice_profile_revision:
            # Directory changes do not alter this profile's advice, so they do
            # not require recomputing the recommendation.  Return the *current*
            # directory/card markers, however, so a shared card can detect that
            # its preceding profiles response came from an older directory
            # generation and immediately refresh the transaction.
            current_directory_revision = _directory_revision_marker(manager)
            current_card_revision = _revision_token_for_connection(
                connection, entry, manager, profile_id
            )
            rec.simulation_active = simulated_model is not None
            return (
                active_model,
                rec,
                simulated_model is not None,
                current_card_revision,
                current_directory_revision,
            )

        if attempt == 0:
            continue
        raise ValueError("profile_changed_retry")

    raise ValueError("profile_changed_retry")


def _work_period_for_target(
    target: datetime,
    actual_windows: list[tuple[datetime, datetime]],
    planning_windows: list[tuple[datetime, datetime]],
) -> tuple[tuple[datetime, datetime] | None, str | None]:
    """Return the most specific work window for a forecast target.

    Actual work always has priority over overlapping buffers from neighbouring
    split intervals (for example immediately after a partial absence).
    """
    actual = next(
        (window for window in actual_windows if is_between_half_open(target, window[0], window[1])),
        None,
    )
    if actual is not None:
        return actual, "actual"
    buffered = next(
        (
            window
            for window in actual_windows
            if is_between(
                target,
                real_add(window[0], -WORK_BUFFER),
                real_add(window[1], WORK_BUFFER),
            )
        ),
        None,
    )
    if buffered is not None:
        return buffered, "buffer"
    planning = next(
        (window for window in planning_windows if is_between(target, window[0], window[1])),
        None,
    )
    if planning is not None:
        return planning, "buffer"
    return None, None


async def _recommendation(
    hass: HomeAssistant,
    entry: ConfigEntry,
    runtime: dict[str, Any],
    model,
) -> Recommendation:
    coordinator = runtime["coordinator"]
    now = dt_util.now()
    weather_entity = str(entry.data[CONF_WEATHER])
    home_current = current_weather(hass, weather_entity)

    indoor = indoor_temperature_c(
        hass,
        entry.data.get(CONF_INDOOR_TEMP),
        float(entry.data.get(CONF_FALLBACK_INDOOR_TEMP, DEFAULT_FALLBACK_INDOOR_TEMP)),
    )
    activity = activity_context_c(now, model.evening_answer)
    work_entity = entry.data.get(CONF_WORK_WEATHER)
    (
        context_horizon,
        context_calendar_status,
        actual_windows,
        planning_windows,
        vacation_calendar_status,
    ) = await _calendar_context_bundle(
        hass, entry, runtime, include_work=bool(isinstance(work_entity, str) and work_entity)
    )
    base_horizon = max(DEFAULT_FORECAST_HOURS, context_horizon or 0)
    max_horizon = max(MAX_FORECAST_HOURS, min(CALENDAR_MAX_HOURS, context_horizon or 0))

    work_points: list[WeatherPoint] = []
    work_forecast_coverage = "not_applicable"
    work_start: datetime | None = None
    work_end: datetime | None = None
    active_work_context = False

    # Resolve work relevance before the forecast freshness decision. This lets
    # the short provider-failure retry apply only to sources that can actually
    # affect the current/planned recommendation.
    if isinstance(work_entity, str) and work_entity:
        active_window = next(
            (window for window in actual_windows if is_between_half_open(now, window[0], window[1])),
            None,
        )
        if active_window is not None:
            work_current = current_weather(hass, work_entity)
            if work_current is None:
                raise ValueError("work_weather_unavailable")
            current = work_current
            active_work_context = True
            work_start, work_end = active_window
            # A living-room sensor is not representative at work.
            indoor = float(
                entry.data.get(CONF_FALLBACK_INDOOR_TEMP, DEFAULT_FALLBACK_INDOOR_TEMP)
            )
        else:
            if home_current is None:
                raise ValueError("weather_unavailable")
            current = home_current
    else:
        if home_current is None:
            raise ValueError("weather_unavailable")
        current = home_current

    required_sources = {"home"}
    if (
        isinstance(work_entity, str)
        and work_entity
        and work_entity != weather_entity
        and planning_windows
    ):
        required_sources.add("work")
    forecast_fresh = await _ensure_forecast_fresh(
        coordinator, required_sources=required_sources
    )
    forecast_data = (
        coordinator.data
        if forecast_fresh and isinstance(getattr(coordinator, "data", None), dict)
        else {}
    )
    forecast = (
        list(forecast_data.get("home_forecast", []))
        if forecast_data.get("home_forecast_success", True)
        else []
    )

    if isinstance(work_entity, str) and work_entity:
        work_forecast = (
            list(forecast_data.get("work_forecast", []))
            if forecast_data.get("work_forecast_success", True)
            else []
        )
        if planning_windows:
            if work_start is None:
                chosen_window = (actual_windows or planning_windows)[0]
                work_start = chosen_window[0]
                work_end = chosen_window[1] if actual_windows else None
            work_points = [
                point
                for point in work_forecast
                if is_after(point.dt, current.dt)
                and any(
                    is_between(point.dt, start, end)
                    for start, end in planning_windows
                )
            ]
            work_forecast_coverage = _work_forecast_coverage(
                current.dt, work_forecast, planning_windows
            )
            # Work forecast replaces home forecast only inside the planned work
            # windows. Missing work points stay missing instead of silently using
            # the wrong location.
            forecast = merge_location_timeline(
                forecast, work_forecast, planning_windows
            )

    # If work planning extends the recommendation beyond the ordinary 12-hour
    # weather window, evaluate the complete claimed period.
    if work_points:
        latest_work = max((point.dt for point in work_points), key=instant_key)
        work_horizon = math.ceil(
            max(0.0, elapsed(current.dt, latest_work).total_seconds()) / 3600.0
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

    # With multiple work windows, show the window that actually contains the
    # work forecast point which drove the later recommendation, not blindly the
    # first window in the 16-hour planning range.
    if recommendation.later_context == "work" and recommendation.later_at is not None:
        target = recommendation.later_at
        matching_work, work_period = _work_period_for_target(
            target, actual_windows, planning_windows
        )
        if matching_work is not None:
            recommendation.work_start, recommendation.work_end = matching_work
            recommendation.later_work_period = work_period

    recommendation.source = "work" if active_work_context else "home"
    recommendation.work_forecast_coverage = work_forecast_coverage
    recommendation.context_calendar_status = context_calendar_status
    recommendation.vacation_calendar_status = vacation_calendar_status
    # Live work weather and future work-forecast coverage are distinct. Missing
    # future points must not be described as if the current work entity failed.
    recommendation.work_weather_available = True
    if active_work_context and not recommendation.work_context:
        recommendation.work_context = True
        recommendation.work_jacket = recommendation.jacket_now
        recommendation.work_name = work_name
        recommendation.work_start = work_start
        recommendation.work_end = work_end
    return recommendation


def _work_forecast_coverage(
    origin: datetime,
    points: list[WeatherPoint],
    windows: list[tuple[datetime, datetime]],
    *,
    max_gap: timedelta = timedelta(minutes=90),
) -> str:
    """Classify remaining work-window coverage by real UTC instants.

    Coverage is aggregated across *all* remaining work windows. A missing first
    window must not short-circuit later windows that are covered; if at least one
    window is usable while another is incomplete/missing, the overall result is
    ``partial``. A short tail of an already-running planning window may be
    anchored by a recent point from the same window.
    """
    remaining_windows = [
        (start, end) for start, end in windows if is_after(end, origin)
    ]
    if not remaining_windows:
        return "not_applicable"

    ordered_points = sorted(points, key=lambda point: instant_key(point.dt))
    statuses: list[str] = []

    for window_start, window_end in remaining_windows:
        start = max((origin, window_start), key=instant_key)
        in_window = [
            point
            for point in ordered_points
            if is_between(point.dt, window_start, window_end)
        ]
        if not in_window:
            statuses.append("missing")
            continue

        future_or_equal = [
            point for point in in_window if not is_before(point.dt, start)
        ]
        prior = [point for point in in_window if is_before(point.dt, start)]
        sequence: list[WeatherPoint] = []
        if prior:
            latest_prior = prior[-1]
            if elapsed(latest_prior.dt, start) <= max_gap:
                sequence.append(latest_prior)
        sequence.extend(future_or_equal)

        if not sequence:
            statuses.append("missing")
            continue

        complete = True
        first = sequence[0]
        if is_after(first.dt, start) and elapsed(start, first.dt) > max_gap:
            complete = False
        if is_before(first.dt, start) and elapsed(first.dt, start) > max_gap:
            complete = False
        if elapsed(sequence[-1].dt, window_end) > max_gap:
            complete = False
        if any(
            elapsed(left.dt, right.dt) > max_gap
            for left, right in zip(sequence, sequence[1:])
        ):
            complete = False
        statuses.append("complete" if complete else "partial")

    if statuses and all(status == "complete" for status in statuses):
        return "complete"
    if statuses and all(status == "missing" for status in statuses):
        return "missing"
    return "partial"


async def _cached_work_window_sets(
    hass: HomeAssistant,
    entry: ConfigEntry,
    runtime: dict[str, Any],
) -> tuple[list[tuple[datetime, datetime]], list[tuple[datetime, datetime]], str]:
    now = dt_util.now()
    cache = runtime.setdefault("context_cache", {})
    updated = cache.get("updated")
    age = elapsed(updated, now) if isinstance(updated, datetime) else None
    if isinstance(age, timedelta) and timedelta(0) <= age < _CONTEXT_CACHE_TTL:
        return (
            list(cache.get("work_windows_actual", [])),
            list(cache.get("work_windows_planning", [])),
            str(
                cache.get(
                    "vacation_calendar_status", CALENDAR_STATUS_NOT_CONFIGURED
                )
            ),
        )

    # At most one retry: if a calendar event invalidates the cache while the
    # service request is in flight, never use that now-stale answer for the
    # current recommendation. A second concurrent invalidation falls back
    # conservatively instead of spinning forever.
    for attempt in range(2):
        generation = int(runtime.get("context_cache_generation", 0))
        actual, planning, vacation_status = await work_windows(
            hass, entry, now, return_actual=True
        )
        if int(runtime.get("context_cache_generation", 0)) != generation:
            if attempt == 0:
                continue
            return [], [], CALENDAR_STATUS_UNAVAILABLE
        cache["updated"] = now
        cache["work_windows_actual"] = actual
        cache["work_windows_planning"] = planning
        cache["vacation_calendar_status"] = vacation_status
        return actual, planning, vacation_status
    return [], [], CALENDAR_STATUS_UNAVAILABLE


async def _cached_calendar_horizon(
    hass: HomeAssistant,
    entry: ConfigEntry,
    runtime: dict[str, Any],
) -> tuple[int | None, str]:
    if not entry.data.get(CONF_CONTEXT_CALENDAR):
        return None, CALENDAR_STATUS_NOT_CONFIGURED
    now = dt_util.now()
    cache = runtime.setdefault("context_cache", {})
    updated = cache.get("calendar_updated")
    age = elapsed(updated, now) if isinstance(updated, datetime) else None
    if isinstance(age, timedelta) and timedelta(0) <= age < _CONTEXT_CACHE_TTL:
        value = cache.get("calendar_horizon")
        status = str(cache.get("calendar_status", CALENDAR_STATUS_AVAILABLE))
        return (int(value) if isinstance(value, int) else None), status

    for attempt in range(2):
        generation = int(runtime.get("context_cache_generation", 0))
        value, status = await calendar_context_horizon(hass, entry, now)
        if int(runtime.get("context_cache_generation", 0)) != generation:
            if attempt == 0:
                continue
            return None, CALENDAR_STATUS_UNAVAILABLE
        cache["calendar_updated"] = now
        cache["calendar_horizon"] = value
        cache["calendar_status"] = status
        return value, status
    return None, CALENDAR_STATUS_UNAVAILABLE


async def _calendar_context_bundle(
    hass: HomeAssistant,
    entry: ConfigEntry,
    runtime: dict[str, Any],
    *,
    include_work: bool,
) -> tuple[
    int | None,
    str,
    list[tuple[datetime, datetime]],
    list[tuple[datetime, datetime]],
    str,
]:
    """Read all calendar-derived inputs from one cache generation.

    The individual cache helpers already reject responses invalidated while
    their own service call is in flight. This outer guard prevents one
    recommendation from knowingly combining a context-horizon result from one
    generation with work/vacation windows from a newer generation.
    """
    for attempt in range(2):
        generation = int(runtime.get("context_cache_generation", 0))
        horizon, context_status = await _cached_calendar_horizon(hass, entry, runtime)
        if include_work:
            actual, planning, vacation_status = await _cached_work_window_sets(
                hass, entry, runtime
            )
        else:
            actual, planning = [], []
            vacation_status = CALENDAR_STATUS_NOT_APPLICABLE

        if int(runtime.get("context_cache_generation", 0)) == generation:
            return horizon, context_status, actual, planning, vacation_status
        if attempt == 0:
            continue

    # A second concurrent invalidation means external calendar state is moving
    # faster than this recommendation can obtain a coherent snapshot. Fall back
    # conservatively rather than mixing known-stale generations.
    return (
        None,
        CALENDAR_STATUS_UNAVAILABLE,
        [],
        [],
        CALENDAR_STATUS_UNAVAILABLE if include_work else CALENDAR_STATUS_NOT_APPLICABLE,
    )


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
        "observed_at": (rec.observed_at or dt_util.now()).isoformat(),
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
        _ensure_runtime_current(entry, runtime, manager)
        (
            active_model,
            rec,
            simulation_active,
            advice_revision,
            advice_directory_revision,
        ) = await _stable_advice_snapshot(
            hass,
            connection,
            entry,
            runtime,
            manager,
            profile_id,
            allow_simulation=True,
        )
        read_only_shared = _is_shared_account(connection, entry) and not connection.user.is_admin
        summary = _profile_summary_for_connection(
            connection, entry, manager.get_profile_summary(profile_id)
        )
        feedback = manager.feedback_candidates(profile_id)
        result = {
            "entry_id": entry.entry_id,
            "profile": summary,
            "recommendation": rec.as_dict(),
            "feedback": [] if simulation_active else feedback,
            "profile_revision": advice_revision,
            "directory_revision": advice_directory_revision,
            "latest_session": (
                None
                if read_only_shared or simulation_active
                else manager.latest_session(profile_id)
            ),
        }
        # Detailed model values are personal diagnostics. Shared control
        # surfaces receive only the selected profile's advice and due feedback.
        if not read_only_shared:
            result["diagnostics"] = model_diagnostics(
                active_model, simulation_active=simulation_active
            )
        connection.send_result(msg["id"], result)
    except (ValueError, KeyError) as err:
        message = "profile_not_found" if isinstance(err, KeyError) else str(err)
        connection.send_error(msg["id"], "unavailable", message)


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
        profile_id, _model = await _profile(
            connection,
            manager,
            msg.get("profile_id"),
            entry,
            allow_shared_read=True,
        )
        _ensure_runtime_current(entry, runtime, manager)
        if profile_id in runtime.setdefault("simulations", {}):
            raise ValueError("simulation_active")
        shared_account = _is_shared_account(connection, entry) and not connection.user.is_admin
        (
            model,
            rec,
            _simulation_active,
            _advice_revision,
            _advice_directory_revision,
        ) = await _stable_advice_snapshot(
            hass,
            connection,
            entry,
            runtime,
            manager,
            profile_id,
            allow_simulation=False,
        )
        if profile_id not in manager.profile_ids:
            raise ValueError("profile_not_found")
        session = await manager.async_open_session(
            profile_id,
            rec,
            weather_context=_weather_context(rec),
            learning_contexts=_learning_contexts(rec),
            opened_by_user_id=str(connection.user.id),
            prepared_model=model,
        )
        _ensure_runtime_current(entry, runtime, manager)
        connection.send_result(
            msg["id"],
            {
                "profile": _profile_summary_for_connection(
                    connection, entry, manager.get_profile_summary(profile_id)
                ),
                "recommendation": rec.as_dict(),
                "session": None if shared_account else session,
                "feedback": manager.feedback_candidates(profile_id),
                # Session creation changes the full-card session snapshot without
                # changing the learned-model revision. Return the post-session
                # card marker; the frontend treats action markers as seen-only
                # until a complete profiles+preview refresh applies them.
                "profile_revision": _revision_token_for_connection(
                    connection, entry, manager, profile_id
                ),
                "directory_revision": _directory_revision_marker(manager),
            },
        )
    except (ValueError, KeyError) as err:
        message = "profile_not_found" if isinstance(err, KeyError) else str(err)
        connection.send_error(msg["id"], "unavailable", message)


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
        _ensure_runtime_current(entry, runtime, manager)
        await manager.async_setup_profile(
            profile_id,
            cold=msg["cold"],
            warm=msg["warm"],
            wind=msg["wind"],
            evening=msg["evening"],
        )
        _ensure_runtime_current(entry, runtime, manager)
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
        profile_id, _ = await _profile(
            connection,
            manager,
            msg.get("profile_id"),
            entry,
            allow_shared_read=True,
        )
        _ensure_runtime_current(entry, runtime, manager)
        if profile_id in runtime.setdefault("simulations", {}):
            raise ValueError("simulation_active")
        shared_account = _is_shared_account(connection, entry) and not connection.user.is_admin
        if shared_account and (
            msg.get("voluntary", False)
            or not manager.is_feedback_candidate(profile_id, msg["session_id"])
        ):
            raise ValueError("shared_feedback_not_allowed")
        session = await manager.async_feedback(
            profile_id,
            msg["session_id"],
            rating=msg["rating"],
            phase=msg.get("phase"),
            recommendation_used=msg.get("recommendation_used"),
            unusual_day=msg.get("unusual_day", False),
            voluntary=msg.get("voluntary", False),
        )
        _ensure_runtime_current(entry, runtime, manager)
        connection.send_result(
            msg["id"],
            {
                "session": session,
                "profile": _profile_summary_for_connection(
                    connection, entry, manager.get_profile_summary(profile_id)
                ),
            },
        )
    except (ValueError, KeyError) as err:
        connection.send_error(msg["id"], "invalid_feedback", str(err))


async def _sync_profile_directory(
    hass: HomeAssistant, entry: ConfigEntry, manager: ProfileManager
) -> bool:
    """Refresh HA users only while *manager* is still the active runtime owner.

    A WebSocket request can survive a config-entry unload while awaiting auth.
    Re-check the runtime after that await so an old request cannot mutate or
    schedule a save on a manager that has already been replaced by reload.
    """
    auth = getattr(hass, "auth", None)
    get_users = getattr(auth, "async_get_users", None)
    if not callable(get_users):
        return True
    users = await get_users()
    runtime = getattr(entry, "runtime_data", None)
    if (
        not isinstance(runtime, dict)
        or runtime.get("unloading")
        or runtime.get("profiles") is not manager
    ):
        return False
    manager.sync_user_directory(users)
    return True


@websocket_api.websocket_command(
    {
        vol.Required("type"): "jackenberater/profiles",
        vol.Optional("entry_id"): str,
        vol.Optional("profile_id"): str,
    }
)
@websocket_api.async_response
async def ws_profiles(hass, connection, msg) -> None:
    try:
        entry, runtime = _runtime(hass, msg.get("entry_id"))
    except ValueError as err:
        connection.send_error(msg["id"], "unavailable", str(err))
        return
    manager: ProfileManager = runtime["profiles"]
    if not await _sync_profile_directory(hass, entry, manager):
        connection.send_error(msg["id"], "unavailable", "integration_reloading")
        return
    if not _runtime_is_current(entry, runtime, manager):
        connection.send_error(msg["id"], "unavailable", "integration_reloading")
        return
    own_id = str(connection.user.id)
    shared_account = _is_shared_account(connection, entry)
    if _can_use_shared_profiles(connection, entry):
        shared_control_ids = _shared_control_ids(entry)
        # A configured shared login is a control surface, not a person to advise.
        # Keep any historical profile persisted, but hide *all* currently shared
        # accounts from every shared/admin profile selector.
        summaries = [
            summary
            for summary in manager.summaries()
            if str(summary.get("id", "")) not in shared_control_ids
        ]
        if shared_account and not connection.user.is_admin:
            summaries = [_read_only_profile_summary(summary) for summary in summaries]
    else:
        summaries = (
            [manager.get_profile_summary(own_id)] if own_id in manager.profile_ids else []
        )
    requested_for_revision = msg.get("profile_id")
    if (
        requested_for_revision
        and requested_for_revision != own_id
        and not _can_use_shared_profiles(connection, entry)
    ):
        # ``profiles`` is the recovery endpoint for a card whose shared access
        # was revoked while a foreign profile was still selected. Do not expose
        # that foreign profile; simply return metadata/revision for the now
        # authorized own scope so the card can clear its stale selection.
        requested_for_revision = None

    connection.send_result(
        msg["id"],
        {
            "entry_id": entry.entry_id,
            "current_user_id": own_id,
            "shared_access": _can_use_shared_profiles(connection, entry),
            "shared_account": shared_account,
            "is_admin": bool(connection.user.is_admin),
            "profile_revision": _revision_token_for_connection(
                connection, entry, manager, requested_for_revision
            ),
            "directory_revision": _directory_revision_marker(manager),
            "watched_entities": list(dict.fromkeys(
                entity_id
                for entity_id in (
                    entry.data.get(CONF_WEATHER),
                    entry.data.get(CONF_WORK_WEATHER),
                    entry.data.get(CONF_INDOOR_TEMP),
                    entry.data.get(CONF_CONTEXT_CALENDAR),
                    entry.data.get(CONF_VACATION_CALENDAR),
                )
                if isinstance(entity_id, str) and entity_id
            )),
            "profiles": summaries,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "jackenberater/profile_revision",
        vol.Optional("entry_id"): str,
        vol.Optional("profile_id"): str,
    }
)
@callback
def ws_profile_revision(hass, connection, msg) -> None:
    """Return a tiny revision scoped to the profile/directory this card uses."""
    try:
        entry, runtime = _runtime(hass, msg.get("entry_id"))
        manager: ProfileManager = runtime["profiles"]
        revision = _revision_token_for_connection(
            connection, entry, manager, msg.get("profile_id")
        )
        connection.send_result(msg["id"], {"revision": revision})
    except (ValueError, KeyError) as err:
        connection.send_error(msg["id"], "unavailable", str(err))


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
        if not PROFILE_BACKUP_ENABLED:
            raise ValueError("profile_backup_disabled")
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
        if not PROFILE_BACKUP_ENABLED:
            raise ValueError("profile_backup_disabled")
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
            _ensure_runtime_current(entry, runtime, manager)
        _ensure_runtime_current(entry, runtime, manager)
        model = await manager.async_import_profile(profile_id, msg["payload"])
        _ensure_runtime_current(entry, runtime, manager)
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
        _ensure_runtime_current(entry, runtime, manager)
        action = msg["action"]
        result: bool | None = None
        if action in {"learning_on", "learning_off"}:
            await manager.async_set_learning(profile_id, action == "learning_on")
        elif action == "reset":
            await manager.async_reset_learning(profile_id)
        else:
            result = await manager.async_undo_last_feedback(profile_id)
        _ensure_runtime_current(entry, runtime, manager)
        connection.send_result(
            msg["id"],
            {"profile": manager.get_profile_summary(profile_id), "result": result},
        )
    except (ValueError, KeyError) as err:
        connection.send_error(msg["id"], "profile_maintenance_failed", str(err))
