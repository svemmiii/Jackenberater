from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
import types

ROOT = Path(__file__).parents[1] / "custom_components" / "jackenberater"
PKG = "jackenberater_testpkg"

package = types.ModuleType(PKG)
package.__path__ = [str(ROOT)]
sys.modules.setdefault(PKG, package)


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

WeatherPoint = models.WeatherPoint
PersonalModel = learning.PersonalModel


def point(hours: int, temp: float, **kwargs):
    return WeatherPoint(
        dt=datetime(2026, 9, 1, 12, tzinfo=timezone.utc) + timedelta(hours=hours),
        temperature_c=temp,
        **kwargs,
    )


def test_stable_hot_weather_hides_card():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    rec = engine.build_recommendation(
        point(0, 28, condition="sunny"),
        [point(i, 27 + i * 0.05, condition="sunny") for i in range(1, 10)],
        model,
        indoor_temperature_c=22,
    )
    assert rec.jacket_now == const.JACKET_NONE
    assert rec.display_mode == const.DISPLAY_HIDDEN


def test_cold_windy_weather_requires_winter_jacket():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    result = engine.assess_point(point(0, -4, wind_kmh=25), model, indoor_temperature_c=22, apply_transition=True)
    assert result.jacket == const.JACKET_WINTER
    assert result.wind_penalty_c > 0


def test_forecast_chooses_warmest_later_class_not_first_change():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    future = [point(1, 17), point(2, 14), point(3, 10), point(4, 7), point(5, 3)]
    rec = engine.build_recommendation(point(0, 20), future, model, indoor_temperature_c=21.5)
    assert rec.jacket_now == const.JACKET_NONE
    assert rec.jacket_later == const.JACKET_WINTER
    assert rec.later_at == future[-1].dt


def test_rain_is_separate_from_warmth():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    future = [point(i, 22, precipitation_probability=75, precipitation_mm=0.4) for i in range(1, 4)]
    rec = engine.build_recommendation(point(0, 23), future, model, indoor_temperature_c=22)
    assert rec.jacket_now == const.JACKET_NONE
    assert rec.rain_status == const.RAIN_RECOMMENDED


def test_transition_temporarily_lowers_effective_temperature():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    p = point(0, 14)
    with_transition = engine.assess_point(p, model, indoor_temperature_c=24, apply_transition=True)
    without_transition = engine.assess_point(p, model, indoor_temperature_c=None, apply_transition=False)
    assert with_transition.effective_temperature_c < without_transition.effective_temperature_c


def test_first_three_cold_feedbacks_learn_quickly():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    for _ in range(3):
        learning.apply_feedback(
            model,
            rating=const.FEEDBACK_TOO_COLD,
            jacket=const.JACKET_NONE,
            wind_kmh=5,
            transition_penalty_c=0,
        )
    assert model.general_offset_c >= 2.5


def test_too_warm_light_jacket_moves_none_light_boundary():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    # Leave the global-only startup phase first.
    for _ in range(11):
        learning.apply_feedback(
            model,
            rating=const.FEEDBACK_PERFECT,
            jacket=const.JACKET_LIGHT,
            wind_kmh=5,
            transition_penalty_c=0,
        )
    before_light = model.light_threshold_delta_c
    before_warm = model.warm_threshold_delta_c
    learning.apply_feedback(
        model,
        rating=const.FEEDBACK_TOO_WARM,
        jacket=const.JACKET_LIGHT,
        wind_kmh=5,
        transition_penalty_c=0,
    )
    assert model.light_threshold_delta_c < before_light
    assert model.warm_threshold_delta_c == before_warm


def test_paused_learning_does_not_increase_model_samples():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    model.learning_enabled = False
    learning.apply_feedback(
        model,
        rating=const.FEEDBACK_TOO_COLD,
        jacket=const.JACKET_NONE,
        wind_kmh=30,
        transition_penalty_c=1.2,
    )
    assert model.total_feedback == 0
    assert model.general_stat.samples == 0
    assert model.general_offset_c == 0


def test_model_storage_is_fixed_shape_after_many_feedbacks():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    keys_before = set(model.to_dict())
    for i in range(500):
        learning.apply_feedback(
            model,
            rating=const.FEEDBACK_TOO_COLD if i % 3 == 0 else const.FEEDBACK_PERFECT,
            jacket=const.JACKET_LIGHT,
            wind_kmh=20 if i % 2 else 5,
            transition_penalty_c=1.0 if i % 5 == 0 else 0.0,
        )
    stored = model.to_dict()
    assert set(stored) == keys_before
    assert "history" not in stored
    assert len(json.dumps(stored)) < 2500


def test_current_only_recommendation_has_short_feedback_horizon():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    rec = engine.build_recommendation(point(0, 16), [], model, indoor_temperature_c=22)
    assert rec.horizon_hours == 1


def test_work_location_rain_can_raise_rain_advice():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    home = [point(i, 20, precipitation_probability=0) for i in range(1, 10)]
    work = [
        point(3, 18, condition="rainy", precipitation_probability=80, precipitation_mm=1.5),
        point(4, 18, condition="rainy", precipitation_probability=80, precipitation_mm=1.0),
    ]
    rec = engine.build_recommendation(
        point(0, 20),
        home,
        model,
        indoor_temperature_c=22,
        work_points=work,
        work_start=work[0].dt,
    )
    assert rec.rain_status == const.RAIN_RECOMMENDED


def test_perfect_feedback_confirms_relevant_jacket_boundaries():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    for _ in range(12):
        learning.apply_feedback(
            model,
            rating=const.FEEDBACK_PERFECT,
            jacket=const.JACKET_LIGHT,
            wind_kmh=5,
            transition_penalty_c=0,
        )
    assert model.light_stat.samples == 12
    assert model.warm_stat.samples == 12
    assert model.light_stat.confidence > 0
    assert model.warm_stat.confidence > 0


def test_unusual_day_counts_less_toward_learning_confidence():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    learning.apply_feedback(
        model,
        rating=const.FEEDBACK_TOO_COLD,
        jacket=const.JACKET_NONE,
        wind_kmh=5,
        transition_penalty_c=0,
        unusual_day=True,
    )
    assert model.general_stat.samples == 1
    assert abs(model.general_stat.weight_sum - 0.30) < 1e-9
    assert abs(model.light_stat.weight_sum - 0.30) < 1e-9


def test_threshold_learning_is_absolutely_bounded():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    for _ in range(250):
        learning.apply_feedback(
            model,
            rating=const.FEEDBACK_TOO_COLD,
            jacket=const.JACKET_NONE,
            wind_kmh=5,
            transition_penalty_c=0,
        )
    assert model.light_threshold_delta_c <= 4.0
    light, warm, winter = engine._thresholds(model)
    assert light <= engine.BASE_LIGHT_THRESHOLD_C + 4.0
    assert warm <= light - 2.5
    assert winter <= warm - 2.5


def test_work_timeline_replaces_home_points_inside_work_window():
    home = [point(i, 20 + i) for i in range(1, 6)]
    work = [point(i, 5 + i) for i in range(2, 5)]
    window = [(work[0].dt, work[-1].dt)]
    merged = engine.merge_location_timeline(home, work, window)
    by_time = {p.dt: p.temperature_c for p in merged}
    assert by_time[point(1, 0).dt] == 21
    assert by_time[point(2, 0).dt] == 7
    assert by_time[point(3, 0).dt] == 8
    assert by_time[point(4, 0).dt] == 9
    assert by_time[point(5, 0).dt] == 25


def test_recommendation_keeps_later_learning_context():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    future = [
        point(1, 16, wind_kmh=10, gust_kmh=15),
        point(2, 7, wind_kmh=20, gust_kmh=38),
    ]
    rec = engine.build_recommendation(point(0, 21), future, model, indoor_temperature_c=22)
    assert rec.jacket_later == const.JACKET_WINTER
    assert rec.later_at == future[-1].dt
    assert rec.later_temperature_c == 7
    assert rec.later_wind_kmh == 20
    assert rec.later_gust_kmh == 38
    assert rec.later_effective_c is not None


def test_warming_forecast_keeps_later_learning_context():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    future = [point(1, 8, wind_kmh=15), point(2, 20, wind_kmh=5)]
    rec = engine.build_recommendation(point(0, 2, wind_kmh=20), future, model, indoor_temperature_c=22)
    assert rec.jacket_now == const.JACKET_WINTER
    assert rec.jacket_later == const.JACKET_NONE
    assert rec.later_at == future[-1].dt
    assert rec.later_temperature_c == 20
    assert rec.later_effective_c is not None


def test_horizon_uses_elapsed_time_not_point_count():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    sparse = [point(2, 18), point(4, 18), point(6, 18), point(8, 18), point(10, 18), point(12, 18)]
    rec = engine.build_recommendation(point(0, 18), sparse, model, indoor_temperature_c=22)
    assert rec.horizon_hours <= 12
    assert rec.horizon_hours in {8, 12}


def test_work_window_removes_home_points_even_without_work_forecast():
    home = [point(i, 20 + i) for i in range(1, 6)]
    window = [(point(2, 0).dt, point(4, 0).dt)]
    merged = engine.merge_location_timeline(home, [], window)
    times = {p.dt for p in merged}
    assert point(1, 0).dt in times
    assert point(2, 0).dt not in times
    assert point(3, 0).dt not in times
    assert point(4, 0).dt not in times
    assert point(5, 0).dt in times


def test_feedback_policy_periodic_sampling_does_not_freeze():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    model.total_feedback = 10
    model.feedback_opportunities = 11
    assert not learning.should_request_feedback(
        model, near_threshold=False, class_change=False, unusual_weather=False, decision_confidence=0.9, opportunity_count=11
    )
    assert learning.should_request_feedback(
        model, near_threshold=False, class_change=False, unusual_weather=False, decision_confidence=0.9, opportunity_count=12
    )


def test_winter_too_cold_does_not_inflate_winter_boundary_confidence():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    for _ in range(12):
        learning.apply_feedback(
            model, rating=const.FEEDBACK_TOO_COLD, jacket=const.JACKET_WINTER, wind_kmh=5, transition_penalty_c=0
        )
    assert model.winter_stat.samples == 0
    assert model.general_offset_c > 0


def test_activity_context_is_evaluated_per_forecast_timestamp():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    current = point(3, 19)   # 15:00 UTC in this test setup
    future = [point(6, 19)]  # 18:00 UTC
    rec = engine.build_recommendation(
        current,
        future,
        model,
        indoor_temperature_c=19,
        activity_context_fn=lambda dt: -2.0 if dt.hour >= 17 else 0.0,
    )
    assert rec.jacket_now == const.JACKET_NONE
    assert rec.jacket_later == const.JACKET_LIGHT
    assert rec.later_at == future[0].dt


def test_corrupt_running_stat_storage_falls_back_safely():
    model = PersonalModel.from_dict({
        "setup_complete": True,
        "general_stat": {"samples": "broken", "weight_sum": "also-broken"},
    })
    assert isinstance(model, PersonalModel)
    assert model.general_stat.samples == 0
    assert model.total_feedback == 0


def test_manifest_version_matches_runtime_version():
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == const.INTEGRATION_VERSION
