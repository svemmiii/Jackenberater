"""Persistent compact per-Home-Assistant-user profiles and feedback sessions."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import logging
from typing import Any
import uuid

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    FEEDBACK_MIN_DELAY,
    FEEDBACK_NOT_USED,
    FEEDBACK_PERFECT,
    FEEDBACK_TOO_COLD,
    FEEDBACK_TOO_WARM,
    FEEDBACK_VALUES,
    MAX_OPEN_FEEDBACK,
    MAX_RECENT_SESSIONS,
    JACKET_NONE,
    JACKET_RANK,
    PHASE_ALL,
    PHASE_LATER,
    PHASE_START,
    PHASE_VALUES,
    SESSION_EXPIRY,
    SIGNAL_PROFILE_CREATED,
    SIGNAL_PROFILE_DELETED,
    SIGNAL_PROFILE_UPDATED,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
)
from .learning import PersonalModel, apply_feedback, should_request_feedback
from .models import Recommendation
from .time_utils import (
    elapsed,
    instant_key,
    is_at_or_after,
    is_before,
    real_add,
)

_LOGGER = logging.getLogger(__name__)


# Feedback undo must only touch state that one rating can actually train.
# User/configuration state and session/cadence counters deliberately stay current.
_FEEDBACK_UNDO_FIELDS = (
    "general_offset_c",
    "wind_bias_c",
    "transition_bias_c",
    "transient_tolerance",
    "winter_bias_c",
    "spring_bias_c",
    "summer_bias_c",
    "autumn_bias_c",
    "light_threshold_delta_c",
    "warm_threshold_delta_c",
    "winter_threshold_delta_c",
    "general_stat",
    "wind_stat",
    "transition_stat",
    "transient_stat",
    "winter_season_stat",
    "spring_season_stat",
    "summer_season_stat",
    "autumn_season_stat",
    "light_stat",
    "warm_stat",
    "winter_stat",
)


def _feedback_learning_snapshot(model: PersonalModel) -> dict[str, Any]:
    """Return only fields a feedback rating is allowed to train."""
    raw = model.to_dict()
    return {name: deepcopy(raw[name]) for name in _FEEDBACK_UNDO_FIELDS}


def _normalize_feedback_learning_snapshot(raw: Any) -> dict[str, Any] | None:
    """Normalize legacy full-model undo snapshots to the compact v0.3 format.

    v0.2.x stored ``PersonalModel.to_dict()`` as ``learning_before``.  Running
    that full snapshot through ``PersonalModel.from_dict`` applies every current
    storage migration (notably the v0.3 seasonal re-centering) before we select
    the feedback-only undo fields.  Current compact snapshots deliberately lack
    model/configuration markers and are only filtered defensively.
    """
    if not isinstance(raw, dict):
        return None

    legacy_full_markers = (
        "setup_complete",
        "learning_enabled",
        "cold_answer",
        "warm_answer",
        "wind_answer",
        "evening_answer",
        "seasonal_model_version",
        "total_feedback",
        "feedback_opportunities",
    )
    if any(name in raw for name in legacy_full_markers):
        return _feedback_learning_snapshot(PersonalModel.from_dict(raw))

    return {
        name: deepcopy(raw[name])
        for name in _FEEDBACK_UNDO_FIELDS
        if name in raw
    }


class ProfileManager:
    """Own all compact user learning state for one config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.store = Store[dict[str, Any]](
            hass,
            STORAGE_VERSION,
            f"{STORAGE_KEY_PREFIX}.{entry.entry_id}",
        )
        self._profiles: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        raw = await self.store.async_load()
        if isinstance(raw, dict) and isinstance(raw.get("profiles"), dict):
            self._profiles = raw["profiles"]
        before_cleanup = deepcopy(self._profiles)
        self._cleanup_all()
        # Persist normalization/expiry cleanup once, but avoid an unnecessary
        # write on every Home Assistant restart when storage was already clean.
        if self._profiles != before_cleanup:
            self._schedule_save()

    @property
    def profile_ids(self) -> list[str]:
        return list(self._profiles)

    def profile_name(self, profile_id: str) -> str:
        raw = self._profiles.get(profile_id, {})
        return str(raw.get("name") or "Home-Assistant-Nutzer")

    def get_model(self, profile_id: str) -> PersonalModel:
        raw = self._profiles.get(profile_id)
        if not isinstance(raw, dict):
            return PersonalModel()
        return PersonalModel.from_dict(raw.get("model"))

    def get_profile_summary(self, profile_id: str) -> dict[str, Any]:
        raw = self._profiles.get(profile_id, {})
        model = self.get_model(profile_id)
        return {
            "id": profile_id,
            "name": str(raw.get("name") or "Home-Assistant-Nutzer"),
            "setup_complete": model.setup_complete,
            "learning_enabled": model.learning_enabled,
            "total_feedback": model.total_feedback,
            "confidence": round(model.confidence(), 3),
            "learning_progress": round(model.learning_progress(), 3),
        }

    def summaries(self) -> list[dict[str, Any]]:
        return [self.get_profile_summary(pid) for pid in self.profile_ids]

    def sync_user_directory(self, users: list[Any]) -> bool:
        """Prune deleted HA users and refresh stored display names."""
        directory = {str(user.id): str(user.name or user.id) for user in users}
        changed = False
        for profile_id in list(self._profiles):
            if profile_id not in directory:
                del self._profiles[profile_id]
                changed = True
                async_dispatcher_send(
                    self.hass,
                    SIGNAL_PROFILE_DELETED.format(entry_id=self.entry.entry_id),
                    profile_id,
                )
                continue
            if self._profiles[profile_id].get("name") != directory[profile_id]:
                self._profiles[profile_id]["name"] = directory[profile_id]
                changed = True
                self._updated(profile_id)
        if changed:
            self._schedule_save()
        return changed

    async def async_ensure_profile(self, profile_id: str, name: str) -> PersonalModel:
        created = profile_id not in self._profiles
        changed = created
        if created:
            self._profiles[profile_id] = {
                "name": name or "Home-Assistant-Nutzer",
                "model": PersonalModel().to_dict(),
                "sessions": [],
            }
        else:
            wanted_name = name or self.profile_name(profile_id)
            if self._profiles[profile_id].get("name") != wanted_name:
                self._profiles[profile_id]["name"] = wanted_name
                changed = True
        if changed:
            self._schedule_save()
        if created:
            async_dispatcher_send(
                self.hass,
                SIGNAL_PROFILE_CREATED.format(entry_id=self.entry.entry_id),
                profile_id,
            )
        elif changed:
            # Existing entities listen for profile updates so a later Home
            # Assistant user rename can refresh their translated display name.
            self._updated(profile_id)
        return self.get_model(profile_id)

    async def async_setup_profile(
        self,
        profile_id: str,
        *,
        cold: int,
        warm: int,
        wind: int,
        evening: int,
    ) -> PersonalModel:
        raw = self._profiles[profile_id]
        old = self.get_model(profile_id)
        fresh = PersonalModel.from_answers(cold, warm, wind, evening)
        fresh.learning_enabled = old.learning_enabled
        raw["model"] = fresh.to_dict()
        # A full setup replaces the personal model.  Feedback sessions contain
        # recommendation/weather/learning context from the previous model and
        # must not be answerable or undoable against the newly initialized one.
        raw["sessions"] = []
        self._schedule_save()
        self._updated(profile_id)
        return fresh

    async def async_set_learning(self, profile_id: str, enabled: bool) -> None:
        model = self.get_model(profile_id)
        model.learning_enabled = bool(enabled)
        self._profiles[profile_id]["model"] = model.to_dict()
        self._schedule_save()
        self._updated(profile_id)

    async def async_reset_learning(self, profile_id: str) -> None:
        model = self.get_model(profile_id)
        model.reset_to_answers()
        self._profiles[profile_id]["model"] = model.to_dict()
        self._profiles[profile_id]["sessions"] = []
        self._schedule_save()
        self._updated(profile_id)

    def export_profile(self, profile_id: str) -> dict[str, Any]:
        """Return a compact, versioned learning backup without weather history."""
        if profile_id not in self._profiles:
            raise KeyError("profile not found")
        return {
            "format": "jackenberater-profile",
            "version": 1,
            "exported_at": dt_util.now().isoformat(),
            "name": self.profile_name(profile_id),
            "model": self.get_model(profile_id).to_dict(),
        }

    async def async_import_profile(
        self, profile_id: str, payload: dict[str, Any]
    ) -> PersonalModel:
        """Restore compact learning state and discard stale feedback sessions."""
        if profile_id not in self._profiles:
            raise KeyError("profile not found")
        if not isinstance(payload, dict) or payload.get("format") != "jackenberater-profile":
            raise ValueError("invalid profile backup")
        try:
            version = int(payload.get("version", 0))
        except (TypeError, ValueError):
            version = 0
        if version != 1 or not isinstance(payload.get("model"), dict):
            raise ValueError("unsupported profile backup")
        model = PersonalModel.from_dict(payload["model"])
        self._profiles[profile_id]["model"] = model.to_dict()
        self._profiles[profile_id]["sessions"] = []
        self._schedule_save()
        self._updated(profile_id)
        return model

    async def async_open_session(
        self,
        profile_id: str,
        recommendation: Recommendation,
        *,
        weather_context: dict[str, Any],
        learning_contexts: dict[str, dict[str, Any]],
        opened_by_user_id: str = "",
    ) -> dict[str, Any]:
        now = dt_util.now()
        raw = self._profiles[profile_id]
        self._cleanup_profile(profile_id, now)
        # Cleanup replaces the stored list, so reacquire it afterwards.
        sessions = self._sessions(profile_id)

        # Reuse a very recent identical deliberate lookup instead of creating
        # duplicate training candidates from repeated taps.
        for session in reversed(sessions):
            created = _parse_dt(session.get("created_at"))
            if created is None:
                continue
            age_seconds = elapsed(created, now).total_seconds()
            if age_seconds < 0:
                continue
            if age_seconds > 600:
                break
            if (
                session.get("feedback") is None
                and _session_context_matches(
                    session, recommendation, weather_context, learning_contexts
                )
            ):
                return _public_session(session)

        model = self.get_model(profile_id)
        near_threshold = "near_threshold" in recommendation.reasons
        class_change = recommendation.jacket_now != recommendation.jacket_later
        unusual_weather = any(
            key in recommendation.reasons
            for key in ("wind", "wet", "work_location", "uncertain_conditions")
        )
        if model.learning_enabled:
            model.feedback_opportunities += 1
        requested = should_request_feedback(
            model,
            near_threshold=near_threshold,
            class_change=class_change,
            unusual_weather=unusual_weather,
            decision_confidence=model.decision_confidence(
                recommendation.jacket_now, recommendation.jacket_later
            ),
            opportunity_count=model.feedback_opportunities,
        )
        raw["model"] = model.to_dict()

        ready_at = real_add(now, FEEDBACK_MIN_DELAY)
        if (
            recommendation.later_at is not None
            and recommendation.jacket_later != recommendation.jacket_now
        ):
            ready_at = max(
                (
                    ready_at,
                    real_add(recommendation.later_at, FEEDBACK_MIN_DELAY),
                ),
                key=instant_key,
            )
        expires_at = real_add(now, SESSION_EXPIRY)
        session = {
            "id": uuid.uuid4().hex[:12],
            "created_at": now.isoformat(),
            "ready_at": ready_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "request_feedback": requested,
            "recommendation": recommendation.as_dict(),
            "weather": weather_context,
            "learning_contexts": learning_contexts,
            "feedback": None,
            "learning_before": None,
            "opened_by_user_id": opened_by_user_id,
        }
        sessions.append(session)
        self._cap_sessions(profile_id)
        self._schedule_save()
        return _public_session(session)

    def feedback_candidates(
        self, profile_id: str, *, opened_by_user_id: str | None = None
    ) -> list[dict[str, Any]]:
        now = dt_util.now()
        self._cleanup_profile(profile_id, now)
        candidates: list[dict[str, Any]] = []
        for session in reversed(self._sessions(profile_id)):
            if (
                opened_by_user_id is not None
                and session.get("opened_by_user_id") != opened_by_user_id
            ):
                continue
            if session.get("feedback") is not None or not session.get("request_feedback"):
                continue
            ready = _parse_dt(session.get("ready_at"))
            expires = _parse_dt(session.get("expires_at"))
            if (
                ready
                and expires
                and is_at_or_after(now, ready)
                and is_before(now, expires)
            ):
                candidates.append(_public_session(session))
            if len(candidates) >= MAX_OPEN_FEEDBACK:
                break
        return candidates

    def is_feedback_candidate(
        self,
        profile_id: str,
        session_id: str,
        *,
        opened_by_user_id: str | None = None,
    ) -> bool:
        """Verify that a mature feedback session is currently due for a profile.

        ``opened_by_user_id`` remains available for callers that deliberately need
        device/login scoping, but shared-profile feedback normally validates the
        selected profile itself so a wall tablet can answer a session opened on a
        phone.
        """
        return any(
            candidate.get("id") == session_id
            for candidate in self.feedback_candidates(
                profile_id, opened_by_user_id=opened_by_user_id
            )
        )

    async def async_feedback(
        self,
        profile_id: str,
        session_id: str,
        *,
        rating: str,
        phase: str | None,
        recommendation_used: bool | None,
        unusual_day: bool,
        voluntary: bool,
    ) -> dict[str, Any]:
        if rating not in FEEDBACK_VALUES:
            raise ValueError("invalid feedback")
        if phase is not None and phase not in PHASE_VALUES:
            raise ValueError("invalid feedback phase")
        session = self._find_session(profile_id, session_id)
        if session is None:
            raise KeyError("session not found")
        if session.get("feedback") is not None:
            raise ValueError("feedback already submitted")
        now = dt_util.now()
        expires = _parse_dt(session.get("expires_at"))
        if expires is not None and is_at_or_after(now, expires):
            raise ValueError("feedback expired")
        if not voluntary:
            ready = _parse_dt(session.get("ready_at"))
            if not session.get("request_feedback") or ready is None or is_before(now, ready):
                raise ValueError("feedback_not_ready")

        model = self.get_model(profile_id)
        recommendation = session.get("recommendation", {})
        # “Perfect” on a recommendation that deliberately changed jacket class is
        # confirmation of the whole recommendation. Do not ask an extra question;
        # use the existing PHASE_ALL path so both relevant boundaries are learned.
        class_change = recommendation.get("jacket_now") != recommendation.get("jacket_later")
        if rating == FEEDBACK_PERFECT and phase is None and class_change:
            phase = PHASE_ALL
        elif rating in {FEEDBACK_TOO_COLD, FEEDBACK_TOO_WARM} and phase is None and class_change:
            # A changing recommendation is ambiguous without the small follow-up
            # question. Refuse to guess which part of the day the user meant.
            raise ValueError("feedback_phase_required")

        # Take the candidate snapshot before learning, but only make it the new
        # undo point after ``apply_feedback`` confirms that learning state really
        # changed. This keeps learnability defined in one place and covers
        # transient/boundary paths without duplicating their rules here.
        learning_before = _feedback_learning_snapshot(model)
        learned_any = False
        session["learning_before"] = None
        contexts = session.get("learning_contexts", {})
        start_context = contexts.get("start") if isinstance(contexts, dict) else None
        later_context = contexts.get("later") if isinstance(contexts, dict) else None
        if not isinstance(start_context, dict):
            # Storage migration/fallback for sessions created by the first
            # v0.1.0 build.
            weather = session.get("weather", {})
            start_context = {
                "jacket": recommendation.get("jacket_now"),
                "wind_kmh": weather.get("wind_kmh") if isinstance(weather, dict) else None,
                "transition_penalty_c": recommendation.get("transition_penalty_c"),
            }
        if not isinstance(later_context, dict):
            later_context = {
                "jacket": recommendation.get("jacket_later"),
                "wind_kmh": None,
                "transition_penalty_c": 0.0,
            }

        def _learn_context(
            target: dict[str, Any],
            *,
            count_feedback: bool,
            apply_general: bool,
            target_phase: str | None,
            boundary_only: bool = False,
            boundary_attribute: str | None = None,
        ) -> None:
            nonlocal learned_any
            learned_here = apply_feedback(
                model,
                rating=rating,
                jacket=str(target.get("jacket") or recommendation.get("jacket_now") or "none"),
                wind_kmh=_safe_float(target.get("wind_kmh")),
                wind_penalty_c=_safe_float(target.get("wind_penalty_c")),
                transition_penalty_c=_safe_float(target.get("transition_penalty_c")) or 0.0,
                effective_c=_safe_float(target.get("effective_c")),
                phase=target_phase,
                recommendation_used=recommendation_used,
                unusual_day=bool(unusual_day),
                voluntary=bool(voluntary),
                count_feedback=count_feedback,
                apply_general=apply_general,
                observed_at=_parse_dt(target.get("observed_at")),
                transient_override=bool(target.get("transient_override")),
                transient_direction=(
                    str(target.get("transient_direction"))
                    if target.get("transient_direction") in {"warming", "cooling"}
                    else None
                ),
                boundary_only=boundary_only,
                boundary_attribute=boundary_attribute,
            )
            learned_any = learned_any or learned_here

        if phase == PHASE_ALL and isinstance(later_context, dict):
            # "Throughout" carries one global signal, but can inform the
            # start-specific transition/boundary and the later weather/boundary.
            _learn_context(start_context, count_feedback=True, apply_general=True, target_phase=PHASE_START)
            if later_context != start_context:
                _learn_context(later_context, count_feedback=False, apply_general=False, target_phase=PHASE_LATER)
        elif phase == PHASE_LATER and class_change:
            # The UI deliberately phrases the later choice as a timing problem
            # ("I should have switched earlier/later"). That is direct evidence
            # about the crossed jacket boundary, not about the user's whole-year
            # body warmth or the current season. Use the weather at the predicted
            # transition, but choose the side of the boundary that maps the rating
            # onto exactly that transition.
            now_jacket = str(recommendation.get("jacket_now") or "none")
            later_jacket = str(recommendation.get("jacket_later") or "none")
            now_rank = JACKET_RANK.get(now_jacket, 0)
            later_rank = JACKET_RANK.get(later_jacket, 0)
            if rating == FEEDBACK_TOO_COLD:
                boundary_jacket = now_jacket if later_rank > now_rank else later_jacket
            else:  # FEEDBACK_TOO_WARM
                boundary_jacket = later_jacket if later_rank > now_rank else now_jacket
            # If the forecast jumps over more than one jacket class, target the
            # actual boundary that controls entry into the later class rather than
            # whichever adjacent boundary the synthetic jacket/rating pair happens
            # to imply.
            boundary_rank = later_rank if later_rank > now_rank else later_rank + 1
            boundary_attribute = {
                1: "light_threshold_delta_c",
                2: "warm_threshold_delta_c",
                3: "winter_threshold_delta_c",
            }.get(boundary_rank)
            transition_target = dict(later_context)
            transition_target["jacket"] = boundary_jacket
            _learn_context(
                transition_target,
                count_feedback=True,
                apply_general=False,
                target_phase=PHASE_LATER,
                boundary_only=True,
                boundary_attribute=boundary_attribute,
            )
        else:
            target = later_context if phase == PHASE_LATER else start_context
            _learn_context(target, count_feedback=True, apply_general=True, target_phase=phase)

        if learned_any:
            for old_session in self._sessions(profile_id):
                old_session["learning_before"] = None
            session["learning_before"] = learning_before

        self._profiles[profile_id]["model"] = model.to_dict()
        session["feedback"] = {
            "rating": rating,
            "phase": phase,
            "recommendation_used": recommendation_used,
            "unusual_day": bool(unusual_day),
            "voluntary": bool(voluntary),
            "at": dt_util.now().isoformat(),
            "undone": False,
        }
        self._schedule_save()
        self._updated(profile_id)
        return _public_session(session)

    async def async_undo_last_feedback(self, profile_id: str) -> bool:
        for session in reversed(self._sessions(profile_id)):
            feedback = session.get("feedback")
            before = _normalize_feedback_learning_snapshot(
                session.get("learning_before")
            )
            if not isinstance(feedback, dict) or feedback.get("undone"):
                continue
            if not isinstance(before, dict):
                continue
            # Restore only the learning fields affected by that rating.  The
            # snapshot may come from an older build and therefore contain the
            # complete model; selecting the explicit allow-list keeps legacy
            # sessions safe too.  Independent state changed after the rating
            # (learning pause, setup/config values, feedback opportunities, ...)
            # must remain exactly as it is now.
            current = self.get_model(profile_id)
            restored = current.to_dict()
            for name in _FEEDBACK_UNDO_FIELDS:
                if name in before:
                    restored[name] = deepcopy(before[name])
            current = PersonalModel.from_dict(restored)

            # One meaningful feedback interaction is being undone.  Use the
            # current counter instead of the historic snapshot so later no-op
            # feedback remains counted.  Feedback opportunities are deliberately
            # untouched because those sessions really happened.
            current.total_feedback = max(0, current.total_feedback - 1)
            self._profiles[profile_id]["model"] = current.to_dict()
            feedback["undone"] = True
            self._schedule_save()
            self._updated(profile_id)
            return True
        return False

    def latest_session(self, profile_id: str) -> dict[str, Any] | None:
        sessions = self._sessions(profile_id)
        return _public_session(sessions[-1]) if sessions else None

    def _sessions(self, profile_id: str) -> list[dict[str, Any]]:
        raw = self._profiles[profile_id]
        sessions = raw.setdefault("sessions", [])
        if not isinstance(sessions, list):
            raw["sessions"] = sessions = []
        return sessions

    def _find_session(self, profile_id: str, session_id: str) -> dict[str, Any] | None:
        for session in self._sessions(profile_id):
            if session.get("id") == session_id:
                return session
        return None

    def _cleanup_all(self) -> None:
        now = dt_util.now()
        for profile_id in list(self._profiles):
            raw = self._profiles.get(profile_id)
            if not isinstance(raw, dict):
                self._profiles.pop(profile_id, None)
                continue
            raw.setdefault("name", "Home-Assistant-Nutzer")
            raw["model"] = PersonalModel.from_dict(raw.get("model")).to_dict()
            raw.setdefault("sessions", [])

            # Migrate v0.2.x full-model undo snapshots at load time as well.
            # This leaves the persistent store in the current compact format and
            # prevents a later undo from reintroducing pre-v0.3 seasonal anchors.
            for session in self._sessions(profile_id):
                before = session.get("learning_before")
                normalized = _normalize_feedback_learning_snapshot(before)
                if normalized is not None and normalized != before:
                    session["learning_before"] = normalized

            self._cleanup_profile(profile_id, now)

    def _cleanup_profile(self, profile_id: str, now: datetime) -> None:
        sessions = self._sessions(profile_id)
        kept: list[dict[str, Any]] = []
        for session in sessions:
            expires = _parse_dt(session.get("expires_at"))
            if (
                session.get("feedback") is None
                and expires
                and is_at_or_after(now, expires)
            ):
                continue
            kept.append(session)
        self._profiles[profile_id]["sessions"] = _bounded_sessions(kept)

    def _cap_sessions(self, profile_id: str) -> None:
        # Requested, unanswered feedback candidates are protected from a burst of
        # manual/unrequested sessions. We still keep at most three of those and
        # at most twenty sessions total, so storage remains fixed-size.
        self._profiles[profile_id]["sessions"] = _bounded_sessions(
            self._sessions(profile_id)
        )

    async def async_flush(self) -> None:
        """Persist the current profile state before a config-entry reload/unload."""
        await self.store.async_save({"profiles": self._profiles})

    async def async_remove_storage(self) -> None:
        """Remove persisted profile/session data when the config entry is deleted."""
        await self.store.async_remove()

    @callback
    def _schedule_save(self) -> None:
        self.store.async_delay_save(lambda: {"profiles": self._profiles}, 5.0)

    @callback
    def _updated(self, profile_id: str) -> None:
        async_dispatcher_send(
            self.hass,
            SIGNAL_PROFILE_UPDATED.format(entry_id=self.entry.entry_id),
            profile_id,
        )


def _public_session(session: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(session)
    result.pop("learning_before", None)
    result.pop("learning_contexts", None)
    result.pop("opened_by_user_id", None)
    return result


def _bounded_sessions(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the ring small without letting manual sessions evict feedback work."""
    requested_open = [
        session
        for session in sessions
        if session.get("feedback") is None and session.get("request_feedback")
    ]
    protected = requested_open[-MAX_OPEN_FEEDBACK:]
    protected_ids = {id(session) for session in protected}

    # Older unanswered requested candidates are deliberately dropped once the
    # per-profile cap is reached. Answered and manual sessions remain eligible
    # for the diagnostic ring.
    eligible = [
        session
        for session in sessions
        if not (
            session.get("feedback") is None
            and session.get("request_feedback")
            and id(session) not in protected_ids
        )
    ]
    if len(eligible) <= MAX_RECENT_SESSIONS:
        return eligible

    protected_indexes = {
        index for index, session in enumerate(eligible) if id(session) in protected_ids
    }
    remaining_slots = max(0, MAX_RECENT_SESSIONS - len(protected_indexes))
    ordinary_indexes = [
        index for index in range(len(eligible)) if index not in protected_indexes
    ]
    keep_indexes = protected_indexes | set(ordinary_indexes[-remaining_slots:])
    return [session for index, session in enumerate(eligible) if index in keep_indexes]


def _optional_close(a: Any, b: Any, tolerance: float) -> bool:
    left = _safe_float(a)
    right = _safe_float(b)
    if left is None or right is None:
        return left is None and right is None
    return abs(left - right) <= tolerance


def _session_context_matches(
    session: dict[str, Any],
    recommendation: Recommendation,
    weather_context: dict[str, Any],
    learning_contexts: dict[str, dict[str, Any]],
) -> bool:
    """Return whether reusing a recent session would train the same conditions."""
    old_rec = session.get("recommendation")
    old_learning = session.get("learning_contexts")
    if not isinstance(old_rec, dict) or not isinstance(old_learning, dict):
        return False

    new_rec = recommendation.as_dict()
    exact_keys = (
        "jacket_now",
        "jacket_later",
        "later_at",
        "rain_status",
        "source",
        "work_jacket",
        "work_context",
        "transient_override",
        "transient_direction",
        "transient_until",
    )
    if any(old_rec.get(key) != new_rec.get(key) for key in exact_keys):
        return False
    if not _optional_close(old_rec.get("effective_now_c"), new_rec.get("effective_now_c"), 0.5):
        return False

    old_start = old_learning.get("start")
    old_later = old_learning.get("later")
    new_start = learning_contexts.get("start")
    new_later = learning_contexts.get("later")
    if not all(isinstance(item, dict) for item in (old_start, old_later, new_start, new_later)):
        return False

    for old_ctx, new_ctx in ((old_start, new_start), (old_later, new_later)):
        if old_ctx.get("jacket") != new_ctx.get("jacket"):
            return False
        if not _optional_close(old_ctx.get("effective_c"), new_ctx.get("effective_c"), 0.5):
            return False
        if not _optional_close(old_ctx.get("wind_penalty_c"), new_ctx.get("wind_penalty_c"), 0.25):
            return False
        if not _optional_close(old_ctx.get("transition_penalty_c"), new_ctx.get("transition_penalty_c"), 0.25):
            return False

    old_weather = session.get("weather")
    if isinstance(old_weather, dict):
        if old_weather.get("condition") != weather_context.get("condition"):
            return False
    return True


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.UTC)
    return dt_util.as_local(parsed)


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
