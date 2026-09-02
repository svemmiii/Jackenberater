"""Compact online-learning model for JackenBerater.

The model intentionally keeps a fixed-size state. Feedback is folded into a few
parameters and weighted counters instead of being retained as an ever-growing
dataset.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import math
from typing import Any

from .const import (
    BASE_LIGHT_THRESHOLD_C,
    BASE_WARM_THRESHOLD_C,
    BASE_WINTER_THRESHOLD_C,
    FEEDBACK_NOT_USED,
    FEEDBACK_PERFECT,
    FEEDBACK_TOO_COLD,
    FEEDBACK_TOO_WARM,
    JACKET_LIGHT,
    JACKET_NONE,
    JACKET_WARM,
    JACKET_WINTER,
    PHASE_ALL,
    PHASE_START,
)


@dataclass(slots=True)
class RunningStat:
    """Fixed-size weighted running statistic.

    ``samples`` remains the human-readable number of observations. ``weight_sum``
    controls confidence and learning speed, so deliberately down-weighted
    feedback (for example an unusual day) does not count as strongly as a normal
    observation.
    """

    samples: int = 0
    weight_sum: float = 0.0
    mean: float = 0.0
    m2: float = 0.0

    def __post_init__(self) -> None:
        # Storage migration from the first v0.1.0 shape, which had no weight_sum.
        if self.samples > 0 and self.weight_sum <= 0:
            self.weight_sum = float(self.samples)

    def add(self, value: float, *, weight: float = 1.0) -> None:
        weight = max(0.0, float(weight))
        if weight <= 0:
            return
        previous_weight = self.weight_sum
        new_weight = previous_weight + weight
        delta = value - self.mean
        self.mean += (weight / new_weight) * delta
        delta2 = value - self.mean
        self.m2 += weight * delta * delta2
        self.weight_sum = new_weight
        self.samples += 1

    @property
    def variance(self) -> float:
        if self.weight_sum <= 1e-9:
            return 0.0
        return max(0.0, self.m2 / self.weight_sum)

    @property
    def confidence(self) -> float:
        sample_conf = 1.0 - math.exp(-self.weight_sum / 18.0)
        consistency = 1.0 / (1.0 + math.sqrt(self.variance))
        return max(0.0, min(0.98, sample_conf * consistency))


@dataclass(slots=True)
class PersonalModel:
    """Persistent compact comfort profile."""

    setup_complete: bool = False
    learning_enabled: bool = True
    cold_answer: int = 3
    warm_answer: int = 3
    wind_answer: int = 3
    evening_answer: int = 3

    # Positive offsets mean the user tends to need more warmth than baseline.
    general_offset_c: float = 0.0
    wind_bias_c: float = 0.0
    transition_bias_c: float = 0.0
    # How willing the user is to accept a short mismatch in exchange for the
    # jacket that fits the continuing trend. 1.0 is neutral; it is deliberately
    # tightly bounded so transient learning can refine, not dominate, the model.
    transient_tolerance: float = 1.0

    # Small fixed-size seasonal corrections. Positive means a little more warmth
    # is preferred in that season. They learn slowly and never replace the global
    # profile.
    winter_bias_c: float = 0.0
    spring_bias_c: float = 0.0
    summer_bias_c: float = 0.0
    autumn_bias_c: float = 0.0

    # Threshold deltas shift the baseline thresholds at which a warmer class is
    # selected. Positive = warmer garment is chosen sooner / at higher temp.
    light_threshold_delta_c: float = 0.0
    warm_threshold_delta_c: float = 0.0
    winter_threshold_delta_c: float = 0.0

    general_stat: RunningStat = field(default_factory=RunningStat)
    wind_stat: RunningStat = field(default_factory=RunningStat)
    transition_stat: RunningStat = field(default_factory=RunningStat)
    transient_stat: RunningStat = field(default_factory=RunningStat)
    winter_season_stat: RunningStat = field(default_factory=RunningStat)
    spring_season_stat: RunningStat = field(default_factory=RunningStat)
    summer_season_stat: RunningStat = field(default_factory=RunningStat)
    autumn_season_stat: RunningStat = field(default_factory=RunningStat)
    light_stat: RunningStat = field(default_factory=RunningStat)
    warm_stat: RunningStat = field(default_factory=RunningStat)
    winter_stat: RunningStat = field(default_factory=RunningStat)
    total_feedback: int = 0
    feedback_opportunities: int = 0

    @classmethod
    def from_answers(
        cls,
        cold: int,
        warm: int,
        wind: int,
        evening: int = 3,
    ) -> "PersonalModel":
        cold = _choice(cold)
        warm = _choice(warm)
        wind = _choice(wind)
        evening = _choice(evening)
        model = cls(
            setup_complete=True,
            cold_answer=cold,
            warm_answer=warm,
            wind_answer=wind,
            evening_answer=evening,
        )
        # Fast but bounded initial personalization. These are starting priors,
        # not permanent truths; real feedback can move them immediately.
        model.general_offset_c = (cold - 3) * 0.9
        warmth_tendency = (3 - warm) * 0.45
        model.light_threshold_delta_c = warmth_tendency * 0.55
        model.warm_threshold_delta_c = warmth_tendency
        model.winter_threshold_delta_c = warmth_tendency * 1.15
        model.wind_bias_c = (wind - 3) * 0.35
        return model

    def seasonal_bias_for(self, when: datetime | None) -> float:
        """Return the small learned seasonal comfort adjustment."""
        if when is None:
            return 0.0
        name = _season_name(when)
        return float(getattr(self, f"{name}_bias_c", 0.0))

    def seasonal_stat_for(self, when: datetime | None) -> RunningStat | None:
        if when is None:
            return None
        name = _season_name(when)
        value = getattr(self, f"{name}_season_stat", None)
        return value if isinstance(value, RunningStat) else None

    def reset_to_answers(self) -> None:
        fresh = PersonalModel.from_answers(
            self.cold_answer,
            self.warm_answer,
            self.wind_answer,
            self.evening_answer,
        )
        fresh.learning_enabled = self.learning_enabled
        for key, value in asdict(fresh).items():
            if key.endswith("_stat"):
                setattr(self, key, RunningStat(**value))
            else:
                setattr(self, key, value)

    def confidence(self) -> float:
        if self.total_feedback == 0:
            return 0.18 if self.setup_complete else 0.08
        return max(0.08, min(0.98, self.general_stat.confidence))

    def jacket_confidence(self, jacket: str) -> float:
        """Confidence of the boundary/boundaries that define one jacket class."""
        if jacket == JACKET_NONE:
            return self.light_stat.confidence
        if jacket == JACKET_LIGHT:
            return min(self.light_stat.confidence, self.warm_stat.confidence)
        if jacket == JACKET_WARM:
            return min(self.warm_stat.confidence, self.winter_stat.confidence)
        if jacket == JACKET_WINTER:
            return self.winter_stat.confidence
        return 0.0

    def decision_confidence(self, jacket_now: str, jacket_later: str) -> float:
        """Return conservative confidence for the recommendation being shown."""
        jacket_conf = min(
            self.jacket_confidence(jacket_now),
            self.jacket_confidence(jacket_later),
        )
        # During the first few ratings the global model is intentionally the main
        # learner. Afterwards the garment-boundary confidence also matters.
        if self.general_stat.weight_sum < 10.0:
            return self.confidence()
        return min(self.confidence(), jacket_conf)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "PersonalModel":
        if not isinstance(raw, dict):
            return cls()

        model = cls()
        model.setup_complete = _safe_bool(raw.get("setup_complete"), False)
        model.learning_enabled = _safe_bool(raw.get("learning_enabled"), True)
        model.cold_answer = _choice(raw.get("cold_answer", 3))
        model.warm_answer = _choice(raw.get("warm_answer", 3))
        model.wind_answer = _choice(raw.get("wind_answer", 3))
        model.evening_answer = _choice(raw.get("evening_answer", 3))

        model.general_offset_c = _safe_number(raw.get("general_offset_c"), 0.0, -5.0, 5.0)
        model.wind_bias_c = _safe_number(raw.get("wind_bias_c"), 0.0, -2.0, 3.0)
        model.transition_bias_c = _safe_number(raw.get("transition_bias_c"), 0.0, -1.5, 2.5)
        model.transient_tolerance = _safe_number(raw.get("transient_tolerance"), 1.0, 0.5, 1.5)
        model.winter_bias_c = _safe_number(raw.get("winter_bias_c"), 0.0, -1.2, 1.2)
        model.spring_bias_c = _safe_number(raw.get("spring_bias_c"), 0.0, -1.2, 1.2)
        model.summer_bias_c = _safe_number(raw.get("summer_bias_c"), 0.0, -1.2, 1.2)
        model.autumn_bias_c = _safe_number(raw.get("autumn_bias_c"), 0.0, -1.2, 1.2)
        model.light_threshold_delta_c = _safe_number(raw.get("light_threshold_delta_c"), 0.0, -3.0, 4.0)
        model.warm_threshold_delta_c = _safe_number(raw.get("warm_threshold_delta_c"), 0.0, -3.0, 4.0)
        model.winter_threshold_delta_c = _safe_number(raw.get("winter_threshold_delta_c"), 0.0, -3.0, 4.0)

        for name in (
            "general_stat", "wind_stat", "transition_stat", "transient_stat",
            "winter_season_stat", "spring_season_stat", "summer_season_stat",
            "autumn_season_stat", "light_stat", "warm_stat", "winter_stat",
        ):
            setattr(model, name, _safe_stat(raw.get(name)))
        model.total_feedback = _safe_int(raw.get("total_feedback"), 0)
        model.feedback_opportunities = _safe_int(raw.get("feedback_opportunities"), 0)
        return model




def _safe_bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _safe_number(value: Any, default: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(number):
        return default
    return max(low, min(high, number))


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(0, number)


def _safe_stat(value: Any) -> RunningStat:
    if not isinstance(value, dict):
        return RunningStat()
    samples = _safe_int(value.get("samples"), 0)
    weight_sum = _safe_number(value.get("weight_sum"), float(samples), 0.0, 1_000_000.0)
    mean = _safe_number(value.get("mean"), 0.0, -1_000_000.0, 1_000_000.0)
    m2 = _safe_number(value.get("m2"), 0.0, 0.0, 1_000_000_000.0)
    return RunningStat(samples=samples, weight_sum=weight_sum, mean=mean, m2=m2)


def _model_thresholds(model: PersonalModel) -> tuple[float, float, float]:
    light = BASE_LIGHT_THRESHOLD_C + model.light_threshold_delta_c
    warm = min(BASE_WARM_THRESHOLD_C + model.warm_threshold_delta_c, light - 2.5)
    winter = min(BASE_WINTER_THRESHOLD_C + model.winter_threshold_delta_c, warm - 2.5)
    return light, warm, winter


def _choice(value: int) -> int:
    try:
        return max(1, min(5, int(value)))
    except (TypeError, ValueError):
        return 3


def _learning_step(samples: float) -> float:
    """Return maximum temperature-equivalent move for one new rating."""
    if samples < 3:
        return 0.9
    if samples < 6:
        return 0.65
    if samples < 11:
        return 0.48
    if samples < 26:
        return 0.30
    if samples < 76:
        return 0.18
    if samples < 201:
        return 0.11
    return 0.065


def _threshold_stats_for_observation(
    model: PersonalModel,
    jacket: str,
    error: float,
    effective_c: float | None = None,
) -> list[RunningStat]:
    """Return only the boundary this observation meaningfully informs.

    A perfect light/warm rating does not make *both* sides of that whole jacket
    interval equally certain. If the effective temperature is known, confirm the
    nearest adjacent boundary; legacy contexts without it stay conservative.
    """
    if error == 0.0:
        if jacket == JACKET_NONE:
            return [model.light_stat]
        if jacket == JACKET_WINTER:
            return [model.winter_stat]
        if effective_c is None or not math.isfinite(effective_c):
            return []
        light, warm, winter = _model_thresholds(model)
        if jacket == JACKET_LIGHT:
            return [model.light_stat] if abs(effective_c - light) <= abs(effective_c - warm) else [model.warm_stat]
        if jacket == JACKET_WARM:
            return [model.warm_stat] if abs(effective_c - warm) <= abs(effective_c - winter) else [model.winter_stat]
        return []

    if (jacket == JACKET_NONE and error > 0) or (jacket == JACKET_LIGHT and error < 0):
        return [model.light_stat]
    if (jacket == JACKET_LIGHT and error > 0) or (jacket == JACKET_WARM and error < 0):
        return [model.warm_stat]
    if (jacket == JACKET_WARM and error > 0) or (jacket == JACKET_WINTER and error < 0):
        return [model.winter_stat]
    # If even the warmest available class was too cold, no existing jacket
    # boundary can correct that error; only the global cold tendency can learn.
    if jacket == JACKET_WINTER and error > 0:
        return []
    return []


def _threshold_target(model: PersonalModel, jacket: str, error: float) -> tuple[str, RunningStat] | None:
    if (jacket == JACKET_NONE and error > 0) or (jacket == JACKET_LIGHT and error < 0):
        return "light_threshold_delta_c", model.light_stat
    if (jacket == JACKET_LIGHT and error > 0) or (jacket == JACKET_WARM and error < 0):
        return "warm_threshold_delta_c", model.warm_stat
    if (jacket == JACKET_WARM and error > 0) or (jacket == JACKET_WINTER and error < 0):
        return "winter_threshold_delta_c", model.winter_stat
    return None


def apply_feedback(
    model: PersonalModel,
    *,
    rating: str,
    jacket: str,
    wind_kmh: float | None = None,
    wind_penalty_c: float | None = None,
    transition_penalty_c: float = 0.0,
    effective_c: float | None = None,
    phase: str | None = None,
    recommendation_used: bool | None = True,
    unusual_day: bool = False,
    voluntary: bool = False,
    count_feedback: bool = True,
    apply_general: bool = True,
    observed_at: datetime | None = None,
    transient_override: bool = False,
    transient_direction: str | None = None,
) -> None:
    """Fold one rating into the compact profile."""
    if rating == FEEDBACK_NOT_USED or recommendation_used is False:
        return
    if rating == FEEDBACK_PERFECT:
        error = 0.0
    elif rating == FEEDBACK_TOO_COLD:
        error = 1.0
    elif rating == FEEDBACK_TOO_WARM:
        error = -1.0
    else:
        return

    # A paused model must remain mathematically frozen. Ratings can still be
    # accepted by the UI, but they must not advance learning counters or alter
    # future learning/feedback cadence.
    if not model.learning_enabled:
        return
    if count_feedback:
        model.total_feedback += 1

    # Voluntary feedback is useful but not inherently more reliable. It can be
    # selection-biased toward especially noticeable misses, so keep normal weight.
    weight = 0.30 if unusual_day else 1.0
    weight = max(0.2, min(1.2, weight))

    # A transient override is a separate decision: accept a short mismatch now
    # because the continuing trend favours another jacket. Feedback on that
    # deliberate compromise must primarily teach *transient tolerance*, not move
    # the user's ordinary all-day jacket thresholds or global comfort offset.
    if transient_override and transient_direction in {"warming", "cooling"}:
        signal = 0.0
        if error != 0.0:
            signal = (-error) if transient_direction == "warming" else error
        previous_transient = model.transient_stat.weight_sum
        model.transient_stat.add(signal, weight=weight)
        if signal != 0.0:
            transient_step = _learning_step(previous_transient) * 0.08 * weight
            model.transient_tolerance = _clamp(
                model.transient_tolerance + signal * transient_step, 0.5, 1.5
            )
        return

    if apply_general:
        previous_general_samples = model.general_stat.weight_sum
        model.general_stat.add(error, weight=weight)
        general_step = _learning_step(previous_general_samples)

        # The first ten ratings deliberately learn fast and mostly adjust one
        # global parameter. Later ratings increasingly refine context-specific
        # parameters.
        global_factor = 1.0 if model.general_stat.weight_sum <= 10.0 else 0.60
        model.general_offset_c = _clamp(
            model.general_offset_c + error * general_step * global_factor * weight,
            -5.0,
            5.0,
        )

        # Season-specific learning is intentionally much slower than the global
        # profile. It lets winter/summer experience nudge the same user in
        # different directions without storing a growing history or forgetting the
        # long-term baseline.
        season_stat = model.seasonal_stat_for(observed_at)
        if season_stat is not None and model.general_stat.weight_sum >= 6.0:
            previous_season = season_stat.weight_sum
            season_stat.add(error, weight=weight)
            if error != 0.0:
                season = _season_name(observed_at)
                attr = f"{season}_bias_c"
                season_step = _learning_step(previous_season) * 0.12 * weight
                setattr(
                    model,
                    attr,
                    _clamp(getattr(model, attr) + error * season_step, -1.2, 1.2),
                )

    # Boundary confidence should still grow during early learning. A perfect
    # rating is especially valuable here because it confirms that the current
    # jacket interval was sensible without forcing the threshold to move.
    threshold_stats = _threshold_stats_for_observation(model, jacket, error, effective_c)
    previous_threshold_weights = {id(stat): stat.weight_sum for stat in threshold_stats}
    for stat in threshold_stats:
        stat.add(error, weight=weight)

    if model.general_stat.weight_sum <= 10.0:
        return

    # Only train the wind model when wind actually changed the thermal decision.
    # Raw gusts can be high while the engine deliberately applies no wind penalty
    # (for example in warm weather); learning from the raw speed would misattribute
    # the user's feedback.
    if (wind_penalty_c or 0.0) >= 0.5:
        previous = model.wind_stat.weight_sum
        model.wind_stat.add(error, weight=weight)
        special_step = _learning_step(previous) * 0.45 * weight
        model.wind_bias_c = _clamp(
            model.wind_bias_c + error * special_step,
            -2.0,
            3.0,
        )

    if transition_penalty_c >= 0.8 and phase in (None, PHASE_START, PHASE_ALL):
        previous = model.transition_stat.weight_sum
        model.transition_stat.add(error, weight=weight)
        special_step = _learning_step(previous) * 0.45 * weight
        model.transition_bias_c = _clamp(
            model.transition_bias_c + error * special_step,
            -1.5,
            2.5,
        )

    if error != 0.0:
        target = _threshold_target(model, jacket, error)
        if target is not None:
            attribute, stat = target
            previous = previous_threshold_weights.get(id(stat), max(0.0, stat.weight_sum - weight))
            threshold_step = _learning_step(previous) * 0.35 * weight
            setattr(
                model,
                attribute,
                _clamp(getattr(model, attribute) + error * threshold_step, -3.0, 4.0),
            )


def should_request_feedback(
    model: PersonalModel,
    *,
    near_threshold: bool,
    class_change: bool,
    unusual_weather: bool,
    decision_confidence: float | None = None,
    opportunity_count: int | None = None,
) -> bool:
    """Active-learning policy: eager first, quiet later, never mathematically stuck."""
    if not model.learning_enabled:
        return False
    n = model.total_feedback
    opportunities = model.feedback_opportunities if opportunity_count is None else opportunity_count
    if model.general_stat.weight_sum < 10.0:
        return True
    confidence = model.confidence() if decision_confidence is None else decision_confidence
    informative = near_threshold or class_change or unusual_weather or confidence < 0.55
    if informative:
        return True
    # Periodic control samples are based on deliberate recommendation sessions,
    # not on feedback count; otherwise a skipped request could freeze forever.
    cadence = 3 if n < 25 else 10
    return opportunities > 0 and opportunities % cadence == 0


def _season_name(when: datetime | None) -> str:
    """Meteorological season name; fixed four-state storage keeps the model tiny."""
    month = when.month if isinstance(when, datetime) else 1
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    return "autumn"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
