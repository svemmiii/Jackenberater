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


load("const")
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
    # The second shift is kept only until the absence starts instead of being
    # discarded wholesale.
    assert filtered[1] == (work[1][0], vacation[0][0])


def test_non_overlapping_vacation_keeps_work_window():
    base = datetime(2026, 9, 1, 6, tzinfo=timezone.utc)
    work = [(base, base + timedelta(hours=8))]
    vacation = [(base + timedelta(hours=12), base + timedelta(hours=20))]
    assert context._subtract_blocked_windows(work, vacation) == work


def test_empty_work_calendar_is_authoritative_over_shift_cycle():
    class Services:
        async def async_call(self, *args, **kwargs):
            entity_id = kwargs.get("target", {}).get("entity_id")
            return {entity_id: {"events": []}}

    hass = types.SimpleNamespace(services=Services())
    entry = types.SimpleNamespace(data={
        context.CONF_WORK_CALENDAR: "calendar.work",
        context.CONF_SHIFT_PATTERN: "F,F,S,S,N,N,N,X,X",
        context.CONF_SHIFT_ANCHOR_DATE: "2026-09-01",
    })
    now = datetime(2026, 9, 1, 5, tzinfo=timezone.utc)
    windows = asyncio.run(context.work_windows(hass, entry, now, horizon_hours=16))
    assert windows == []
