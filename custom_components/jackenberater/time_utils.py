"""UTC-instant helpers for elapsed-time calculations and ordering."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def as_utc(value: datetime) -> datetime:
    """Return a stable UTC representation of an instant.

    Home Assistant datetimes are timezone-aware. Treating a defensive naive
    value as UTC keeps helpers deterministic without mixing aware and naive
    values in comparisons.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def instant_key(value: datetime) -> datetime:
    """Return a key that orders ambiguous local times by their real instant."""
    return as_utc(value)


def elapsed(start: datetime, end: datetime) -> timedelta:
    """Return real elapsed time, including across DST folds and gaps."""
    return as_utc(end) - as_utc(start)


def real_add(value: datetime, delta: timedelta) -> datetime:
    """Add real elapsed time and retain the input timezone for display."""
    if value.tzinfo is None:
        return value + delta
    return (as_utc(value) + delta).astimezone(value.tzinfo)


def is_before(left: datetime, right: datetime) -> bool:
    return instant_key(left) < instant_key(right)


def is_at_or_before(left: datetime, right: datetime) -> bool:
    return instant_key(left) <= instant_key(right)


def is_after(left: datetime, right: datetime) -> bool:
    return instant_key(left) > instant_key(right)


def is_at_or_after(left: datetime, right: datetime) -> bool:
    return instant_key(left) >= instant_key(right)


def is_between(value: datetime, start: datetime, end: datetime) -> bool:
    """Return whether an instant lies inside an inclusive interval."""
    key = instant_key(value)
    return instant_key(start) <= key <= instant_key(end)
