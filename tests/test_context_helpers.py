from __future__ import annotations

from datetime import datetime, timedelta, timezone
import asyncio
import importlib.util
from pathlib import Path
import sys
import types

ROOT = Path(__file__).parents[1] / "custom_components" / "jackenberater"
PKG = "jackenberater_context_testpkg"

package = types.ModuleType(PKG)
package.__path__ = [str(ROOT)]
sys.modules.setdefault(PKG, package)

ha = types.ModuleType("homeassistant")
sys.modules.setdefault("homeassistant", ha)
config_entries = types.ModuleType("homeassistant.config_entries")
config_entries.ConfigEntry = type("ConfigEntry", (), {})
sys.modules[config_entries.__name__] = config_entries
core = types.ModuleType("homeassistant.core")
core.HomeAssistant = type("HomeAssistant", (), {})
sys.modules[core.__name__] = core
exceptions = types.ModuleType("homeassistant.exceptions")
exceptions.HomeAssistantError = type("HomeAssistantError", (Exception,), {})
sys.modules[exceptions.__name__] = exceptions
util = types.ModuleType("homeassistant.util")
sys.modules[util.__name__] = util
ha_dt = types.ModuleType("homeassistant.util.dt")
ha_dt.UTC = timezone.utc
ha_dt.as_local = lambda value: value
ha_dt.parse_datetime = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00"))
sys.modules[ha_dt.__name__] = ha_dt
util.dt = ha_dt


def load(name: str):
    fullname = f"{PKG}.{name}"
    if fullname in sys.modules:
        return sys.modules[fullname]
    spec = importlib.util.spec_from_file_location(fullname, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[fullname] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


const = load("const")
context = load("context")


def test_vacation_only_suppresses_overlapping_work_window():
    base = datetime(2026, 9, 1, 6, tzinfo=timezone.utc)
    work = [
        (base, base + timedelta(hours=8)),
        (base + timedelta(days=1), base + timedelta(days=1, hours=8)),
    ]
    vacation = [(base + timedelta(days=1, hours=4), base + timedelta(days=2))]
    filtered = context._subtract_blocked_windows(work, vacation)
    assert filtered[0] == work[0]
    assert filtered[1] == (work[1][0], vacation[0][0])


def test_non_overlapping_vacation_keeps_work_window():
    base = datetime(2026, 9, 1, 6, tzinfo=timezone.utc)
    work = [(base, base + timedelta(hours=8))]
    vacation = [(base + timedelta(hours=12), base + timedelta(hours=20))]
    assert context._subtract_blocked_windows(work, vacation) == work


def test_default_work_model_is_monday_to_friday_with_buffer():
    # 2026-09-01 is a Tuesday.
    entry = types.SimpleNamespace(data={
        const.CONF_WORK_MODE: const.WORK_MODE_WEEKDAY,
        const.CONF_WORKDAY_START: "08:00",
        const.CONF_WORKDAY_END: "17:00",
    })
    now = datetime(2026, 9, 1, 7, tzinfo=timezone.utc)
    windows = context._weekday_windows(entry, now, now + timedelta(hours=12))
    assert (datetime(2026, 9, 1, 7, 30, tzinfo=timezone.utc), datetime(2026, 9, 1, 17, 30, tzinfo=timezone.utc)) in windows


def test_weekend_has_no_default_work_window():
    entry = types.SimpleNamespace(data={
        const.CONF_WORK_MODE: const.WORK_MODE_WEEKDAY,
        const.CONF_WORKDAY_START: "08:00",
        const.CONF_WORKDAY_END: "17:00",
    })
    # 2026-09-05 is Saturday; keep the horizon inside the weekend.
    now = datetime(2026, 9, 5, 8, tzinfo=timezone.utc)
    windows = context._weekday_windows(entry, now, now + timedelta(hours=12))
    assert windows == []


def test_shift_mode_uses_rotating_cycle_instead_of_weekday_default():
    entry = types.SimpleNamespace(data={
        const.CONF_WORK_MODE: const.WORK_MODE_SHIFT,
        const.CONF_SHIFT_PATTERN: "F,X",
        const.CONF_SHIFT_ANCHOR_DATE: "2026-09-01",
        const.CONF_SHIFT_EARLY_START: "06:00",
        const.CONF_SHIFT_EARLY_END: "14:00",
    })
    start = datetime(2026, 9, 1, 5, tzinfo=timezone.utc)
    windows = context._cycle_windows(entry, start, start + timedelta(days=2))
    assert any(a == datetime(2026, 9, 1, 5, 30, tzinfo=timezone.utc) for a, _ in windows)
    assert not any(a.date().isoformat() == "2026-09-02" for a, _ in windows)


def test_work_windows_defaults_to_weekday_when_no_mode_is_stored():
    class Services:
        async def async_call(self, *args, **kwargs):
            return {}

    hass = types.SimpleNamespace(services=Services())
    entry = types.SimpleNamespace(data={})
    now = datetime(2026, 9, 1, 7, tzinfo=timezone.utc)
    windows = asyncio.run(context.work_windows(hass, entry, now, horizon_hours=12))
    assert windows


def test_actual_work_window_has_no_planning_buffer():
    entry = types.SimpleNamespace(data={
        const.CONF_WORK_MODE: const.WORK_MODE_WEEKDAY,
        const.CONF_WORKDAY_START: "08:00",
        const.CONF_WORKDAY_END: "17:00",
    })
    now = datetime(2026, 9, 1, 7, tzinfo=timezone.utc)
    actual = context._weekday_windows(
        entry, now, now + timedelta(hours=12), buffered=False
    )
    assert (
        datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 1, 17, 0, tzinfo=timezone.utc),
    ) in actual


def test_work_windows_can_return_actual_and_planning_sets():
    class Services:
        async def async_call(self, *args, **kwargs):
            return {}

    hass = types.SimpleNamespace(services=Services())
    entry = types.SimpleNamespace(data={
        const.CONF_WORK_MODE: const.WORK_MODE_WEEKDAY,
        const.CONF_WORKDAY_START: "08:00",
        const.CONF_WORKDAY_END: "17:00",
    })
    now = datetime(2026, 9, 1, 7, tzinfo=timezone.utc)
    actual, planning = asyncio.run(
        context.work_windows(hass, entry, now, horizon_hours=12, return_actual=True)
    )
    assert actual[0][0].hour == 8
    assert planning[0][0].hour == 7 and planning[0][0].minute == 30


def test_evening_activity_answer_maps_to_actual_activity_not_outing_frequency():
    evening = datetime(2026, 9, 1, 19, tzinfo=timezone.utc)
    noon = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    assert context.activity_context_c(evening, 1) < 0
    assert context.activity_context_c(evening, 5) > context.activity_context_c(evening, 1)
    assert context.activity_context_c(noon, 1) == 0


def test_full_shift_absence_removes_planning_buffer_too():
    async def run():
        entry = types.SimpleNamespace(data={
            const.CONF_WORK_MODE: const.WORK_MODE_WEEKDAY,
            const.CONF_WORKDAY_START: "08:00",
            const.CONF_WORKDAY_END: "17:00",
            const.CONF_VACATION_CALENDAR: "calendar.vacation",
        })
        now = datetime(2026, 9, 1, 7, tzinfo=timezone.utc)
        original = context._calendar_windows

        async def fake_calendar(*args, **kwargs):
            return [(
                datetime(2026, 9, 1, 8, tzinfo=timezone.utc),
                datetime(2026, 9, 1, 17, tzinfo=timezone.utc),
            )]

        context._calendar_windows = fake_calendar
        try:
            actual, planning = await context.work_windows(
                types.SimpleNamespace(), entry, now, horizon_hours=12, return_actual=True
            )
        finally:
            context._calendar_windows = original
        assert actual == []
        assert planning == []

    asyncio.run(run())


def test_partial_absence_stays_a_gap_in_planning_window():
    async def run():
        entry = types.SimpleNamespace(data={
            const.CONF_WORK_MODE: const.WORK_MODE_WEEKDAY,
            const.CONF_WORKDAY_START: "08:00",
            const.CONF_WORKDAY_END: "17:00",
            const.CONF_VACATION_CALENDAR: "calendar.vacation",
        })
        now = datetime(2026, 9, 1, 7, tzinfo=timezone.utc)
        original = context._calendar_windows

        async def fake_calendar(*args, **kwargs):
            return [(
                datetime(2026, 9, 1, 12, tzinfo=timezone.utc),
                datetime(2026, 9, 1, 13, tzinfo=timezone.utc),
            )]

        context._calendar_windows = fake_calendar
        try:
            actual, planning = await context.work_windows(
                types.SimpleNamespace(), entry, now, horizon_hours=12, return_actual=True
            )
        finally:
            context._calendar_windows = original
        assert actual == [
            (datetime(2026, 9, 1, 8, tzinfo=timezone.utc), datetime(2026, 9, 1, 12, tzinfo=timezone.utc)),
            (datetime(2026, 9, 1, 13, tzinfo=timezone.utc), datetime(2026, 9, 1, 17, tzinfo=timezone.utc)),
        ]
        assert planning == [
            (datetime(2026, 9, 1, 7, 30, tzinfo=timezone.utc), datetime(2026, 9, 1, 12, tzinfo=timezone.utc)),
            (datetime(2026, 9, 1, 13, tzinfo=timezone.utc), datetime(2026, 9, 1, 17, 30, tzinfo=timezone.utc)),
        ]

    asyncio.run(run())


def test_mixed_evening_activity_is_thermally_neutral():
    evening = datetime(2026, 9, 1, 19, tzinfo=timezone.utc)
    assert context.activity_context_c(evening, 3) == 0.0


def test_equal_weekday_times_do_not_become_24_hour_work_window():
    entry = types.SimpleNamespace(data={
        const.CONF_WORK_MODE: const.WORK_MODE_WEEKDAY,
        const.CONF_WORKDAY_START: "08:00",
        const.CONF_WORKDAY_END: "08:00",
    })
    now = datetime(2026, 9, 1, 7, tzinfo=timezone.utc)
    assert context._weekday_windows(entry, now, now + timedelta(hours=12), buffered=False) == []


def test_equal_shift_times_do_not_become_24_hour_shift():
    entry = types.SimpleNamespace(data={
        const.CONF_SHIFT_PATTERN: "F",
        const.CONF_SHIFT_ANCHOR_DATE: "2026-09-01",
        const.CONF_SHIFT_EARLY_START: "06:00",
        const.CONF_SHIFT_EARLY_END: "06:00",
    })
    now = datetime(2026, 9, 1, 5, tzinfo=timezone.utc)
    assert context._cycle_windows(entry, now, now + timedelta(hours=12), buffered=False) == []


def test_work_windows_are_capped_at_configured_horizon():
    class Services:
        async def async_call(self, *args, **kwargs):
            return {}

    hass = types.SimpleNamespace(services=Services())
    entry = types.SimpleNamespace(data={
        const.CONF_WORK_MODE: const.WORK_MODE_WEEKDAY,
        const.CONF_WORKDAY_START: "08:00",
        const.CONF_WORKDAY_END: "17:00",
    })
    now = datetime(2026, 9, 6, 18, tzinfo=timezone.utc)  # Sunday
    end = now + timedelta(hours=16)  # Monday 10:00
    actual, planning = asyncio.run(
        context.work_windows(hass, entry, now, horizon_hours=16, return_actual=True)
    )
    assert actual == [(
        datetime(2026, 9, 7, 8, tzinfo=timezone.utc),
        end,
    )]
    assert planning[-1][1] == end


def test_post_work_planning_buffer_survives_fresh_recalculation_after_shift_end():
    class Services:
        async def async_call(self, *args, **kwargs):
            return {}

    hass = types.SimpleNamespace(services=Services())
    entry = types.SimpleNamespace(data={
        const.CONF_WORK_MODE: const.WORK_MODE_WEEKDAY,
        const.CONF_WORKDAY_START: "08:00",
        const.CONF_WORKDAY_END: "17:00",
    })
    now = datetime(2026, 9, 1, 17, 10, tzinfo=timezone.utc)
    actual, planning = asyncio.run(
        context.work_windows(hass, entry, now, horizon_hours=12, return_actual=True)
    )
    assert not any(start <= now <= end for start, end in actual)
    assert any(
        start <= now <= end and end == datetime(2026, 9, 1, 17, 30, tzinfo=timezone.utc)
        for start, end in planning
    )
