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

from .const import (
    CALENDAR_MAX_HOURS,
    DISPLAY_COMPACT,
    DISPLAY_FULL,
    DISPLAY_HIDDEN,
    JACKET_LIGHT,
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

BASE_LIGHT_THRESHOLD_C = 18.0
BASE_WARM_THRESHOLD_C = 12.0
BASE_WINTER_THRESHOLD_C = 5.0

RAIN_CONDITIONS = {
    "rainy",
    "pouring",
    "lightning-rainy",
    "snowy-rainy",
}
WET_CONDITIONS = RAIN_CONDITIONS | {"snowy", "hail"}


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

    wind_penalty = _wind_penalty(temp, effective_wind)
    if wind_penalty > 0:
        wind_penalty *= max(0.55, min(1.65, 1.0 + model.wind_bias_c * 0.12))

    solar_gain = _solar_gain(point.condition, point.cloud_coverage)
    humidity_adjustment = _humidity_adjustment(temp, point.humidity)
    rain_penalty = _rain_penalty(point)

    transition_penalty = 0.0
    if apply_transition and indoor_temperature_c is not None:
        delta = indoor_temperature_c - temp
        transition_penalty = max(0.0, min(3.0, (delta - 4.0) * 0.18))
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
    if abs(model.general_offset_c) >= 0.8:
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
    work_name: str | None = None,
    calendar_context: bool = False,
    activity_context_c: float = 0.0,
    activity_context_fn: Callable[[datetime], float] | None = None,
) -> Recommendation:
    """Build the full current + future garment recommendation."""
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

    all_results = [current_result, *(result for _, result in future_results)]
    jacket_later = current_result.jacket
    later_at: datetime | None = None
    later_point: WeatherPoint | None = None
    later_result: ThermalResult | None = None

    # Clothing has to survive the whole relevant period. Prefer the warmest
    # class that is expected later, and report the first time that class is
    # reached. This avoids stopping at an intermediate class when conditions
    # continue cooling afterwards.
    if future_results:
        future_max_rank = max(JACKET_RANK[result.jacket] for _, result in future_results)
        if future_max_rank > JACKET_RANK[current_result.jacket]:
            for point, result in future_results:
                if JACKET_RANK[result.jacket] == future_max_rank:
                    jacket_later = result.jacket
                    later_at = point.dt
                    later_point = point
                    later_result = result
                    break
        else:
            # If it only gets warmer, tell the card when the lightest useful
            # class is reached instead.
            minimum_rank = min(JACKET_RANK[result.jacket] for _, result in future_results)
            if minimum_rank < JACKET_RANK[current_result.jacket]:
                for point, result in future_results:
                    if JACKET_RANK[result.jacket] == minimum_rank:
                        jacket_later = result.jacket
                        later_at = point.dt
                        later_point = point
                        later_result = result
                        break

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
        # Work/calendar context may intentionally extend beyond the ordinary
        # 9–12 h weather window, but never beyond the data that was supplied.
        latest_work = max((p.dt for p in work_points), default=None)
        if latest_work is not None:
            work_hours = int(max(0.0, (latest_work - current.dt).total_seconds()) / 3600.0 + 0.999)
            horizon_hours = max(horizon_hours, min(CALENDAR_MAX_HOURS, work_hours))

    rain_status = _rain_status(current, horizon_points) if rain_advice else RAIN_NONE
    if rain_advice and work_points:
        work_rain = _rain_status(work_points[0], work_points[1:])
        rain_rank = {RAIN_NONE: 0, RAIN_TAKE: 1, RAIN_RECOMMENDED: 2}
        if rain_rank[work_rain] > rain_rank[rain_status]:
            rain_status = work_rain

    effective_values = [r.effective_temperature_c for r in all_results]
    if work_pairs:
        effective_values.extend(result.effective_temperature_c for _, result in work_pairs)

    class_change = jacket_later != current_result.jacket
    near_threshold = current_result.threshold_margin_c <= 1.5
    unusual_weather = (
        current_result.wind_penalty_c >= 1.5
        or current_result.rain_penalty_c > 0
        or rain_status != RAIN_NONE
    )
    display = _display_mode(
        current_result,
        future_results,
        rain_status,
        class_change=class_change,
        work_jacket=work_jacket,
    )

    reasons = list(current_result.reasons)
    if class_change:
        reasons.append("forecast_change")
    if work_jacket and JACKET_RANK[work_jacket] > JACKET_RANK[current_result.jacket]:
        reasons.append("work_location")
    if rain_status != RAIN_NONE:
        reasons.append("rain")
    if calendar_context:
        reasons.append("calendar_context")
    if near_threshold:
        reasons.append("near_threshold")
    if unusual_weather:
        reasons.append("uncertain_conditions")

    return Recommendation(
        jacket_now=current_result.jacket,
        jacket_later=jacket_later,
        later_at=later_at,
        rain_status=rain_status,
        display_mode=display,
        horizon_hours=horizon_hours,
        effective_now_c=current_result.effective_temperature_c,
        min_effective_c=round(min(effective_values), 1),
        max_effective_c=round(max(effective_values), 1),
        confidence=round(model.confidence(), 3),
        reasons=list(dict.fromkeys(reasons)),
        current_temperature_c=round(current.temperature_c, 1),
        current_wind_kmh=round(current.wind_kmh, 1) if current.wind_kmh is not None else None,
        current_gust_kmh=round(current.gust_kmh, 1) if current.gust_kmh is not None else None,
        current_condition=current.condition,
        transition_penalty_c=current_result.transition_penalty_c,
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
        work_context=work_context,
        work_jacket=work_jacket,
        work_start=work_start,
        work_name=work_name,
        calendar_context=calendar_context,
    )


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


def _wind_penalty(temp_c: float, wind_kmh: float) -> float:
    if wind_kmh < 4.8:
        return 0.0
    if temp_c <= 10.0:
        v16 = wind_kmh ** 0.16
        wind_chill = 13.12 + 0.6215 * temp_c - 11.37 * v16 + 0.3965 * temp_c * v16
        return max(0.0, min(8.0, temp_c - wind_chill))
    if temp_c >= 20.0:
        return 0.0
    # Above the official wind-chill range, taper to a small comfort correction
    # instead of extending the wind-chill formula beyond its intended domain.
    intensity = max(0.0, min(1.0, (20.0 - temp_c) / 10.0))
    return min(2.0, max(0.0, wind_kmh - 5.0) * 0.04 * intensity)


def _solar_gain(condition: str | None, cloud: float | None) -> float:
    condition = (condition or "").lower()
    if condition == "sunny":
        base = 2.0
    elif condition == "partlycloudy":
        base = 0.9
    elif condition == "clear-night":
        base = -0.35
    else:
        base = 0.0
    if cloud is not None and base > 0:
        base *= max(0.25, min(1.0, 1.0 - cloud / 125.0))
    return base


def _humidity_adjustment(temp_c: float, humidity: float | None) -> float:
    if humidity is None:
        return 0.0
    humidity = max(0.0, min(100.0, humidity))
    if temp_c <= 10.0 and humidity > 80.0:
        return -min(0.55, (humidity - 80.0) * 0.0275)
    if temp_c >= 24.0 and humidity > 65.0:
        return min(1.0, (humidity - 65.0) * 0.03)
    return 0.0


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
    if (current.condition or "").lower() in RAIN_CONDITIONS:
        return RAIN_RECOMMENDED
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
    for point, probability in zip(relevant, probabilities, strict=False):
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
        return [], 1

    base_end = origin + timedelta(hours=base_horizon_hours)
    max_end = origin + timedelta(hours=max_horizon_hours)
    points = [point for point in forecast if origin < point.dt <= max_end]
    if not points:
        return [], 1
    base = [point for point in points if point.dt <= base_end]
    extension = [point for point in points if point.dt > base_end]

    def actual_hours(selected: list[WeatherPoint]) -> int:
        if not selected:
            return 1
        return max(1, min(max_horizon_hours, math.ceil((selected[-1].dt - origin).total_seconds() / 3600.0)))

    if not extension or not base:
        selected = base or points
        return selected, actual_hours(selected)

    base_last = assess_point(
        base[-1], model,
        activity_context_c=_activity_for(base[-1].dt, activity_context_c, activity_context_fn),
    )
    ext_last = assess_point(
        extension[-1], model,
        activity_context_c=_activity_for(extension[-1].dt, activity_context_c, activity_context_fn),
    )
    temp_trend = abs(extension[-1].temperature_c - base[-1].temperature_c)
    class_change = base_last.jacket != ext_last.jacket
    rain_change = _rain_status(base[-1], extension) != RAIN_NONE
    selected = points if (temp_trend >= 2.0 or class_change or rain_change) else base
    return selected, actual_hours(selected)


def _display_mode(
    current: ThermalResult,
    future: list[tuple[WeatherPoint, ThermalResult]],
    rain_status: str,
    *,
    class_change: bool,
    work_jacket: str | None,
) -> str:
    jackets = [current.jacket, *(result.jacket for _, result in future)]
    stable = all(j == current.jacket for j in jackets)
    if work_jacket and work_jacket != current.jacket:
        stable = False

    if (
        stable
        and current.jacket == JACKET_NONE
        and rain_status == RAIN_NONE
        and current.threshold_margin_c >= 3.0
        and all(result.threshold_margin_c >= 2.5 for _, result in future)
    ):
        return DISPLAY_HIDDEN

    if (
        stable
        and current.jacket in {JACKET_LIGHT, JACKET_WARM, JACKET_WINTER}
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
