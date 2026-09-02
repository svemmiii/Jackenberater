"""Optional time/context helpers.

Calendar contents are deliberately ignored: only start/end timestamps are read.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .const import (
    CALENDAR_MAX_HOURS,
    CONF_CONTEXT_CALENDAR,
    CONF_SHIFT_ANCHOR_DATE,
    CONF_SHIFT_EARLY_END,
    CONF_SHIFT_EARLY_START,
    CONF_SHIFT_LATE_END,
    CONF_SHIFT_LATE_START,
    CONF_SHIFT_NIGHT_END,
    CONF_SHIFT_NIGHT_START,
    CONF_SHIFT_PATTERN,
    CONF_VACATION_CALENDAR,
    CONF_WORK_MODE,
    CONF_WORKDAY_END,
    CONF_WORKDAY_START,
    DEFAULT_WORKDAY_END,
    DEFAULT_WORKDAY_START,
    WORK_BUFFER,
    WORK_MODE_NONE,
    WORK_MODE_SHIFT,
    WORK_MODE_WEEKDAY,
)

_LOGGER = logging.getLogger(__name__)


def _absolute_horizon_end(now: datetime, hours: int) -> datetime:
    """Add real elapsed hours while retaining the input timezone for comparisons."""
    if now.tzinfo is None:
        return now + timedelta(hours=hours)
    return (now.astimezone(dt_util.UTC) + timedelta(hours=hours)).astimezone(now.tzinfo)


async def calendar_context_horizon(
    hass: HomeAssistant,
    entry: ConfigEntry,
    now: datetime,
    horizon_hours: int = CALENDAR_MAX_HOURS,
) -> int | None:
    """Return the furthest relevant timed calendar hour, without reading content."""
    entity_id = entry.data.get(CONF_CONTEXT_CALENDAR)
    if not isinstance(entity_id, str) or not entity_id:
        return None
    end = _absolute_horizon_end(now, horizon_hours)
    windows = await _calendar_windows(hass, entity_id, now, end, timed_only=True)
    if not windows:
        return None
    furthest = max(window_end for _, window_end in windows)
    hours = int(((furthest - now).total_seconds() + 3599) // 3600)
    return max(1, min(horizon_hours, hours))


async def work_windows(
    hass: HomeAssistant,
    entry: ConfigEntry,
    now: datetime,
    horizon_hours: int = CALENDAR_MAX_HOURS,
    *,
    return_actual: bool = False,
) -> list[tuple[datetime, datetime]] | tuple[
    list[tuple[datetime, datetime]], list[tuple[datetime, datetime]]
]:
    """Return probable work windows without tracking the user.

    The actual window represents the configured work hours. The planning window
    adds the ±30 minute buffer used to consider destination weather before/after
    work without pretending the user is already physically at that location.
    """
    end = _absolute_horizon_end(now, horizon_hours)
    # Search one planning buffer into the past as well. Otherwise a fresh context
    # calculation at 17:10 would forget a 17:00 work end, while a cached result
    # from 16:59 would still retain the intended planning relevance until 17:30.
    search_start = now - WORK_BUFFER
    vacation_windows: list[tuple[datetime, datetime]] = []
    vacation_calendar = entry.data.get(CONF_VACATION_CALENDAR)
    if isinstance(vacation_calendar, str) and vacation_calendar:
        vacation_windows = await _calendar_windows(
            hass, vacation_calendar, search_start, end, timed_only=False
        )

    mode = str(entry.data.get(CONF_WORK_MODE) or "").strip().lower()
    if not mode:
        mode = WORK_MODE_SHIFT if entry.data.get(CONF_SHIFT_PATTERN) else WORK_MODE_WEEKDAY

    if mode == WORK_MODE_NONE:
        return ([], []) if return_actual else []
    if mode == WORK_MODE_SHIFT:
        raw_actual = _cycle_windows(entry, search_start, end, buffered=False)
    else:
        raw_actual = _weekday_windows(entry, search_start, end, buffered=False)

    # Absence/holiday is applied to the real work period first. Planning windows
    # are then derived from whatever work is actually left. This prevents a full
    # day absence from leaving artificial 30-minute work buffers behind.
    surviving = _subtract_blocked_windows(raw_actual, vacation_windows)
    surviving = _clip_window_ends(surviving, end)
    planning = _buffer_windows(surviving)
    # Actual work must only describe a real current/future work period; the
    # just-ended shift remains available only through the planning buffer.
    actual = _current_or_future_windows(surviving, now, end)
    # A partial absence must also remain a gap in the expanded planning range.
    planning = _subtract_blocked_windows(planning, vacation_windows)
    planning = _clip_window_ends(planning, end)
    return (actual, planning) if return_actual else planning


def activity_context_c(now: datetime, evening_answer: int) -> float:
    """Return a weak correction for the user's typical evening activity.

    The setup question now measures the thing this value actually represents:
    quiet/standing versus active movement while spending longer outside. This is
    deliberately small and applies only in the evening, so it can refine close
    calls without overpowering weather or personal feedback.
    """
    local = dt_util.as_local(now)
    hour = local.hour + local.minute / 60.0
    if not (16.0 <= hour <= 23.5):
        return 0.0
    answer = max(1, min(5, int(evening_answer or 3)))
    # Keep the middle answer truly neutral. The correction remains deliberately
    # small so activity can refine close calls without dominating the weather.
    return {1: -0.50, 2: -0.25, 3: 0.0, 4: 0.10, 5: 0.20}[answer]


async def _calendar_windows(
    hass: HomeAssistant,
    entity_id: str,
    start: datetime,
    end: datetime,
    *,
    timed_only: bool,
) -> list[tuple[datetime, datetime]]:
    try:
        response = await hass.services.async_call(
            "calendar",
            "get_events",
            {
                "start_date_time": start.isoformat(),
                "end_date_time": end.isoformat(),
            },
            target={"entity_id": entity_id},
            blocking=True,
            return_response=True,
        )
    except (HomeAssistantError, ValueError) as err:
        _LOGGER.debug("Calendar context unavailable for %s: %s", entity_id, err)
        return []
    payload = response.get(entity_id) if isinstance(response, dict) else None
    events = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(events, list):
        return []

    result: list[tuple[datetime, datetime]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        # Privacy rule: summary/description/location are intentionally ignored.
        raw_start = event.get("start")
        raw_end = event.get("end")
        if timed_only and _looks_all_day(raw_start, raw_end):
            continue
        parsed_start = _parse_calendar_time(raw_start, start.tzinfo)
        parsed_end = _parse_calendar_time(raw_end, start.tzinfo)
        if parsed_start is None or parsed_end is None or parsed_end <= parsed_start:
            continue
        result.append((parsed_start, parsed_end))
    return result


def _looks_all_day(start: Any, end: Any) -> bool:
    return (
        isinstance(start, str)
        and len(start) == 10
        and isinstance(end, str)
        and len(end) == 10
    )


def _parse_calendar_time(value: Any, tzinfo) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min, tzinfo=tzinfo)
    elif isinstance(value, str):
        if len(value) == 10:
            try:
                parsed = datetime.combine(date.fromisoformat(value), time.min, tzinfo=tzinfo)
            except ValueError:
                return None
        else:
            parsed = dt_util.parse_datetime(value)
    else:
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tzinfo or dt_util.UTC)
    return dt_util.as_local(parsed)


def _weekday_windows(
    entry: ConfigEntry,
    start: datetime,
    end: datetime,
    *,
    buffered: bool = True,
) -> list[tuple[datetime, datetime]]:
    """Return Monday-Friday work windows, optionally with planning buffer."""
    start_time = _parse_time(
        str(entry.data.get(CONF_WORKDAY_START, DEFAULT_WORKDAY_START))
    )
    end_time = _parse_time(
        str(entry.data.get(CONF_WORKDAY_END, DEFAULT_WORKDAY_END))
    )
    if start_time is None or end_time is None or start_time == end_time:
        return []

    windows: list[tuple[datetime, datetime]] = []
    day = start.date() - timedelta(days=1)
    last_day = end.date() + timedelta(days=1)
    while day <= last_day:
        if day.weekday() < 5:
            a = datetime.combine(day, start_time, tzinfo=start.tzinfo)
            b = datetime.combine(day, end_time, tzinfo=start.tzinfo)
            if b <= a:
                b += timedelta(days=1)
            if b >= start and a <= end:
                windows.append(
                    (a - WORK_BUFFER, b + WORK_BUFFER) if buffered else (a, b)
                )
        day += timedelta(days=1)
    return _merge_windows(windows)


def _cycle_windows(
    entry: ConfigEntry,
    start: datetime,
    end: datetime,
    *,
    buffered: bool = True,
) -> list[tuple[datetime, datetime]]:
    pattern_raw = entry.data.get(CONF_SHIFT_PATTERN)
    anchor_raw = entry.data.get(CONF_SHIFT_ANCHOR_DATE)
    if not isinstance(pattern_raw, str) or not pattern_raw.strip() or not anchor_raw:
        return []
    pattern = [token.strip().upper() for token in pattern_raw.split(",") if token.strip()]
    if not pattern or any(token not in {"F", "S", "N", "X"} for token in pattern):
        return []
    try:
        anchor = date.fromisoformat(str(anchor_raw))
    except ValueError:
        return []

    windows: list[tuple[datetime, datetime]] = []
    day = start.date() - timedelta(days=1)
    last_day = end.date() + timedelta(days=1)
    while day <= last_day:
        token = pattern[(day - anchor).days % len(pattern)]
        if token != "X":
            bounds = _shift_bounds(entry, token, day, start.tzinfo)
            if bounds and bounds[1] >= start and bounds[0] <= end:
                windows.append(
                    (bounds[0] - WORK_BUFFER, bounds[1] + WORK_BUFFER)
                    if buffered
                    else bounds
                )
        day += timedelta(days=1)
    return _merge_windows(windows)


def _shift_bounds(
    entry: ConfigEntry,
    token: str,
    day: date,
    tzinfo,
) -> tuple[datetime, datetime] | None:
    keys = {
        "F": (CONF_SHIFT_EARLY_START, CONF_SHIFT_EARLY_END, "06:00", "14:00"),
        "S": (CONF_SHIFT_LATE_START, CONF_SHIFT_LATE_END, "14:00", "22:00"),
        "N": (CONF_SHIFT_NIGHT_START, CONF_SHIFT_NIGHT_END, "22:00", "06:00"),
    }
    start_key, end_key, default_start, default_end = keys[token]
    start_time = _parse_time(str(entry.data.get(start_key, default_start)))
    end_time = _parse_time(str(entry.data.get(end_key, default_end)))
    if start_time is None or end_time is None or start_time == end_time:
        return None
    a = datetime.combine(day, start_time, tzinfo=tzinfo)
    b = datetime.combine(day, end_time, tzinfo=tzinfo)
    if b <= a:
        b += timedelta(days=1)
    return a, b


def _parse_time(value: str) -> time | None:
    try:
        parts = value.split(":")
        return time(hour=int(parts[0]), minute=int(parts[1]))
    except (ValueError, IndexError):
        return None


def _current_or_future_windows(
    windows: list[tuple[datetime, datetime]],
    now: datetime,
    end: datetime,
) -> list[tuple[datetime, datetime]]:
    """Keep current/future real work periods while preserving their true start."""
    kept: list[tuple[datetime, datetime]] = []
    for window_start, window_end in windows:
        clipped_end = min(window_end, end)
        if clipped_end >= now and window_start <= end and clipped_end > window_start:
            kept.append((window_start, clipped_end))
    return kept


def _clip_window_ends(
    windows: list[tuple[datetime, datetime]],
    end: datetime,
) -> list[tuple[datetime, datetime]]:
    """Clip work/planning windows to the configured maximum future horizon."""
    clipped: list[tuple[datetime, datetime]] = []
    for start, stop in windows:
        clipped_stop = min(stop, end)
        if clipped_stop > start:
            clipped.append((start, clipped_stop))
    return clipped


def _buffer_windows(
    windows: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    """Expand surviving work periods for planning without changing actual work."""
    return _merge_windows(
        [(start - WORK_BUFFER, end + WORK_BUFFER) for start, end in windows]
    )


def _subtract_blocked_windows(
    windows: list[tuple[datetime, datetime]],
    blocked: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    """Subtract vacation/absence intervals instead of dropping whole shifts."""
    if not blocked:
        return windows
    result: list[tuple[datetime, datetime]] = []
    for start, end in windows:
        parts = [(start, end)]
        for block_start, block_end in blocked:
            next_parts: list[tuple[datetime, datetime]] = []
            for part_start, part_end in parts:
                if block_end <= part_start or block_start >= part_end:
                    next_parts.append((part_start, part_end))
                    continue
                if block_start > part_start:
                    next_parts.append((part_start, min(block_start, part_end)))
                if block_end < part_end:
                    next_parts.append((max(block_end, part_start), part_end))
            parts = next_parts
        result.extend((a, b) for a, b in parts if b > a)
    return _merge_windows(result)


def _merge_windows(windows: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    if not windows:
        return []
    ordered = sorted(windows, key=lambda item: item[0])
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        old_start, old_end = merged[-1]
        if start <= old_end:
            merged[-1] = (old_start, max(old_end, end))
        else:
            merged.append((start, end))
    return merged
