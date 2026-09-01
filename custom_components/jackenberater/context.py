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
    CONF_WORK_CALENDAR,
    WORK_BUFFER,
)

_LOGGER = logging.getLogger(__name__)


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
    end = now + timedelta(hours=horizon_hours)
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
) -> list[tuple[datetime, datetime]]:
    """Return probable work windows. Calendar wins over a rotating cycle."""
    end = now + timedelta(hours=horizon_hours)
    vacation_windows: list[tuple[datetime, datetime]] = []
    vacation_calendar = entry.data.get(CONF_VACATION_CALENDAR)
    if isinstance(vacation_calendar, str) and vacation_calendar:
        vacation_windows = await _calendar_windows(
            hass, vacation_calendar, now, end, timed_only=False
        )

    work_calendar = entry.data.get(CONF_WORK_CALENDAR)
    if isinstance(work_calendar, str) and work_calendar:
        # An explicitly selected work calendar is authoritative: no event means
        # no probable work window. Do not resurrect a cycle on calendar days off.
        windows = await _calendar_windows(hass, work_calendar, now, end, timed_only=True)
        buffered = _merge_windows([(a - WORK_BUFFER, b + WORK_BUFFER) for a, b in windows])
        return _subtract_blocked_windows(buffered, vacation_windows)

    return _subtract_blocked_windows(_cycle_windows(entry, now, end), vacation_windows)


def activity_context_c(now: datetime, evening_answer: int) -> float:
    """Return a deliberately weak event-season activity correction.

    Negative means slightly less body heat than the default everyday activity.
    It can influence a close call, but is capped so it cannot overturn an
    otherwise clear recommendation by itself.
    """
    local = dt_util.as_local(now)
    hour = local.hour + local.minute / 60.0
    if not (16.0 <= hour <= 23.5):
        return 0.0
    if not _event_season(local.date()):
        return 0.0
    answer = max(1, min(5, int(evening_answer or 3)))
    # Someone who is normally almost never out in the evening gets the stronger
    # "probably standing/slow social activity" hint during classic event times.
    correction = {1: -0.55, 2: -0.42, 3: -0.30, 4: -0.18, 5: -0.10}[answer]
    return correction


def _event_season(day: date) -> bool:
    # Broad Advent/Christmas-market season, New Year's Eve, and the main German
    # street-carnival days. This is a weak context hint, never a factual claim.
    if (day.month == 11 and day.day >= 20) or day.month == 12:
        return True
    if day.month == 1 and day.day == 1:
        return True
    easter = _easter_sunday(day.year)
    carnival_start = easter - timedelta(days=52)  # Weiberfastnacht
    carnival_end = easter - timedelta(days=48)    # Rosenmontag
    return carnival_start <= day <= carnival_end


def _easter_sunday(year: int) -> date:
    # Gregorian Anonymous algorithm / Meeus-Jones-Butcher.
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


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


def _cycle_windows(
    entry: ConfigEntry,
    start: datetime,
    end: datetime,
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
                windows.append((bounds[0] - WORK_BUFFER, bounds[1] + WORK_BUFFER))
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
    if start_time is None or end_time is None:
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
