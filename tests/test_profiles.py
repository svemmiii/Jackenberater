from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
import types
from zoneinfo import ZoneInfo

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
engine = load("engine")
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


def weather_point(minutes: int, temperature_c: float) -> models.WeatherPoint:
    return models.WeatherPoint(
        dt=datetime(2026, 9, 1, 12, tzinfo=timezone.utc) + timedelta(minutes=minutes),
        temperature_c=temperature_c,
    )


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
            voluntary=True,
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
                "start": {"jacket": const.JACKET_LIGHT, "wind_kmh": 5.0, "wind_penalty_c": 0.0, "transition_penalty_c": 1.2},
                "later": {"jacket": const.JACKET_WARM, "wind_kmh": 30.0, "wind_penalty_c": 1.2, "transition_penalty_c": 0.0},
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
            voluntary=True,
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



def test_async_flush_persists_current_profile_state_immediately():
    class RecordingStore:
        def __init__(self):
            self.saved = None

        async def async_save(self, data):
            self.saved = data

    async def run():
        manager = make_manager()
        store = RecordingStore()
        manager.store = store
        model = manager.get_model("user")
        model.total_feedback = 7
        manager._profiles["user"]["model"] = model.to_dict()
        await manager.async_flush()
        assert store.saved["profiles"]["user"]["model"]["total_feedback"] == 7

    asyncio.run(run())


def test_async_remove_storage_deletes_profile_store():
    class RecordingStore:
        def __init__(self):
            self.removed = False

        async def async_remove(self):
            self.removed = True

    async def run():
        manager = make_manager()
        store = RecordingStore()
        manager.store = store
        await manager.async_remove_storage()
        assert store.removed is True

    asyncio.run(run())

def test_feedback_is_not_ready_immediately_for_current_advice():
    async def run():
        manager = make_manager()
        session = await manager.async_open_session(
            "user",
            recommendation(),
            weather_context={"temperature_c": 15.0},
            learning_contexts={
                "start": {"jacket": const.JACKET_LIGHT, "wind_kmh": 5.0, "transition_penalty_c": 0.0},
                "later": {"jacket": const.JACKET_LIGHT, "wind_kmh": 5.0, "transition_penalty_c": 0.0},
            },
        )
        assert session["ready_at"] == "2026-09-01T12:30:00+00:00"
        assert manager.feedback_candidates("user") == []

    asyncio.run(run())


def test_feedback_waits_until_thirty_minutes_after_relevant_later_change():
    async def run():
        manager = make_manager()
        rec = recommendation()
        rec.jacket_later = const.JACKET_WARM
        rec.later_at = datetime(2026, 9, 1, 18, tzinfo=timezone.utc)
        session = await manager.async_open_session(
            "user",
            rec,
            weather_context={"temperature_c": 15.0},
            learning_contexts={
                "start": {"jacket": const.JACKET_LIGHT, "wind_kmh": 5.0, "transition_penalty_c": 0.0},
                "later": {"jacket": const.JACKET_WARM, "wind_kmh": 10.0, "transition_penalty_c": 0.0},
            },
        )
        assert session["ready_at"] == "2026-09-01T18:30:00+00:00"

    asyncio.run(run())


def test_perfect_class_change_confirms_start_and_later_boundaries():
    async def run():
        manager = make_manager()
        rec = recommendation()
        rec.jacket_now = const.JACKET_NONE
        rec.jacket_later = const.JACKET_WINTER
        rec.later_at = datetime(2026, 9, 1, 18, tzinfo=timezone.utc)
        session = await manager.async_open_session(
            "user",
            rec,
            weather_context={"temperature_c": 22.0},
            learning_contexts={
                "start": {
                    "jacket": const.JACKET_NONE,
                    "effective_c": 22.0,
                    "wind_penalty_c": 0.0,
                    "transition_penalty_c": 0.0,
                },
                "later": {
                    "jacket": const.JACKET_WINTER,
                    "effective_c": 2.0,
                    "wind_penalty_c": 1.0,
                    "transition_penalty_c": 0.0,
                },
            },
        )
        result = await manager.async_feedback(
            "user",
            session["id"],
            rating=const.FEEDBACK_PERFECT,
            phase=None,
            recommendation_used=True,
            unusual_day=False,
            voluntary=True,
        )
        learned = manager.get_model("user")
        assert result["feedback"]["phase"] == const.PHASE_ALL
        assert learned.total_feedback == 1
        assert learned.light_stat.samples == 1
        assert learned.winter_stat.samples == 1

    asyncio.run(run())


def test_recent_session_is_not_reused_when_learning_context_changed():
    async def run():
        manager = make_manager()
        rec = recommendation()
        first = await manager.async_open_session(
            "user",
            rec,
            weather_context={"temperature_c": 15.0, "condition": "cloudy"},
            learning_contexts={
                "start": {
                    "jacket": const.JACKET_LIGHT,
                    "effective_c": 15.0,
                    "wind_penalty_c": 0.1,
                    "transition_penalty_c": 0.0,
                },
                "later": {
                    "jacket": const.JACKET_LIGHT,
                    "effective_c": 15.0,
                    "wind_penalty_c": 0.1,
                    "transition_penalty_c": 0.0,
                },
            },
        )
        second = await manager.async_open_session(
            "user",
            rec,
            weather_context={"temperature_c": 15.0, "condition": "cloudy"},
            learning_contexts={
                "start": {
                    "jacket": const.JACKET_LIGHT,
                    "effective_c": 14.0,
                    "wind_penalty_c": 1.1,
                    "transition_penalty_c": 0.0,
                },
                "later": {
                    "jacket": const.JACKET_LIGHT,
                    "effective_c": 14.0,
                    "wind_penalty_c": 1.1,
                    "transition_penalty_c": 0.0,
                },
            },
        )
        assert second["id"] != first["id"]

    asyncio.run(run())


def test_recent_session_reuses_nearly_identical_learning_context():
    async def run():
        manager = make_manager()
        rec = recommendation()
        context = {
            "start": {
                "jacket": const.JACKET_LIGHT,
                "effective_c": 15.0,
                "wind_penalty_c": 0.2,
                "transition_penalty_c": 0.0,
            },
            "later": {
                "jacket": const.JACKET_LIGHT,
                "effective_c": 15.0,
                "wind_penalty_c": 0.2,
                "transition_penalty_c": 0.0,
            },
        }
        first = await manager.async_open_session(
            "user", rec, weather_context={"condition": "cloudy"}, learning_contexts=context
        )
        second = await manager.async_open_session(
            "user", rec, weather_context={"condition": "cloudy"}, learning_contexts=context
        )
        assert second["id"] == first["id"]

    asyncio.run(run())


def test_recent_identical_sessions_are_deduplicated_across_logins_for_same_profile():
    async def run():
        manager = make_manager()
        rec = recommendation()
        context = {
            "start": {"jacket": const.JACKET_LIGHT, "effective_c": 15.0},
            "later": {"jacket": const.JACKET_LIGHT, "effective_c": 15.0},
        }
        first = await manager.async_open_session(
            "user", rec, weather_context={"condition": "cloudy"},
            learning_contexts=context, opened_by_user_id="phone",
        )
        other_login = await manager.async_open_session(
            "user", rec, weather_context={"condition": "cloudy"},
            learning_contexts=context, opened_by_user_id="wall-tablet",
        )
        assert other_login["id"] == first["id"]
        assert manager.get_model("user").feedback_opportunities == 1
        assert "opened_by_user_id" not in first

    asyncio.run(run())

def test_session_feedback_delay_and_expiry_use_real_time_across_dst():
    async def run():
        manager = make_manager()
        start = datetime(2026, 3, 28, 20, tzinfo=ZoneInfo("Europe/Berlin"))
        original_now = profiles.dt_util.now
        profiles.dt_util.now = lambda: start
        try:
            session = await manager.async_open_session(
                "user",
                recommendation(),
                weather_context={"condition": "cloudy"},
                learning_contexts={
                    "start": {"jacket": const.JACKET_LIGHT, "effective_c": 15.0},
                    "later": {"jacket": const.JACKET_LIGHT, "effective_c": 15.0},
                },
            )
        finally:
            profiles.dt_util.now = original_now

        ready = profiles._parse_dt(session["ready_at"])
        expires = profiles._parse_dt(session["expires_at"])
        assert profiles.elapsed(start, ready) == timedelta(minutes=30)
        assert profiles.elapsed(start, expires) == timedelta(hours=36)

    asyncio.run(run())


def test_feedback_candidates_can_be_scoped_to_the_opening_login():
    manager = make_manager()
    manager._profiles["user"]["sessions"] = [
        {
            "id": "a", "created_at": "2026-09-01T10:00:00+00:00",
            "ready_at": "2026-09-01T11:00:00+00:00",
            "expires_at": "2026-09-02T11:00:00+00:00",
            "request_feedback": True, "feedback": None,
            "opened_by_user_id": "tablet-a",
        },
        {
            "id": "b", "created_at": "2026-09-01T10:05:00+00:00",
            "ready_at": "2026-09-01T11:00:00+00:00",
            "expires_at": "2026-09-02T11:00:00+00:00",
            "request_feedback": True, "feedback": None,
            "opened_by_user_id": "tablet-b",
        },
    ]
    assert [item["id"] for item in manager.feedback_candidates(
        "user", opened_by_user_id="tablet-a"
    )] == ["a"]
    assert manager.is_feedback_candidate(
        "user", "a", opened_by_user_id="tablet-a"
    ) is True
    assert manager.is_feedback_candidate(
        "user", "b", opened_by_user_id="tablet-a"
    ) is False


def test_existing_profile_rename_emits_profile_update_signal():
    async def run():
        manager = make_manager()
        manager.hass = object()
        seen = []
        original = profiles.async_dispatcher_send
        profiles.async_dispatcher_send = lambda *args: seen.append(args)
        try:
            await manager.async_ensure_profile("user", "Renamed User")
        finally:
            profiles.async_dispatcher_send = original
        assert manager.profile_name("user") == "Renamed User"
        assert any("profile_updated" in str(args[1]) for args in seen)

    asyncio.run(run())


def test_rain_reason_alone_does_not_request_thermal_feedback():
    async def run():
        manager = make_manager()
        model = manager.get_model("user")
        model.total_feedback = 30
        model.general_stat.samples = 30
        model.general_stat.weight_sum = 30.0
        model.general_stat.mean = 0.0
        model.light_stat.samples = 30
        model.light_stat.weight_sum = 30.0
        manager._profiles["user"]["model"] = model.to_dict()
        rec = recommendation()
        rec.jacket_now = const.JACKET_NONE
        rec.jacket_later = const.JACKET_NONE
        rec.reasons = ["rain"]
        session = await manager.async_open_session(
            "user", rec,
            weather_context={"temperature_c": 25.0},
            learning_contexts={
                "start": {"jacket": const.JACKET_NONE, "effective_c": 25.0},
                "later": {"jacket": const.JACKET_NONE, "effective_c": None},
            },
        )
        assert session["request_feedback"] is False
    asyncio.run(run())


def test_not_used_feedback_does_not_consume_previous_learning_undo_snapshot():
    async def run():
        manager = make_manager()
        first = await manager.async_open_session(
            "user", recommendation(),
            weather_context={"temperature_c": 20.0},
            learning_contexts={
                "start": {"jacket": const.JACKET_NONE, "effective_c": 20.0},
                "later": {"jacket": const.JACKET_NONE, "effective_c": None},
            },
        )
        await manager.async_feedback(
            "user", first["id"], rating=const.FEEDBACK_TOO_COLD, phase=None,
            recommendation_used=True, unusual_day=False, voluntary=True,
        )
        learned_offset = manager.get_model("user").general_offset_c
        assert learned_offset > 0

        second = await manager.async_open_session(
            "user", recommendation(),
            weather_context={"temperature_c": 20.0},
            learning_contexts={
                "start": {"jacket": const.JACKET_NONE, "effective_c": 20.0},
                "later": {"jacket": const.JACKET_NONE, "effective_c": None},
            },
        )
        await manager.async_feedback(
            "user", second["id"], rating=const.FEEDBACK_NOT_USED, phase=None,
            recommendation_used=False, unusual_day=False, voluntary=True,
        )
        assert await manager.async_undo_last_feedback("user") is True
        assert manager.get_model("user").general_offset_c == 0.0
    asyncio.run(run())


def test_v030_no_jacket_too_warm_does_not_consume_previous_learning_undo_snapshot():
    async def run():
        manager = make_manager()
        first_rec = recommendation()
        first_rec.jacket_now = const.JACKET_NONE
        first_rec.jacket_later = const.JACKET_NONE
        first = await manager.async_open_session(
            "user",
            first_rec,
            weather_context={"temperature_c": 10.0},
            learning_contexts={
                "start": {"jacket": const.JACKET_NONE, "effective_c": 10.0},
                "later": {"jacket": const.JACKET_NONE, "effective_c": None},
            },
        )
        await manager.async_feedback(
            "user", first["id"], rating=const.FEEDBACK_TOO_COLD, phase=None,
            recommendation_used=True, unusual_day=False, voluntary=True,
        )
        learned_offset = manager.get_model("user").general_offset_c
        assert learned_offset > 0.0

        second_rec = recommendation()
        second_rec.jacket_now = const.JACKET_NONE
        second_rec.jacket_later = const.JACKET_NONE
        second = await manager.async_open_session(
            "user",
            second_rec,
            weather_context={"temperature_c": 30.0},
            learning_contexts={
                "start": {"jacket": const.JACKET_NONE, "effective_c": 30.0},
                "later": {"jacket": const.JACKET_NONE, "effective_c": None},
            },
        )
        await manager.async_feedback(
            "user", second["id"], rating=const.FEEDBACK_TOO_WARM, phase=None,
            recommendation_used=True, unusual_day=False, voluntary=True,
        )
        assert manager.get_model("user").general_offset_c == learned_offset
        assert second["id"] == manager.latest_session("user")["id"]
        assert await manager.async_undo_last_feedback("user") is True
        assert manager.get_model("user").general_offset_c == 0.0

    asyncio.run(run())


def test_profile_export_import_roundtrip_preserves_compact_learning_and_clears_sessions():
    async def run():
        manager = make_manager()
        model = manager.get_model("user")
        model.general_offset_c = 1.25
        model.transient_tolerance = 0.82
        model.winter_bias_c = 0.35
        manager._profiles["user"]["model"] = model.to_dict()
        manager._profiles["user"]["sessions"] = [{"id": "stale"}]
        payload = manager.export_profile("user")
        assert payload["format"] == "jackenberater-profile"
        assert "sessions" not in payload
        assert "weather" not in payload

        manager._profiles["user"]["model"] = learning.PersonalModel.from_answers(3, 3, 3, 3).to_dict()
        restored = await manager.async_import_profile("user", payload)
        assert restored.general_offset_c == 1.25
        assert restored.transient_tolerance == 0.82
        assert restored.winter_bias_c == 0.35
        assert manager._profiles["user"]["sessions"] == []

    asyncio.run(run())


def test_profile_import_sanitizes_values_and_rejects_wrong_format():
    async def run():
        manager = make_manager()
        payload = {
            "format": "jackenberater-profile",
            "version": 1,
            "model": {"setup_complete": True, "transient_tolerance": 99, "winter_bias_c": "oops"},
        }
        restored = await manager.async_import_profile("user", payload)
        assert restored.transient_tolerance == 1.5
        assert restored.winter_bias_c == 0.0
        try:
            await manager.async_import_profile("user", {"format": "wrong", "version": 1, "model": {}})
        except ValueError:
            pass
        else:
            raise AssertionError("invalid profile backup must be rejected")

    asyncio.run(run())


def test_nonvoluntary_feedback_is_rejected_until_ready_but_voluntary_is_immediate():
    async def run():
        manager = make_manager()
        session = await manager.async_open_session(
            "user", recommendation(), weather_context={"temperature_c": 15.0},
            learning_contexts={
                "start": {"jacket": const.JACKET_LIGHT, "effective_c": 15.0},
                "later": {"jacket": const.JACKET_LIGHT, "effective_c": 15.0},
            },
        )
        try:
            await manager.async_feedback(
                "user", session["id"], rating=const.FEEDBACK_PERFECT, phase=None,
                recommendation_used=True, unusual_day=False, voluntary=False,
            )
        except ValueError as err:
            assert str(err) == "feedback_not_ready"
        else:
            raise AssertionError("automatic feedback must respect ready_at")

        # A fresh session can still be rated explicitly as voluntary feedback.
        result = await manager.async_feedback(
            "user", session["id"], rating=const.FEEDBACK_PERFECT, phase=None,
            recommendation_used=True, unusual_day=False, voluntary=True,
        )
        assert result["feedback"]["rating"] == const.FEEDBACK_PERFECT

    asyncio.run(run())


def test_learning_progress_never_drops_after_first_feedback():
    model = learning.PersonalModel.from_answers(3, 3, 3, 3)
    start = model.learning_progress()
    learning.apply_feedback(
        model, rating=const.FEEDBACK_PERFECT, jacket=const.JACKET_LIGHT,
        effective_c=15.0, recommendation_used=True, observed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    assert start == 0.18
    assert model.learning_progress() >= start


def test_sync_user_directory_prunes_deleted_users_refreshes_names_and_signals_delete():
    manager = make_manager()
    extra = learning.PersonalModel.from_answers(3, 3, 3, 3)
    manager._profiles["deleted"] = {"name": "Deleted", "model": extra.to_dict(), "sessions": []}
    calls = []
    original_send = profiles.async_dispatcher_send
    profiles.async_dispatcher_send = lambda hass, signal, profile_id: calls.append((signal, profile_id))
    try:
        changed = manager.sync_user_directory([types.SimpleNamespace(id="user", name="Renamed")])
    finally:
        profiles.async_dispatcher_send = original_send
    assert changed is True
    assert manager.profile_ids == ["user"]
    assert manager.profile_name("user") == "Renamed"
    assert (
        const.SIGNAL_PROFILE_DELETED.format(entry_id=manager.entry.entry_id),
        "deleted",
    ) in calls


def test_v030_transient_no_jacket_too_warm_gets_its_own_undo_snapshot():
    async def run():
        manager = make_manager()

        # First create an older, genuinely learned state so the regression also
        # proves that the next transient feedback replaces the correct undo point.
        first = recommendation()
        first.jacket_now = const.JACKET_NONE
        first.jacket_later = const.JACKET_NONE
        first_session = await manager.async_open_session(
            "user",
            first,
            weather_context={"temperature_c": 18.0},
            learning_contexts={
                "start": {"jacket": const.JACKET_NONE, "effective_c": 18.0},
                "later": {"jacket": const.JACKET_NONE, "effective_c": 18.0},
            },
        )
        await manager.async_feedback(
            "user",
            first_session["id"],
            rating=const.FEEDBACK_TOO_COLD,
            phase=None,
            recommendation_used=True,
            unusual_day=False,
            voluntary=True,
        )
        general_after_first = manager.get_model("user").general_offset_c
        assert general_after_first > 0.0

        # Build the second recommendation with the real engine.  It deliberately
        # chooses no jacket although the immediate thermal class is light because
        # the continuing trend warms quickly.
        transient_model = manager.get_model("user")
        transient_rec = engine.build_recommendation(
            weather_point(0, 18.0),
            [
                weather_point(10, 19.0),
                weather_point(60, 19.5),
                weather_point(120, 20.5),
            ],
            transient_model,
            indoor_temperature_c=18.0,
            base_horizon_hours=2,
            max_horizon_hours=2,
        )
        assert transient_rec.jacket_now == const.JACKET_NONE
        assert transient_rec.transient_override is True
        assert transient_rec.transient_direction == "warming"

        transient_session = await manager.async_open_session(
            "user",
            transient_rec,
            weather_context={"temperature_c": transient_rec.current_temperature_c},
            learning_contexts={
                "start": {
                    "jacket": transient_rec.jacket_now,
                    "effective_c": transient_rec.effective_now_c,
                    "observed_at": "2026-09-01T12:00:00+00:00",
                    "transient_override": transient_rec.transient_override,
                    "transient_direction": transient_rec.transient_direction,
                },
                "later": {
                    "jacket": transient_rec.jacket_later,
                    "effective_c": transient_rec.later_effective_c,
                },
            },
        )
        transient_before = manager.get_model("user").transient_tolerance
        await manager.async_feedback(
            "user",
            transient_session["id"],
            rating=const.FEEDBACK_TOO_WARM,
            phase=None,
            recommendation_used=True,
            unusual_day=False,
            voluntary=True,
        )
        after = manager.get_model("user")
        assert after.transient_tolerance > transient_before
        assert after.general_offset_c == general_after_first

        stored = manager._find_session("user", transient_session["id"])
        assert isinstance(stored.get("learning_before"), dict)
        older = manager._find_session("user", first_session["id"])
        assert older.get("learning_before") is None

        assert await manager.async_undo_last_feedback("user") is True
        undone = manager.get_model("user")
        assert undone.transient_tolerance == transient_before
        assert undone.general_offset_c == general_after_first

    asyncio.run(run())


def test_v030_phase_all_noop_does_not_replace_previous_meaningful_undo():
    async def run():
        manager = make_manager()
        first = recommendation()
        first_session = await manager.async_open_session(
            "user",
            first,
            weather_context={"temperature_c": 15.0},
            learning_contexts={
                "start": {"jacket": const.JACKET_LIGHT, "effective_c": 15.0},
                "later": {"jacket": const.JACKET_LIGHT, "effective_c": 15.0},
            },
        )
        await manager.async_feedback(
            "user", first_session["id"], rating=const.FEEDBACK_TOO_COLD, phase=None,
            recommendation_used=True, unusual_day=False, voluntary=True,
        )
        learned_general = manager.get_model("user").general_offset_c

        noop = recommendation()
        noop.jacket_now = const.JACKET_NONE
        noop.jacket_later = const.JACKET_NONE
        noop_session = await manager.async_open_session(
            "user",
            noop,
            weather_context={"temperature_c": 28.0},
            learning_contexts={
                "start": {"jacket": const.JACKET_NONE, "effective_c": 28.0},
                "later": {"jacket": const.JACKET_NONE, "effective_c": 28.0},
            },
        )
        await manager.async_feedback(
            "user", noop_session["id"], rating=const.FEEDBACK_TOO_WARM, phase=const.PHASE_ALL,
            recommendation_used=True, unusual_day=False, voluntary=True,
        )
        assert manager.get_model("user").general_offset_c == learned_general
        noop_stored = manager._find_session("user", noop_session["id"])
        assert noop_stored.get("learning_before") is None
        old_stored = manager._find_session("user", first_session["id"])
        assert isinstance(old_stored.get("learning_before"), dict)

    asyncio.run(run())



def test_v030_undo_keeps_learning_paused_after_meaningful_feedback():
    async def run():
        manager = make_manager()
        session = await manager.async_open_session(
            "user",
            recommendation(),
            weather_context={"temperature_c": 15.0},
            learning_contexts={
                "start": {"jacket": const.JACKET_LIGHT, "effective_c": 15.0},
                "later": {"jacket": const.JACKET_LIGHT, "effective_c": 15.0},
            },
        )
        await manager.async_feedback(
            "user", session["id"], rating=const.FEEDBACK_TOO_COLD, phase=None,
            recommendation_used=True, unusual_day=False, voluntary=True,
        )
        assert manager.get_model("user").general_offset_c > 0.0

        await manager.async_set_learning("user", False)
        assert manager.get_model("user").learning_enabled is False

        assert await manager.async_undo_last_feedback("user") is True
        undone = manager.get_model("user")
        assert undone.general_offset_c == 0.0
        assert undone.learning_enabled is False

    asyncio.run(run())


def test_v030_undo_keeps_later_noop_feedback_and_all_opportunities_counted():
    async def run():
        manager = make_manager()

        first_session = await manager.async_open_session(
            "user",
            recommendation(),
            weather_context={"temperature_c": 15.0},
            learning_contexts={
                "start": {"jacket": const.JACKET_LIGHT, "effective_c": 15.0},
                "later": {"jacket": const.JACKET_LIGHT, "effective_c": 15.0},
            },
        )
        await manager.async_feedback(
            "user", first_session["id"], rating=const.FEEDBACK_TOO_COLD, phase=None,
            recommendation_used=True, unusual_day=False, voluntary=True,
        )
        after_first = manager.get_model("user")
        assert after_first.total_feedback == 1
        assert after_first.feedback_opportunities == 1
        assert after_first.general_offset_c > 0.0

        noop = recommendation()
        noop.jacket_now = const.JACKET_NONE
        noop.jacket_later = const.JACKET_NONE
        noop_session = await manager.async_open_session(
            "user",
            noop,
            weather_context={"temperature_c": 28.0},
            learning_contexts={
                "start": {"jacket": const.JACKET_NONE, "effective_c": 28.0},
                "later": {"jacket": const.JACKET_NONE, "effective_c": 28.0},
            },
        )
        await manager.async_feedback(
            "user", noop_session["id"], rating=const.FEEDBACK_TOO_WARM, phase=None,
            recommendation_used=True, unusual_day=False, voluntary=True,
        )
        before_undo = manager.get_model("user")
        assert before_undo.total_feedback == 2
        assert before_undo.feedback_opportunities == 2
        assert before_undo.general_offset_c > 0.0

        assert await manager.async_undo_last_feedback("user") is True
        undone = manager.get_model("user")
        assert undone.general_offset_c == 0.0
        assert undone.total_feedback == 1
        assert undone.feedback_opportunities == 2

        # The later no-op rating is still an existing, non-undone session.
        stored_noop = manager._find_session("user", noop_session["id"])
        assert stored_noop["feedback"]["undone"] is False

    asyncio.run(run())


def test_v030_undo_keeps_opportunity_from_later_unrated_session():
    async def run():
        manager = make_manager()
        first_session = await manager.async_open_session(
            "user",
            recommendation(),
            weather_context={"temperature_c": 15.0},
            learning_contexts={
                "start": {"jacket": const.JACKET_LIGHT, "effective_c": 15.0},
                "later": {"jacket": const.JACKET_LIGHT, "effective_c": 15.0},
            },
        )
        await manager.async_feedback(
            "user", first_session["id"], rating=const.FEEDBACK_TOO_COLD, phase=None,
            recommendation_used=True, unusual_day=False, voluntary=True,
        )

        later = recommendation()
        later.current_temperature_c = 17.0
        later.effective_now_c = 17.0
        later.min_effective_c = 17.0
        later.max_effective_c = 17.0
        await manager.async_open_session(
            "user",
            later,
            weather_context={"temperature_c": 17.0},
            learning_contexts={
                "start": {"jacket": const.JACKET_LIGHT, "effective_c": 17.0},
                "later": {"jacket": const.JACKET_LIGHT, "effective_c": 17.0},
            },
        )
        assert manager.get_model("user").feedback_opportunities == 2

        assert await manager.async_undo_last_feedback("user") is True
        undone = manager.get_model("user")
        assert undone.feedback_opportunities == 2
        assert undone.total_feedback == 0
        assert undone.general_offset_c == 0.0

    asyncio.run(run())


def test_v030_later_too_warm_on_light_to_none_trains_only_transition_boundary():
    async def run():
        manager = make_manager()
        rec = recommendation()
        rec.jacket_now = const.JACKET_LIGHT
        rec.jacket_later = const.JACKET_NONE
        rec.later_at = datetime(2026, 9, 1, 18, tzinfo=timezone.utc)
        session = await manager.async_open_session(
            "user",
            rec,
            weather_context={"temperature_c": 14.0},
            learning_contexts={
                "start": {
                    "jacket": const.JACKET_LIGHT,
                    "effective_c": 14.0,
                    "observed_at": "2026-09-01T12:00:00+00:00",
                },
                "later": {
                    "jacket": const.JACKET_NONE,
                    "effective_c": 20.0,
                    "observed_at": "2026-09-01T18:00:00+00:00",
                },
            },
        )
        before = manager.get_model("user")
        general_before = before.general_offset_c
        autumn_before = before.autumn_bias_c
        light_before = before.light_threshold_delta_c

        await manager.async_feedback(
            "user",
            session["id"],
            rating=const.FEEDBACK_TOO_WARM,
            phase=const.PHASE_LATER,
            recommendation_used=True,
            unusual_day=False,
            voluntary=True,
        )
        learned = manager.get_model("user")
        assert learned.general_offset_c == general_before
        assert learned.autumn_bias_c == autumn_before
        assert learned.light_threshold_delta_c < light_before
        assert learned.total_feedback == 1

    asyncio.run(run())


def test_v030_later_too_cold_on_none_to_light_trains_only_transition_boundary():
    async def run():
        manager = make_manager()
        rec = recommendation()
        rec.jacket_now = const.JACKET_NONE
        rec.jacket_later = const.JACKET_LIGHT
        rec.later_at = datetime(2026, 9, 1, 18, tzinfo=timezone.utc)
        session = await manager.async_open_session(
            "user",
            rec,
            weather_context={"temperature_c": 22.0},
            learning_contexts={
                "start": {
                    "jacket": const.JACKET_NONE,
                    "effective_c": 22.0,
                    "observed_at": "2026-09-01T12:00:00+00:00",
                },
                "later": {
                    "jacket": const.JACKET_LIGHT,
                    "effective_c": 17.0,
                    "observed_at": "2026-09-01T18:00:00+00:00",
                },
            },
        )
        before = manager.get_model("user")
        general_before = before.general_offset_c
        autumn_before = before.autumn_bias_c
        light_before = before.light_threshold_delta_c

        await manager.async_feedback(
            "user",
            session["id"],
            rating=const.FEEDBACK_TOO_COLD,
            phase=const.PHASE_LATER,
            recommendation_used=True,
            unusual_day=False,
            voluntary=True,
        )
        learned = manager.get_model("user")
        assert learned.general_offset_c == general_before
        assert learned.autumn_bias_c == autumn_before
        assert learned.light_threshold_delta_c > light_before
        assert learned.total_feedback == 1

    asyncio.run(run())


def test_v030_nonperfect_class_change_requires_concrete_phase():
    async def run():
        manager = make_manager()
        rec = recommendation()
        rec.jacket_now = const.JACKET_LIGHT
        rec.jacket_later = const.JACKET_NONE
        rec.later_at = datetime(2026, 9, 1, 18, tzinfo=timezone.utc)
        session = await manager.async_open_session(
            "user",
            rec,
            weather_context={"temperature_c": 14.0},
            learning_contexts={
                "start": {"jacket": const.JACKET_LIGHT, "effective_c": 14.0},
                "later": {"jacket": const.JACKET_NONE, "effective_c": 20.0},
            },
        )
        try:
            await manager.async_feedback(
                "user",
                session["id"],
                rating=const.FEEDBACK_TOO_WARM,
                phase=None,
                recommendation_used=True,
                unusual_day=False,
                voluntary=True,
            )
        except ValueError as err:
            assert str(err) == "feedback_phase_required"
        else:
            raise AssertionError("ambiguous class-change feedback must require a phase")

    asyncio.run(run())


def test_v030_later_timing_targets_arrival_boundary_even_when_classes_are_skipped():
    async def run():
        manager = make_manager()
        rec = recommendation()
        rec.jacket_now = const.JACKET_NONE
        rec.jacket_later = const.JACKET_WINTER
        rec.later_at = datetime(2026, 9, 1, 18, tzinfo=timezone.utc)
        session = await manager.async_open_session(
            "user",
            rec,
            weather_context={"temperature_c": 22.0},
            learning_contexts={
                "start": {"jacket": const.JACKET_NONE, "effective_c": 22.0},
                "later": {"jacket": const.JACKET_WINTER, "effective_c": 3.0},
            },
        )
        before = manager.get_model("user")
        light_before = before.light_threshold_delta_c
        warm_before = before.warm_threshold_delta_c
        winter_before = before.winter_threshold_delta_c

        await manager.async_feedback(
            "user",
            session["id"],
            rating=const.FEEDBACK_TOO_COLD,
            phase=const.PHASE_LATER,
            recommendation_used=True,
            unusual_day=False,
            voluntary=True,
        )
        learned = manager.get_model("user")
        assert learned.light_threshold_delta_c == light_before
        assert learned.warm_threshold_delta_c == warm_before
        assert learned.winter_threshold_delta_c > winter_before

    asyncio.run(run())


def test_v030_profile_re_setup_discards_sessions_from_previous_model():
    async def run():
        manager = make_manager()

        learned_session = await manager.async_open_session(
            "user",
            recommendation(),
            weather_context={"temperature_c": 15.0},
            learning_contexts={
                "start": {"jacket": const.JACKET_LIGHT, "effective_c": 15.0},
                "later": {"jacket": const.JACKET_LIGHT, "effective_c": 15.0},
            },
        )
        await manager.async_feedback(
            "user", learned_session["id"], rating=const.FEEDBACK_TOO_COLD, phase=None,
            recommendation_used=True, unusual_day=False, voluntary=True,
        )

        later = recommendation()
        later.current_temperature_c = 17.0
        later.effective_now_c = 17.0
        later.min_effective_c = 17.0
        later.max_effective_c = 17.0
        open_session = await manager.async_open_session(
            "user",
            later,
            weather_context={"temperature_c": 17.0},
            learning_contexts={
                "start": {"jacket": const.JACKET_LIGHT, "effective_c": 17.0},
                "later": {"jacket": const.JACKET_LIGHT, "effective_c": 17.0},
            },
        )
        assert len(manager._sessions("user")) == 2
        assert manager._find_session("user", learned_session["id"])["learning_before"]
        assert manager._find_session("user", open_session["id"])["feedback"] is None

        # Re-setup is a full model replacement. Preserve only the independent
        # learning pause switch; all old recommendation/feedback contexts vanish.
        await manager.async_set_learning("user", False)
        fresh = await manager.async_setup_profile(
            "user", cold=5, warm=1, wind=5, evening=5,
        )

        assert manager._sessions("user") == []
        assert fresh.learning_enabled is False
        assert fresh.cold_answer == 5
        assert fresh.warm_answer == 1
        assert fresh.wind_answer == 5
        assert fresh.evening_answer == 5
        assert fresh.general_offset_c == 1.8
        assert abs(fresh.light_threshold_delta_c - 0.495) < 1e-12
        assert fresh.total_feedback == 0
        assert fresh.feedback_opportunities == 0
        assert await manager.async_undo_last_feedback("user") is False

    asyncio.run(run())


def test_v030_cleanup_migrates_legacy_full_undo_snapshot_before_undo():
    async def run():
        manager = make_manager()

        legacy_before = learning.PersonalModel.from_answers(3, 3, 3, 3)
        legacy_before.seasonal_model_version = 1
        legacy_before.general_offset_c = 0.6
        legacy_before.winter_bias_c = 0.4
        legacy_before.spring_bias_c = 0.1
        legacy_before.summer_bias_c = -0.2
        legacy_before.autumn_bias_c = 0.1
        expected_effective = {
            name: legacy_before.general_offset_c + getattr(legacy_before, f"{name}_bias_c")
            for name in ("winter", "spring", "summer", "autumn")
        }

        legacy_after = learning.PersonalModel.from_answers(3, 3, 3, 3)
        legacy_after.seasonal_model_version = 1
        legacy_after.general_offset_c = 0.9
        legacy_after.winter_bias_c = 0.6
        legacy_after.spring_bias_c = 0.2
        legacy_after.summer_bias_c = -0.1
        legacy_after.autumn_bias_c = 0.2
        legacy_after.total_feedback = 1
        legacy_after.feedback_opportunities = 1

        manager._profiles["user"] = {
            "name": "User",
            "model": legacy_after.to_dict(),
            "sessions": [
                {
                    "id": "legacy-feedback",
                    "feedback": {
                        "rating": const.FEEDBACK_TOO_COLD,
                        "undone": False,
                    },
                    # v0.2.x stored the complete PersonalModel here.
                    "learning_before": legacy_before.to_dict(),
                }
            ],
        }

        manager._cleanup_all()

        migrated_model = manager.get_model("user")
        assert migrated_model.seasonal_model_version == 3
        assert abs(sum(
            getattr(migrated_model, f"{name}_bias_c")
            for name in ("winter", "spring", "summer", "autumn")
        )) < 1e-12

        stored = manager._find_session("user", "legacy-feedback")
        compact = stored["learning_before"]
        assert set(compact) == set(profiles._FEEDBACK_UNDO_FIELDS)
        assert "seasonal_model_version" not in compact
        assert "setup_complete" not in compact
        assert abs(sum(
            compact[f"{name}_bias_c"]
            for name in ("winter", "spring", "summer", "autumn")
        )) < 1e-12
        for name, expected in expected_effective.items():
            assert abs(compact["general_offset_c"] + compact[f"{name}_bias_c"] - expected) < 1e-12

        assert await manager.async_undo_last_feedback("user") is True
        restored = manager.get_model("user")
        assert restored.seasonal_model_version == 3
        assert restored.total_feedback == 0
        assert restored.feedback_opportunities == 1
        assert abs(sum(
            getattr(restored, f"{name}_bias_c")
            for name in ("winter", "spring", "summer", "autumn")
        )) < 1e-12
        for name, expected in expected_effective.items():
            actual = restored.general_offset_c + getattr(restored, f"{name}_bias_c")
            assert abs(actual - expected) < 1e-12

    asyncio.run(run())
