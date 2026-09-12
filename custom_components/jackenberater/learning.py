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

    # Seasonal values are independent offsets from the personal year-round
    # baseline. They are never automatically re-centered. A shared component may
    # move into ``general_offset_c`` only through the explicit four-season
    # consensus pooling rule.
    seasonal_model_version: int = 4
    winter_bias_c: float = 0.0
    spring_bias_c: float = 0.0
    summer_bias_c: float = 0.0
    autumn_bias_c: float = 0.0

    # A season can be initialized before it has any own evidence: on its first
    # transition it inherits only the previous season's offset. The evidence and
    # learning history remain independent. Empty ``seeded_from`` means the season
    # started neutral rather than from another season.
    winter_season_initialized: bool = False
    spring_season_initialized: bool = False
    summer_season_initialized: bool = False
    autumn_season_initialized: bool = False
    winter_seeded_from: str = ""
    spring_seeded_from: str = ""
    summer_seeded_from: str = ""
    autumn_seeded_from: str = ""

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

    def prepare_seasons_for(self, when: datetime | None) -> bool:
        """Initialize/seed seasonal anchors for the supplied date if needed."""
        return _prepare_season_bootstrap(self, when)

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

    def _season_context_confidence(self, when: datetime | None) -> float:
        """Confidence contributed by the season anchors active at one instant.

        A freshly seeded season is a useful starting estimate, not confirmed
        personal evidence. Keep decision confidence below the hide threshold until
        the active season has accumulated some own feedback. During an overlap the
        two anchors contribute proportionally to their actual season weights.
        """
        weights = _season_weights(when)
        if not weights:
            return 1.0
        confidence = 0.0
        for name, season_weight in weights.items():
            evidence = _season_stat(self, name).weight_sum
            anchor_confidence = 0.45 + 0.50 * (1.0 - math.exp(-evidence / 2.5))
            confidence += season_weight * min(0.95, anchor_confidence)
        return max(0.0, min(0.95, confidence))

    def has_low_evidence_season_anchor(
        self,
        when: datetime | None,
        *,
        min_weight: float = 0.10,
        min_real_evidence: float = 1.0,
    ) -> bool:
        """Return whether a materially active season still lacks own evidence.

        A seeded season is only a starting estimate. Once it contributes at
        least ``min_weight`` to the recommendation, keep the card reachable
        until roughly one full equivalent real seasonal rating has confirmed
        it. Tiny transition tails intentionally do not prevent hiding.
        """
        for name, weight in _season_weights(when).items():
            if weight + 1e-12 < min_weight:
                continue
            if _season_stat(self, name).weight_sum + 1e-12 < min_real_evidence:
                return True
        return False

    def decision_confidence(
        self,
        jacket_now: str,
        jacket_later: str,
        *,
        observed_at: datetime | None = None,
        later_at: datetime | None = None,
    ) -> float:
        """Return conservative confidence for the recommendation being shown."""
        jacket_conf = min(
            self.jacket_confidence(jacket_now),
            self.jacket_confidence(jacket_later),
        )
        # During the first few ratings the global model is intentionally the main
        # learner. Afterwards the garment-boundary confidence also matters.
        if self.general_stat.weight_sum < 10.0:
            confidence = self.confidence()
        else:
            confidence = min(self.confidence(), jacket_conf)

        if observed_at is not None:
            confidence = min(confidence, self._season_context_confidence(observed_at))
        if later_at is not None:
            confidence = min(confidence, self._season_context_confidence(later_at))
        return confidence

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
        old_season_limit = 4.0 if model.seasonal_model_version >= 4 else 1.8
        model.winter_bias_c = _safe_number(raw.get("winter_bias_c"), 0.0, -old_season_limit, old_season_limit)
        model.spring_bias_c = _safe_number(raw.get("spring_bias_c"), 0.0, -old_season_limit, old_season_limit)
        model.summer_bias_c = _safe_number(raw.get("summer_bias_c"), 0.0, -old_season_limit, old_season_limit)
        model.autumn_bias_c = _safe_number(raw.get("autumn_bias_c"), 0.0, -old_season_limit, old_season_limit)
        for season in ("winter", "spring", "summer", "autumn"):
            setattr(
                model,
                f"{season}_season_initialized",
                _safe_bool(raw.get(f"{season}_season_initialized"), False),
            )
            seeded_from = raw.get(f"{season}_seeded_from", "")
            setattr(
                model,
                f"{season}_seeded_from",
                str(seeded_from) if seeded_from in {"winter", "spring", "summer", "autumn"} else "",
            )
        model.light_threshold_delta_c = _safe_number(raw.get("light_threshold_delta_c"), 0.0, -3.0, 4.0)
        model.warm_threshold_delta_c = _safe_number(raw.get("warm_threshold_delta_c"), 0.0, -3.0, 4.0)
        model.winter_threshold_delta_c = _safe_number(raw.get("winter_threshold_delta_c"), 0.0, -3.0, 4.0)
        # Older profiles could retain raw threshold values beyond a neighbour-
        # imposed effective cap. Collapse that hidden excess on load without
        # changing any effective jacket boundary or evidence. This makes the
        # v0.3.2 "no invisible threshold learning" rule apply immediately to
        # upgraded profiles as well as newly created ones.
        _canonicalize_threshold_deltas(model)

        for name in (
            "general_stat", "wind_stat", "transition_stat", "transient_stat",
            "winter_season_stat", "spring_season_stat", "summer_season_stat",
            "autumn_season_stat", "light_stat", "warm_stat", "winter_stat",
        ):
            setattr(model, name, _safe_stat(raw.get(name)))
        model.total_feedback = _safe_int(raw.get("total_feedback"), 0)
        model.feedback_opportunities = _safe_int(raw.get("feedback_opportunities"), 0)

        # Legacy v0.2 -> v0.3 normalization is kept as an intermediate migration
        # so very old stores first reach the exact representation v0.3 used.
        if model.seasonal_model_version < 2:
            _legacy_recenter_seasonal_biases(model)
        if model.seasonal_model_version < 3:
            model.seasonal_model_version = 3

        # v0.3.1 seasonal model v4: seasons become true independent offsets. Old
        # re-centering could leave synthetic values in seasons with zero own
        # evidence. Move their common synthetic component back into Main where
        # possible, neutralize the untrained anchors and preserve the effective
        # value of every season that actually had real evidence.
        if model.seasonal_model_version < 4:
            _migrate_seasonal_model_v4(model)

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


def _canonicalize_threshold_deltas(model: PersonalModel) -> None:
    """Remove raw threshold excess hidden behind neighbour spacing caps.

    The effective three thresholds are preserved exactly; only the persisted
    representation is normalized so future learning cannot count movement that
    was merely a collapse of previously hidden raw state.
    """
    light, warm, winter = _model_thresholds(model)
    model.light_threshold_delta_c = _clamp(
        light - BASE_LIGHT_THRESHOLD_C, -3.0, 4.0
    )
    model.warm_threshold_delta_c = _clamp(
        warm - BASE_WARM_THRESHOLD_C, -3.0, 4.0
    )
    model.winter_threshold_delta_c = _clamp(
        winter - BASE_WINTER_THRESHOLD_C, -3.0, 4.0
    )


def _threshold_delta_bounds(
    model: PersonalModel, attribute: str
) -> tuple[float, float]:
    """Return raw-delta bounds that preserve the 2.5 °C threshold spacing."""
    light, warm, winter = _model_thresholds(model)
    if attribute == "light_threshold_delta_c":
        low = max(-3.0, warm + 2.5 - BASE_LIGHT_THRESHOLD_C)
        high = 4.0
    elif attribute == "warm_threshold_delta_c":
        low = max(-3.0, winter + 2.5 - BASE_WARM_THRESHOLD_C)
        high = min(4.0, light - 2.5 - BASE_WARM_THRESHOLD_C)
    elif attribute == "winter_threshold_delta_c":
        low = -3.0
        high = min(4.0, warm - 2.5 - BASE_WINTER_THRESHOLD_C)
    else:
        return -3.0, 4.0
    if low > high:
        # Defensive fallback for a hand-edited/legacy model that is already
        # inconsistent. Freeze this boundary rather than accumulating invisible
        # learning behind a neighbour-imposed cap.
        current = float(getattr(model, attribute))
        return current, current
    return low, high


def _apply_threshold_move(
    model: PersonalModel,
    attribute: str,
    stat: RunningStat,
    *,
    error: float,
    weight: float,
) -> bool:
    """Move one stored threshold only when its effective boundary can move."""
    previous = stat.weight_sum
    threshold_step = _learning_step(previous) * 0.35 * weight
    before = float(getattr(model, attribute))
    before_effective = _model_thresholds(model)
    index = {
        "light_threshold_delta_c": 0,
        "warm_threshold_delta_c": 1,
        "winter_threshold_delta_c": 2,
    }.get(attribute)
    if index is None:
        return False
    low, high = _threshold_delta_bounds(model, attribute)
    after = _clamp(before + error * threshold_step, low, high)
    if abs(after - before) <= 1e-12:
        return False
    setattr(model, attribute, after)
    after_effective = _model_thresholds(model)
    if abs(after_effective[index] - before_effective[index]) <= 1e-12:
        # The raw value changed but the boundary actually used by the engine did
        # not. Revert and do not manufacture evidence/confidence for a masked
        # learning step.
        setattr(model, attribute, before)
        return False
    stat.add(error, weight=weight)
    return True


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


_SEASON_NAMES: tuple[str, str, str, str] = (
    "winter",
    "spring",
    "summer",
    "autumn",
)
_SEASON_LIMIT_C = 4.0
_SEASON_CONSENSUS_MIN_REAL_WEIGHT = 3.0
_SEASON_CONSENSUS_RESIDUAL_C = 0.2


def _season_bias_attributes() -> tuple[str, str, str, str]:
    return tuple(f"{name}_bias_c" for name in _SEASON_NAMES)


_SEASON_TRANSITION_HALF_DAYS = 15
_SEASON_TRANSITIONS: tuple[tuple[int, int, str, str], ...] = (
    (3, 1, "winter", "spring"),
    (6, 1, "spring", "summer"),
    (9, 1, "summer", "autumn"),
    (12, 1, "autumn", "winter"),
)
_SEASON_PREDECESSOR = {
    "winter": "autumn",
    "spring": "winter",
    "summer": "spring",
    "autumn": "summer",
}


def _smoothstep(value: float) -> float:
    """Cubic 0..1 blend with zero slope at both ends."""
    value = _clamp(value, 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)


def _season_transition_for(when: datetime | None) -> tuple[str, str] | None:
    """Return the neighbouring anchors for an active 30-day transition."""
    if not isinstance(when, datetime):
        return None
    current = when.date()
    half = timedelta(days=_SEASON_TRANSITION_HALF_DAYS)
    for year in (current.year - 1, current.year, current.year + 1):
        for month, day, previous_name, next_name in _SEASON_TRANSITIONS:
            boundary = date(year, month, day)
            if boundary - half <= current < boundary + half:
                return previous_name, next_name
    return None


def _season_weights(when: datetime | None) -> dict[str, float]:
    """Return one or two season-anchor weights that always sum to one.

    Each meteorological boundary is surrounded by one month of smooth overlap:
    15 calendar days before the boundary through 14 days after it (30 active
    dates total). Outside these windows exactly one season anchor is active. No
    transition value is stored or learned.
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
            if not (start <= current < end):
                continue
            # ``date`` values are discrete. Mapping the inclusive first active
            # day directly to 0 would technically expose only one anchor there
            # and leave 29 genuinely mixed dates. Keep the meteorological
            # boundary exactly 50/50 while placing the mathematical 0/1 endpoints
            # half a day beyond the active date range; all 30 active calendar
            # dates then contain both neighbouring anchors.
            day_offset = (current - boundary).days
            progress = 0.5 + day_offset / float(2 * (_SEASON_TRANSITION_HALF_DAYS + 1))
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


def _season_initialized(model: PersonalModel, name: str) -> bool:
    return bool(getattr(model, f"{name}_season_initialized", False))


def _initialize_season(
    model: PersonalModel,
    name: str,
    *,
    offset_c: float = 0.0,
    seeded_from: str = "",
) -> bool:
    """Initialize one season without copying any evidence or history."""
    if _season_initialized(model, name):
        return False
    setattr(model, f"{name}_bias_c", _clamp(float(offset_c), -_SEASON_LIMIT_C, _SEASON_LIMIT_C))
    setattr(model, f"{name}_season_initialized", True)
    setattr(model, f"{name}_seeded_from", seeded_from if seeded_from in _SEASON_NAMES else "")
    return True


def _prepare_season_bootstrap(model: PersonalModel, when: datetime | None) -> bool:
    """Initialize/seed seasonal anchors for the current point in the year.

    The very first encountered meteorological season starts neutral. During the
    first transition into a new season, the next anchor copies only the previous
    season's offset. If the whole transition window was missed, the same one-time
    seed is caught up on the first later access while that season is current.

    A skipped *chain* is never fabricated: if the direct predecessor itself was
    never initialized, the current season starts neutral instead of recursively
    creating unseen seasons. Statistics and evidence are never copied. Once a
    season is initialized it is never seeded again in later years.
    """
    if not isinstance(when, datetime) or not model.setup_complete:
        return False

    changed = False
    current_name = _season_name(when)
    if not any(_season_initialized(model, name) for name in _SEASON_NAMES):
        changed |= _initialize_season(model, current_name)

    # Catch up a completely missed transition. This runs on ordinary model
    # access, so recommendations and any later feedback snapshot already see the
    # legitimate first-season seed. Only the direct predecessor may seed the
    # current season. If that predecessor was also never encountered, do not
    # synthesize an unseen historical chain; start this current season neutral.
    if not _season_initialized(model, current_name):
        previous_name = _SEASON_PREDECESSOR[current_name]
        if _season_initialized(model, previous_name):
            changed |= _initialize_season(
                model,
                current_name,
                offset_c=float(getattr(model, f"{previous_name}_bias_c")),
                seeded_from=previous_name,
            )
        else:
            changed |= _initialize_season(model, current_name)

    # Do this after current-season catch-up: a user may return for the first time
    # late enough that the *next* transition is already active (for example first
    # winter access on 20 February). In that case the current season is first
    # legitimately restored from its predecessor, then the active next season may
    # seed from the now-known current anchor. No unseen past season is fabricated.
    transition = _season_transition_for(when)
    if transition is not None:
        previous_name, next_name = transition
        if _season_initialized(model, previous_name) and not _season_initialized(model, next_name):
            changed |= _initialize_season(
                model,
                next_name,
                offset_c=float(getattr(model, f"{previous_name}_bias_c")),
                seeded_from=previous_name,
            )

    return changed


def _ensure_active_seasons_for_learning(
    model: PersonalModel,
    when: datetime | None,
    weights: dict[str, float],
) -> None:
    """Ensure every season receiving real feedback has its own initialized state."""
    _prepare_season_bootstrap(model, when)
    for name in weights:
        if not _season_initialized(model, name):
            _initialize_season(model, name)


def _legacy_recenter_seasonal_biases(model: PersonalModel) -> None:
    """Reproduce the old v0.3 migration before converting that state to v4."""
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


def _migrate_seasonal_model_v4(model: PersonalModel) -> None:
    """Convert the centered v0.3 season representation to independent offsets.

    A v0.3 season with zero own ``weight_sum`` has no real season evidence even
    if re-centering gave it a numeric bias. The mean of those untrained values is
    treated as synthetic common shift and moved into Main where the existing
    Main safety bound permits it. Every trained season is counter-shifted by the
    same amount, so its historic effective value ``main + season`` is preserved
    exactly. Untrained seasons become neutral and uninitialized.
    """
    trained = {
        name: _season_stat(model, name).weight_sum > 1e-12
        for name in _SEASON_NAMES
    }
    untrained = [name for name in _SEASON_NAMES if not trained[name]]

    if untrained:
        synthetic_shift = sum(
            float(getattr(model, f"{name}_bias_c")) for name in untrained
        ) / len(untrained)
        shift = _clamp(synthetic_shift, -5.0 - model.general_offset_c, 5.0 - model.general_offset_c)
        if abs(shift) > 1e-12:
            model.general_offset_c += shift
            for name in _SEASON_NAMES:
                if trained[name]:
                    setattr(
                        model,
                        f"{name}_bias_c",
                        _clamp(
                            float(getattr(model, f"{name}_bias_c")) - shift,
                            -_SEASON_LIMIT_C,
                            _SEASON_LIMIT_C,
                        ),
                    )
        for name in untrained:
            setattr(model, f"{name}_bias_c", 0.0)

    for name in _SEASON_NAMES:
        setattr(model, f"{name}_season_initialized", bool(trained[name]))
        setattr(model, f"{name}_seeded_from", "")
        setattr(
            model,
            f"{name}_bias_c",
            _clamp(float(getattr(model, f"{name}_bias_c")), -_SEASON_LIMIT_C, _SEASON_LIMIT_C),
        )
    model.seasonal_model_version = 4


def _season_learning_step(model: PersonalModel, name: str) -> float:
    """Season-specific learning rate derived only from that season's real evidence."""
    return _learning_step(max(0.0, _season_stat(model, name).weight_sum))


def _apply_weighted_seasonal_learning_move(
    model: PersonalModel,
    weights: dict[str, float],
    error: float,
    *,
    feedback_weight: float,
    previous_evidence: dict[str, float],
) -> float:
    """Apply a normalized overlap move using each season's own learning rate.

    For equal learning rates the primary update is exactly
    ``delta_i = delta * w_i / sum(w_j^2)``. Thus a 50/50 overlap changes the
    blended effective seasonal value by a full learning step, not half a step.
    Different real evidence changes each anchor's own base step. If clipping at
    ±4 C removes part of the intended effective move, the residual is
    redistributed among the still-free active anchors. Residual that cannot be
    represented by the seasons is deliberately dropped; it never leaks into Main.
    """
    active = {
        name: float(weight)
        for name, weight in weights.items()
        if name in _SEASON_NAMES and weight > 1e-12
    }
    if not active or abs(error) <= 1e-12:
        return 0.0

    denom = sum(weight * weight for weight in active.values())
    if denom <= 1e-12:
        return 0.0

    current = {name: float(getattr(model, f"{name}_bias_c")) for name in active}
    deltas: dict[str, float] = {}
    target_effective = 0.0
    actual_effective = 0.0
    for name, season_weight in active.items():
        step = _learning_step(max(0.0, previous_evidence.get(name, 0.0)))
        proposed = error * feedback_weight * step * season_weight / denom
        target_effective += season_weight * proposed
        candidate = _clamp(current[name] + proposed, -_SEASON_LIMIT_C, _SEASON_LIMIT_C)
        actual = candidate - current[name]
        deltas[name] = actual
        actual_effective += season_weight * actual

    residual = target_effective - actual_effective
    free = {
        name for name in active
        if -_SEASON_LIMIT_C + 1e-12 < current[name] + deltas[name] < _SEASON_LIMIT_C - 1e-12
    }
    while free and abs(residual) > 1e-12:
        free_denom = sum(active[name] ** 2 for name in free)
        if free_denom <= 1e-12:
            break
        saturated: list[str] = []
        proposals = {name: residual * active[name] / free_denom for name in free}
        for name, proposal in proposals.items():
            before = current[name] + deltas[name]
            candidate = _clamp(before + proposal, -_SEASON_LIMIT_C, _SEASON_LIMIT_C)
            actual = candidate - before
            deltas[name] += actual
            residual -= active[name] * actual
            if abs(actual - proposal) > 1e-12:
                saturated.append(name)
        if not saturated:
            break
        free.difference_update(saturated)

    for name, change in deltas.items():
        setattr(model, f"{name}_bias_c", current[name] + change)
    return residual


def _pool_season_consensus(model: PersonalModel) -> float:
    """Move a confirmed common four-season component losslessly into Main."""
    if any(
        _season_stat(model, name).weight_sum + 1e-12 < _SEASON_CONSENSUS_MIN_REAL_WEIGHT
        for name in _SEASON_NAMES
    ):
        return 0.0

    values = [float(getattr(model, f"{name}_bias_c")) for name in _SEASON_NAMES]
    if all(value > 0.0 for value in values):
        direction = 1.0
    elif all(value < 0.0 for value in values):
        direction = -1.0
    else:
        return 0.0

    common_abs = min(abs(value) for value in values)
    transfer_abs = max(0.0, common_abs - _SEASON_CONSENSUS_RESIDUAL_C)
    if transfer_abs <= 1e-12:
        return 0.0

    if direction > 0:
        transfer_abs = min(transfer_abs, max(0.0, 5.0 - model.general_offset_c))
    else:
        transfer_abs = min(transfer_abs, max(0.0, model.general_offset_c + 5.0))
    if transfer_abs <= 1e-12:
        return 0.0

    transfer = direction * transfer_abs
    model.general_offset_c += transfer
    for name in _SEASON_NAMES:
        setattr(model, f"{name}_bias_c", float(getattr(model, f"{name}_bias_c")) - transfer)
    return transfer


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
        explicit_target = (str(boundary_attribute), explicit_stat) if explicit_stat is not None else None
        if error == 0.0:
            stats = (
                [explicit_stat]
                if explicit_stat is not None
                else _threshold_stats_for_observation(model, jacket, error, effective_c)
            )
            for stat in stats:
                stat.add(error, weight=weight)
        else:
            target = explicit_target or _threshold_target(model, jacket, error)
            if target is not None:
                attribute, stat = target
                _apply_threshold_move(
                    model, attribute, stat, error=error, weight=weight
                )
        return _learned()

    if apply_general:
        season_weights = _season_weights(observed_at)

        # ``general_stat`` remains global evidence for confidence/cadence, but
        # normal thermal feedback no longer moves ``general_offset_c`` directly.
        # After setup, temperature correction belongs to the active season(s).
        model.general_stat.add(error, weight=weight)

        if season_weights:
            _ensure_active_seasons_for_learning(model, observed_at, season_weights)
            previous_evidence = {
                name: _season_stat(model, name).weight_sum
                for name in season_weights
            }
            for name, season_weight in season_weights.items():
                # One real rating contributes exactly one weighted unit in total
                # across an overlap. Seeded values never contribute evidence.
                _season_stat(model, name).add(
                    error, weight=weight * season_weight
                )

            if error != 0.0:
                _apply_weighted_seasonal_learning_move(
                    model,
                    season_weights,
                    error,
                    feedback_weight=weight,
                    previous_evidence=previous_evidence,
                )

            # Main can change only through a confirmed common component shared by
            # all four independently evidenced seasons. The transfer preserves
            # ``main + season`` for every anchor exactly.
            _pool_season_consensus(model)

    # During bootstrap the garment boundaries intentionally collect evidence
    # before they start moving. Once the mature threshold learner is active, a
    # non-perfect rating only counts as boundary evidence if the real boundary
    # can actually move; this prevents confidence from increasing behind a
    # neighbour-imposed 2.5 °C spacing cap.
    threshold_stats = _threshold_stats_for_observation(model, jacket, error, effective_c)
    if model.general_stat.weight_sum <= 10.0:
        for stat in threshold_stats:
            stat.add(error, weight=weight)
        return _learned()

    if error == 0.0:
        for stat in threshold_stats:
            stat.add(error, weight=weight)

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
            _apply_threshold_move(
                model, attribute, stat, error=error, weight=weight
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
