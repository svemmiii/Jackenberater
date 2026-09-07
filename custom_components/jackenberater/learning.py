"""Compact online-learning model for JackenBerater.

The model intentionally keeps a fixed-size state. Feedback is folded into a few
parameters and weighted counters instead of being retained as an ever-growing
dataset.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
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

    # Seasonal values are relative deviations from the personal year-round
    # baseline. Their four-value mean is kept near zero so a tendency that is
    # common to every season is carried by ``general_offset_c`` instead of being
    # learned twice.
    seasonal_model_version: int = 3
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
        """Return the smoothly blended deviation from the year-round baseline."""
        weights = _season_weights(when)
        return sum(
            weight * float(getattr(self, f"{name}_bias_c", 0.0))
            for name, weight in weights.items()
        )

    def seasonal_stat_for(self, when: datetime | None) -> RunningStat | None:
        """Return the dominant seasonal statistic for compatibility helpers.

        Learning itself uses all active seasonal weights during overlap periods.
        """
        weights = _season_weights(when)
        if not weights:
            return None
        name = max(weights, key=weights.get)
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
        # Keep the setup prior until there is actual general learning evidence.
        # Some valid feedback is intentionally non-general (for example
        # transition-boundary timing, or "no jacket + too warm"). Counting such
        # feedback must not make decision confidence fall merely because
        # total_feedback became non-zero.
        if self.general_stat.weight_sum <= 0.0:
            return 0.18 if self.setup_complete else 0.08
        return max(0.08, min(0.98, self.general_stat.confidence))

    def learning_progress(self) -> float:
        """User-facing breadth of learned evidence during normal forward use.

        The value starts with the setup prior and grows from a blend of general,
        garment-boundary and specialist evidence. Using a blend instead of the
        single largest statistic prevents one heavily trained niche (for example
        short-transition tolerance) from making the whole profile look mature.
        Reset and undo intentionally may move this value backwards.
        """
        if not self.setup_complete:
            return 0.08
        boundary_evidence = (
            self.light_stat.weight_sum
            + self.warm_stat.weight_sum
            + self.winter_stat.weight_sum
        ) / 3.0
        specialist_evidence = (
            self.wind_stat.weight_sum
            + self.transition_stat.weight_sum
            + self.transient_stat.weight_sum
            + self.winter_season_stat.weight_sum
            + self.spring_season_stat.weight_sum
            + self.summer_season_stat.weight_sum
            + self.autumn_season_stat.weight_sum
        ) / 7.0
        evidence = (
            0.55 * self.general_stat.weight_sum
            + 0.35 * boundary_evidence
            + 0.10 * specialist_evidence
        )
        learned = 0.18 + 0.80 * (1.0 - math.exp(-evidence / 12.0))
        return max(0.18, min(0.98, learned))

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
        model.seasonal_model_version = _safe_int(raw.get("seasonal_model_version"), 1) or 1
        model.wind_bias_c = _safe_number(raw.get("wind_bias_c"), 0.0, -2.0, 3.0)
        model.transition_bias_c = _safe_number(raw.get("transition_bias_c"), 0.0, -1.5, 2.5)
        model.transient_tolerance = _safe_number(raw.get("transient_tolerance"), 1.0, 0.5, 1.5)
        model.winter_bias_c = _safe_number(raw.get("winter_bias_c"), 0.0, -1.8, 1.8)
        model.spring_bias_c = _safe_number(raw.get("spring_bias_c"), 0.0, -1.8, 1.8)
        model.summer_bias_c = _safe_number(raw.get("summer_bias_c"), 0.0, -1.8, 1.8)
        model.autumn_bias_c = _safe_number(raw.get("autumn_bias_c"), 0.0, -1.8, 1.8)
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

        # v0.3.0 migration: older profiles stored four additive seasonal nudges
        # without enforcing a common baseline. Re-centering moves their common
        # mean into ``general_offset_c`` and subtracts the same amount from every
        # season. Therefore ``general + season`` stays identical for all four
        # seasons while the new representation becomes mathematically identifiable.
        if model.seasonal_model_version < 2:
            _recenter_seasonal_biases(model)
        # v0.3.0 overlap model: storage still consists of the same four seasonal
        # anchors. Version 3 only records that their runtime effect is blended
        # smoothly around the four meteorological boundaries.
        if model.seasonal_model_version < 3:
            model.seasonal_model_version = 3
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


def _season_bias_attributes() -> tuple[str, str, str, str]:
    return (
        "winter_bias_c",
        "spring_bias_c",
        "summer_bias_c",
        "autumn_bias_c",
    )


_SEASON_TRANSITION_HALF_DAYS = 15
_SEASON_TRANSITIONS: tuple[tuple[int, int, str, str], ...] = (
    (3, 1, "winter", "spring"),
    (6, 1, "spring", "summer"),
    (9, 1, "summer", "autumn"),
    (12, 1, "autumn", "winter"),
)


def _smoothstep(value: float) -> float:
    """Cubic 0..1 blend with zero slope at both ends."""
    value = _clamp(value, 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)


def _season_weights(when: datetime | None) -> dict[str, float]:
    """Return one or two season-anchor weights that always sum to one.

    Each meteorological boundary is surrounded by one month of smooth overlap:
    15 days before through 15 days after. Outside these windows exactly one
    season anchor is active. No transition value is stored or learned.
    """
    if not isinstance(when, datetime):
        return {}
    current = when.date()
    half = timedelta(days=_SEASON_TRANSITION_HALF_DAYS)
    for year in (current.year - 1, current.year, current.year + 1):
        for month, day, previous_name, next_name in _SEASON_TRANSITIONS:
            boundary = date(year, month, day)
            start = boundary - half
            end = boundary + half
            if not (start < current < end):
                continue
            progress = (current - start).days / float((end - start).days)
            next_weight = _smoothstep(progress)
            previous_weight = 1.0 - next_weight
            # Avoid tiny floating tails so pure-anchor logic remains exact close
            # to the transition edges.
            if previous_weight <= 1e-12:
                return {next_name: 1.0}
            if next_weight <= 1e-12:
                return {previous_name: 1.0}
            return {previous_name: previous_weight, next_name: next_weight}
    return {_season_name(when): 1.0}


def _season_stat(model: PersonalModel, name: str) -> RunningStat:
    value = getattr(model, f"{name}_season_stat")
    if not isinstance(value, RunningStat):  # defensive for hand-built objects
        value = RunningStat()
        setattr(model, f"{name}_season_stat", value)
    return value


def _recenter_seasonal_biases(model: PersonalModel) -> None:
    """Center seasonal deviations while preserving all effective anchor totals.

    The shared mean is moved into ``general_offset_c``. The transfer amount is
    constrained so neither the general safety bound nor any seasonal bound has
    to be clipped afterwards; therefore every ``general + season`` total stays
    exactly unchanged whenever a transfer is possible.
    """
    attrs = _season_bias_attributes()
    values = [float(getattr(model, attr)) for attr in attrs]
    mean = sum(values) / len(values)
    if abs(mean) <= 1e-12:
        return

    lower = -5.0 - model.general_offset_c
    upper = 5.0 - model.general_offset_c
    for value in values:
        lower = max(lower, value - 1.8)
        upper = min(upper, value + 1.8)
    if lower > upper:
        return
    shift = _clamp(mean, lower, upper)
    if abs(shift) <= 1e-12:
        return
    model.general_offset_c += shift
    for attr in attrs:
        setattr(model, attr, float(getattr(model, attr)) - shift)


def _season_learning_share(model: PersonalModel, observed_at: datetime | None) -> float:
    """Return the part of one correction assigned to seasonal deviation.

    The current situation always receives one fixed correction budget. Early on,
    almost all of it goes into the year-round baseline so a new profile becomes
    useful quickly. During overlap periods evidence from both active anchors is
    combined using the same date weights as the runtime seasonal adjustment.
    """
    weights = _season_weights(observed_at)
    if not weights:
        return 0.0

    all_evidence = {
        name: max(0.0, _season_stat(model, name).weight_sum)
        for name in ("winter", "spring", "summer", "autumn")
    }
    total = sum(all_evidence.values())
    own = sum(weight * all_evidence[name] for name, weight in weights.items())
    # For every currently possible anchor, ask how much evidence exists outside
    # that anchor, then blend those answers by the current overlap weights. This
    # lets an already-known winter help distinguish a nascent spring near March
    # without pretending that one winter observation is two observations.
    other = sum(
        weight * max(0.0, total - all_evidence[name])
        for name, weight in weights.items()
    )
    own_conf = 1.0 - math.exp(-own / 6.0)
    cross_conf = 1.0 - math.exp(-other / 10.0)
    max_share = 0.15 + 0.55 * cross_conf
    return _clamp(own_conf * max_share, 0.0, 0.70)


def _apply_weighted_seasonal_move(
    model: PersonalModel,
    weights: dict[str, float],
    desired_effective_move: float,
) -> float:
    """Move active seasonal anchors while preserving the effective date move.

    The minimal-norm update is proportional to ``w / sum(w^2)``. Consequently
    a 50/50 transition does *not* halve learning: moving both anchors by +0.12 C
    changes their 50/50 blend by exactly +0.12 C. If an anchor hits its safety
    bound, the remaining effective move is redistributed to the other active
    anchor. Any residual returned to the caller can fall back to the general
    baseline, so a correction is not silently discarded at a seasonal limit.
    """
    remaining = float(desired_effective_move)
    if abs(remaining) <= 1e-12:
        return 0.0

    active = {name: float(weight) for name, weight in weights.items() if weight > 1e-12}
    free = set(active)
    current = {name: float(getattr(model, f"{name}_bias_c")) for name in active}
    delta = {name: 0.0 for name in active}

    while free and abs(remaining) > 1e-12:
        denom = sum(active[name] ** 2 for name in free)
        if denom <= 1e-12:
            break

        saturated: list[str] = []
        proposals = {name: remaining * active[name] / denom for name in free}
        for name, proposal in proposals.items():
            before = current[name] + delta[name]
            candidate = before + proposal
            clipped = _clamp(candidate, -1.8, 1.8)
            if abs(clipped - candidate) > 1e-12:
                actual = clipped - before
                delta[name] += actual
                remaining -= active[name] * actual
                saturated.append(name)

        if saturated:
            free.difference_update(saturated)
            continue

        for name, proposal in proposals.items():
            delta[name] += proposal
        remaining = 0.0

    for name, change in delta.items():
        setattr(model, f"{name}_bias_c", current[name] + change)
    return remaining



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
    boundary_only: bool = False,
    boundary_attribute: str | None = None,
) -> bool:
    """Fold one rating into the compact profile and report real learning change."""
    if rating == FEEDBACK_NOT_USED or recommendation_used is False:
        return False
    if rating == FEEDBACK_PERFECT:
        error = 0.0
    elif rating == FEEDBACK_TOO_COLD:
        error = 1.0
    elif rating == FEEDBACK_TOO_WARM:
        error = -1.0
    else:
        return False

    # A paused model must remain mathematically frozen. Ratings can still be
    # accepted by the UI, but they must not advance learning counters or alter
    # future learning/feedback cadence.
    if not model.learning_enabled:
        return False

    # ``total_feedback`` is an interaction counter, not learning evidence.  Keep
    # it out of the change check so a deliberately non-learnable rating can be
    # recorded without consuming the previous meaningful undo point.
    before_learning = model.to_dict()
    before_learning.pop("total_feedback", None)
    before_learning.pop("feedback_opportunities", None)

    def _learned() -> bool:
        after = model.to_dict()
        after.pop("total_feedback", None)
        after.pop("feedback_opportunities", None)
        return after != before_learning

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
        return _learned()

    # There is no lighter class than "no jacket". A plain "too warm" rating
    # in that state can describe the weather/person, but it cannot identify a
    # correctable jacket decision and therefore must not drag the whole profile
    # colder. Transition-timing feedback avoids this branch by targeting the
    # actual boundary that was crossed.
    if jacket == JACKET_NONE and error < 0.0 and not boundary_only:
        return _learned()

    if boundary_only:
        explicit_targets = {
            "light_threshold_delta_c": model.light_stat,
            "warm_threshold_delta_c": model.warm_stat,
            "winter_threshold_delta_c": model.winter_stat,
        }
        explicit_stat = explicit_targets.get(boundary_attribute or "")
        if explicit_stat is not None:
            threshold_stats = [explicit_stat]
            explicit_target = (str(boundary_attribute), explicit_stat)
        else:
            threshold_stats = _threshold_stats_for_observation(model, jacket, error, effective_c)
            explicit_target = None
        previous_threshold_weights = {id(stat): stat.weight_sum for stat in threshold_stats}
        for stat in threshold_stats:
            stat.add(error, weight=weight)
        if error != 0.0:
            target = explicit_target or _threshold_target(model, jacket, error)
            if target is not None:
                attribute, stat = target
                previous = previous_threshold_weights.get(id(stat), max(0.0, stat.weight_sum - weight))
                threshold_step = _learning_step(previous) * 0.35 * weight
                setattr(
                    model,
                    attribute,
                    _clamp(float(getattr(model, attribute)) + error * threshold_step, -3.0, 4.0),
                )
        return _learned()

    if apply_general:
        previous_general_samples = model.general_stat.weight_sum
        season_weights = _season_weights(observed_at)
        season_share = _season_learning_share(model, observed_at)
        model.general_stat.add(error, weight=weight)
        for name, season_weight in season_weights.items():
            # One real experience contributes one unit of seasonal evidence in
            # total. During a 50/50 overlap each neighbouring anchor receives 0.5.
            _season_stat(model, name).add(error, weight=weight * season_weight)
        general_step = _learning_step(previous_general_samples)

        # Keep one fixed correction budget for this rating. Season learning does
        # not add a second correction on top: it only decides how much of the
        # same budget belongs to the year-round baseline versus the date-weighted
        # seasonal deviation.
        global_factor = 1.0 if model.general_stat.weight_sum <= 10.0 else 0.60
        total_move = error * general_step * global_factor * weight
        seasonal_move = total_move * season_share if season_weights else 0.0
        general_move = total_move - seasonal_move

        if season_weights and error != 0.0:
            # The helper normalizes the anchor deltas so the blended seasonal
            # change at this exact date equals ``seasonal_move``. If a seasonal
            # safety limit prevents that, keep the unused part in General rather
            # than silently dropping learning signal.
            general_move += _apply_weighted_seasonal_move(
                model, season_weights, seasonal_move
            )

        model.general_offset_c = _clamp(
            model.general_offset_c + general_move,
            -5.0,
            5.0,
        )
        if season_weights and error != 0.0:
            # Any component common to all four anchors is a general tendency.
            # Re-centering preserves every anchor's total and therefore also any
            # weighted transition blend because the weights sum to one.
            _recenter_seasonal_biases(model)

    # Boundary confidence should still grow during early learning. A perfect
    # rating is especially valuable here because it confirms that the current
    # jacket interval was sensible without forcing the threshold to move.
    threshold_stats = _threshold_stats_for_observation(model, jacket, error, effective_c)
    previous_threshold_weights = {id(stat): stat.weight_sum for stat in threshold_stats}
    for stat in threshold_stats:
        stat.add(error, weight=weight)

    if model.general_stat.weight_sum <= 10.0:
        return _learned()

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

    return _learned()


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
