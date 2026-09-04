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
    return None, const.CALENDAR_STATUS_NOT_CONFIGURED
async def unused_windows(*args, **kwargs):
    return ([], [], const.CALENDAR_STATUS_NOT_CONFIGURED)
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


def test_real_recommendation_survives_ws_preview_and_shared_diagnostics_stay_private():
    results = []
    model = learning.PersonalModel.from_answers(3, 3, 3, 3)
    entry = types.SimpleNamespace(
        entry_id="entry", data={const.CONF_SHARED_USER_IDS: ["tablet"]}
    )

    async def fixed_recommendation(*args, **kwargs):
        return models.Recommendation(
            jacket_now=const.JACKET_LIGHT, jacket_later=const.JACKET_LIGHT,
            later_at=None, rain_status=const.RAIN_NONE,
            display_mode=const.DISPLAY_FULL, horizon_hours=1,
            effective_now_c=15.0, min_effective_c=15.0, max_effective_c=15.0,
            confidence=0.2, reasons=[], current_temperature_c=15.0,
            current_wind_kmh=5.0, current_gust_kmh=5.0,
            current_condition="cloudy", transition_penalty_c=0.0,
        )

    manager = types.SimpleNamespace(
        profile_ids={"person"}, get_model=lambda profile_id: model,
        get_profile_summary=lambda profile_id: {
            "id": profile_id, "name": "Person", "setup_complete": True,
            "confidence": 0.2, "total_feedback": 0,
        },
        feedback_candidates=lambda profile_id, **kwargs: [],
        latest_session=lambda profile_id: None,
    )
    hass = types.SimpleNamespace(
        config_entries=types.SimpleNamespace(async_entries=lambda domain: [entry]),
        data={const.DOMAIN: {"entry": {"profiles": manager, "simulations": {}}}},
    )
    connection = types.SimpleNamespace(
        user=types.SimpleNamespace(id="tablet", name="Tablet", is_admin=False),
        send_error=lambda *args: (_ for _ in ()).throw(AssertionError(args)),
        send_result=lambda *args: results.append(args[1]),
    )
    original = api._recommendation
    api._recommendation = fixed_recommendation
    try:
        asyncio.run(api.ws_preview(hass, connection, {"id": 1, "profile_id": "person"}))
    finally:
        api._recommendation = original
    assert results[0]["recommendation"]["simulation_active"] is False
    assert "diagnostics" not in results[0]
    assert set(results[0]["profile"]) == {"id", "name", "setup_complete"}


def test_own_ws_preview_contains_personal_diagnostics():
    results = []
    model = learning.PersonalModel.from_answers(3, 3, 3, 3)
    entry = types.SimpleNamespace(
        entry_id="entry", data={const.CONF_SHARED_USER_IDS: []}
    )

    async def ensure(*args, **kwargs):
        return model

    async def fixed_recommendation(*args, **kwargs):
        return models.Recommendation(
            jacket_now=const.JACKET_LIGHT, jacket_later=const.JACKET_LIGHT,
            later_at=None, rain_status=const.RAIN_NONE,
            display_mode=const.DISPLAY_FULL, horizon_hours=1,
            effective_now_c=15.0, min_effective_c=15.0, max_effective_c=15.0,
            confidence=0.2, reasons=[], current_temperature_c=15.0,
            current_wind_kmh=5.0, current_gust_kmh=5.0,
            current_condition="cloudy", transition_penalty_c=0.0,
        )

    manager = types.SimpleNamespace(
        profile_ids={"person"}, get_model=lambda profile_id: model,
        async_ensure_profile=ensure,
        get_profile_summary=lambda profile_id: {
            "id": profile_id, "name": "Person", "setup_complete": True,
            "confidence": 0.2, "total_feedback": 0,
        },
        feedback_candidates=lambda profile_id, **kwargs: [],
        latest_session=lambda profile_id: None,
    )
    hass = types.SimpleNamespace(
        config_entries=types.SimpleNamespace(async_entries=lambda domain: [entry]),
        data={const.DOMAIN: {"entry": {"profiles": manager, "simulations": {}}}},
    )
    connection = types.SimpleNamespace(
        user=types.SimpleNamespace(id="person", name="Person", is_admin=False),
        send_error=lambda *args: (_ for _ in ()).throw(AssertionError(args)),
        send_result=lambda *args: results.append(args[1]),
    )
    original = api._recommendation
    api._recommendation = fixed_recommendation
    try:
        asyncio.run(api.ws_preview(hass, connection, {"id": 1, "profile_id": "person"}))
    finally:
        api._recommendation = original
    assert results[0]["diagnostics"]["cold_answer"] == 3
    assert results[0]["diagnostics"]["simulation_active"] is False


def test_work_forecast_coverage_detects_missing_partial_and_complete():
    start = NOW + timedelta(hours=1)
    end = NOW + timedelta(hours=9)
    windows = [(start, end)]
    assert api._work_forecast_coverage(NOW, [], windows) == "missing"
    assert api._work_forecast_coverage(
        NOW, [point(10, dt=NOW + timedelta(hours=5))], windows
    ) == "partial"
    hourly = [
        point(10, dt=NOW + timedelta(hours=hour))
        for hour in range(1, 10)
    ]
    assert api._work_forecast_coverage(NOW, hourly, windows) == "complete"


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
        return ([], [], const.CALENDAR_STATUS_AVAILABLE)

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
    assert result == ([], [], const.CALENDAR_STATUS_AVAILABLE)


def test_future_calendar_cache_timestamp_is_not_treated_as_fresh():
    calls = []

    async def fresh_calendar(*args, **kwargs):
        calls.append(True)
        return 6, const.CALENDAR_STATUS_AVAILABLE

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
    assert result == (6, const.CALENDAR_STATUS_AVAILABLE)


def test_shared_user_opens_own_profile_scoped_session_but_not_other_writes():
    errors = []
    results = []
    opened_by = []
    entry = types.SimpleNamespace(
        entry_id="entry",
        data={const.CONF_SHARED_USER_IDS: ["tablet"]},
    )
    model = learning.PersonalModel.from_answers(3, 3, 3, 3)

    async def open_session(profile_id, recommendation, **kwargs):
        opened_by.append((profile_id, kwargs["opened_by_user_id"]))
        return {"id": "private-server-session"}

    manager = types.SimpleNamespace(
        profile_ids={"person"}, get_model=lambda profile_id: model,
        async_open_session=open_session,
        feedback_candidates=lambda profile_id, **kwargs: [],
        get_profile_summary=lambda profile_id: {
            "id": profile_id,
            "name": "Person",
            "setup_complete": True,
            "total_feedback": 42,
            "learning_enabled": True,
        },
        is_feedback_candidate=lambda *args, **kwargs: False,
        export_profile=lambda profile_id: (_ for _ in ()).throw(
            AssertionError("disabled export reached manager")
        ),
    )
    hass = types.SimpleNamespace(
        config_entries=types.SimpleNamespace(async_entries=lambda domain: [entry]),
        data={const.DOMAIN: {"entry": {"profiles": manager, "simulations": {}}}},
    )
    connection = types.SimpleNamespace(
        user=types.SimpleNamespace(id="tablet", name="Tablet", is_admin=False),
        send_error=lambda *args: errors.append(args),
        send_result=lambda *args: results.append(args),
    )
    original_recommendation = api._recommendation

    async def fixed_recommendation(*args, **kwargs):
        return models.Recommendation(
            jacket_now=const.JACKET_LIGHT, jacket_later=const.JACKET_LIGHT,
            later_at=None, rain_status=const.RAIN_NONE, display_mode=const.DISPLAY_FULL,
            horizon_hours=1, effective_now_c=15.0, min_effective_c=15.0,
            max_effective_c=15.0, confidence=0.2, reasons=[],
            current_temperature_c=15.0, current_wind_kmh=5.0,
            current_gust_kmh=5.0, current_condition="cloudy",
            transition_penalty_c=0.0,
        )

    api._recommendation = fixed_recommendation
    try:
        asyncio.run(api.ws_open_session(hass, connection, {"id": 1, "profile_id": "person"}))
    finally:
        api._recommendation = original_recommendation

    assert opened_by == [("person", "tablet")]
    assert results[0][1]["session"] is None
    assert results[0][1]["profile"] == {
        "id": "person",
        "name": "Person",
        "setup_complete": True,
    }
    calls = [
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
    assert len(errors) == 4


def test_shared_feedback_requires_a_mature_session_opened_by_same_login():
    errors = []
    results = []
    feedback_calls = []
    entry = types.SimpleNamespace(
        entry_id="entry", data={const.CONF_SHARED_USER_IDS: ["tablet"]}
    )
    model = learning.PersonalModel.from_answers(3, 3, 3, 3)

    async def accept_feedback(profile_id, session_id, **kwargs):
        feedback_calls.append((profile_id, session_id, kwargs))
        return {"id": session_id, "feedback": {"rating": kwargs["rating"]}}

    manager = types.SimpleNamespace(
        profile_ids={"person"}, get_model=lambda profile_id: model,
        is_feedback_candidate=lambda profile_id, session_id, **kwargs: (
            session_id == "due-owned" and kwargs["opened_by_user_id"] == "tablet"
        ),
        async_feedback=accept_feedback,
        get_profile_summary=lambda profile_id: {
            "id": profile_id,
            "name": "Person",
            "setup_complete": True,
            "total_feedback": 42,
        },
    )
    hass = types.SimpleNamespace(
        config_entries=types.SimpleNamespace(async_entries=lambda domain: [entry]),
        data={const.DOMAIN: {"entry": {"profiles": manager, "simulations": {}}}},
    )
    connection = types.SimpleNamespace(
        user=types.SimpleNamespace(id="tablet", name="Tablet", is_admin=False),
        send_error=lambda *args: errors.append(args), send_result=lambda *args: results.append(args),
    )
    base = {"profile_id": "person", "rating": const.FEEDBACK_PERFECT}
    asyncio.run(api.ws_feedback(hass, connection, {"id": 1, "session_id": "other", **base}))
    asyncio.run(api.ws_feedback(hass, connection, {"id": 2, "session_id": "due-owned", "voluntary": True, **base}))
    asyncio.run(api.ws_feedback(hass, connection, {"id": 3, "session_id": "due-owned", **base}))
    assert len(errors) == 2
    assert len(results) == 1
    assert results[0][1]["profile"] == {
        "id": "person",
        "name": "Person",
        "setup_complete": True,
    }
    assert [(call[0], call[1]) for call in feedback_calls] == [("person", "due-owned")]


def test_simulation_blocks_sessions_and_feedback_without_changing_persistent_data():
    import copy

    errors = []
    entry = types.SimpleNamespace(
        entry_id="entry", data={const.CONF_SHARED_USER_IDS: []}
    )
    real = learning.PersonalModel.from_answers(3, 3, 3, 3)
    simulated = learning.PersonalModel.from_dict(real.to_dict())
    simulated.general_offset_c = 4.0
    persistent = {
        "person": {
            "model": real.to_dict(),
            "sessions": [{"id": "existing", "feedback": None}],
        }
    }
    before = copy.deepcopy(persistent)

    async def forbidden(*args, **kwargs):
        raise AssertionError("simulation reached a persistent mutation")

    async def ensure_existing(*args, **kwargs):
        return False

    manager = types.SimpleNamespace(
        profile_ids={"person"},
        get_model=lambda profile_id: learning.PersonalModel.from_dict(
            persistent[profile_id]["model"]
        ),
        async_ensure_profile=ensure_existing,
        async_open_session=forbidden,
        async_feedback=forbidden,
        is_feedback_candidate=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("simulation checked a feedback candidate")
        ),
    )
    hass = types.SimpleNamespace(
        config_entries=types.SimpleNamespace(async_entries=lambda domain: [entry]),
        data={
            const.DOMAIN: {
                "entry": {"profiles": manager, "simulations": {"person": simulated}}
            }
        },
    )
    connection = types.SimpleNamespace(
        user=types.SimpleNamespace(id="person", name="Person", is_admin=False),
        send_error=lambda *args: errors.append(args),
        send_result=lambda *args: (_ for _ in ()).throw(
            AssertionError("simulation mutation unexpectedly succeeded")
        ),
    )
    asyncio.run(api.ws_open_session(hass, connection, {"id": 1, "profile_id": "person"}))
    asyncio.run(
        api.ws_feedback(
            hass, connection,
            {"id": 2, "profile_id": "person", "session_id": "existing", "rating": "perfect"},
        )
    )
    assert len(errors) == 2
    assert persistent == before


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
        return None, const.CALENDAR_STATUS_NOT_CONFIGURED

    async def work_sets(*args, **kwargs):
        return (
            [(NOW - timedelta(hours=1), NOW + timedelta(hours=2))],
            [(NOW - timedelta(hours=1, minutes=30), NOW + timedelta(hours=2, minutes=30))],
            const.CALENDAR_STATUS_NOT_CONFIGURED,
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
        return None, const.CALENDAR_STATUS_NOT_CONFIGURED

    async def work_sets(*args, **kwargs):
        return (
            [(NOW - timedelta(hours=1), NOW + timedelta(hours=2))],
            [(NOW - timedelta(hours=1, minutes=30), NOW + timedelta(hours=2, minutes=30))],
            const.CALENDAR_STATUS_NOT_CONFIGURED,
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
        return None, const.CALENDAR_STATUS_NOT_CONFIGURED

    async def work_sets(*args, **kwargs):
        return (
            [(NOW + timedelta(hours=14), NOW + timedelta(hours=15))],
            [(NOW + timedelta(hours=13, minutes=30), NOW + timedelta(hours=15, minutes=30))],
            const.CALENDAR_STATUS_NOT_CONFIGURED,
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
        return None, const.CALENDAR_STATUS_NOT_CONFIGURED

    async def future_work(*args, **kwargs):
        return (
            [(NOW + timedelta(hours=2), NOW + timedelta(hours=5))],
            [(NOW + timedelta(hours=1, minutes=30), NOW + timedelta(hours=5, minutes=30))],
            const.CALENDAR_STATUS_NOT_CONFIGURED,
        )

    api._cached_calendar_horizon = no_calendar
    api._cached_work_window_sets = future_work
    rec = asyncio.run(api._recommendation(types.SimpleNamespace(states=types.SimpleNamespace(get=lambda *_: None)), entry, runtime, model))
    assert rec.work_weather_available is False


def test_calendar_unavailable_status_reaches_recommendation_response():
    home = point(18)
    entry = types.SimpleNamespace(data={
        const.CONF_WEATHER: "weather.home",
        const.CONF_FALLBACK_INDOOR_TEMP: 21.5,
        const.CONF_RAIN_ADVICE: True,
        const.CONF_CONTEXT_CALENDAR: "calendar.context",
    })
    runtime = {
        "coordinator": types.SimpleNamespace(
            data={"home_forecast": [], "work_forecast": []}
        ),
        "context_cache": {},
    }
    model = learning.PersonalModel.from_answers(3, 3, 3, 3)
    api.current_weather = lambda hass, entity_id: home
    api.indoor_temperature_c = lambda *args, **kwargs: 21.5

    async def unavailable_calendar(*args, **kwargs):
        return None, const.CALENDAR_STATUS_UNAVAILABLE

    original = api._cached_calendar_horizon
    api._cached_calendar_horizon = unavailable_calendar
    try:
        rec = asyncio.run(
            api._recommendation(types.SimpleNamespace(states=None), entry, runtime, model)
        )
    finally:
        api._cached_calendar_horizon = original
    assert rec.context_calendar_status == const.CALENDAR_STATUS_UNAVAILABLE
    assert rec.as_dict()["context_calendar_status"] == "unavailable"
