"""Thermal decision engine for JackenBerater.

This is deliberately lightweight: it uses a small, transparent set of outdoor
comfort corrections instead of a large ML model or the full UTCI polynomial.
The weather inputs mirror the UTCI-relevant variables where Home Assistant can
provide them, then a personal online model adjusts the practical garment
thresholds from real feedback.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import math
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

from .const import (
    BASE_LIGHT_THRESHOLD_C,
    BASE_WARM_THRESHOLD_C,
    BASE_WINTER_THRESHOLD_C,
    CALENDAR_MAX_HOURS,
    DISPLAY_COMPACT,
    DISPLAY_FULL,
    DISPLAY_HIDDEN,
    JACKET_LIGHT,
    JACKET_LEVELS,
    JACKET_NONE,
    JACKET_RANK,
    JACKET_WARM,
    JACKET_WINTER,
    MAX_FORECAST_HOURS,
    RAIN_NONE,
    RAIN_RECOMMENDED,
    RAIN_TAKE,
)
from .learning import PersonalModel
from .models import Recommendation, ThermalResult, WeatherPoint


RAIN_CONDITIONS = {
    "rainy",
    "pouring",
    "lightning-rainy",
    "snowy-rainy",
    "snowy",
    "hail",
}
WET_CONDITIONS = RAIN_CONDITIONS


def assess_point(
    point: WeatherPoint,
    model: PersonalModel,
    *,
    indoor_temperature_c: float | None = None,
    apply_transition: bool = False,
    activity_context_c: float = 0.0,
) -> ThermalResult:
    """Assess one point and return an effective outdoor temperature."""
    temp = point.temperature_c
    wind = max(0.0, point.wind_kmh or 0.0)
    gust = max(wind, point.gust_kmh or wind)
    effective_wind = wind + max(0.0, gust - wind) * 0.25

    base_wind_penalty = _wind_penalty(temp, effective_wind)
    wind_penalty = base_wind_penalty
    if wind_penalty > 0:
        wind_penalty *= max(0.55, min(1.65, 1.0 + model.wind_bias_c * 0.12))

    solar_gain = _solar_gain(point.condition, point.cloud_coverage)
    humidity_adjustment = _humidity_adjustment(temp, point.humidity)
    rain_penalty = _rain_penalty(point)
    seasonal_adjustment = model.seasonal_bias_for(point.dt)

    base_transition_penalty = 0.0
    transition_penalty = 0.0
    if apply_transition and indoor_temperature_c is not None:
        delta = indoor_temperature_c - temp
        base_transition_penalty = max(0.0, min(3.0, (delta - 4.0) * 0.18))
        transition_penalty = base_transition_penalty
        if transition_penalty > 0:
            transition_penalty = max(
                0.0,
                transition_penalty + model.transition_bias_c * 0.45,
            )

    effective = (
        temp
        - wind_penalty
        + solar_gain
        + humidity_adjustment
        - rain_penalty
        - transition_penalty
        - model.general_offset_c
        - seasonal_adjustment
        + activity_context_c
    )

    thresholds = _thresholds(model)
    jacket = _jacket_for_temperature(effective, thresholds)
    margin = _nearest_threshold_margin(effective, thresholds)

    reasons: list[str] = []
    if wind_penalty >= 0.8:
        reasons.append("wind")
    if transition_penalty >= 0.8:
        reasons.append("transition")
    if solar_gain >= 1.0:
        reasons.append("sun")
    if rain_penalty > 0:
        reasons.append("wet")
    # Mark personalization whenever the learned profile changes the actual
    # garment class compared with the same weather evaluated with neutral
    # personal parameters. This also catches learned wind/transition sensitivity,
    # not just the general offset and learned jacket thresholds.
    neutral_effective = (
        temp
        - base_wind_penalty
        + solar_gain
        + humidity_adjustment
        - rain_penalty
        - base_transition_penalty
        + activity_context_c
    )
    neutral_jacket = _jacket_for_temperature(
        neutral_effective,
        (BASE_LIGHT_THRESHOLD_C, BASE_WARM_THRESHOLD_C, BASE_WINTER_THRESHOLD_C),
    )
    if jacket != neutral_jacket:
        reasons.append("personal")

    return ThermalResult(
        effective_temperature_c=round(effective, 2),
        jacket=jacket,
        wind_penalty_c=round(wind_penalty, 2),
        transition_penalty_c=round(transition_penalty, 2),
        solar_gain_c=round(solar_gain, 2),
        rain_penalty_c=round(rain_penalty, 2),
        humidity_adjustment_c=round(humidity_adjustment, 2),
        threshold_margin_c=round(margin, 2),
        seasonal_adjustment_c=round(seasonal_adjustment, 2),
        reasons=reasons,
    )


def build_recommendation(
    current: WeatherPoint,
    forecast: list[WeatherPoint],
    model: PersonalModel,
    *,
    indoor_temperature_c: float | None,
    base_horizon_hours: int = 9,
    max_horizon_hours: int = MAX_FORECAST_HOURS,
    rain_advice: bool = True,
    work_points: list[WeatherPoint] | None = None,
    work_start: datetime | None = None,
    work_end: datetime | None = None,
    work_name: str | None = None,
    calendar_context: bool = False,
    activity_context_c: float = 0.0,
    activity_context_fn: Callable[[datetime], float] | None = None,
) -> Recommendation:
    """Build the current + future practical garment recommendation.

    The immediate thermal class remains the physical starting point, but a short
    transient can be intentionally smoothed when the continuing personal comfort
    trend clearly favours the neighbouring jacket class. This avoids telling a
    user to wear a heavier jacket for only a few minutes before a lasting warm-up,
    or to carry two jackets just to switch almost immediately.
    """
    current_result = assess_point(
        current,
        model,
        indoor_temperature_c=indoor_temperature_c,
        apply_transition=True,
        activity_context_c=_activity_for(current.dt, activity_context_c, activity_context_fn),
    )

    forecast = sorted(
        (point for point in forecast if point.dt > current.dt),
        key=lambda point: point.dt,
    )
    horizon_points, horizon_hours = _select_horizon(
        current.dt,
        forecast,
        model,
        base_horizon_hours=base_horizon_hours,
        max_horizon_hours=max_horizon_hours,
        activity_context_c=activity_context_c,
        activity_context_fn=activity_context_fn,
    )
    future_results = [
        (
            point,
            assess_point(
                point,
                model,
                activity_context_c=_activity_for(
                    point.dt, activity_context_c, activity_context_fn
                ),
            ),
        )
        for point in horizon_points
    ]

    trend = _trend_label(current_result, future_results)
    transient = _transient_now_override(
        current.dt,
        current_result,
        future_results,
        model,
    )
    jacket_now = current_result.jacket
    instant_jacket: str | None = None
    transient_direction: str | None = None
    transient_until: datetime | None = None
    transient_burden: float | None = None
    if transient is not None:
        instant_jacket = current_result.jacket
        jacket_now = str(transient["jacket"])
        transient_direction = str(transient["direction"])
        transient_until = transient["until"]
        transient_burden = float(transient["burden"])

    all_results = [current_result, *(result for _, result in future_results)]
    jacket_later = jacket_now
    later_at: datetime | None = None
    later_point: WeatherPoint | None = None
    later_result: ThermalResult | None = None

    # Clothing has to survive the relevant period. Prefer the warmest class that
    # is expected later. If conditions become milder, report a lighter class only
    # once that class remains sufficient for the rest of the considered period.
    if future_results:
        future_max_rank = max(JACKET_RANK[result.jacket] for _, result in future_results)
        if future_max_rank > JACKET_RANK[jacket_now]:
            for point, result in future_results:
                if JACKET_RANK[result.jacket] == future_max_rank:
                    jacket_later = result.jacket
                    later_at = point.dt
                    later_point = point
                    later_result = result
                    break
        else:
            # Prefer the lightest class that becomes sufficient for the complete
            # remaining suffix, then fall back through slightly warmer classes.
            # Thus an isolated no-jacket point cannot hide a later stable light
            # jacket, while a genuinely stable no-jacket phase is still reported.
            current_rank = JACKET_RANK[jacket_now]
            for candidate_rank in range(current_rank):
                found = False
                for index, (point, result) in enumerate(future_results):
                    if JACKET_RANK[result.jacket] != candidate_rank:
                        continue
                    if all(
                        JACKET_RANK[later.jacket] <= candidate_rank
                        for _, later in future_results[index:]
                    ):
                        jacket_later = result.jacket
                        later_at = point.dt
                        later_point = point
                        later_result = result
                        found = True
                        break
                if found:
                    break

    # Work context must never pull an already-past provider point back into the
    # future decision or bypass the global calendar/work maximum horizon.
    work_limit = _absolute_horizon_end(current.dt, CALENDAR_MAX_HOURS)
    work_points = sorted(
        (p for p in (work_points or []) if current.dt < p.dt <= work_limit),
        key=lambda p: p.dt,
    )
    work_jacket: str | None = None
    work_context = bool(work_points)
    work_pairs: list[tuple[WeatherPoint, ThermalResult]] = []
    if work_points:
        work_pairs = [
            (
                p,
                assess_point(
                    p,
                    model,
                    activity_context_c=_activity_for(
                        p.dt, activity_context_c, activity_context_fn
                    ),
                ),
            )
            for p in work_points
        ]
        if work_pairs:
            work_target_point, work_target_result = max(
                work_pairs, key=lambda pair: JACKET_RANK[pair[1].jacket]
            )
            work_jacket = work_target_result.jacket
            if JACKET_RANK[work_jacket] > JACKET_RANK[jacket_later]:
                jacket_later = work_jacket
                later_at = work_target_point.dt
                later_point = work_target_point
                later_result = work_target_result
        latest_work = max((p.dt for p in work_points), default=None)
        if latest_work is not None:
            work_hours = math.ceil(
                max(0.0, (latest_work - current.dt).total_seconds()) / 3600.0
            )
            horizon_hours = max(
                horizon_hours, min(CALENDAR_MAX_HOURS, work_hours)
            )

    later_context = "work" if (later_at is not None and any(p.dt == later_at for p in work_points)) else "home"

    # later_* describes a real final class change. A work override may cancel a
    # previously detected home change, in which case no future feedback target may
    # survive.
    if jacket_later == jacket_now:
        later_at = None
        later_point = None
        later_result = None
        later_context = "home"

    rain_status = _rain_status(current, horizon_points) if rain_advice else RAIN_NONE
    if rain_advice and work_points:
        work_rain = _rain_status_forecast_only(work_points)
        rain_rank = {RAIN_NONE: 0, RAIN_TAKE: 1, RAIN_RECOMMENDED: 2}
        if rain_rank[work_rain] > rain_rank[rain_status]:
            rain_status = work_rain

    effective_values = [r.effective_temperature_c for r in all_results]
    if work_pairs:
        effective_values.extend(result.effective_temperature_c for _, result in work_pairs)

    class_change = jacket_later != jacket_now
    # Automatic feedback may only be triggered by contexts that the session can
    # actually learn from later.
    feedback_results = [current_result]
    if class_change and later_result is not None:
        feedback_results.append(later_result)
    near_threshold = min(
        (result.threshold_margin_c for result in feedback_results),
        default=current_result.threshold_margin_c,
    ) <= 1.5
    unusual_weather = any(result.wind_penalty_c >= 1.5 for result in feedback_results)

    decision_confidence = model.decision_confidence(jacket_now, jacket_later)
    forecast_coverage_complete = _forecast_covers_horizon(
        current.dt, forecast, horizon_hours
    )
    display = _display_mode(
        current_result,
        future_results,
        rain_status,
        jacket_now=jacket_now,
        class_change=class_change,
        work_jacket=work_jacket,
        allow_hidden=(
            model.total_feedback >= 10
            and decision_confidence >= 0.65
            and forecast_coverage_complete
        ),
    )

    reasons = list(current_result.reasons)
    if transient is not None:
        reasons.append("transient_trend")
    if class_change:
        reasons.append("forecast_change")
        if later_result is not None:
            reasons.extend(later_result.reasons)
    if work_jacket and JACKET_RANK[work_jacket] > JACKET_RANK[jacket_now]:
        reasons.append("work_location")
    if rain_status != RAIN_NONE:
        reasons.append("rain")
    if calendar_context:
        reasons.append("calendar_context")
    if near_threshold:
        reasons.append("near_threshold")
    if unusual_weather:
        reasons.append("uncertain_conditions")

    stay_context = "work" if work_context else ("calendar" if calendar_context else "unknown")

    return Recommendation(
        jacket_now=jacket_now,
        jacket_later=jacket_later,
        later_at=later_at,
        rain_status=rain_status,
        display_mode=display,
        horizon_hours=horizon_hours,
        effective_now_c=current_result.effective_temperature_c,
        min_effective_c=round(min(effective_values), 1),
        max_effective_c=round(max(effective_values), 1),
        confidence=round(decision_confidence, 3),
        reasons=list(dict.fromkeys(reasons)),
        current_temperature_c=round(current.temperature_c, 1),
        current_wind_kmh=round(current.wind_kmh, 1) if current.wind_kmh is not None else None,
        current_gust_kmh=round(current.gust_kmh, 1) if current.gust_kmh is not None else None,
        current_condition=current.condition,
        transition_penalty_c=current_result.transition_penalty_c,
        current_wind_penalty_c=current_result.wind_penalty_c,
        later_temperature_c=(
            round(later_point.temperature_c, 1) if later_point is not None else None
        ),
        later_wind_kmh=(
            round(later_point.wind_kmh, 1)
            if later_point is not None and later_point.wind_kmh is not None
            else None
        ),
        later_gust_kmh=(
            round(later_point.gust_kmh, 1)
            if later_point is not None and later_point.gust_kmh is not None
            else None
        ),
        later_condition=later_point.condition if later_point is not None else None,
        later_effective_c=(
            later_result.effective_temperature_c if later_result is not None else None
        ),
        later_wind_penalty_c=(
            later_result.wind_penalty_c if later_result is not None else None
        ),
        work_context=work_context,
        work_jacket=work_jacket,
        work_start=work_start,
        work_end=work_end,
        work_name=work_name,
        calendar_context=calendar_context,
        trend=trend,
        forecast_coverage_complete=forecast_coverage_complete,
        stay_context=stay_context,
        later_context=later_context,
        transient_override=transient is not None,
        transient_direction=transient_direction,
        transient_until=transient_until,
        transient_burden=(round(transient_burden, 2) if transient_burden is not None else None),
        instant_jacket=instant_jacket,
        seasonal_adjustment_c=current_result.seasonal_adjustment_c,
    )


def _trend_label(
    current: ThermalResult,
    future: list[tuple[WeatherPoint, ThermalResult]],
) -> str:
    """Return a small human-facing trend label from effective comfort values."""
    if not future:
        return "unknown"
    values = [current.effective_temperature_c, *(result.effective_temperature_c for _, result in future)]
    ranks = [JACKET_RANK[current.jacket], *(JACKET_RANK[result.jacket] for _, result in future)]
    n = min(3, len(values))
    start_avg = sum(values[:n]) / n
    end_avg = sum(values[-n:]) / n
    delta = end_avg - start_avg
    spread = max(values) - min(values)
    if spread <= 1.5 and max(ranks) == min(ranks):
        return "stable"
    if delta >= 1.5 and ranks[-1] <= ranks[0]:
        return "warming"
    if delta <= -1.5 and ranks[-1] >= ranks[0]:
        return "cooling"
    return "variable"


def _absolute_horizon_end(now: datetime, hours: int) -> datetime:
    """Return a horizon measured in elapsed hours across DST boundaries."""
    if now.tzinfo is None:
        return now + timedelta(hours=hours)
    utc = ZoneInfo("UTC")
    return (now.astimezone(utc) + timedelta(hours=hours)).astimezone(now.tzinfo)


def _transition_boundary(
    current_rank: int,
    target_rank: int,
    thresholds: tuple[float, float, float],
) -> float | None:
    """Boundary crossed between two neighbouring practical jacket classes."""
    if abs(current_rank - target_rank) != 1:
        return None
    warmer_rank = max(current_rank, target_rank)
    light, warm, winter = thresholds
    return {1: light, 2: warm, 3: winter}.get(warmer_rank)


def _transient_burden_degree_minutes(
    current_dt: datetime,
    current_result: ThermalResult,
    future_results: list[tuple[WeatherPoint, ThermalResult]],
    until: datetime,
    *,
    boundary: float,
    direction: str,
) -> float:
    """Integrate the temporary mismatch against a personal jacket boundary."""
    samples: list[tuple[datetime, float]] = [(current_dt, current_result.effective_temperature_c)]
    samples.extend(
        (point.dt, result.effective_temperature_c)
        for point, result in future_results
        if current_dt < point.dt < until
    )
    # At the persistent change point the mismatch has effectively reached zero.
    samples.append((until, boundary))
    samples.sort(key=lambda item: item[0])

    def mismatch(value: float) -> float:
        if direction == "warming":
            return max(0.0, boundary - value)
        return max(0.0, value - boundary)

    burden = 0.0
    for (a_dt, a_value), (b_dt, b_value) in zip(samples, samples[1:], strict=False):
        minutes = max(0.0, (b_dt - a_dt).total_seconds() / 60.0)
        burden += (mismatch(a_value) + mismatch(b_value)) * 0.5 * minutes
    return burden


def _transient_now_override(
    current_dt: datetime,
    current_result: ThermalResult,
    future_results: list[tuple[WeatherPoint, ThermalResult]],
    model: PersonalModel,
) -> dict[str, object] | None:
    """Collapse a short, personally tolerable transition into one practical jacket.

    The rule is deliberately not a fixed ``20 minutes`` switch. Fifteen minutes is
    only the anti-flapping floor; above that, the personally learned tolerance,
    setup sensitivity and cumulative distance from the user's current learned
    jacket boundary decide whether the short mismatch is acceptable. The future
    class must also remain valid afterwards, so a temporary warm/cold blip is never
    used to override ``now``.
    """
    if not future_results:
        return None

    current_rank = JACKET_RANK[current_result.jacket]
    candidates: list[tuple[datetime, int, str]] = []

    # Warming: find the first lower class that is never followed by a heavier
    # requirement. Only move one class immediately; larger jumps remain visible as
    # later advice instead of pretending several clothing levels are identical.
    for index, (point, result) in enumerate(future_results):
        rank = JACKET_RANK[result.jacket]
        if rank >= current_rank:
            continue
        if all(JACKET_RANK[later.jacket] <= rank for _, later in future_results[index:]):
            candidates.append((point.dt, current_rank - 1, "warming"))
            break

    # Cooling: analogously, the next warmer class may be selected immediately only
    # if at least that warmth remains useful for the rest of the relevant period.
    for index, (point, result) in enumerate(future_results):
        rank = JACKET_RANK[result.jacket]
        if rank <= current_rank:
            continue
        if all(JACKET_RANK[later.jacket] >= rank for _, later in future_results[index:]):
            candidates.append((point.dt, current_rank + 1, "cooling"))
            break

    if not candidates:
        return None
    until, target_rank, direction = min(candidates, key=lambda item: item[0])
    if target_rank < 0 or target_rank >= len(JACKET_LEVELS):
        return None

    duration_minutes = max(0.0, (until - current_dt).total_seconds() / 60.0)
    if duration_minutes <= 0:
        return None

    threshold = _transition_boundary(current_rank, target_rank, _thresholds(model))
    if threshold is None:
        return None
    burden = _transient_burden_degree_minutes(
        current_dt,
        current_result,
        future_results,
        until,
        boundary=threshold,
        direction=direction,
    )

    answer = model.cold_answer if direction == "warming" else model.warm_answer
    answer_factor = 1.0 + (3 - max(1, min(5, int(answer)))) * 0.10
    tolerance = max(0.5, min(1.5, float(model.transient_tolerance)))
    # The personal upper transition window naturally spans roughly 15–45 min.
    personal_max_minutes = max(
        15.0,
        min(45.0, 30.0 + (tolerance - 1.0) * 20.0 + (3 - answer) * 4.0),
    )
    burden_limit = 25.0 * tolerance * answer_factor

    if duration_minutes < 15.0:
        allowed = burden <= burden_limit * 2.0
    else:
        allowed = duration_minutes <= personal_max_minutes and burden <= burden_limit
    if not allowed:
        return None

    return {
        "jacket": JACKET_LEVELS[target_rank],
        "until": until,
        "direction": direction,
        "burden": burden,
        "duration_minutes": duration_minutes,
    }


def _thresholds(model: PersonalModel) -> tuple[float, float, float]:
    light = BASE_LIGHT_THRESHOLD_C + model.light_threshold_delta_c
    warm = BASE_WARM_THRESHOLD_C + model.warm_threshold_delta_c
    winter = BASE_WINTER_THRESHOLD_C + model.winter_threshold_delta_c
    # Keep ordering and a useful minimum separation even after years of learning.
    warm = min(warm, light - 2.5)
    winter = min(winter, warm - 2.5)
    return light, warm, winter


def _jacket_for_temperature(
    effective_c: float,
    thresholds: tuple[float, float, float],
) -> str:
    light, warm, winter = thresholds
    if effective_c >= light:
        return JACKET_NONE
    if effective_c >= warm:
        return JACKET_LIGHT
    if effective_c >= winter:
        return JACKET_WARM
    return JACKET_WINTER


def _nearest_threshold_margin(
    effective_c: float,
    thresholds: tuple[float, float, float],
) -> float:
    return min(abs(effective_c - threshold) for threshold in thresholds)


def _smoothstep(edge0: float, edge1: float, value: float) -> float:
    """Return a smooth 0..1 transition between two edges."""
    if edge1 <= edge0:
        return 1.0 if value >= edge1 else 0.0
    t = max(0.0, min(1.0, (value - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


def _cold_wind_penalty(temp_c: float, wind_kmh: float) -> float:
    """Cold-range wind penalty with a smooth low-speed transition.

    Environment and Climate Change Canada documents a separate low-wind
    equation below roughly 5 km/h. Blending the low- and regular-speed forms
    around that boundary avoids a sensor-noise step at 4.8/5 km/h.
    """
    if wind_kmh <= 0.0:
        return 0.0

    low_wind_chill = temp_c + ((-1.59 + 0.1345 * temp_c) / 5.0) * wind_kmh
    low_penalty = max(0.0, temp_c - low_wind_chill)

    v16 = max(0.1, wind_kmh) ** 0.16
    regular_wind_chill = (
        13.12
        + 0.6215 * temp_c
        - 11.37 * v16
        + 0.3965 * temp_c * v16
    )
    regular_penalty = max(0.0, temp_c - regular_wind_chill)

    speed_blend = _smoothstep(4.0, 6.0, wind_kmh)
    return min(8.0, low_penalty * (1.0 - speed_blend) + regular_penalty * speed_blend)


def _wind_penalty(temp_c: float, wind_kmh: float) -> float:
    """Return a continuous comfort penalty for wind.

    The official cold-range equations are used as an anchor, then smoothly
    blended into a deliberately small comfort correction above the classic
    wind-chill range. This keeps the heuristic stable around 5 km/h and 10 °C.
    """
    if wind_kmh <= 0.0 or temp_c >= 20.0:
        return 0.0

    cold_penalty = _cold_wind_penalty(temp_c, wind_kmh)
    mild_intensity = max(0.0, min(1.0, (20.0 - temp_c) / 10.0))
    mild_penalty = min(2.0, max(0.0, wind_kmh - 5.0) * 0.04 * mild_intensity)

    if temp_c <= 8.0:
        return cold_penalty
    if temp_c >= 14.0:
        return mild_penalty

    temperature_blend = _smoothstep(8.0, 14.0, temp_c)
    return (
        cold_penalty * (1.0 - temperature_blend)
        + mild_penalty * temperature_blend
    )


def _solar_gain(condition: str | None, cloud: float | None) -> float:
    condition = (condition or "").lower()
    if condition == "sunny":
        base = 2.0
    elif condition == "partlycloudy":
        # Hourly HA forecasts do not guarantee an explicit day/night flag and
        # there is no standardized "partlycloudy-night" state. Be conservative:
        # a few clouds alone are not proof of useful solar warming.
        base = 0.0
    elif condition == "clear-night":
        base = -0.35
    else:
        base = 0.0
    if cloud is not None and base > 0:
        base *= max(0.25, min(1.0, 1.0 - cloud / 125.0))
    return base


def _humidity_adjustment(temp_c: float, humidity: float | None) -> float:
    """Small humidity correction with smooth temperature transitions."""
    if humidity is None:
        return 0.0
    humidity = max(0.0, min(100.0, humidity))

    cold_base = 0.0
    if humidity > 80.0:
        cold_base = -min(0.55, (humidity - 80.0) * 0.0275)
    # Full cold-damp effect through 10 °C, then fade it out by 14 °C.
    cold_strength = 1.0 - _smoothstep(10.0, 14.0, temp_c)

    warm_base = 0.0
    if humidity > 65.0:
        warm_base = min(1.0, (humidity - 65.0) * 0.03)
    # Warm-humid discomfort fades in gradually instead of jumping at 24 °C.
    warm_strength = _smoothstep(22.0, 26.0, temp_c)

    return cold_base * cold_strength + warm_base * warm_strength


def _rain_penalty(point: WeatherPoint) -> float:
    condition = (point.condition or "").lower()
    if condition in WET_CONDITIONS:
        return 0.9 if condition != "pouring" else 1.4
    probability = point.precipitation_probability or 0.0
    amount = point.precipitation_mm or 0.0
    if probability >= 65.0 and amount >= 0.2:
        return 0.6
    return 0.0


def _rain_status(current: WeatherPoint, forecast: list[WeatherPoint]) -> str:
    """Combine observed rain now with probabilistic/forecast rain later."""
    if (current.condition or "").lower() in RAIN_CONDITIONS:
        return RAIN_RECOMMENDED
    return _rain_status_forecast_only(forecast)


def _rain_status_forecast_only(forecast: list[WeatherPoint]) -> str:
    """Evaluate future rain without pretending the first point is current rain."""
    relevant = forecast
    if not relevant:
        return RAIN_NONE
    probabilities = [p.precipitation_probability or 0.0 for p in relevant]
    total_mm = sum(max(0.0, p.precipitation_mm or 0.0) for p in relevant)
    max_probability = max(probabilities, default=0.0)
    consecutive_high = 0
    max_consecutive_high = 0
    consecutive_rain = 0
    max_consecutive_rain = 0
    rainy_points = 0
    pouring = False
    previous_dt: datetime | None = None
    for point, probability in zip(relevant, probabilities, strict=False):
        if previous_dt is not None and point.dt - previous_dt > timedelta(minutes=90):
            # Missing hours break a rain streak. Two rainy points five hours apart
            # are not a continuous rain period just because they are adjacent in
            # the provider list.
            consecutive_high = 0
            consecutive_rain = 0
        previous_dt = point.dt
        if probability >= 60.0:
            consecutive_high += 1
            max_consecutive_high = max(max_consecutive_high, consecutive_high)
        else:
            consecutive_high = 0
        condition = (point.condition or "").lower()
        if condition in RAIN_CONDITIONS:
            rainy_points += 1
            consecutive_rain += 1
            max_consecutive_rain = max(max_consecutive_rain, consecutive_rain)
            pouring = pouring or condition == "pouring"
        else:
            consecutive_rain = 0
    if (
        pouring
        or (max_probability >= 70.0 and total_mm >= 1.0)
        or max_consecutive_high >= 2
        or max_consecutive_rain >= 2
    ):
        return RAIN_RECOMMENDED
    if max_probability >= 40.0 or total_mm >= 0.2 or rainy_points >= 1:
        return RAIN_TAKE
    return RAIN_NONE


def _activity_for(
    when: datetime,
    fixed_c: float,
    fn: Callable[[datetime], float] | None,
) -> float:
    return float(fn(when)) if fn is not None else fixed_c


def _forecast_covers_horizon(
    origin: datetime,
    forecast: list[WeatherPoint],
    horizon_hours: int,
    *,
    max_gap: timedelta = timedelta(minutes=90),
) -> bool:
    """Return whether forecast data continuously covers the normal horizon.

    A far-away point alone must never make a recommendation look fully covered.
    Hourly providers may be slightly offset from ``origin``, so up to 90 minutes
    between points (and at both edges) is tolerated.
    """
    if horizon_hours <= 0:
        return False
    target = origin + timedelta(hours=horizon_hours)
    points = sorted(
        (point for point in forecast if origin < point.dt <= target + max_gap),
        key=lambda point: point.dt,
    )
    if not points or points[0].dt - origin > max_gap:
        return False
    previous = points[0].dt
    for point in points[1:]:
        if point.dt - previous > max_gap:
            return False
        previous = point.dt
        if previous >= target:
            return True
    return target - previous <= max_gap


def _select_horizon(
    origin: datetime,
    forecast: list[WeatherPoint],
    model: PersonalModel,
    *,
    base_horizon_hours: int,
    max_horizon_hours: int,
    activity_context_c: float,
    activity_context_fn: Callable[[datetime], float] | None = None,
) -> tuple[list[WeatherPoint], int]:
    if not forecast:
        return [], 0

    base_end = origin + timedelta(hours=base_horizon_hours)
    max_end = origin + timedelta(hours=max_horizon_hours)
    points = [point for point in forecast if origin < point.dt <= max_end]
    if not points:
        return [], 0
    base = [point for point in points if point.dt <= base_end]
    extension = [point for point in points if point.dt > base_end]

    def actual_hours(selected: list[WeatherPoint]) -> int:
        if not selected:
            return 0
        return max(
            0,
            min(
                max_horizon_hours,
                math.ceil((selected[-1].dt - origin).total_seconds() / 3600.0),
            ),
        )

    if not extension or not base:
        selected = base or points
        return selected, actual_hours(selected)

    base_last_point = base[-1]
    base_last = assess_point(
        base_last_point,
        model,
        activity_context_c=_activity_for(
            base_last_point.dt, activity_context_c, activity_context_fn
        ),
    )
    extension_results = [
        (
            point,
            assess_point(
                point,
                model,
                activity_context_c=_activity_for(
                    point.dt, activity_context_c, activity_context_fn
                ),
            ),
        )
        for point in extension
    ]

    # The extension decision must inspect every point. A short cold/wind/rain
    # event at hour 10 must not disappear merely because hour 12 looks like
    # hour 9 again.
    relevant_extension = any(
        abs(point.temperature_c - base_last_point.temperature_c) >= 2.0
        or abs(result.effective_temperature_c - base_last.effective_temperature_c) >= 2.0
        or result.jacket != base_last.jacket
        for point, result in extension_results
    )
    rain_change = _rain_status_forecast_only(extension) != RAIN_NONE
    selected = points if (relevant_extension or rain_change) else base
    return selected, actual_hours(selected)


def _display_mode(
    current: ThermalResult,
    future: list[tuple[WeatherPoint, ThermalResult]],
    rain_status: str,
    *,
    jacket_now: str | None = None,
    class_change: bool,
    work_jacket: str | None,
    allow_hidden: bool,
) -> str:
    practical_now = jacket_now or current.jacket
    jackets = [practical_now, *(result.jacket for _, result in future)]
    stable = all(j == practical_now for j in jackets)
    if work_jacket and work_jacket != practical_now:
        stable = False

    if (
        stable
        and practical_now == JACKET_NONE
        and rain_status == RAIN_NONE
        and current.threshold_margin_c >= 3.0
        and all(result.threshold_margin_c >= 2.5 for _, result in future)
    ):
        # A young/uncertain profile must remain reachable so the user can correct
        # an overconfident “no jacket” assumption. Once enough personal evidence
        # exists, the fully hidden summer state can keep the dashboard quiet.
        return DISPLAY_HIDDEN if allow_hidden else DISPLAY_COMPACT

    if (
        stable
        and practical_now in {JACKET_LIGHT, JACKET_WARM, JACKET_WINTER}
        and not class_change
        and rain_status == RAIN_NONE
        and current.threshold_margin_c >= 2.5
    ):
        return DISPLAY_COMPACT

    return DISPLAY_FULL


def merge_location_timeline(
    home_points: list[WeatherPoint],
    work_points: list[WeatherPoint],
    work_windows: list[tuple[datetime, datetime]],
) -> list[WeatherPoint]:
    """Merge forecasts without double-counting home weather during work windows.

    Work points replace home points that fall inside a probable work window.
    Outside those windows the home forecast remains relevant. When both sources
    provide the same timestamp, the context-appropriate point wins.
    """
    if not work_windows:
        return sorted(home_points, key=lambda point: point.dt)

    def in_work_window(point: WeatherPoint) -> bool:
        return any(start <= point.dt <= end for start, end in work_windows)

    merged: dict[datetime, WeatherPoint] = {
        point.dt: point for point in home_points if not in_work_window(point)
    }
    for point in work_points:
        if in_work_window(point):
            merged[point.dt] = point
    return [merged[key] for key in sorted(merged)]


def max_jacket(points: Iterable[ThermalResult]) -> str:
    """Return the warmest jacket in a result sequence."""
    return max(points, key=lambda item: JACKET_RANK[item.jacket]).jacket
