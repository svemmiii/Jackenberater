from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
import types

ROOT = Path(__file__).parents[1] / "custom_components" / "jackenberater"
PKG = "jackenberater_api_testpkg"

package = types.ModuleType(PKG)
package.__path__ = [str(ROOT)]
sys.modules.setdefault(PKG, package)

# Minimal third-party / Home Assistant surface needed to import api.py.
vol = types.ModuleType("voluptuous")
vol.Required = lambda key, *args, **kwargs: key
vol.Optional = lambda key, *args, **kwargs: key
vol.All = lambda *args, **kwargs: object()
vol.Range = lambda *args, **kwargs: object()
vol.In = lambda *args, **kwargs: object()
vol.Any = lambda *args, **kwargs: object()
sys.modules.setdefault("voluptuous", vol)

ha = types.ModuleType("homeassistant")
ha.__path__ = []
sys.modules.setdefault("homeassistant", ha)
components = types.ModuleType("homeassistant.components")
components.__path__ = []
sys.modules.setdefault(components.__name__, components)
ws = types.ModuleType("homeassistant.components.websocket_api")
ws.websocket_command = lambda schema: (lambda func: func)
ws.async_response = lambda func: func
ws.async_register_command = lambda *args, **kwargs: None
ws.ActiveConnection = type("ActiveConnection", (), {})
sys.modules[ws.__name__] = ws
components.websocket_api = ws
config_entries = types.ModuleType("homeassistant.config_entries")
config_entries.ConfigEntry = type("ConfigEntry", (), {})
sys.modules[config_entries.__name__] = config_entries
core = types.ModuleType("homeassistant.core")
core.HomeAssistant = type("HomeAssistant", (), {})
core.callback = lambda func: func
sys.modules[core.__name__] = core
util = types.ModuleType("homeassistant.util")
util.__path__ = []
sys.modules[util.__name__] = util
ha_dt = types.ModuleType("homeassistant.util.dt")
NOW = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
ha_dt.now = lambda: NOW
ha_dt.as_local = lambda value: value
ha_dt.UTC = timezone.utc
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
models = load("models")
learning = load("learning")
engine = load("engine")

# Stub HA-heavy sibling modules; api.py only needs these callables/types here.
context_stub = types.ModuleType(f"{PKG}.context")
context_stub.activity_context_c = lambda when, answer: 0.0
async def unused_calendar(*args, **kwargs):
    return None
async def unused_windows(*args, **kwargs):
    return ([], [])
context_stub.calendar_context_horizon = unused_calendar
context_stub.work_windows = unused_windows
sys.modules[context_stub.__name__] = context_stub

profiles_stub = types.ModuleType(f"{PKG}.profiles")
profiles_stub.ProfileManager = type("ProfileManager", (), {})
sys.modules[profiles_stub.__name__] = profiles_stub

weather_stub = types.ModuleType(f"{PKG}.weather")
weather_stub.current_weather = lambda *args, **kwargs: None
weather_stub.indoor_temperature_c = lambda *args, **kwargs: 21.5
sys.modules[weather_stub.__name__] = weather_stub

api = load("api")


def point(temp: float, *, dt: datetime = NOW):
    return models.WeatherPoint(dt=dt, temperature_c=temp, condition="cloudy")


def test_normal_user_cannot_mutate_another_profile_through_authenticated_api():
    connection = types.SimpleNamespace(
        user=types.SimpleNamespace(id="user-a", name="A", is_admin=False)
    )
    manager = types.SimpleNamespace(profile_ids={"user-a", "user-b"})
    entry = types.SimpleNamespace(data={const.CONF_SHARED_USER_IDS: []})
    try:
        asyncio.run(api._profile(connection, manager, "user-b", entry))
    except ValueError as err:
        assert str(err) == "shared_profile_access_denied"
    else:
        raise AssertionError("normal users must not access another profile")


def test_shared_user_can_preview_but_cannot_mutate_or_export_another_profile():
    connection = types.SimpleNamespace(
        user=types.SimpleNamespace(id="tablet", name="Tablet", is_admin=False)
    )
    model = object()
    manager = types.SimpleNamespace(
        profile_ids={"person"}, get_model=lambda profile_id: model
    )
    entry = types.SimpleNamespace(data={const.CONF_SHARED_USER_IDS: ["tablet"]})
    profile_id, selected = asyncio.run(
        api._profile(
            connection,
            manager,
            "person",
            entry,
            allow_shared_read=True,
        )
    )
    assert (profile_id, selected) == ("person", model)
    try:
        asyncio.run(api._profile(connection, manager, "person", entry))
    except ValueError as err:
        assert str(err) == "shared_profile_access_denied"
    else:
        raise AssertionError("shared users must not mutate another profile")


def test_admin_can_mutate_another_profile():
    connection = types.SimpleNamespace(
        user=types.SimpleNamespace(id="admin", name="Admin", is_admin=True)
    )
    model = object()
    manager = types.SimpleNamespace(
        profile_ids={"person"}, get_model=lambda profile_id: model
    )
    entry = types.SimpleNamespace(data={const.CONF_SHARED_USER_IDS: []})
    assert asyncio.run(api._profile(connection, manager, "person", entry)) == (
        "person",
        model,
    )


def test_future_work_cache_timestamp_is_not_treated_as_fresh():
    calls = []

    async def fresh_windows(*args, **kwargs):
        calls.append(True)
        return ([], [])

    original = api.work_windows
    api.work_windows = fresh_windows
    runtime = {
        "context_cache": {
            "updated": NOW + timedelta(hours=1),
            "work_windows_actual": [(NOW, NOW)],
            "work_windows_planning": [(NOW, NOW)],
        }
    }
    try:
        result = asyncio.run(
            api._cached_work_window_sets(
                types.SimpleNamespace(), types.SimpleNamespace(data={}), runtime
            )
        )
    finally:
        api.work_windows = original
    assert calls == [True]
    assert result == ([], [])


def test_future_calendar_cache_timestamp_is_not_treated_as_fresh():
    calls = []

    async def fresh_calendar(*args, **kwargs):
        calls.append(True)
        return 6

    original = api.calendar_context_horizon
    api.calendar_context_horizon = fresh_calendar
    runtime = {
        "context_cache": {
            "calendar_updated": NOW + timedelta(hours=1),
            "calendar_horizon": 12,
        }
    }
    entry = types.SimpleNamespace(data={const.CONF_CONTEXT_CALENDAR: "calendar.test"})
    try:
        result = asyncio.run(
            api._cached_calendar_horizon(types.SimpleNamespace(), entry, runtime)
        )
    finally:
        api.calendar_context_horizon = original
    assert calls == [True]
    assert result == 6


def test_shared_user_is_rejected_by_all_foreign_profile_write_endpoints():
    errors = []
    exported = []
    entry = types.SimpleNamespace(
        entry_id="entry",
        data={const.CONF_SHARED_USER_IDS: ["tablet"]},
    )
    manager = types.SimpleNamespace(
        profile_ids={"person"},
        get_model=lambda profile_id: object(),
        export_profile=lambda profile_id: exported.append(profile_id),
    )
    hass = types.SimpleNamespace(
        config_entries=types.SimpleNamespace(async_entries=lambda domain: [entry]),
        data={const.DOMAIN: {"entry": {"profiles": manager}}},
    )
    connection = types.SimpleNamespace(
        user=types.SimpleNamespace(id="tablet", name="Tablet", is_admin=False),
        send_error=lambda *args: errors.append(args),
        send_result=lambda *args: (_ for _ in ()).throw(
            AssertionError("shared write unexpectedly succeeded")
        ),
    )
    calls = [
        (api.ws_open_session, {"id": 1, "profile_id": "person"}),
        (
            api.ws_profile_setup,
            {"id": 2, "profile_id": "person", "cold": 3, "warm": 3, "wind": 3, "evening": 3},
        ),
        (
            api.ws_feedback,
            {"id": 3, "profile_id": "person", "session_id": "x", "rating": "perfect"},
        ),
        (
            api.ws_profile_maintenance,
            {"id": 4, "profile_id": "person", "action": "reset"},
        ),
    ]
    for handler, message in calls:
        asyncio.run(handler(hass, connection, message))
    api.ws_profile_export(hass, connection, {"id": 5, "profile_id": "person"})
    assert len(errors) == 5
    assert exported == []


def test_actual_work_window_does_not_fall_back_to_home_when_work_current_is_missing():
    home = point(18)
    entry = types.SimpleNamespace(
        data={
            const.CONF_WEATHER: "weather.home",
            const.CONF_WORK_WEATHER: "weather.work",
            const.CONF_FALLBACK_INDOOR_TEMP: 21.5,
            const.CONF_RAIN_ADVICE: True,
        }
    )
    runtime = {
        "coordinator": types.SimpleNamespace(data={"home_forecast": [], "work_forecast": []}),
        "context_cache": {},
    }
    model = learning.PersonalModel.from_answers(3, 3, 3, 3)

    api.current_weather = lambda hass, entity_id: home if entity_id == "weather.home" else None
    api.indoor_temperature_c = lambda *args, **kwargs: 21.5

    async def no_calendar(*args, **kwargs):
        return None

    async def work_sets(*args, **kwargs):
        return (
            [(NOW - timedelta(hours=1), NOW + timedelta(hours=2))],
            [(NOW - timedelta(hours=1, minutes=30), NOW + timedelta(hours=2, minutes=30))],
        )

    api._cached_calendar_horizon = no_calendar
    api._cached_work_window_sets = work_sets

    try:
        asyncio.run(api._recommendation(types.SimpleNamespace(states=None), entry, runtime, model))
    except ValueError as err:
        assert str(err) == "work_weather_unavailable"
    else:
        raise AssertionError("work weather outage must not silently use home current weather")


def test_current_work_weather_is_used_inside_actual_work_window():
    home = point(18)
    work = point(6)
    entry = types.SimpleNamespace(
        data={
            const.CONF_WEATHER: "weather.home",
            const.CONF_WORK_WEATHER: "weather.work",
            const.CONF_FALLBACK_INDOOR_TEMP: 21.5,
            const.CONF_RAIN_ADVICE: True,
        }
    )
    runtime = {
        "coordinator": types.SimpleNamespace(data={"home_forecast": [], "work_forecast": []}),
        "context_cache": {},
    }
    model = learning.PersonalModel.from_answers(3, 3, 3, 3)
    api.current_weather = lambda hass, entity_id: work if entity_id == "weather.work" else home
    api.indoor_temperature_c = lambda *args, **kwargs: 23.0

    async def no_calendar(*args, **kwargs):
        return None

    async def work_sets(*args, **kwargs):
        return (
            [(NOW - timedelta(hours=1), NOW + timedelta(hours=2))],
            [(NOW - timedelta(hours=1, minutes=30), NOW + timedelta(hours=2, minutes=30))],
        )

    api._cached_calendar_horizon = no_calendar
    api._cached_work_window_sets = work_sets
    rec = asyncio.run(api._recommendation(types.SimpleNamespace(states=None), entry, runtime, model))
    assert rec.source == "work"
    assert rec.current_temperature_c == 6


def test_work_horizon_extends_home_timeline_before_building_recommendation():
    """A later work point must extend the normal timeline before evaluation."""
    home = point(28)
    home_forecast = [
        point(0 if hour == 13 else 28, dt=NOW + timedelta(hours=hour))
        for hour in range(1, 14)
    ]
    work_forecast = [point(28, dt=NOW + timedelta(hours=14))]
    entry = types.SimpleNamespace(
        data={
            const.CONF_WEATHER: "weather.home",
            const.CONF_WORK_WEATHER: "weather.work",
            const.CONF_FALLBACK_INDOOR_TEMP: 21.5,
            const.CONF_RAIN_ADVICE: True,
        }
    )
    runtime = {
        "coordinator": types.SimpleNamespace(
            data={"home_forecast": home_forecast, "work_forecast": work_forecast}
        ),
        "context_cache": {},
    }
    model = learning.PersonalModel.from_answers(3, 3, 3, 3)
    api.current_weather = lambda hass, entity_id: home
    api.indoor_temperature_c = lambda *args, **kwargs: 21.5

    async def no_calendar(*args, **kwargs):
        return None

    async def work_sets(*args, **kwargs):
        return (
            [(NOW + timedelta(hours=14), NOW + timedelta(hours=15))],
            [(NOW + timedelta(hours=13, minutes=30), NOW + timedelta(hours=15, minutes=30))],
        )

    api._cached_calendar_horizon = no_calendar
    api._cached_work_window_sets = work_sets
    rec = asyncio.run(
        api._recommendation(types.SimpleNamespace(states=None), entry, runtime, model)
    )

    assert rec.horizon_hours >= 14
    assert rec.jacket_later == const.JACKET_WINTER
    assert rec.later_at == NOW + timedelta(hours=13)
    assert rec.min_effective_c < 5


def test_missing_planned_work_forecast_is_reported_as_incomplete():
    home = point(18)
    entry = types.SimpleNamespace(data={
        const.CONF_WEATHER: "weather.home",
        const.CONF_WORK_WEATHER: "weather.work",
        const.CONF_FALLBACK_INDOOR_TEMP: 21.5,
        const.CONF_RAIN_ADVICE: True,
    })
    runtime = {"coordinator": types.SimpleNamespace(data={"home_forecast": [], "work_forecast": []}), "context_cache": {}}
    model = learning.PersonalModel.from_answers(3, 3, 3, 3)
    api.current_weather = lambda hass, entity_id: home
    api.indoor_temperature_c = lambda *args, **kwargs: 21.5

    async def no_calendar(*args, **kwargs):
        return None

    async def future_work(*args, **kwargs):
        return ([(NOW + timedelta(hours=2), NOW + timedelta(hours=5))], [(NOW + timedelta(hours=1, minutes=30), NOW + timedelta(hours=5, minutes=30))])

    api._cached_calendar_horizon = no_calendar
    api._cached_work_window_sets = future_work
    rec = asyncio.run(api._recommendation(types.SimpleNamespace(states=types.SimpleNamespace(get=lambda *_: None)), entry, runtime, model))
    assert rec.work_weather_available is False
