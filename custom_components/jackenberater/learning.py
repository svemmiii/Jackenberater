"""Compact online-learning model for JackenBerater.

The model intentionally keeps a fixed-size state. Feedback is folded into a few
parameters and weighted counters instead of being retained as an ever-growing
dataset.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any

from .const import (
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

    # Threshold deltas shift the baseline thresholds at which a warmer class is
    # selected. Positive = warmer garment is chosen sooner / at higher temp.
    light_threshold_delta_c: float = 0.0
    warm_threshold_delta_c: float = 0.0
    winter_threshold_delta_c: float = 0.0

    general_stat: RunningStat = field(default_factory=RunningStat)
    wind_stat: RunningStat = field(default_factory=RunningStat)
    transition_stat: RunningStat = field(default_factory=RunningStat)
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
        if self.total_feedback < 10:
            return self.confidence()
        return min(self.confidence(), jacket_conf)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "PersonalModel":
        if not isinstance(raw, dict):
            return cls()
        kwargs: dict[str, Any] = {}
        try:
            for key in cls.__dataclass_fields__:
                if key.endswith("_stat"):
                    value = raw.get(key)
                    kwargs[key] = RunningStat(**value) if isinstance(value, dict) else RunningStat()
                elif key in raw:
                    kwargs[key] = raw[key]
            return cls(**kwargs)
        except (TypeError, ValueError, OverflowError):
            return cls()


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


def _threshold_stats_for_observation(model: PersonalModel, jacket: str, error: float) -> list[RunningStat]:
    """Return the boundary stats this observation actually informs.

    A perfect rating validates the interval occupied by the selected jacket and
    therefore can confirm both adjacent boundaries. A cold/warm error only
    informs the boundary that would have corrected that error.
    """
    if error == 0.0:
        if jacket == JACKET_NONE:
            return [model.light_stat]
        if jacket == JACKET_LIGHT:
            return [model.light_stat, model.warm_stat]
        if jacket == JACKET_WARM:
            return [model.warm_stat, model.winter_stat]
        if jacket == JACKET_WINTER:
            return [model.winter_stat]
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
    wind_kmh: float | None,
    transition_penalty_c: float,
    phase: str | None = None,
    recommendation_used: bool | None = True,
    unusual_day: bool = False,
    voluntary: bool = False,
    count_feedback: bool = True,
    apply_general: bool = True,
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

    weight = 0.30 if unusual_day else (1.12 if voluntary else 1.0)
    weight = max(0.2, min(1.2, weight))

    if apply_general:
        previous_general_samples = model.general_stat.weight_sum
        model.general_stat.add(error, weight=weight)
        general_step = _learning_step(previous_general_samples)

        # The first ten ratings deliberately learn fast and mostly adjust one
        # global parameter. Later ratings increasingly refine context-specific
        # parameters.
        global_factor = 1.0 if model.total_feedback <= 10 else 0.60
        model.general_offset_c = _clamp(
            model.general_offset_c + error * general_step * global_factor * weight,
            -5.0,
            5.0,
        )

    # Boundary confidence should still grow during early learning. A perfect
    # rating is especially valuable here because it confirms that the current
    # jacket interval was sensible without forcing the threshold to move.
    threshold_stats = _threshold_stats_for_observation(model, jacket, error)
    previous_threshold_weights = {id(stat): stat.weight_sum for stat in threshold_stats}
    for stat in threshold_stats:
        stat.add(error, weight=weight)

    if model.total_feedback <= 10:
        return

    if (wind_kmh or 0.0) >= 15.0:
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
    if n < 10:
        return True
    confidence = model.confidence() if decision_confidence is None else decision_confidence
    informative = near_threshold or class_change or unusual_weather or confidence < 0.55
    if informative:
        return True
    # Periodic control samples are based on deliberate recommendation sessions,
    # not on feedback count; otherwise a skipped request could freeze forever.
    cadence = 3 if n < 25 else 10
    return opportunities > 0 and opportunities % cadence == 0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
