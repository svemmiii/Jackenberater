from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
import types
import pytest
from zoneinfo import ZoneInfo

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


def point_minutes(minutes: int, temp: float, **kwargs):
    return WeatherPoint(
        dt=datetime(2026, 9, 1, 12, tzinfo=timezone.utc) + timedelta(minutes=minutes),
        temperature_c=temp,
        **kwargs,
    )


def dst_point(start: datetime, hours: int, temp: float, **kwargs):
    instant = start.astimezone(timezone.utc) + timedelta(hours=hours)
    return WeatherPoint(
        dt=instant.astimezone(start.tzinfo), temperature_c=temp, **kwargs
    )


def test_spring_dst_keeps_the_sixteenth_real_forecast_hour():
    berlin = ZoneInfo("Europe/Berlin")
    start = datetime(2026, 3, 28, 20, tzinfo=berlin)
    forecast = [
        dst_point(start, hour, 0.0 if hour == 16 else 20.0)
        for hour in range(1, 17)
    ]
    rec = engine.build_recommendation(
        dst_point(start, 0, 20.0), forecast,
        PersonalModel.from_answers(3, 3, 3, 3),
        indoor_temperature_c=20.0, base_horizon_hours=16, max_horizon_hours=16,
    )
    assert rec.horizon_hours == 16
    assert rec.jacket_later == const.JACKET_WINTER
    assert rec.later_at == forecast[-1].dt


def test_autumn_dst_excludes_the_seventeenth_real_forecast_hour():
    berlin = ZoneInfo("Europe/Berlin")
    start = datetime(2026, 10, 24, 20, tzinfo=berlin)
    forecast = [
        dst_point(start, hour, 0.0 if hour == 17 else 25.0)
        for hour in range(1, 18)
    ]
    rec = engine.build_recommendation(
        dst_point(start, 0, 25.0), forecast,
        PersonalModel.from_answers(3, 3, 3, 3),
        indoor_temperature_c=25.0, base_horizon_hours=16, max_horizon_hours=16,
    )
    assert rec.horizon_hours == 16
    assert rec.jacket_now == const.JACKET_NONE
    assert rec.jacket_later == const.JACKET_NONE
    assert rec.later_at is None


def test_second_fold_hour_is_kept_when_it_is_really_in_the_future():
    berlin = ZoneInfo("Europe/Berlin")
    current = WeatherPoint(
        dt=datetime(2026, 10, 25, 2, 30, tzinfo=berlin, fold=0),
        temperature_c=25.0,
    )
    future = WeatherPoint(
        dt=datetime(2026, 10, 25, 2, 15, tzinfo=berlin, fold=1),
        temperature_c=0.0,
    )
    rec = engine.build_recommendation(
        current, [future], PersonalModel.from_answers(3, 3, 3, 3),
        indoor_temperature_c=25.0, base_horizon_hours=1, max_horizon_hours=1,
    )
    assert rec.jacket_later == const.JACKET_WINTER
    assert rec.later_at == future.dt


def test_fold_hours_do_not_collide_when_location_timelines_are_merged():
    berlin = ZoneInfo("Europe/Berlin")
    first = WeatherPoint(
        dt=datetime(2026, 10, 25, 2, 0, tzinfo=berlin, fold=0),
        temperature_c=10.0,
    )
    second = WeatherPoint(
        dt=datetime(2026, 10, 25, 2, 0, tzinfo=berlin, fold=1),
        temperature_c=9.0,
    )
    window = [(
        datetime(2026, 10, 26, 1, 0, tzinfo=berlin),
        datetime(2026, 10, 26, 4, 0, tzinfo=berlin),
    )]
    merged = engine.merge_location_timeline([first, second], [], window)
    assert merged == [first, second]


def test_young_profile_keeps_clear_hot_advice_reachable():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    rec = engine.build_recommendation(
        point(0, 28, condition="sunny"),
        [point(i, 27 + i * 0.05, condition="sunny") for i in range(1, 10)],
        model,
        indoor_temperature_c=22,
    )
    assert rec.jacket_now == const.JACKET_NONE
    assert rec.display_mode == const.DISPLAY_COMPACT


def test_mature_confident_profile_can_hide_clear_hot_advice():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    for _ in range(30):
        learning.apply_feedback(
            model, rating=const.FEEDBACK_PERFECT, jacket=const.JACKET_NONE
        )
    rec = engine.build_recommendation(
        point(0, 28, condition="sunny"),
        [point(i, 27 + i * 0.05, condition="sunny") for i in range(1, 10)],
        model,
        indoor_temperature_c=22,
    )
    assert rec.display_mode == const.DISPLAY_HIDDEN


def test_transient_override_never_hides_the_card_even_for_mature_profile():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    for _ in range(30):
        learning.apply_feedback(
            model, rating=const.FEEDBACK_PERFECT, jacket=const.JACKET_NONE
        )
    rec = engine.build_recommendation(
        point_minutes(0, 15.0),
        [
            point_minutes(10, 21.0),
            *[point_minutes(hour * 60, 21.0) for hour in range(1, 10)],
        ],
        model,
        indoor_temperature_c=15.0,
    )
    assert rec.instant_jacket == const.JACKET_LIGHT
    assert rec.jacket_now == const.JACKET_NONE
    assert rec.transient_override is True
    assert rec.display_mode == const.DISPLAY_COMPACT


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
    winter = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)
    for _ in range(3):
        learning.apply_feedback(
            model,
            rating=const.FEEDBACK_TOO_COLD,
            jacket=const.JACKET_NONE,
            wind_kmh=5,
            transition_penalty_c=0,
            observed_at=winter,
        )
    assert model.winter_bias_c >= 2.5
    assert model.general_offset_c == 0.0


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


def test_current_only_recommendation_has_no_fake_forecast_horizon():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    rec = engine.build_recommendation(point(0, 16), [], model, indoor_temperature_c=22)
    assert rec.horizon_hours == 0




def test_short_cached_forecast_does_not_claim_full_default_coverage():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    rec = engine.build_recommendation(
        point(0, 18), [point(1, 17)], model, indoor_temperature_c=22
    )
    assert rec.horizon_hours == 1
    assert rec.forecast_coverage_complete is False


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


def test_perfect_feedback_confirms_nearest_relevant_jacket_boundary():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    # 17.5 °C is much closer to the none/light boundary (~18 °C) than to
    # light/warm (~12 °C), so perfect feedback should not make both borders
    # equally certain.
    for _ in range(12):
        learning.apply_feedback(
            model,
            rating=const.FEEDBACK_PERFECT,
            jacket=const.JACKET_LIGHT,
            wind_kmh=5,
            transition_penalty_c=0,
            effective_c=17.5,
        )
    assert model.light_stat.samples == 12
    assert model.warm_stat.samples == 0
    assert model.light_stat.confidence > 0
    assert model.warm_stat.confidence == 0


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
    model.general_stat.samples = 10
    model.general_stat.weight_sum = 10.0
    model.feedback_opportunities = 11
    assert not learning.should_request_feedback(
        model, near_threshold=False, class_change=False, unusual_weather=False, decision_confidence=0.9, opportunity_count=11
    )
    assert learning.should_request_feedback(
        model, near_threshold=False, class_change=False, unusual_weather=False, decision_confidence=0.9, opportunity_count=12
    )


def test_winter_too_cold_does_not_inflate_winter_boundary_confidence():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    winter = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)
    for _ in range(12):
        learning.apply_feedback(
            model, rating=const.FEEDBACK_TOO_COLD, jacket=const.JACKET_WINTER,
            wind_kmh=5, transition_penalty_c=0, observed_at=winter,
        )
    assert model.winter_stat.samples == 0
    assert model.winter_bias_c > 0
    assert model.general_offset_c == 0.0


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


def test_past_work_points_cannot_change_future_recommendation():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    current = point(0, 22)
    future = [point(1, 22), point(2, 22)]
    past_work = WeatherPoint(
        dt=current.dt - timedelta(hours=2),
        temperature_c=-3,
        condition="rainy",
        precipitation_probability=100,
        precipitation_mm=4,
    )
    rec = engine.build_recommendation(
        current, future, model, indoor_temperature_c=22, work_points=[past_work]
    )
    assert rec.jacket_later == const.JACKET_NONE
    assert rec.rain_status == const.RAIN_NONE
    assert rec.later_at is None


def test_wind_learning_requires_applied_wind_penalty_not_raw_speed():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    model.total_feedback = 11
    model.general_stat.samples = 11
    model.general_stat.weight_sum = 11.0
    learning.apply_feedback(
        model,
        rating=const.FEEDBACK_TOO_COLD,
        jacket=const.JACKET_NONE,
        wind_kmh=35,
        wind_penalty_c=0.0,
    )
    assert model.wind_stat.samples == 0
    before = model.wind_bias_c
    learning.apply_feedback(
        model,
        rating=const.FEEDBACK_TOO_COLD,
        jacket=const.JACKET_LIGHT,
        wind_kmh=15,
        wind_penalty_c=1.0,
    )
    assert model.wind_stat.samples == 1
    assert model.wind_bias_c > before


def test_voluntary_feedback_has_normal_learning_weight():
    normal = PersonalModel.from_answers(3, 3, 3, 3)
    voluntary = PersonalModel.from_answers(3, 3, 3, 3)
    learning.apply_feedback(
        normal, rating=const.FEEDBACK_TOO_COLD, jacket=const.JACKET_NONE, voluntary=False
    )
    learning.apply_feedback(
        voluntary, rating=const.FEEDBACK_TOO_COLD, jacket=const.JACKET_NONE, voluntary=True
    )
    assert normal.general_stat.weight_sum == voluntary.general_stat.weight_sum == 1.0
    assert normal.general_offset_c == voluntary.general_offset_c




def test_learning_progress_does_not_treat_one_specialist_channel_as_global_maturity():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    model.transient_stat.weight_sum = 100.0
    model.transient_stat.samples = 100
    # Specialist-only evidence contributes, but must not make an otherwise new
    # profile look almost fully learned.
    assert 0.18 < model.learning_progress() < 0.50

def test_recommendation_confidence_is_specific_to_shown_jacket_change():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    # Mature overall/no-jacket knowledge, but no winter-boundary experience.
    for _ in range(30):
        learning.apply_feedback(
            model, rating=const.FEEDBACK_PERFECT, jacket=const.JACKET_NONE
        )
    rec = engine.build_recommendation(
        point(0, 23), [point(1, 2)], model, indoor_temperature_c=22
    )
    assert rec.jacket_now == const.JACKET_NONE
    assert rec.jacket_later == const.JACKET_WINTER
    assert rec.confidence == 0.0


def test_manifest_version_matches_runtime_version():
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == const.INTEGRATION_VERSION


def test_single_future_work_rain_is_take_not_current_rain():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    home = [point(i, 20, precipitation_probability=0) for i in range(1, 10)]
    work = [
        point(3, 18, condition="rainy", precipitation_probability=80, precipitation_mm=0.4),
    ]
    rec = engine.build_recommendation(
        point(0, 20),
        home,
        model,
        indoor_temperature_c=22,
        work_points=work,
        work_start=work[0].dt,
    )
    assert rec.rain_status == const.RAIN_TAKE


def test_future_work_rain_matches_same_future_home_rain_strength():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    rainy = point(3, 18, condition="rainy", precipitation_probability=80, precipitation_mm=0.4)
    home_rec = engine.build_recommendation(
        point(0, 20),
        [rainy],
        model,
        indoor_temperature_c=22,
    )
    work_rec = engine.build_recommendation(
        point(0, 20),
        [point(1, 20, precipitation_probability=0)],
        model,
        indoor_temperature_c=22,
        work_points=[rainy],
        work_start=rainy.dt,
    )
    assert work_rec.rain_status == home_rec.rain_status == const.RAIN_TAKE


def test_horizon_extends_for_short_cold_spike_between_hour_9_and_12():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    future = [point(i, 20) for i in range(1, 10)] + [
        point(10, 2),
        point(11, 20),
        point(12, 20),
    ]
    rec = engine.build_recommendation(
        point(0, 20), future, model, indoor_temperature_c=22
    )
    assert rec.horizon_hours == 12
    assert rec.jacket_later == const.JACKET_WINTER
    assert rec.later_at == point(10, 2).dt


def test_horizon_extends_for_short_wind_spike_between_hour_9_and_12():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    future = [point(i, 13, wind_kmh=5) for i in range(1, 10)] + [
        point(10, 13, wind_kmh=60),
        point(11, 13, wind_kmh=5),
        point(12, 13, wind_kmh=5),
    ]
    rec = engine.build_recommendation(
        point(0, 13, wind_kmh=5), future, model, indoor_temperature_c=13
    )
    assert rec.horizon_hours == 12
    assert "wind" in rec.reasons


def test_wind_penalty_is_continuous_around_five_kmh():
    below = engine._wind_penalty(0.0, 4.79)
    above = engine._wind_penalty(0.0, 4.81)
    assert abs(above - below) < 0.10


def test_wind_penalty_is_continuous_around_ten_celsius():
    below = engine._wind_penalty(9.99, 30.0)
    above = engine._wind_penalty(10.01, 30.0)
    assert abs(above - below) < 0.10


def test_humidity_adjustment_is_continuous_at_transition_temperatures():
    cold_below = engine._humidity_adjustment(9.99, 100.0)
    cold_above = engine._humidity_adjustment(10.01, 100.0)
    warm_below = engine._humidity_adjustment(23.99, 100.0)
    warm_above = engine._humidity_adjustment(24.01, 100.0)
    assert abs(cold_above - cold_below) < 0.05
    assert abs(warm_above - warm_below) < 0.05


def test_later_decision_preserves_its_reason():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    rec = engine.build_recommendation(
        point(0, 13, wind_kmh=5),
        [point(2, 13, wind_kmh=60)],
        model,
        indoor_temperature_c=13,
    )
    assert rec.jacket_later != rec.jacket_now
    assert "forecast_change" in rec.reasons
    assert "wind" in rec.reasons


def test_personal_reason_is_set_when_learned_threshold_changes_class():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    model.light_threshold_delta_c = 4.0
    result = engine.assess_point(point(0, 20), model)
    assert result.jacket == const.JACKET_LIGHT
    assert "personal" in result.reasons


def test_same_class_future_threshold_does_not_create_unlearnable_feedback_target():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    rec = engine.build_recommendation(
        point(0, 25),
        [point(2, 18.1)],
        model,
        indoor_temperature_c=25,
    )
    assert rec.jacket_later == rec.jacket_now
    assert rec.later_at is None
    assert "near_threshold" not in rec.reasons


def test_current_only_recommendation_reports_zero_forecast_hours():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    rec = engine.build_recommendation(point(0, 16), [], model, indoor_temperature_c=22)
    assert rec.horizon_hours == 0


def test_work_points_beyond_calendar_max_horizon_are_ignored():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    home = [point(i, 20) for i in range(1, 10)]
    rec = engine.build_recommendation(
        point(0, 20),
        home,
        model,
        indoor_temperature_c=22,
        work_points=[point(20, 0, condition="rainy", precipitation_probability=100, precipitation_mm=5)],
    )
    assert rec.jacket_later == const.JACKET_NONE
    assert rec.later_at is None
    assert rec.rain_status == const.RAIN_NONE
    assert rec.work_context is False
    assert rec.horizon_hours <= const.CALENDAR_MAX_HOURS


def test_short_global_minimum_does_not_hide_stable_lighter_jacket_later():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    rec = engine.build_recommendation(
        point(0, 0),
        [point(1, 20), point(2, 0), point(3, 15), point(4, 15)],
        model,
        indoor_temperature_c=0,
    )
    assert rec.jacket_now == const.JACKET_WINTER
    assert rec.jacket_later == const.JACKET_LIGHT
    assert rec.later_at == point(3, 15).dt


def test_snow_and_hail_trigger_precipitation_protection():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    for condition in ("snowy", "hail"):
        rec = engine.build_recommendation(
            point(0, 10, condition=condition), [], model, indoor_temperature_c=20
        )
        assert rec.rain_status == const.RAIN_RECOMMENDED


def test_work_override_clears_later_target_when_final_class_matches_now():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    home = [point(i, 14) for i in range(1, 10)]
    rec = engine.build_recommendation(
        point(0, 8),
        home,
        model,
        indoor_temperature_c=8,
        work_points=[point(14, 11.9)],
    )
    assert rec.jacket_now == const.JACKET_WARM
    assert rec.jacket_later == const.JACKET_WARM
    assert rec.later_at is None
    assert rec.later_temperature_c is None
    assert "near_threshold" not in rec.reasons


def test_sparse_far_forecast_cannot_hide_card():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    for _ in range(30):
        learning.apply_feedback(
            model, rating=const.FEEDBACK_PERFECT, jacket=const.JACKET_NONE
        )
    rec = engine.build_recommendation(
        point(0, 28, condition="sunny"),
        [point(9, 28, condition="sunny")],
        model,
        indoor_temperature_c=22,
    )
    assert rec.horizon_hours == 9
    assert rec.display_mode == const.DISPLAY_COMPACT


def test_rain_streak_breaks_across_large_forecast_gap():
    status = engine._rain_status_forecast_only([
        point(1, 18, condition="rainy"),
        point(6, 18, condition="rainy"),
    ])
    assert status == const.RAIN_TAKE


def test_personal_reason_includes_learned_wind_sensitivity_when_it_changes_class():
    neutral = PersonalModel.from_answers(3, 3, 3, 3)
    personal = PersonalModel.from_answers(3, 3, 3, 3)
    personal.wind_bias_c = 4.0
    candidate = None
    for temp in [x / 10 for x in range(40, 181)]:
        for wind in range(10, 61, 5):
            base = engine.assess_point(point(0, temp, wind_kmh=wind), neutral)
            learned = engine.assess_point(point(0, temp, wind_kmh=wind), personal)
            if base.jacket != learned.jacket:
                candidate = learned
                break
        if candidate is not None:
            break
    assert candidate is not None
    assert "personal" in candidate.reasons


def test_lighter_later_waits_until_lightest_class_stays_sufficient():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    current = point(0, 8)
    future = [point(1, 14), point(2, 8), point(3, 14)]
    rec = engine.build_recommendation(current, future, model, indoor_temperature_c=8)
    assert rec.jacket_now == const.JACKET_WARM
    assert rec.jacket_later == const.JACKET_LIGHT
    assert rec.later_at == future[2].dt


def test_future_rain_only_does_not_become_thermal_active_learning_trigger():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    for _ in range(30):
        learning.apply_feedback(
            model,
            rating=const.FEEDBACK_PERFECT,
            jacket=const.JACKET_NONE,
            effective_c=25.0,
        )
    future = [point(i, 25) for i in range(1, 8)] + [
        point(8, 25, condition="rainy", precipitation_probability=80, precipitation_mm=1.0)
    ]
    rec = engine.build_recommendation(point(0, 25), future, model, indoor_temperature_c=22)
    assert rec.rain_status != const.RAIN_NONE
    assert "rain" in rec.reasons
    assert "uncertain_conditions" not in rec.reasons


def test_perfect_warm_rating_does_not_inflate_far_winter_boundary():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    for _ in range(30):
        learning.apply_feedback(
            model,
            rating=const.FEEDBACK_PERFECT,
            jacket=const.JACKET_WARM,
            effective_c=11.0,
        )
    assert model.warm_stat.samples == 30
    assert model.winter_stat.samples == 0


def test_unusual_days_keep_model_in_fast_learning_until_weighted_experience_is_mature():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    for _ in range(10):
        learning.apply_feedback(
            model,
            rating=const.FEEDBACK_TOO_COLD,
            jacket=const.JACKET_NONE,
            effective_c=19.0,
            unusual_day=True,
        )
    assert model.total_feedback == 10
    assert abs(model.general_stat.weight_sum - 3.0) < 1e-9
    assert learning.should_request_feedback(
        model,
        near_threshold=False,
        class_change=False,
        unusual_weather=False,
        decision_confidence=0.9,
        opportunity_count=11,
    )


def test_partlycloudy_without_daylight_signal_has_no_solar_bonus():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    result = engine.assess_point(
        point(0, 17.5, condition="partlycloudy", cloud_coverage=30),
        model,
    )
    assert result.solar_gain_c == 0.0


def test_corrupt_scalar_storage_is_sanitized_instead_of_crashing_engine():
    model = PersonalModel.from_dict({
        "setup_complete": True,
        "general_offset_c": "oops",
        "wind_bias_c": float("inf"),
        "transition_bias_c": None,
        "light_threshold_delta_c": "999",
        "total_feedback": "broken",
    })
    assert model.general_offset_c == 0.0
    assert model.wind_bias_c == 0.0
    assert model.transition_bias_c == 0.0
    assert model.light_threshold_delta_c == 4.0
    assert model.total_feedback == 0
    rec = engine.build_recommendation(point(0, 18), [], model, indoor_temperature_c=22)
    assert rec.jacket_now in const.JACKET_LEVELS


def test_hidden_requires_coverage_to_the_actual_work_extended_horizon():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    for _ in range(30):
        learning.apply_feedback(
            model, rating=const.FEEDBACK_PERFECT, jacket=const.JACKET_NONE
        )
    rec = engine.build_recommendation(
        point(0, 28, condition="sunny"),
        [point(i, 28, condition="sunny") for i in range(1, 10)],
        model,
        indoor_temperature_c=22,
        base_horizon_hours=9,
        max_horizon_hours=14,
        work_points=[point(14, 28, condition="sunny")],
    )
    assert rec.horizon_hours == 14
    assert rec.display_mode == const.DISPLAY_COMPACT




def test_single_last_warming_point_cannot_override_now_without_confirmation():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    current = point_minutes(0, 11.5)  # warm
    future = [point_minutes(5, 14.0)]  # light, but nothing confirms it persists
    rec = engine.build_recommendation(current, future, model, indoor_temperature_c=11.5)
    assert rec.jacket_now == const.JACKET_WARM
    assert rec.transient_override is False
    assert rec.forecast_coverage_complete is False




def test_change_only_at_last_forecast_point_cannot_override_now():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    current = point_minutes(0, 11.5)
    future = [
        point_minutes(2, 11.6),
        point_minutes(4, 11.7),
        point_minutes(6, 14.0),
    ]
    rec = engine.build_recommendation(current, future, model, indoor_temperature_c=11.5)
    assert rec.jacket_now == const.JACKET_WARM
    assert rec.jacket_later == const.JACKET_LIGHT
    assert rec.transient_override is False

def test_single_last_cooling_point_cannot_override_now_without_confirmation():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    current = point_minutes(0, 14.0)  # light
    future = [point_minutes(10, 8.0)]  # warm, but nothing confirms it persists
    rec = engine.build_recommendation(current, future, model, indoor_temperature_c=14.0)
    assert rec.jacket_now == const.JACKET_LIGHT
    assert rec.transient_override is False
    assert rec.forecast_coverage_complete is False

def test_large_gap_cannot_confirm_warming_transient_override():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    current = point_minutes(0, 11.5)  # warm
    future = [
        point_minutes(5, 14.0),
        point_minutes(360, 14.0),
    ]
    rec = engine.build_recommendation(current, future, model, indoor_temperature_c=11.5)
    assert rec.jacket_now == const.JACKET_WARM
    assert rec.transient_override is False
    assert rec.forecast_coverage_complete is False


def test_large_gap_cannot_confirm_cooling_transient_override():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    current = point_minutes(0, 14.0)  # light
    future = [
        point_minutes(10, 8.0),
        point_minutes(360, 8.0),
    ]
    rec = engine.build_recommendation(current, future, model, indoor_temperature_c=14.0)
    assert rec.jacket_now == const.JACKET_LIGHT
    assert rec.transient_override is False
    assert rec.forecast_coverage_complete is False


def test_large_gap_does_not_claim_lighter_class_from_first_unconfirmed_point():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    current = point(0, 11.5)  # warm
    future = [
        point(1, 14.0),
        point(8, 14.0),
    ]
    rec = engine.build_recommendation(current, future, model, indoor_temperature_c=11.5)
    assert rec.jacket_now == const.JACKET_WARM
    assert rec.jacket_later == const.JACKET_LIGHT
    assert rec.later_at == future[1].dt
    assert rec.forecast_coverage_complete is False


def test_short_warming_transition_prefers_personally_practical_lighter_jacket():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    current = point_minutes(0, 11.5)  # raw: warm
    future = [
        point_minutes(5, 14.0),
        point_minutes(60, 15.0),
        point_minutes(120, 16.0),
    ]
    rec = engine.build_recommendation(current, future, model, indoor_temperature_c=11.5)
    assert rec.instant_jacket == const.JACKET_WARM
    assert rec.jacket_now == const.JACKET_LIGHT
    assert rec.transient_override is True
    assert rec.transient_direction == "warming"
    assert rec.trend == "warming"


def test_short_but_severe_warming_mismatch_is_not_smoothed_away():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    current = point_minutes(0, -10.0)  # far below winter boundary
    future = [
        point_minutes(10, 8.0),
        point_minutes(60, 9.0),
        point_minutes(120, 10.0),
    ]
    rec = engine.build_recommendation(current, future, model, indoor_temperature_c=-10.0)
    assert rec.jacket_now == const.JACKET_WINTER
    assert rec.transient_override is False


def test_short_cooling_transition_can_choose_warmer_jacket_immediately():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    current = point_minutes(0, 14.0)  # raw: light
    future = [
        point_minutes(10, 8.0),
        point_minutes(60, 8.0),
        point_minutes(120, 7.5),
    ]
    rec = engine.build_recommendation(current, future, model, indoor_temperature_c=14.0)
    assert rec.instant_jacket == const.JACKET_LIGHT
    assert rec.jacket_now == const.JACKET_WARM
    assert rec.transient_override is True
    assert rec.transient_direction == "cooling"


def test_cooling_only_after_two_hours_remains_later_advice_not_immediate_override():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    current = point(0, 14.0)
    future = [point(1, 14.0), point(2, 8.0), point(3, 8.0), point(4, 7.5)]
    rec = engine.build_recommendation(current, future, model, indoor_temperature_c=14.0)
    assert rec.jacket_now == const.JACKET_LIGHT
    assert rec.jacket_later == const.JACKET_WARM
    assert rec.later_at == future[1].dt
    assert rec.transient_override is False


def test_transient_feedback_personalizes_short_term_tolerance_without_history():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    before = model.transient_tolerance
    general_before = model.general_offset_c
    light_before = model.light_threshold_delta_c
    warm_before = model.warm_threshold_delta_c
    learning.apply_feedback(
        model,
        rating=const.FEEDBACK_TOO_COLD,
        jacket=const.JACKET_LIGHT,
        effective_c=11.8,
        observed_at=datetime(2026, 9, 2, 12, tzinfo=timezone.utc),
        transient_override=True,
        transient_direction="warming",
    )
    assert model.transient_tolerance < before
    assert model.transient_stat.samples == 1
    assert model.general_offset_c == general_before
    assert model.light_threshold_delta_c == light_before
    assert model.warm_threshold_delta_c == warm_before
    assert "history" not in model.to_dict()


def test_v031_winter_feedback_changes_only_winter_offset_and_not_main():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    winter = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)
    before = (
        model.general_offset_c,
        model.spring_bias_c,
        model.summer_bias_c,
        model.autumn_bias_c,
    )

    learning.apply_feedback(
        model,
        rating=const.FEEDBACK_TOO_COLD,
        jacket=const.JACKET_LIGHT,
        effective_c=15.0,
        observed_at=winter,
    )

    assert model.winter_bias_c > 0.0
    assert (
        model.general_offset_c,
        model.spring_bias_c,
        model.summer_bias_c,
        model.autumn_bias_c,
    ) == before
    assert model.winter_season_stat.weight_sum == pytest.approx(1.0)
    assert model.spring_season_stat.weight_sum == 0.0
    assert model.summer_season_stat.weight_sum == 0.0
    assert model.autumn_season_stat.weight_sum == 0.0


def test_v031_summer_feedback_changes_only_summer_offset_and_not_main():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    summer = datetime(2026, 7, 15, 12, tzinfo=timezone.utc)
    model.winter_bias_c = 0.4
    model.spring_bias_c = -0.3
    model.autumn_bias_c = 0.2
    before = (
        model.general_offset_c,
        model.winter_bias_c,
        model.spring_bias_c,
        model.autumn_bias_c,
    )

    learning.apply_feedback(
        model,
        rating=const.FEEDBACK_TOO_WARM,
        jacket=const.JACKET_LIGHT,
        effective_c=15.0,
        observed_at=summer,
    )

    assert model.summer_bias_c < 0.0
    assert (
        model.general_offset_c,
        model.winter_bias_c,
        model.spring_bias_c,
        model.autumn_bias_c,
    ) == before


def test_matching_season_bias_affects_only_that_seasons_assessment():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    model.winter_bias_c = 0.8
    model.summer_bias_c = 0.0
    winter_point = WeatherPoint(dt=datetime(2026, 1, 15, 12, tzinfo=timezone.utc), temperature_c=15.0)
    summer_point = WeatherPoint(dt=datetime(2026, 7, 15, 12, tzinfo=timezone.utc), temperature_c=15.0)
    winter_result = engine.assess_point(winter_point, model)
    summer_result = engine.assess_point(summer_point, model)
    assert winter_result.seasonal_adjustment_c == 0.8
    assert summer_result.seasonal_adjustment_c == 0.0
    assert winter_result.effective_temperature_c < summer_result.effective_temperature_c


def test_v031_migration_with_only_autumn_evidence_neutralizes_synthetic_untrained_seasons():
    raw = PersonalModel.from_answers(3, 3, 3, 3).to_dict()
    raw["seasonal_model_version"] = 3
    raw["general_offset_c"] = 0.3
    # Representative centered v0.3 state after only autumn had real feedback.
    raw["winter_bias_c"] = -0.2
    raw["spring_bias_c"] = -0.2
    raw["summer_bias_c"] = -0.2
    raw["autumn_bias_c"] = 0.6
    raw["autumn_season_stat"] = {"samples": 5, "weight_sum": 5.0, "mean": 0.2, "m2": 0.0}
    old_autumn_effective = raw["general_offset_c"] + raw["autumn_bias_c"]

    model = PersonalModel.from_dict(raw)

    assert model.seasonal_model_version == 4
    assert model.autumn_season_initialized is True
    assert model.autumn_season_stat.weight_sum == pytest.approx(5.0)
    assert model.winter_season_initialized is False
    assert model.spring_season_initialized is False
    assert model.summer_season_initialized is False
    assert model.winter_bias_c == 0.0
    assert model.spring_bias_c == 0.0
    assert model.summer_bias_c == 0.0
    assert model.general_offset_c + model.autumn_bias_c == pytest.approx(old_autumn_effective)


def test_v031_season_learning_rate_uses_own_real_evidence():
    winter = PersonalModel.from_answers(3, 3, 3, 3)
    summer = PersonalModel.from_answers(3, 3, 3, 3)
    summer.summer_season_stat = learning.RunningStat(samples=300, weight_sum=300.0)
    summer.summer_season_initialized = True

    learning.apply_feedback(
        winter,
        rating=const.FEEDBACK_TOO_COLD,
        jacket=const.JACKET_LIGHT,
        observed_at=datetime(2026, 1, 15, 12, tzinfo=timezone.utc),
    )
    learning.apply_feedback(
        summer,
        rating=const.FEEDBACK_TOO_COLD,
        jacket=const.JACKET_LIGHT,
        observed_at=datetime(2026, 7, 15, 12, tzinfo=timezone.utc),
    )

    assert winter.winter_bias_c == pytest.approx(0.9)
    assert summer.summer_bias_c == pytest.approx(0.065)


def test_v031_season_learning_never_freezes_with_old_evidence():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    model.winter_season_initialized = True
    model.winter_season_stat = learning.RunningStat(samples=10000, weight_sum=10000.0)
    before = model.winter_bias_c
    learning.apply_feedback(
        model,
        rating=const.FEEDBACK_TOO_COLD,
        jacket=const.JACKET_LIGHT,
        observed_at=datetime(2026, 1, 15, 12, tzinfo=timezone.utc),
    )
    assert model.winter_bias_c - before == pytest.approx(0.065)


def test_v031_season_overlap_blends_one_month_smoothly_without_extra_anchor():
    boundary = datetime(2026, 3, 1, 12, tzinfo=timezone.utc)
    weights = learning._season_weights(boundary)
    assert weights == pytest.approx({"winter": 0.5, "spring": 0.5})
    assert sum(weights.values()) == pytest.approx(1.0)

    before = learning._season_weights(datetime(2026, 2, 20, 12, tzinfo=timezone.utc))
    after = learning._season_weights(datetime(2026, 3, 10, 12, tzinfo=timezone.utc))
    assert before["winter"] > before["spring"]
    assert after["spring"] > after["winter"]
    assert learning._season_weights(datetime(2026, 2, 14, 12, tzinfo=timezone.utc)) == {"winter": 1.0}
    assert learning._season_weights(datetime(2026, 3, 16, 12, tzinfo=timezone.utc)) == {"spring": 1.0}


def test_v031_season_overlap_blends_runtime_bias_at_boundary():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    model.winter_bias_c = -0.6
    model.spring_bias_c = 1.0
    boundary = datetime(2026, 3, 1, 12, tzinfo=timezone.utc)
    assert model.seasonal_bias_for(boundary) == pytest.approx(0.2)


def test_v031_overlap_feedback_changes_only_two_neighbouring_seasons():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    model.summer_bias_c = 0.31
    model.autumn_bias_c = -0.27
    observed = datetime(2026, 3, 1, 12, tzinfo=timezone.utc)
    before_main = model.general_offset_c
    before_summer = model.summer_bias_c
    before_autumn = model.autumn_bias_c

    learning.apply_feedback(
        model,
        rating=const.FEEDBACK_TOO_COLD,
        jacket=const.JACKET_LIGHT,
        observed_at=observed,
    )

    assert model.winter_bias_c > 0.0
    assert model.spring_bias_c > 0.0
    assert model.summer_bias_c == before_summer
    assert model.autumn_bias_c == before_autumn
    assert model.general_offset_c == before_main


def test_v031_overlap_evidence_sums_to_exactly_one_real_rating():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    observed = datetime(2026, 2, 20, 12, tzinfo=timezone.utc)
    weights = learning._season_weights(observed)
    assert set(weights) == {"winter", "spring"}

    learning.apply_feedback(
        model,
        rating=const.FEEDBACK_PERFECT,
        jacket=const.JACKET_LIGHT,
        observed_at=observed,
    )

    assert model.winter_season_stat.weight_sum == pytest.approx(weights["winter"])
    assert model.spring_season_stat.weight_sum == pytest.approx(weights["spring"])
    assert (
        model.winter_season_stat.weight_sum
        + model.spring_season_stat.weight_sum
    ) == pytest.approx(1.0)


def test_v031_fifty_fifty_overlap_keeps_full_effective_learning_step():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    observed = datetime(2026, 3, 1, 12, tzinfo=timezone.utc)
    before = model.seasonal_bias_for(observed)

    learning.apply_feedback(
        model,
        rating=const.FEEDBACK_TOO_COLD,
        jacket=const.JACKET_LIGHT,
        observed_at=observed,
    )

    after = model.seasonal_bias_for(observed)
    assert after - before == pytest.approx(0.9)
    assert model.winter_bias_c == pytest.approx(0.9)
    assert model.spring_bias_c == pytest.approx(0.9)


def test_v031_weighted_overlap_move_redistributes_at_four_degree_saturation_without_main_fallback():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    model.winter_bias_c = 4.0
    model.spring_bias_c = 0.0
    previous = {"winter": 0.0, "spring": 0.0}
    before_main = model.general_offset_c
    residual = learning._apply_weighted_seasonal_learning_move(
        model,
        {"winter": 0.5, "spring": 0.5},
        1.0,
        feedback_weight=1.0,
        previous_evidence=previous,
    )
    assert residual == pytest.approx(0.0)
    assert model.winter_bias_c == pytest.approx(4.0)
    assert model.spring_bias_c == pytest.approx(1.8)
    assert model.general_offset_c == before_main


def test_v031_december_overlap_is_cyclic_and_new_year_has_no_season_jump():
    december_boundary = datetime(2026, 12, 1, 12, tzinfo=timezone.utc)
    assert learning._season_weights(december_boundary) == pytest.approx({"autumn": 0.5, "winter": 0.5})
    assert learning._season_weights(datetime(2026, 12, 16, 12, tzinfo=timezone.utc)) == {"winter": 1.0}
    assert learning._season_weights(datetime(2026, 12, 31, 12, tzinfo=timezone.utc)) == {"winter": 1.0}
    assert learning._season_weights(datetime(2027, 1, 1, 12, tzinfo=timezone.utc)) == {"winter": 1.0}


def test_v031_boundary_only_feedback_does_not_train_main_or_seasons_in_overlap():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    observed = datetime(2026, 3, 1, 12, tzinfo=timezone.utc)
    before = (
        model.general_offset_c,
        model.winter_bias_c,
        model.spring_bias_c,
        model.winter_season_stat.weight_sum,
        model.spring_season_stat.weight_sum,
    )
    learning.apply_feedback(
        model,
        rating=const.FEEDBACK_TOO_WARM,
        jacket=const.JACKET_LIGHT,
        effective_c=15.0,
        observed_at=observed,
        boundary_only=True,
        boundary_attribute="light_threshold_delta_c",
    )
    after = (
        model.general_offset_c,
        model.winter_bias_c,
        model.spring_bias_c,
        model.winter_season_stat.weight_sum,
        model.spring_season_stat.weight_sum,
    )
    assert after == pytest.approx(before)
    assert model.light_threshold_delta_c < 0.0


def test_v031_perfect_feedback_confirms_season_without_moving_offset():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    winter = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)
    model.winter_season_initialized = True
    model.winter_bias_c = 0.7
    before = model.winter_bias_c
    learning.apply_feedback(
        model,
        rating=const.FEEDBACK_PERFECT,
        jacket=const.JACKET_LIGHT,
        observed_at=winter,
    )
    assert model.winter_bias_c == before
    assert model.winter_season_stat.weight_sum == pytest.approx(1.0)




def test_v031_first_encountered_season_starts_neutral_relative_to_main():
    model = PersonalModel.from_answers(5, 3, 3, 3)
    assert model.general_offset_c == pytest.approx(1.8)

    changed = model.prepare_seasons_for(datetime(2026, 10, 1, 12, tzinfo=timezone.utc))

    assert changed is True
    assert model.autumn_season_initialized is True
    assert model.autumn_bias_c == 0.0
    assert model.autumn_seeded_from == ""
    assert model.autumn_season_stat.weight_sum == 0.0


def test_v031_bootstrap_can_chain_seed_new_seasons_without_copying_evidence():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    model.prepare_seasons_for(datetime(2026, 10, 1, 12, tzinfo=timezone.utc))
    model.autumn_bias_c = 0.6
    model.autumn_season_stat = learning.RunningStat(samples=5, weight_sum=5.0)

    model.prepare_seasons_for(datetime(2026, 11, 20, 12, tzinfo=timezone.utc))
    assert model.winter_bias_c == pytest.approx(0.6)
    assert model.winter_season_stat.weight_sum == 0.0
    model.winter_bias_c = 0.3
    model.winter_season_stat = learning.RunningStat(samples=4, weight_sum=4.0)

    model.prepare_seasons_for(datetime(2027, 2, 20, 12, tzinfo=timezone.utc))
    assert model.spring_bias_c == pytest.approx(0.3)
    assert model.spring_seeded_from == "winter"
    assert model.spring_season_stat.weight_sum == 0.0
    model.spring_bias_c = -0.1
    model.spring_season_stat = learning.RunningStat(samples=3, weight_sum=3.0)

    model.prepare_seasons_for(datetime(2027, 5, 20, 12, tzinfo=timezone.utc))
    assert model.summer_bias_c == pytest.approx(-0.1)
    assert model.summer_seeded_from == "spring"
    assert model.summer_season_stat.weight_sum == 0.0


def test_v031_not_used_feedback_adds_no_real_season_evidence():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    winter = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)
    before = model.to_dict()

    learned = learning.apply_feedback(
        model,
        rating=const.FEEDBACK_NOT_USED,
        jacket=const.JACKET_LIGHT,
        observed_at=winter,
    )

    assert learned is False
    assert model.to_dict() == before


@pytest.mark.parametrize(
    ("current", "previous", "when", "previous_bias"),
    [
        ("winter", "autumn", datetime(2027, 1, 10, 12, tzinfo=timezone.utc), 0.8),
        ("spring", "winter", datetime(2027, 4, 10, 12, tzinfo=timezone.utc), -0.7),
        ("summer", "spring", datetime(2027, 7, 10, 12, tzinfo=timezone.utc), 1.1),
        ("autumn", "summer", datetime(2027, 10, 10, 12, tzinfo=timezone.utc), -1.2),
    ],
)
def test_v031_late_seed_catches_up_after_entire_transition_was_missed(
    current, previous, when, previous_bias
):
    model = PersonalModel.from_answers(3, 3, 3, 3)
    setattr(model, f"{previous}_season_initialized", True)
    setattr(model, f"{previous}_bias_c", previous_bias)
    setattr(
        model,
        f"{previous}_season_stat",
        learning.RunningStat(samples=17, mean=0.4, m2=1.2, weight_sum=14.7),
    )

    changed = model.prepare_seasons_for(when)

    assert changed is True
    assert getattr(model, f"{current}_season_initialized") is True
    assert getattr(model, f"{current}_bias_c") == pytest.approx(previous_bias)
    assert getattr(model, f"{current}_seeded_from") == previous
    stat = getattr(model, f"{current}_season_stat")
    assert stat.samples == 0
    assert stat.weight_sum == 0.0
    assert stat.mean == 0.0
    assert stat.m2 == 0.0


def test_v031_late_seed_happens_before_first_real_season_feedback():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    model.autumn_season_initialized = True
    model.autumn_bias_c = 1.0
    model.autumn_season_stat = learning.RunningStat(samples=8, weight_sum=8.0)
    january = datetime(2027, 1, 10, 12, tzinfo=timezone.utc)

    learned = learning.apply_feedback(
        model,
        rating=const.FEEDBACK_TOO_COLD,
        jacket=const.JACKET_LIGHT,
        observed_at=january,
    )

    assert learned is True
    assert model.winter_season_initialized is True
    assert model.winter_seeded_from == "autumn"
    assert model.winter_bias_c > 1.0
    assert model.winter_season_stat.weight_sum == pytest.approx(1.0)
    assert model.autumn_bias_c == pytest.approx(1.0)
    assert model.autumn_season_stat.weight_sum == pytest.approx(8.0)


def test_v031_late_seed_is_one_time_even_after_predecessor_changes():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    model.autumn_season_initialized = True
    model.autumn_bias_c = 0.8
    january = datetime(2027, 1, 10, 12, tzinfo=timezone.utc)

    assert model.prepare_seasons_for(january) is True
    model.winter_bias_c = 0.2
    model.winter_season_stat = learning.RunningStat(samples=4, weight_sum=4.0)
    model.autumn_bias_c = 1.5

    assert model.prepare_seasons_for(datetime(2028, 1, 10, 12, tzinfo=timezone.utc)) is False
    assert model.winter_bias_c == pytest.approx(0.2)
    assert model.winter_seeded_from == "autumn"
    assert model.winter_season_stat.weight_sum == pytest.approx(4.0)


def test_v031_multiple_fully_skipped_seasons_do_not_fabricate_seed_chain():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    model.autumn_season_initialized = True
    model.autumn_bias_c = 0.9
    model.autumn_season_stat = learning.RunningStat(samples=5, weight_sum=5.0)

    # Winter and spring were never encountered. On the first July access, the
    # direct predecessor (spring) is unknown, so summer starts neutral. The
    # implementation must not retroactively invent winter -> spring -> summer.
    changed = model.prepare_seasons_for(datetime(2027, 7, 10, 12, tzinfo=timezone.utc))

    assert changed is True
    assert model.summer_season_initialized is True
    assert model.summer_bias_c == pytest.approx(0.0)
    assert model.summer_seeded_from == ""
    assert model.summer_season_stat.weight_sum == 0.0
    assert model.winter_season_initialized is False
    assert model.spring_season_initialized is False


def test_v031_first_winter_seeds_once_from_autumn_without_copying_evidence():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    model.autumn_season_initialized = True
    model.autumn_bias_c = 0.75
    model.autumn_season_stat = learning.RunningStat(samples=8, weight_sum=8.0)

    changed = model.prepare_seasons_for(datetime(2026, 11, 20, 12, tzinfo=timezone.utc))

    assert changed is True
    assert model.winter_season_initialized is True
    assert model.winter_seeded_from == "autumn"
    assert model.winter_bias_c == pytest.approx(0.75)
    assert model.winter_season_stat.samples == 0
    assert model.winter_season_stat.weight_sum == 0.0


def test_v031_second_winter_keeps_own_value_and_is_never_reseeded():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    model.autumn_season_initialized = True
    model.autumn_bias_c = 0.75
    model.prepare_seasons_for(datetime(2026, 11, 20, 12, tzinfo=timezone.utc))
    model.winter_bias_c = 0.25
    model.winter_season_stat = learning.RunningStat(samples=4, weight_sum=4.0)
    model.autumn_bias_c = 1.4

    changed = model.prepare_seasons_for(datetime(2027, 11, 20, 12, tzinfo=timezone.utc))

    assert changed is False
    assert model.winter_bias_c == pytest.approx(0.25)
    assert model.winter_seeded_from == "autumn"
    assert model.winter_season_stat.weight_sum == pytest.approx(4.0)


def _confirmed_consensus_model() -> PersonalModel:
    model = PersonalModel.from_answers(3, 3, 3, 3)
    for name in ("winter", "spring", "summer", "autumn"):
        setattr(model, f"{name}_season_initialized", True)
        setattr(model, f"{name}_season_stat", learning.RunningStat(samples=3, weight_sum=3.0))
    return model


def test_v031_seeded_only_season_cannot_trigger_main_consensus():
    model = _confirmed_consensus_model()
    model.winter_bias_c = 1.0
    model.spring_bias_c = 1.1
    model.summer_bias_c = 1.2
    model.autumn_bias_c = 0.9
    model.autumn_season_stat = learning.RunningStat()
    model.autumn_seeded_from = "summer"
    before = model.general_offset_c

    assert learning._pool_season_consensus(model) == 0.0
    assert model.general_offset_c == before


def test_v031_four_confirmed_positive_seasons_pool_common_component_to_main():
    model = _confirmed_consensus_model()
    model.winter_bias_c = 1.6
    model.spring_bias_c = 1.4
    model.summer_bias_c = 1.7
    model.autumn_bias_c = 1.5

    transfer = learning._pool_season_consensus(model)

    assert transfer == pytest.approx(1.2)
    assert model.general_offset_c == pytest.approx(1.2)
    assert model.winter_bias_c == pytest.approx(0.4)
    assert model.spring_bias_c == pytest.approx(0.2)
    assert model.summer_bias_c == pytest.approx(0.5)
    assert model.autumn_bias_c == pytest.approx(0.3)


def test_v031_four_confirmed_negative_seasons_pool_common_component_to_main():
    model = _confirmed_consensus_model()
    model.winter_bias_c = -1.6
    model.spring_bias_c = -1.4
    model.summer_bias_c = -1.7
    model.autumn_bias_c = -1.5

    transfer = learning._pool_season_consensus(model)

    assert transfer == pytest.approx(-1.2)
    assert model.general_offset_c == pytest.approx(-1.2)
    assert model.winter_bias_c == pytest.approx(-0.4)
    assert model.spring_bias_c == pytest.approx(-0.2)
    assert model.summer_bias_c == pytest.approx(-0.5)
    assert model.autumn_bias_c == pytest.approx(-0.3)


def test_v031_consensus_pooling_preserves_every_effective_season_value():
    model = _confirmed_consensus_model()
    model.general_offset_c = 0.6
    model.winter_bias_c = 1.6
    model.spring_bias_c = 1.4
    model.summer_bias_c = 1.7
    model.autumn_bias_c = 1.5
    before = {
        name: model.general_offset_c + getattr(model, f"{name}_bias_c")
        for name in ("winter", "spring", "summer", "autumn")
    }

    learning._pool_season_consensus(model)

    after = {
        name: model.general_offset_c + getattr(model, f"{name}_bias_c")
        for name in ("winter", "spring", "summer", "autumn")
    }
    assert after == pytest.approx(before)


@pytest.mark.parametrize(
    "values",
    [
        (0.8, 0.7, -0.6, -0.5),
        (0.8, 0.7, 0.6, -0.5),
    ],
)
def test_v031_mixed_season_signs_never_move_main(values):
    model = _confirmed_consensus_model()
    for name, value in zip(("winter", "spring", "summer", "autumn"), values):
        setattr(model, f"{name}_bias_c", value)
    before = model.general_offset_c
    assert learning._pool_season_consensus(model) == 0.0
    assert model.general_offset_c == before


def test_v031_later_common_negative_trend_can_reverse_earlier_positive_main_transfer():
    model = _confirmed_consensus_model()
    model.general_offset_c = 1.2
    model.winter_bias_c = -0.4
    model.spring_bias_c = -0.3
    model.summer_bias_c = -1.2
    model.autumn_bias_c = -0.5

    transfer = learning._pool_season_consensus(model)

    assert transfer == pytest.approx(-0.1)
    assert model.general_offset_c == pytest.approx(1.1)
    assert model.winter_bias_c == pytest.approx(-0.3)
    assert model.spring_bias_c == pytest.approx(-0.2)
    assert model.summer_bias_c == pytest.approx(-1.1)
    assert model.autumn_bias_c == pytest.approx(-0.4)


def test_v031_single_extreme_summer_does_not_move_main_against_other_seasons():
    model = _confirmed_consensus_model()
    model.general_offset_c = 0.8
    model.winter_bias_c = 0.4
    model.spring_bias_c = 0.3
    model.summer_bias_c = -3.8
    model.autumn_bias_c = 0.5
    before = model.general_offset_c

    learning._pool_season_consensus(model)

    assert model.general_offset_c == before


def test_v031_season_offsets_can_learn_to_plus_and_minus_four_degrees():
    winter = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)
    warmer = PersonalModel.from_answers(3, 3, 3, 3)
    colder = PersonalModel.from_answers(3, 3, 3, 3)

    for _ in range(200):
        learning.apply_feedback(
            warmer,
            rating=const.FEEDBACK_TOO_COLD,
            jacket=const.JACKET_WINTER,
            observed_at=winter,
        )
        learning.apply_feedback(
            colder,
            rating=const.FEEDBACK_TOO_WARM,
            jacket=const.JACKET_LIGHT,
            observed_at=winter,
        )

    assert warmer.winter_bias_c == pytest.approx(4.0)
    assert colder.winter_bias_c == pytest.approx(-4.0)
    assert warmer.general_offset_c == 0.0
    assert colder.general_offset_c == 0.0


def test_v030_no_jacket_too_warm_does_not_drag_personal_offsets_colder():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    summer = datetime(2026, 7, 15, 12, tzinfo=timezone.utc)
    before = model.to_dict()
    confidence_before = model.confidence()
    learning.apply_feedback(
        model,
        rating=const.FEEDBACK_TOO_WARM,
        jacket=const.JACKET_NONE,
        effective_c=30.0,
        observed_at=summer,
    )
    assert model.general_offset_c == before["general_offset_c"]
    assert model.summer_bias_c == before["summer_bias_c"]
    assert model.light_threshold_delta_c == before["light_threshold_delta_c"]
    assert model.general_stat.weight_sum == 0.0
    assert model.total_feedback == before["total_feedback"] + 1
    assert model.confidence() == pytest.approx(confidence_before)


def test_v031_late_current_seed_can_feed_the_transition_that_is_already_active():
    model = PersonalModel.from_answers(3, 3, 3, 3)
    model.autumn_season_initialized = True
    model.autumn_bias_c = 0.8

    # No access during the autumn->winter overlap. The first access happens in
    # the following winter->spring overlap. Winter must first catch up from
    # autumn; spring may then legitimately seed from winter in the active overlap.
    changed = model.prepare_seasons_for(datetime(2027, 2, 20, 12, tzinfo=timezone.utc))

    assert changed is True
    assert model.winter_season_initialized is True
    assert model.winter_bias_c == pytest.approx(0.8)
    assert model.winter_seeded_from == "autumn"
    assert model.winter_season_stat.weight_sum == 0.0
    assert model.spring_season_initialized is True
    assert model.spring_bias_c == pytest.approx(0.8)
    assert model.spring_seeded_from == "winter"
    assert model.spring_season_stat.weight_sum == 0.0


def test_v031_late_seed_can_change_first_recommendation_before_any_feedback():
    when = datetime(2027, 1, 10, 12, tzinfo=timezone.utc)
    current = WeatherPoint(
        dt=when,
        temperature_c=16.5,
        wind_kmh=0.0,
        gust_kmh=0.0,
        precipitation_probability=0.0,
        condition="sunny",
    )
    model = PersonalModel.from_answers(3, 3, 3, 3)
    model.autumn_season_initialized = True
    model.autumn_bias_c = 1.0

    without_late_seed = engine.build_recommendation(
        current, [], model, indoor_temperature_c=21.0
    )
    assert without_late_seed.jacket_now == const.JACKET_NONE

    assert model.prepare_seasons_for(when) is True
    with_late_seed = engine.build_recommendation(
        current, [], model, indoor_temperature_c=21.0
    )

    assert model.winter_bias_c == pytest.approx(1.0)
    assert with_late_seed.jacket_now == const.JACKET_LIGHT
