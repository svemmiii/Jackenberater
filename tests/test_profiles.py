from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import types

ROOT = Path(__file__).parents[1] / "custom_components" / "jackenberater"
PKG = "jackenberater_profiles_testpkg"

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
core.callback = lambda func: func
sys.modules[core.__name__] = core
helpers = types.ModuleType("homeassistant.helpers")
sys.modules[helpers.__name__] = helpers
dispatcher = types.ModuleType("homeassistant.helpers.dispatcher")
dispatcher.async_dispatcher_send = lambda *args, **kwargs: None
sys.modules[dispatcher.__name__] = dispatcher
storage = types.ModuleType("homeassistant.helpers.storage")
class DummyStore:
    @classmethod
    def __class_getitem__(cls, item):
        return cls
    def async_delay_save(self, *args, **kwargs):
        return None
storage.Store = DummyStore
sys.modules[storage.__name__] = storage
util = types.ModuleType("homeassistant.util")
sys.modules[util.__name__] = util
ha_dt = types.ModuleType("homeassistant.util.dt")
ha_dt.UTC = timezone.utc
ha_dt.now = lambda: datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
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
models = load("models")
learning = load("learning")
profiles = load("profiles")


def recommendation():
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
        current_gust_kmh=8.0,
        current_condition="cloudy",
        transition_penalty_c=0.0,
    )


def make_manager():
    manager = object.__new__(profiles.ProfileManager)
    manager.hass = None
    manager.entry = types.SimpleNamespace(entry_id="entry")
    manager.store = DummyStore()
    model = learning.PersonalModel.from_answers(3, 3, 3, 3)
    manager._profiles = {
        "user": {"name": "User", "model": model.to_dict(), "sessions": []}
    }
    return manager


def test_open_session_persists_and_accepts_feedback():
    async def run():
        manager = make_manager()
        rec = recommendation()
        session = await manager.async_open_session(
            "user",
            rec,
            weather_context={"temperature_c": 15.0, "wind_kmh": 8.0},
            learning_contexts={
                "start": {"jacket": const.JACKET_LIGHT, "wind_kmh": 8.0, "transition_penalty_c": 0.0},
                "later": {"jacket": const.JACKET_LIGHT, "wind_kmh": 8.0, "transition_penalty_c": 0.0},
            },
        )
        assert manager.latest_session("user")["id"] == session["id"]
        result = await manager.async_feedback(
            "user",
            session["id"],
            rating=const.FEEDBACK_PERFECT,
            phase=None,
            recommendation_used=True,
            unusual_day=False,
            voluntary=False,
        )
        assert result["feedback"]["rating"] == const.FEEDBACK_PERFECT
        assert manager.get_model("user").total_feedback == 1
    asyncio.run(run())


def test_unrequested_sessions_do_not_evict_requested_candidate():
    manager = make_manager()
    sessions = manager._profiles["user"]["sessions"]
    sessions.append({"id": "requested", "feedback": None, "request_feedback": True})
    for idx in range(5):
        sessions.append({"id": f"manual-{idx}", "feedback": None, "request_feedback": False})
    manager._cap_sessions("user")
    assert any(item["id"] == "requested" for item in manager._profiles["user"]["sessions"])


def test_phase_all_learns_start_and_later_without_double_counting_global_feedback():
    async def run():
        manager = make_manager()
        model = manager.get_model("user")
        # Leave the global-only startup phase so both context refinements are active.
        model.total_feedback = 11
        model.general_stat.samples = 11
        model.general_stat.weight_sum = 11.0
        manager._profiles["user"]["model"] = model.to_dict()
        rec = recommendation()
        rec.jacket_now = const.JACKET_LIGHT
        rec.jacket_later = const.JACKET_WARM
        rec.later_at = datetime(2026, 9, 1, 18, tzinfo=timezone.utc)
        session = await manager.async_open_session(
            "user",
            rec,
            weather_context={"temperature_c": 15.0, "wind_kmh": 5.0},
            learning_contexts={
                "start": {"jacket": const.JACKET_LIGHT, "wind_kmh": 5.0, "transition_penalty_c": 1.2},
                "later": {"jacket": const.JACKET_WARM, "wind_kmh": 30.0, "transition_penalty_c": 0.0},
            },
        )
        before = manager.get_model("user").total_feedback
        await manager.async_feedback(
            "user",
            session["id"],
            rating=const.FEEDBACK_TOO_COLD,
            phase=const.PHASE_ALL,
            recommendation_used=True,
            unusual_day=False,
            voluntary=False,
        )
        learned = manager.get_model("user")
        assert learned.total_feedback == before + 1
        assert learned.transition_stat.samples == 1
        assert learned.wind_stat.samples == 1
    asyncio.run(run())


def test_requested_candidate_survives_twenty_new_manual_sessions():
    manager = make_manager()
    sessions = manager._profiles["user"]["sessions"]
    sessions.append({"id": "requested", "feedback": None, "request_feedback": True})
    for idx in range(25):
        sessions.append({"id": f"manual-{idx}", "feedback": None, "request_feedback": False})
    manager._cap_sessions("user")
    kept = manager._profiles["user"]["sessions"]
    assert len(kept) == const.MAX_RECENT_SESSIONS
    assert any(item["id"] == "requested" for item in kept)


def test_async_load_persists_cleanup_only_when_storage_changes():
    class LoadStore:
        def __init__(self):
            self.save_calls = 0

        async def async_load(self):
            model = learning.PersonalModel.from_answers(3, 3, 3, 3)
            return {
                "profiles": {
                    "user": {
                        "name": "User",
                        "model": model.to_dict(),
                        "sessions": [
                            {
                                "id": "expired",
                                "feedback": None,
                                "request_feedback": True,
                                "expires_at": "2026-09-01T11:00:00+00:00",
                            }
                        ],
                    }
                }
            }

        def async_delay_save(self, *args, **kwargs):
            self.save_calls += 1

    async def run():
        manager = object.__new__(profiles.ProfileManager)
        manager.hass = None
        manager.entry = types.SimpleNamespace(entry_id="entry")
        manager.store = LoadStore()
        manager._profiles = {}
        await manager.async_load()
        assert manager._profiles["user"]["sessions"] == []
        assert manager.store.save_calls == 1

    asyncio.run(run())
