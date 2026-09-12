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
REAL_CACHED_WORK_WINDOW_SETS = api._cached_work_window_sets
REAL_CACHED_CALENDAR_HORIZON = api._cached_calendar_horizon


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
        prepare_model_for_advice=lambda profile_id, when=None: model,
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
        prepare_model_for_advice=lambda profile_id, when=None: model,
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
        prepare_model_for_advice=lambda profile_id, when=None: model,
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


def test_shared_feedback_accepts_any_mature_session_for_selected_profile():
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
            session_id == "due-owned" and not kwargs
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


def test_calendar_cache_generation_prevents_inflight_work_request_from_repopulating_stale_cache():
    runtime = {"context_cache": {}, "context_cache_generation": 0}

    calls = 0
    async def raced_windows(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            runtime["context_cache_generation"] += 1
            runtime["context_cache"].clear()
            return ([(NOW, NOW + timedelta(hours=1))], [], const.CALENDAR_STATUS_AVAILABLE)
        return ([(NOW + timedelta(hours=1), NOW + timedelta(hours=2))], [], const.CALENDAR_STATUS_AVAILABLE)

    original = api.work_windows
    api.work_windows = raced_windows
    try:
        result = asyncio.run(api._cached_work_window_sets(types.SimpleNamespace(), types.SimpleNamespace(data={}), runtime))
    finally:
        api.work_windows = original

    assert result[2] == const.CALENDAR_STATUS_AVAILABLE
    assert result[0][0][0] == NOW + timedelta(hours=1)
    assert calls == 2
    assert "updated" in runtime["context_cache"]


def test_calendar_cache_generation_prevents_inflight_context_request_from_repopulating_stale_cache():
    runtime = {"context_cache": {}, "context_cache_generation": 0}
    entry = types.SimpleNamespace(data={const.CONF_CONTEXT_CALENDAR: "calendar.context"})

    calls = 0
    async def raced_context(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            runtime["context_cache_generation"] += 1
            runtime["context_cache"].clear()
            return 6, const.CALENDAR_STATUS_AVAILABLE
        return 8, const.CALENDAR_STATUS_AVAILABLE

    original = api.calendar_context_horizon
    api.calendar_context_horizon = raced_context
    try:
        result = asyncio.run(api._cached_calendar_horizon(types.SimpleNamespace(), entry, runtime))
    finally:
        api.calendar_context_horizon = original

    assert result == (8, const.CALENDAR_STATUS_AVAILABLE)
    assert calls == 2
    assert "calendar_updated" in runtime["context_cache"]


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
    assert rec.work_weather_available is True
    assert rec.work_forecast_coverage == "missing"


def test_forecast_freshness_guard_rejects_retained_stale_data_after_failed_refresh():
    class Coordinator:
        def __init__(self):
            self.data = {
                "updated": NOW - const.FORECAST_REFRESH - timedelta(seconds=1),
                "home_forecast": [point(3, dt=NOW + timedelta(hours=1))],
            }
            self.last_update_success = True

        async def async_refresh(self):
            # Match DataUpdateCoordinator behaviour on provider failure: the old
            # data can remain while success is marked false.
            self.last_update_success = False

    original_now = api.dt_util.now
    api.dt_util.now = lambda: NOW
    coordinator = Coordinator()
    try:
        fresh = asyncio.run(api._ensure_forecast_fresh(coordinator))
    finally:
        api.dt_util.now = original_now
    assert fresh is False
    assert coordinator.data["home_forecast"]  # retained by coordinator, but rejected by API


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


def test_forecast_freshness_guard_refreshes_stale_coordinator():
    calls = []

    class Coordinator:
        def __init__(self):
            self.data = {"updated": NOW - const.FORECAST_REFRESH - timedelta(seconds=1)}

        async def async_refresh(self):
            calls.append("refresh")
            self.data["updated"] = NOW

    original_now = api.dt_util.now
    api.dt_util.now = lambda: NOW
    try:
        asyncio.run(api._ensure_forecast_fresh(Coordinator()))
    finally:
        api.dt_util.now = original_now
    assert calls == ["refresh"]




def test_recommendation_does_not_use_stale_forecast_after_failed_refresh():
    current = point(18)

    class Coordinator:
        def __init__(self):
            self.data = {
                "updated": NOW - const.FORECAST_REFRESH - timedelta(seconds=1),
                "home_forecast": [point(-8, dt=NOW + timedelta(hours=1))],
                "work_forecast": [],
            }
            self.last_update_success = True

        async def async_refresh(self):
            self.last_update_success = False

    entry = types.SimpleNamespace(data={
        const.CONF_WEATHER: "weather.home",
        const.CONF_FALLBACK_INDOOR_TEMP: 21.5,
        const.CONF_RAIN_ADVICE: True,
    })
    runtime = {"coordinator": Coordinator(), "context_cache": {}}
    model = learning.PersonalModel.from_answers(3, 3, 3, 3)
    original_current = api.current_weather
    original_indoor = api.indoor_temperature_c
    original_calendar = api._cached_calendar_horizon
    original_now = api.dt_util.now
    api.current_weather = lambda *args, **kwargs: current
    api.indoor_temperature_c = lambda *args, **kwargs: 21.5
    api.dt_util.now = lambda: NOW

    async def no_calendar(*args, **kwargs):
        return None, const.CALENDAR_STATUS_NOT_CONFIGURED

    api._cached_calendar_horizon = no_calendar
    try:
        rec = asyncio.run(api._recommendation(types.SimpleNamespace(states=None), entry, runtime, model))
    finally:
        api.current_weather = original_current
        api.indoor_temperature_c = original_indoor
        api._cached_calendar_horizon = original_calendar
        api.dt_util.now = original_now
    assert rec.horizon_hours == 0
    assert rec.jacket_later == rec.jacket_now

def test_forecast_freshness_guard_keeps_recent_coordinator():
    calls = []

    class Coordinator:
        def __init__(self):
            self.data = {"updated": NOW - timedelta(minutes=5)}

        async def async_refresh(self):
            calls.append("refresh")

    original_now = api.dt_util.now
    api.dt_util.now = lambda: NOW
    try:
        asyncio.run(api._ensure_forecast_fresh(Coordinator()))
    finally:
        api.dt_util.now = original_now
    assert calls == []


def test_active_work_weather_is_used_even_when_home_weather_is_unavailable():
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

    original_current = api.current_weather
    original_indoor = api.indoor_temperature_c
    original_calendar = api._cached_calendar_horizon
    original_work_sets = api._cached_work_window_sets
    api.current_weather = lambda hass, entity_id: work if entity_id == "weather.work" else None
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
    hass = types.SimpleNamespace(states=types.SimpleNamespace(get=lambda entity_id: None))
    try:
        rec = asyncio.run(api._recommendation(hass, entry, runtime, model))
    finally:
        api.current_weather = original_current
        api.indoor_temperature_c = original_indoor
        api._cached_calendar_horizon = original_calendar
        api._cached_work_window_sets = original_work_sets

    assert rec.source == "work"
    assert rec.current_temperature_c == 6.0


def test_multiple_work_windows_display_the_window_that_drives_later_advice():
    home = point(20)
    first = (NOW + timedelta(hours=1), NOW + timedelta(hours=3))
    second = (NOW + timedelta(hours=10), NOW + timedelta(hours=14))
    later_at = NOW + timedelta(hours=12)
    work_forecast = [point(5, dt=later_at)]
    entry = types.SimpleNamespace(
        data={
            const.CONF_WEATHER: "weather.home",
            const.CONF_WORK_WEATHER: "weather.work",
            const.CONF_FALLBACK_INDOOR_TEMP: 21.5,
            const.CONF_RAIN_ADVICE: True,
        }
    )
    runtime = {
        "coordinator": types.SimpleNamespace(data={"home_forecast": [], "work_forecast": work_forecast}),
        "context_cache": {},
    }
    model = learning.PersonalModel.from_answers(3, 3, 3, 3)

    original_current = api.current_weather
    original_indoor = api.indoor_temperature_c
    original_calendar = api._cached_calendar_horizon
    original_work_sets = api._cached_work_window_sets
    original_build = api.build_recommendation
    api.current_weather = lambda hass, entity_id: home
    api.indoor_temperature_c = lambda *args, **kwargs: 21.5

    async def no_calendar(*args, **kwargs):
        return None, const.CALENDAR_STATUS_NOT_CONFIGURED

    async def work_sets(*args, **kwargs):
        planning = [
            (first[0] - timedelta(minutes=30), first[1] + timedelta(minutes=30)),
            (second[0] - timedelta(minutes=30), second[1] + timedelta(minutes=30)),
        ]
        return [first, second], planning, const.CALENDAR_STATUS_NOT_CONFIGURED

    def fixed_build(*args, **kwargs):
        return models.Recommendation(
            jacket_now=const.JACKET_NONE,
            jacket_later=const.JACKET_WARM,
            later_at=later_at,
            rain_status=const.RAIN_NONE,
            display_mode=const.DISPLAY_FULL,
            horizon_hours=12,
            effective_now_c=20.0,
            min_effective_c=5.0,
            max_effective_c=20.0,
            confidence=0.5,
            reasons=["forecast_change", "work_location"],
            current_temperature_c=20.0,
            current_wind_kmh=0.0,
            current_gust_kmh=0.0,
            current_condition="sunny",
            transition_penalty_c=0.0,
            later_context="work",
            work_context=True,
            work_jacket=const.JACKET_WARM,
        )

    api._cached_calendar_horizon = no_calendar
    api._cached_work_window_sets = work_sets
    api.build_recommendation = fixed_build
    hass = types.SimpleNamespace(states=types.SimpleNamespace(get=lambda entity_id: None))
    try:
        rec = asyncio.run(api._recommendation(hass, entry, runtime, model))
    finally:
        api.current_weather = original_current
        api.indoor_temperature_c = original_indoor
        api._cached_calendar_horizon = original_calendar
        api._cached_work_window_sets = original_work_sets
        api.build_recommendation = original_build

    assert rec.work_start == second[0]
    assert rec.work_end == second[1]


def test_work_forecast_coverage_shift_end_short_tail_and_past_window():
    shift_end = datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc)
    window = [(datetime(2026, 9, 1, 5, 30, tzinfo=timezone.utc), shift_end + timedelta(minutes=30))]
    points = [
        point(10, dt=datetime(2026, 9, 1, hour, 0, tzinfo=timezone.utc))
        for hour in (13, 14, 15, 16)
    ]
    for minute in (59,):
        origin = datetime(2026, 9, 1, 13, minute, tzinfo=timezone.utc)
        assert api._work_forecast_coverage(origin, points, window) == "complete"
    for minute in (0, 1, 10, 29):
        origin = datetime(2026, 9, 1, 14, minute, tzinfo=timezone.utc)
        assert api._work_forecast_coverage(origin, points, window) == "complete"
    for minute in (30, 31):
        origin = datetime(2026, 9, 1, 14, minute, tzinfo=timezone.utc)
        assert api._work_forecast_coverage(origin, points, window) == "not_applicable"


def test_work_forecast_coverage_all_standard_shift_end_hours():
    for hour in (6, 14, 17, 22):
        shift_end = datetime(2026, 9, 1, hour, 0, tzinfo=timezone.utc)
        window = [(shift_end - timedelta(hours=8, minutes=30), shift_end + timedelta(minutes=30))]
        points = [
            point(10, dt=shift_end - timedelta(hours=1)),
            point(10, dt=shift_end),
            point(10, dt=shift_end + timedelta(hours=1)),
        ]
        assert api._work_forecast_coverage(shift_end, points, window) == "complete"
        assert api._work_forecast_coverage(shift_end + timedelta(minutes=10), points, window) == "complete"


def test_post_work_buffer_keeps_true_shift_bounds_and_marks_buffer_context():
    home = point(20, dt=NOW + timedelta(hours=3, minutes=5))  # 15:05
    actual = (NOW + timedelta(hours=1), NOW + timedelta(hours=3))  # 13:00-15:00
    planning = (actual[0] - timedelta(minutes=30), actual[1] + timedelta(minutes=30))
    later_at = NOW + timedelta(hours=3, minutes=15)  # 15:15, buffer only
    entry = types.SimpleNamespace(data={
        const.CONF_WEATHER: "weather.home",
        const.CONF_WORK_WEATHER: "weather.work",
        const.CONF_FALLBACK_INDOOR_TEMP: 21.5,
        const.CONF_RAIN_ADVICE: True,
    })
    runtime = {"coordinator": types.SimpleNamespace(data={"home_forecast": [], "work_forecast": [point(8, dt=later_at)]}), "context_cache": {}}
    model = learning.PersonalModel.from_answers(3, 3, 3, 3)

    original_now = api.dt_util.now
    original_current = api.current_weather
    original_indoor = api.indoor_temperature_c
    original_calendar = api._cached_calendar_horizon
    original_work_sets = api._cached_work_window_sets
    original_build = api.build_recommendation
    api.dt_util.now = lambda: home.dt
    api.current_weather = lambda hass, entity_id: home
    api.indoor_temperature_c = lambda *args, **kwargs: 21.5

    async def no_calendar(*args, **kwargs):
        return None, const.CALENDAR_STATUS_NOT_CONFIGURED

    async def work_sets(*args, **kwargs):
        return [actual], [planning], const.CALENDAR_STATUS_NOT_CONFIGURED

    def fixed_build(*args, **kwargs):
        return models.Recommendation(
            jacket_now=const.JACKET_NONE, jacket_later=const.JACKET_LIGHT,
            later_at=later_at, rain_status=const.RAIN_NONE, display_mode=const.DISPLAY_FULL,
            horizon_hours=1, effective_now_c=20.0, min_effective_c=8.0, max_effective_c=20.0,
            confidence=0.5, reasons=["forecast_change", "work_location"],
            current_temperature_c=20.0, current_wind_kmh=0.0, current_gust_kmh=0.0,
            current_condition="sunny", transition_penalty_c=0.0,
            later_context="work", work_context=True, work_jacket=const.JACKET_LIGHT,
        )

    api._cached_calendar_horizon = no_calendar
    api._cached_work_window_sets = work_sets
    api.build_recommendation = fixed_build
    hass = types.SimpleNamespace(states=types.SimpleNamespace(get=lambda entity_id: None))
    try:
        rec = asyncio.run(api._recommendation(hass, entry, runtime, model))
    finally:
        api.dt_util.now = original_now
        api.current_weather = original_current
        api.indoor_temperature_c = original_indoor
        api._cached_calendar_horizon = original_calendar
        api._cached_work_window_sets = original_work_sets
        api.build_recommendation = original_build

    assert rec.work_start == actual[0]
    assert rec.work_end == actual[1]
    assert rec.later_work_period == "buffer"



def test_exact_shift_end_is_buffer_not_actual_work():
    home = point(18, dt=NOW)
    work = point(6, dt=NOW)
    actual = (NOW - timedelta(hours=2), NOW)
    planning = (actual[0] - timedelta(minutes=30), actual[1] + timedelta(minutes=30))
    entry = types.SimpleNamespace(data={
        const.CONF_WEATHER: "weather.home",
        const.CONF_WORK_WEATHER: "weather.work",
        const.CONF_FALLBACK_INDOOR_TEMP: 21.5,
        const.CONF_RAIN_ADVICE: True,
    })
    runtime = {"coordinator": types.SimpleNamespace(data={"home_forecast": [], "work_forecast": []}), "context_cache": {}}
    model = learning.PersonalModel.from_answers(3, 3, 3, 3)

    original_now = api.dt_util.now
    original_current = api.current_weather
    original_indoor = api.indoor_temperature_c
    original_calendar = api._cached_calendar_horizon
    original_work_sets = api._cached_work_window_sets
    api.dt_util.now = lambda: NOW
    api.current_weather = lambda hass, entity_id: work if entity_id == "weather.work" else home
    api.indoor_temperature_c = lambda *args, **kwargs: 21.5

    async def no_calendar(*args, **kwargs):
        return None, const.CALENDAR_STATUS_NOT_CONFIGURED

    async def work_sets(*args, **kwargs):
        return [actual], [planning], const.CALENDAR_STATUS_NOT_CONFIGURED

    api._cached_calendar_horizon = no_calendar
    api._cached_work_window_sets = work_sets
    try:
        rec = asyncio.run(api._recommendation(types.SimpleNamespace(states=types.SimpleNamespace(get=lambda _e: None)), entry, runtime, model))
    finally:
        api.dt_util.now = original_now
        api.current_weather = original_current
        api.indoor_temperature_c = original_indoor
        api._cached_calendar_horizon = original_calendar
        api._cached_work_window_sets = original_work_sets

    assert rec.source == "home"
    assert rec.current_temperature_c == 18.0



def test_failed_forecast_source_is_not_consumed_as_fresh_forecast_data():
    class Coordinator:
        last_update_success = True
        data = {
            "updated": NOW,
            "home_forecast": [point(-10, dt=NOW + timedelta(hours=1))],
            "home_forecast_success": False,
            "work_forecast": [],
            "work_forecast_success": True,
            "forecast_fetch_failed": True,
        }

        async def async_refresh(self):
            raise AssertionError("fresh failure backoff should avoid immediate refetch")

    home = point(18)
    entry = types.SimpleNamespace(data={
        const.CONF_WEATHER: "weather.home",
        const.CONF_FALLBACK_INDOOR_TEMP: 21.5,
        const.CONF_RAIN_ADVICE: True,
    })
    runtime = {"coordinator": Coordinator(), "context_cache": {}}
    model = learning.PersonalModel.from_answers(3, 3, 3, 3)

    original_current = api.current_weather
    original_indoor = api.indoor_temperature_c
    original_calendar = api._cached_calendar_horizon
    api.current_weather = lambda hass, entity_id: home
    api.indoor_temperature_c = lambda *args, **kwargs: 21.5

    async def no_calendar(*args, **kwargs):
        return None, const.CALENDAR_STATUS_NOT_CONFIGURED

    api._cached_calendar_horizon = no_calendar
    try:
        rec = asyncio.run(api._recommendation(types.SimpleNamespace(states=None), entry, runtime, model))
    finally:
        api.current_weather = original_current
        api.indoor_temperature_c = original_indoor
        api._cached_calendar_horizon = original_calendar

    assert rec.jacket_later == rec.jacket_now
    assert rec.forecast_coverage_complete is False


def test_calendar_generation_second_invalidation_falls_back_conservatively():
    runtime = {"context_cache": {}, "context_cache_generation": 0}

    async def always_raced(*args, **kwargs):
        runtime["context_cache_generation"] += 1
        runtime["context_cache"].clear()
        return ([(NOW, NOW + timedelta(hours=1))], [], const.CALENDAR_STATUS_AVAILABLE)

    original = api.work_windows
    api.work_windows = always_raced
    try:
        result = asyncio.run(
            REAL_CACHED_WORK_WINDOW_SETS(
                types.SimpleNamespace(), types.SimpleNamespace(data={}), runtime
            )
        )
    finally:
        api.work_windows = original

    assert result == ([], [], const.CALENDAR_STATUS_UNAVAILABLE)
    assert "updated" not in runtime["context_cache"]


def test_learning_context_uses_exact_recommendation_observation_timestamp():
    observed = datetime(2026, 11, 30, 23, 59, 59, tzinfo=timezone.utc)
    rec = models.Recommendation(
        jacket_now=const.JACKET_LIGHT,
        jacket_later=const.JACKET_LIGHT,
        later_at=None,
        rain_status=const.RAIN_NONE,
        display_mode=const.DISPLAY_FULL,
        horizon_hours=1,
        effective_now_c=15.0,
        min_effective_c=15.0,
        max_effective_c=15.0,
        confidence=0.5,
        reasons=[],
        current_temperature_c=15.0,
        current_wind_kmh=5.0,
        current_gust_kmh=5.0,
        current_condition="cloudy",
        transition_penalty_c=0.0,
        observed_at=observed,
    )
    contexts = api._learning_contexts(rec)
    assert contexts["start"]["observed_at"] == observed.isoformat()


def test_work_forecast_coverage_multiple_windows_is_order_independent_partial():
    first = (NOW + timedelta(hours=1), NOW + timedelta(hours=3))
    second = (NOW + timedelta(hours=5), NOW + timedelta(hours=7))
    first_points = [
        point(10, dt=NOW + timedelta(hours=hour)) for hour in (1, 2, 3)
    ]
    second_points = [
        point(10, dt=NOW + timedelta(hours=hour)) for hour in (5, 6, 7)
    ]
    assert api._work_forecast_coverage(NOW, second_points, [first, second]) == "partial"
    assert api._work_forecast_coverage(NOW, first_points, [first, second]) == "partial"
    assert api._work_forecast_coverage(NOW, [], [first, second]) == "missing"
    assert api._work_forecast_coverage(NOW, first_points + second_points, [first, second]) == "complete"


def test_forecast_retry_ignores_failed_work_source_when_only_home_is_required():
    calls = []

    class Coordinator:
        last_update_success = True

        def __init__(self):
            self.data = {
                "updated": NOW - timedelta(minutes=2),
                "home_forecast_success": True,
                "work_forecast_success": False,
                "forecast_fetch_failed": True,
            }

        async def async_refresh(self):
            calls.append("refresh")
            self.data["updated"] = NOW

    original_now = api.dt_util.now
    api.dt_util.now = lambda: NOW
    try:
        fresh = asyncio.run(
            api._ensure_forecast_fresh(Coordinator(), required_sources={"home"})
        )
    finally:
        api.dt_util.now = original_now

    assert fresh is True
    assert calls == []


def test_forecast_retry_uses_short_backoff_when_failed_work_source_is_required():
    calls = []

    class Coordinator:
        last_update_success = True

        def __init__(self):
            self.data = {
                "updated": NOW - timedelta(minutes=2),
                "home_forecast_success": True,
                "work_forecast_success": False,
                "forecast_fetch_failed": True,
            }

        async def async_refresh(self):
            calls.append("refresh")
            self.data["updated"] = NOW
            self.data["work_forecast_success"] = True

    original_now = api.dt_util.now
    api.dt_util.now = lambda: NOW
    try:
        fresh = asyncio.run(
            api._ensure_forecast_fresh(
                Coordinator(), required_sources={"home", "work"}
            )
        )
    finally:
        api.dt_util.now = original_now

    assert fresh is True
    assert calls == ["refresh"]


def test_websocket_user_sync_does_not_mutate_replaced_manager_after_await():
    synced = []

    class Manager:
        def sync_user_directory(self, users):
            synced.append(users)

    manager = Manager()
    entry = types.SimpleNamespace(
        runtime_data={"profiles": manager, "unloading": False}
    )

    async def get_users():
        entry.runtime_data = {"profiles": object(), "unloading": False}
        return [types.SimpleNamespace(id="user")]

    hass = types.SimpleNamespace(
        auth=types.SimpleNamespace(async_get_users=get_users)
    )
    result = asyncio.run(api._sync_profile_directory(hass, entry, manager))

    assert result is False
    assert synced == []


def test_irrelevant_failed_work_forecast_does_not_force_short_retry_for_home_advice():
    home = point(18)

    class Coordinator:
        last_update_success = True

        def __init__(self):
            self.data = {
                "updated": NOW - timedelta(minutes=2),
                "home_forecast": [point(17, dt=NOW + timedelta(hours=1))],
                "home_forecast_success": True,
                "work_forecast": [],
                "work_forecast_success": False,
                "forecast_fetch_failed": True,
            }

        async def async_refresh(self):
            raise AssertionError("irrelevant failed work source must not trigger short retry")

    entry = types.SimpleNamespace(data={
        const.CONF_WEATHER: "weather.home",
        const.CONF_WORK_WEATHER: "weather.work",
        const.CONF_FALLBACK_INDOOR_TEMP: 21.5,
        const.CONF_RAIN_ADVICE: True,
    })
    runtime = {"coordinator": Coordinator(), "context_cache": {}}
    model = learning.PersonalModel.from_answers(3, 3, 3, 3)

    original_current = api.current_weather
    original_indoor = api.indoor_temperature_c
    original_calendar = api._cached_calendar_horizon
    original_work_sets = api._cached_work_window_sets
    original_now = api.dt_util.now
    api.current_weather = lambda hass, entity_id: home if entity_id == "weather.home" else None
    api.indoor_temperature_c = lambda *args, **kwargs: 21.5
    api.dt_util.now = lambda: NOW

    async def no_calendar(*args, **kwargs):
        return None, const.CALENDAR_STATUS_NOT_CONFIGURED

    async def no_work(*args, **kwargs):
        return [], [], const.CALENDAR_STATUS_NOT_CONFIGURED

    api._cached_calendar_horizon = no_calendar
    api._cached_work_window_sets = no_work
    try:
        rec = asyncio.run(
            api._recommendation(types.SimpleNamespace(states=types.SimpleNamespace(get=lambda *_: None)), entry, runtime, model)
        )
    finally:
        api.current_weather = original_current
        api.indoor_temperature_c = original_indoor
        api._cached_calendar_horizon = original_calendar
        api._cached_work_window_sets = original_work_sets
        api.dt_util.now = original_now

    assert rec.source == "home"
    assert rec.work_forecast_coverage == "not_applicable"


def test_actual_work_wins_over_previous_split_window_buffer_at_absence_end():
    first = (NOW, NOW + timedelta(hours=4))
    second = (NOW + timedelta(hours=4, minutes=30), NOW + timedelta(hours=8))
    target = second[0]
    planning = [
        (first[0] - const.WORK_BUFFER, first[1] + const.WORK_BUFFER),
        (second[0] - const.WORK_BUFFER, second[1] + const.WORK_BUFFER),
    ]
    matched, period = api._work_period_for_target(target, [first, second], planning)
    assert matched == second
    assert period == "actual"


def test_calendar_context_bundle_retries_both_sources_as_one_generation():
    runtime = {"context_cache": {}, "context_cache_generation": 10}
    calls = {"horizon": 0, "work": 0}

    async def horizon(*args, **kwargs):
        calls["horizon"] += 1
        if calls["horizon"] == 1:
            return 16, const.CALENDAR_STATUS_AVAILABLE
        return 4, const.CALENDAR_STATUS_AVAILABLE

    async def work(*args, **kwargs):
        calls["work"] += 1
        if calls["work"] == 1:
            runtime["context_cache_generation"] += 1
            return (
                [(NOW, NOW + timedelta(hours=8))],
                [(NOW, NOW + timedelta(hours=8, minutes=30))],
                const.CALENDAR_STATUS_AVAILABLE,
            )
        return (
            [(NOW + timedelta(hours=1), NOW + timedelta(hours=2))],
            [(NOW + timedelta(minutes=30), NOW + timedelta(hours=2, minutes=30))],
            const.CALENDAR_STATUS_AVAILABLE,
        )

    original_horizon = api._cached_calendar_horizon
    original_work = api._cached_work_window_sets
    api._cached_calendar_horizon = horizon
    api._cached_work_window_sets = work
    try:
        result = asyncio.run(
            api._calendar_context_bundle(
                types.SimpleNamespace(), types.SimpleNamespace(data={}), runtime,
                include_work=True,
            )
        )
    finally:
        api._cached_calendar_horizon = original_horizon
        api._cached_work_window_sets = original_work

    assert result[0] == 4
    assert result[2] == [(NOW + timedelta(hours=1), NOW + timedelta(hours=2))]
    assert calls == {"horizon": 2, "work": 2}


def test_revision_token_for_connection_is_profile_scoped_for_normal_user():
    connection = types.SimpleNamespace(
        user=types.SimpleNamespace(id="user-a", name="A", is_admin=False)
    )
    entry = types.SimpleNamespace(data={const.CONF_SHARED_USER_IDS: []})
    manager = types.SimpleNamespace(
        profile_ids={"user-a", "user-b"},
        profile_revision_token=lambda profile_id: f"profile:{profile_id}",
        directory_revision_token="directory:1",
        card_revision_token=lambda profile_id, include_directory=False: (
            f"directory+card:{profile_id}" if include_directory else f"card:{profile_id}"
        ),
    )
    assert api._revision_token_for_connection(connection, entry, manager, None) == "card:user-a"


def test_shared_revision_poll_survives_just_deleted_selected_profile():
    connection = types.SimpleNamespace(
        user=types.SimpleNamespace(id="tablet", name="Tablet", is_admin=False)
    )
    entry = types.SimpleNamespace(data={const.CONF_SHARED_USER_IDS: ["tablet"]})
    manager = types.SimpleNamespace(
        profile_ids={"other"},
        directory_revision_token="directory:9",
        revision_token="legacy:9",
    )
    assert (
        api._revision_token_for_connection(connection, entry, manager, "deleted")
        == "directory:9"
    )


def test_runtime_rejects_unloading_or_non_loaded_entry_state():
    manager = object()
    runtime = {"profiles": manager, "unloading": True}
    entry = types.SimpleNamespace(
        entry_id="entry",
        data={},
        runtime_data=runtime,
    )
    hass = types.SimpleNamespace(
        config_entries=types.SimpleNamespace(async_entries=lambda domain: [entry]),
        data={},
    )
    try:
        api._runtime(hass, "entry")
    except ValueError as err:
        assert str(err) == "integration_reloading"
    else:
        raise AssertionError("unloading runtime must be rejected")

    runtime["unloading"] = False
    entry.state = types.SimpleNamespace(value="unload_in_progress")
    try:
        api._runtime(hass, "entry")
    except ValueError as err:
        assert str(err) == "integration_reloading"
    else:
        raise AssertionError("non-loaded config entry must be rejected")


def test_profiles_endpoint_recovers_stale_foreign_selection_after_shared_access_revoked():
    results = []
    errors = []
    manager = types.SimpleNamespace(
        profile_ids={"tablet", "person"},
        summaries=lambda: [
            {"id": "tablet", "name": "Tablet", "setup_complete": True},
            {"id": "person", "name": "Person", "setup_complete": True},
        ],
        get_profile_summary=lambda profile_id: {
            "id": profile_id,
            "name": "Tablet" if profile_id == "tablet" else "Person",
            "setup_complete": True,
        },
        profile_revision_token=lambda profile_id: f"profile:{profile_id}",
        directory_revision_token="directory:4",
        revision_token="legacy:4",
        sync_user_directory=lambda users: False,
    )
    runtime = {"profiles": manager, "unloading": False}
    entry = types.SimpleNamespace(
        entry_id="entry",
        data={const.CONF_SHARED_USER_IDS: []},
        runtime_data=runtime,
    )

    async def users():
        return [types.SimpleNamespace(id="tablet", name="Tablet")]

    hass = types.SimpleNamespace(
        config_entries=types.SimpleNamespace(async_entries=lambda domain: [entry]),
        data={},
        auth=types.SimpleNamespace(async_get_users=users),
    )
    connection = types.SimpleNamespace(
        user=types.SimpleNamespace(id="tablet", name="Tablet", is_admin=False),
        send_error=lambda *args: errors.append(args),
        send_result=lambda *args: results.append(args[1]),
    )

    asyncio.run(
        api.ws_profiles(
            hass,
            connection,
            {"id": 1, "entry_id": "entry", "profile_id": "person"},
        )
    )

    assert errors == []
    assert results[0]["shared_account"] is False
    assert results[0]["shared_access"] is False
    assert results[0]["profile_revision"] == "profile:tablet"
    assert [item["id"] for item in results[0]["profiles"]] == ["tablet"]


def test_open_session_drops_old_runtime_before_mutating_replaced_manager():
    async def run():
        results = []
        errors = []
        started = asyncio.Event()
        release = asyncio.Event()
        opened = []
        model = learning.PersonalModel.from_answers(3, 3, 3, 3)

        async def open_session(*args, **kwargs):
            opened.append((args, kwargs))
            return {"id": "must-not-exist"}

        async def ensure_profile(profile_id, name):
            return model

        old_manager = types.SimpleNamespace(
            profile_ids={"person"},
            get_model=lambda profile_id: model,
            prepare_model_for_advice=lambda profile_id, when=None: model,
            async_ensure_profile=ensure_profile,
            async_open_session=open_session,
            feedback_candidates=lambda profile_id: [],
            get_profile_summary=lambda profile_id: {
                "id": profile_id,
                "name": "Person",
                "setup_complete": True,
            },
            profile_revision_token=lambda profile_id: "old:p:1",
            card_revision_token=lambda profile_id, include_directory=False: "old:d1:p1",
        )
        old_runtime = {
            "profiles": old_manager,
            "simulations": {},
            "unloading": False,
        }
        entry = types.SimpleNamespace(
            entry_id="entry",
            data={const.CONF_SHARED_USER_IDS: []},
            runtime_data=old_runtime,
        )
        hass = types.SimpleNamespace(
            config_entries=types.SimpleNamespace(async_entries=lambda domain: [entry]),
            data={},
        )
        connection = types.SimpleNamespace(
            user=types.SimpleNamespace(id="person", name="Person", is_admin=False),
            send_error=lambda *args: errors.append(args),
            send_result=lambda *args: results.append(args),
        )

        async def delayed_recommendation(*args, **kwargs):
            started.set()
            await release.wait()
            return models.Recommendation(
                jacket_now=const.JACKET_LIGHT,
                jacket_later=const.JACKET_LIGHT,
                later_at=None,
                rain_status=const.RAIN_NONE,
                display_mode=const.DISPLAY_FULL,
                horizon_hours=1,
                effective_now_c=15.0,
                min_effective_c=15.0,
                max_effective_c=15.0,
                confidence=0.2,
                reasons=[],
                current_temperature_c=15.0,
                current_wind_kmh=5.0,
                current_gust_kmh=5.0,
                current_condition="cloudy",
                transition_penalty_c=0.0,
            )

        original = api._recommendation
        api._recommendation = delayed_recommendation
        try:
            task = asyncio.create_task(
                api.ws_open_session(
                    hass,
                    connection,
                    {"id": 1, "entry_id": "entry"},
                )
            )
            await started.wait()
            old_runtime["unloading"] = True
            entry.runtime_data = {
                "profiles": types.SimpleNamespace(),
                "simulations": {},
                "unloading": False,
            }
            release.set()
            await task
        finally:
            api._recommendation = original

        assert opened == []
        assert results == []
        assert errors and errors[0][2] == "integration_reloading"

    asyncio.run(run())


def _snapshot_rec(marker: str) -> models.Recommendation:
    return models.Recommendation(
        jacket_now=const.JACKET_LIGHT,
        jacket_later=const.JACKET_LIGHT,
        later_at=None,
        rain_status=const.RAIN_NONE,
        display_mode=const.DISPLAY_FULL,
        horizon_hours=1,
        effective_now_c=15.0,
        min_effective_c=15.0,
        max_effective_c=15.0,
        confidence=0.4,
        reasons=[marker],
        current_temperature_c=15.0,
        current_wind_kmh=5.0,
        current_gust_kmh=5.0,
        current_condition="cloudy",
        transition_penalty_c=0.0,
    )


def test_stable_advice_snapshot_retries_when_profile_changes_mid_recommendation():
    state = {
        "rev": 1,
        "model": learning.PersonalModel.from_answers(3, 3, 3, 3),
    }
    state["model"].general_offset_c = 0.0
    newer = learning.PersonalModel.from_answers(3, 3, 3, 3)
    newer.general_offset_c = 2.0
    calls = []

    manager = types.SimpleNamespace(
        profile_ids={"person"},
        prepare_model_for_advice=lambda profile_id, when=None: state["model"],
        profile_revision_token=lambda profile_id: f"runtime:p:{state['rev']}",
        directory_revision_token="runtime:d:1",
        revision_token="runtime:1",
    )
    runtime = {"profiles": manager, "simulations": {}, "unloading": False}
    entry = types.SimpleNamespace(
        entry_id="entry", data={const.CONF_SHARED_USER_IDS: []}, runtime_data=runtime
    )
    hass = types.SimpleNamespace()
    connection = types.SimpleNamespace(
        user=types.SimpleNamespace(id="person", name="Person", is_admin=False)
    )

    async def changing_recommendation(*args):
        model = args[-1]
        calls.append(model.general_offset_c)
        if len(calls) == 1:
            state["model"] = newer
            state["rev"] = 2
        return _snapshot_rec(f"offset:{model.general_offset_c}")

    original = api._recommendation
    api._recommendation = changing_recommendation
    try:
        model, rec, simulated, revision, directory = asyncio.run(
            api._stable_advice_snapshot(
                hass,
                connection,
                entry,
                runtime,
                manager,
                "person",
                allow_simulation=False,
            )
        )
    finally:
        api._recommendation = original

    assert calls == [0.0, 2.0]
    assert model.general_offset_c == 2.0
    assert rec.reasons == ["offset:2.0"]
    assert simulated is False
    assert revision == "runtime:p:2"
    assert directory == "runtime:d:1"


def test_open_session_uses_same_stable_model_snapshot_as_returned_recommendation():
    state = {
        "rev": 1,
        "model": learning.PersonalModel.from_answers(3, 3, 3, 3),
    }
    state["model"].general_offset_c = 0.0
    newer = learning.PersonalModel.from_answers(3, 3, 3, 3)
    newer.general_offset_c = 2.0
    opened = []
    results = []
    errors = []
    calls = 0

    async def ensure_profile(profile_id, name):
        return state["model"]

    async def open_session(profile_id, rec, **kwargs):
        opened.append((rec.reasons[:], kwargs["prepared_model"].general_offset_c))
        return {"id": "session-new", "recommendation": rec.as_dict()}

    manager = types.SimpleNamespace(
        profile_ids={"person"},
        get_model=lambda profile_id: state["model"],
        prepare_model_for_advice=lambda profile_id, when=None: state["model"],
        async_ensure_profile=ensure_profile,
        async_open_session=open_session,
        feedback_candidates=lambda profile_id: [],
        get_profile_summary=lambda profile_id: {
            "id": profile_id, "name": "Person", "setup_complete": True
        },
        profile_revision_token=lambda profile_id: f"runtime:p:{state['rev']}",
        directory_revision_token="runtime:d:3",
        revision_token="runtime:3",
    )
    runtime = {"profiles": manager, "simulations": {}, "unloading": False}
    entry = types.SimpleNamespace(
        entry_id="entry", data={const.CONF_SHARED_USER_IDS: []}, runtime_data=runtime
    )
    hass = types.SimpleNamespace(
        config_entries=types.SimpleNamespace(async_entries=lambda domain: [entry]), data={}
    )
    connection = types.SimpleNamespace(
        user=types.SimpleNamespace(id="person", name="Person", is_admin=False),
        send_result=lambda *args: results.append(args[1]),
        send_error=lambda *args: errors.append(args),
    )

    async def changing_recommendation(*args):
        nonlocal calls
        calls += 1
        model = args[-1]
        if calls == 1:
            state["model"] = newer
            state["rev"] = 2
        return _snapshot_rec(f"offset:{model.general_offset_c}")

    original = api._recommendation
    api._recommendation = changing_recommendation
    try:
        asyncio.run(api.ws_open_session(hass, connection, {"id": 1, "entry_id": "entry"}))
    finally:
        api._recommendation = original

    assert errors == []
    assert calls == 2
    assert opened == [(["offset:2.0"], 2.0)]
    assert results[0]["recommendation"]["reasons"] == ["offset:2.0"]
    assert results[0]["profile_revision"] == "runtime:p:2"
    assert results[0]["directory_revision"] == "runtime:d:3"


def test_open_session_profile_deleted_during_recommendation_returns_profile_not_found():
    results = []
    errors = []
    profile_ids = {"person"}
    model = learning.PersonalModel.from_answers(3, 3, 3, 3)

    async def ensure_profile(profile_id, name):
        return model

    manager = types.SimpleNamespace(
        profile_ids=profile_ids,
        get_model=lambda profile_id: model,
        prepare_model_for_advice=lambda profile_id, when=None: model,
        async_ensure_profile=ensure_profile,
        async_open_session=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("deleted profile must never reach async_open_session")
        ),
        feedback_candidates=lambda profile_id: [],
        get_profile_summary=lambda profile_id: {"id": profile_id},
        profile_revision_token=lambda profile_id: "runtime:p:1",
        directory_revision_token="runtime:d:1",
        revision_token="runtime:1",
    )
    runtime = {"profiles": manager, "simulations": {}, "unloading": False}
    entry = types.SimpleNamespace(
        entry_id="entry", data={const.CONF_SHARED_USER_IDS: []}, runtime_data=runtime
    )
    hass = types.SimpleNamespace(
        config_entries=types.SimpleNamespace(async_entries=lambda domain: [entry]), data={}
    )
    connection = types.SimpleNamespace(
        user=types.SimpleNamespace(id="person", name="Person", is_admin=False),
        send_result=lambda *args: results.append(args),
        send_error=lambda *args: errors.append(args),
    )

    async def deleting_recommendation(*args):
        profile_ids.clear()
        return _snapshot_rec("stale")

    original = api._recommendation
    api._recommendation = deleting_recommendation
    try:
        asyncio.run(api.ws_open_session(hass, connection, {"id": 1, "entry_id": "entry"}))
    finally:
        api._recommendation = original

    assert results == []
    assert errors
    assert errors[0][1] == "unavailable"
    assert errors[0][2] == "profile_not_found"


def test_stable_advice_snapshot_aborts_after_second_concurrent_profile_change():
    state = {"rev": 1}
    model = learning.PersonalModel.from_answers(3, 3, 3, 3)
    manager = types.SimpleNamespace(
        profile_ids={"person"},
        prepare_model_for_advice=lambda profile_id, when=None: model,
        profile_revision_token=lambda profile_id: f"runtime:p:{state['rev']}",
        directory_revision_token="runtime:d:1",
        revision_token="runtime:1",
    )
    runtime = {"profiles": manager, "simulations": {}, "unloading": False}
    entry = types.SimpleNamespace(
        entry_id="entry", data={const.CONF_SHARED_USER_IDS: []}, runtime_data=runtime
    )
    connection = types.SimpleNamespace(
        user=types.SimpleNamespace(id="person", name="Person", is_admin=False)
    )

    async def always_changes(*args):
        state["rev"] += 1
        return _snapshot_rec(f"attempt:{state['rev']}")

    original = api._recommendation
    api._recommendation = always_changes
    try:
        try:
            asyncio.run(
                api._stable_advice_snapshot(
                    types.SimpleNamespace(), connection, entry, runtime, manager,
                    "person", allow_simulation=False,
                )
            )
        except ValueError as err:
            assert str(err) == "profile_changed_retry"
        else:
            raise AssertionError("two consecutive model races must abort conservatively")
    finally:
        api._recommendation = original

    assert state["rev"] == 3


def test_stable_advice_snapshot_rejects_simulation_activated_during_open_session_retry():
    state = {"rev": 1}
    model = learning.PersonalModel.from_answers(3, 3, 3, 3)
    simulated = learning.PersonalModel.from_answers(3, 3, 3, 3)
    runtime = {"simulations": {}, "unloading": False}
    manager = types.SimpleNamespace(
        profile_ids={"person"},
        prepare_model_for_advice=lambda profile_id, when=None: model,
        profile_revision_token=lambda profile_id: f"runtime:p:{state['rev']}",
        directory_revision_token="runtime:d:1",
        revision_token="runtime:1",
    )
    runtime["profiles"] = manager
    entry = types.SimpleNamespace(
        entry_id="entry", data={const.CONF_SHARED_USER_IDS: []}, runtime_data=runtime
    )
    connection = types.SimpleNamespace(
        user=types.SimpleNamespace(id="person", name="Person", is_admin=False)
    )
    calls = 0

    async def enable_simulation(*args):
        nonlocal calls
        calls += 1
        runtime["simulations"]["person"] = simulated
        state["rev"] = 2
        return _snapshot_rec("before-simulation")

    original = api._recommendation
    api._recommendation = enable_simulation
    try:
        try:
            asyncio.run(
                api._stable_advice_snapshot(
                    types.SimpleNamespace(), connection, entry, runtime, manager,
                    "person", allow_simulation=False,
                )
            )
        except ValueError as err:
            assert str(err) == "simulation_active"
        else:
            raise AssertionError("open-session advice must abort when simulation becomes active")
    finally:
        api._recommendation = original

    assert calls == 1


def test_stable_advice_snapshot_returns_current_directory_marker_after_directory_race():
    state = {"directory": 1}
    model = learning.PersonalModel.from_answers(3, 3, 3, 3)
    class DynamicManager:
        profile_ids = {"admin", "person"}
        revision_token = "runtime:1"

        @property
        def directory_revision_token(self):
            return f"runtime:d:{state['directory']}"

        def prepare_model_for_advice(self, profile_id, when=None):
            return model

        def profile_revision_token(self, profile_id):
            return "runtime:p:1"

        def card_revision_token(self, profile_id, include_directory=False):
            return (
                f"runtime:d{state['directory']}:p1"
                if include_directory
                else "runtime:p1"
            )

    manager = DynamicManager()
    runtime = {"profiles": manager, "simulations": {}, "unloading": False}
    entry = types.SimpleNamespace(
        entry_id="entry", data={const.CONF_SHARED_USER_IDS: []}, runtime_data=runtime
    )
    connection = types.SimpleNamespace(
        user=types.SimpleNamespace(id="admin", name="Admin", is_admin=True)
    )

    async def directory_changes(*args):
        state["directory"] = 2
        return _snapshot_rec("stable-profile")

    original = api._recommendation
    api._recommendation = directory_changes
    try:
        _model, rec, _sim, card_revision, directory_revision = asyncio.run(
            api._stable_advice_snapshot(
                types.SimpleNamespace(), connection, entry, runtime, manager,
                "person", allow_simulation=False,
            )
        )
    finally:
        api._recommendation = original

    assert rec.reasons == ["stable-profile"]
    assert directory_revision == "runtime:d:2"
    assert card_revision == "runtime:d2:p1"


def test_open_session_does_not_create_real_session_if_simulation_activates_mid_advice():
    state = {"rev": 1}
    model = learning.PersonalModel.from_answers(3, 3, 3, 3)
    simulated = learning.PersonalModel.from_answers(3, 3, 3, 3)
    opened = []
    results = []
    errors = []

    async def ensure_profile(profile_id, name):
        return model

    async def forbidden_open(*args, **kwargs):
        opened.append((args, kwargs))
        raise AssertionError("simulation-active advice must never create a real session")

    manager = types.SimpleNamespace(
        profile_ids={"person"},
        get_model=lambda profile_id: model,
        prepare_model_for_advice=lambda profile_id, when=None: model,
        async_ensure_profile=ensure_profile,
        async_open_session=forbidden_open,
        feedback_candidates=lambda profile_id: [],
        get_profile_summary=lambda profile_id: {"id": profile_id},
        profile_revision_token=lambda profile_id: f"runtime:p:{state['rev']}",
        directory_revision_token="runtime:d:1",
        revision_token="runtime:1",
    )
    runtime = {"profiles": manager, "simulations": {}, "unloading": False}
    entry = types.SimpleNamespace(
        entry_id="entry", data={const.CONF_SHARED_USER_IDS: []}, runtime_data=runtime
    )
    hass = types.SimpleNamespace(
        config_entries=types.SimpleNamespace(async_entries=lambda domain: [entry]), data={}
    )
    connection = types.SimpleNamespace(
        user=types.SimpleNamespace(id="person", name="Person", is_admin=False),
        send_result=lambda *args: results.append(args),
        send_error=lambda *args: errors.append(args),
    )
    calls = 0

    async def enable_simulation(*args):
        nonlocal calls
        calls += 1
        runtime["simulations"]["person"] = simulated
        state["rev"] = 2
        return _snapshot_rec("before-simulation")

    original = api._recommendation
    api._recommendation = enable_simulation
    try:
        asyncio.run(api.ws_open_session(hass, connection, {"id": 1, "entry_id": "entry"}))
    finally:
        api._recommendation = original

    assert calls == 1
    assert opened == []
    assert results == []
    assert errors
    assert errors[0][1] == "unavailable"
    assert errors[0][2] == "simulation_active"


def test_shared_profile_list_excludes_all_current_shared_control_accounts_and_advice_rejects_them():
    results = []
    errors = []
    model = learning.PersonalModel.from_answers(3, 3, 3, 3)
    manager = types.SimpleNamespace(
        profile_ids={"tablet1", "tablet2", "person"},
        summaries=lambda: [
            {"id": "tablet1", "name": "Tablet 1", "setup_complete": True},
            {"id": "tablet2", "name": "Tablet 2", "setup_complete": True},
            {"id": "person", "name": "Person", "setup_complete": True},
        ],
        get_model=lambda profile_id: model,
        get_profile_summary=lambda profile_id: {
            "id": profile_id, "name": profile_id, "setup_complete": True,
        },
        card_revision_token=lambda profile_id, include_directory=False: f"card:{profile_id}",
        profile_revision_token=lambda profile_id: f"profile:{profile_id}",
        directory_revision_token="directory:1",
        revision_token="legacy:1",
        sync_user_directory=lambda users: False,
    )
    runtime = {"profiles": manager, "unloading": False}
    entry = types.SimpleNamespace(
        entry_id="entry",
        data={const.CONF_SHARED_USER_IDS: ["tablet1", "tablet2"]},
        runtime_data=runtime,
    )

    async def users():
        return [
            types.SimpleNamespace(id="tablet1", name="Tablet 1"),
            types.SimpleNamespace(id="tablet2", name="Tablet 2"),
            types.SimpleNamespace(id="person", name="Person"),
        ]

    hass = types.SimpleNamespace(
        config_entries=types.SimpleNamespace(async_entries=lambda domain: [entry]),
        data={},
        auth=types.SimpleNamespace(async_get_users=users),
    )
    connection = types.SimpleNamespace(
        user=types.SimpleNamespace(id="tablet1", name="Tablet 1", is_admin=False),
        send_error=lambda *args: errors.append(args),
        send_result=lambda *args: results.append(args[1]),
    )

    asyncio.run(api.ws_profiles(hass, connection, {"id": 1, "entry_id": "entry"}))
    assert errors == []
    assert [item["id"] for item in results[0]["profiles"]] == ["person"]

    try:
        asyncio.run(
            api._profile(
                connection,
                manager,
                "tablet2",
                entry,
                allow_shared_read=True,
            )
        )
    except ValueError as err:
        assert str(err) == "shared_profile_is_control"
    else:
        raise AssertionError("current shared-control accounts must never be advice targets")
