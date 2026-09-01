"""Persistent compact per-Home-Assistant-user profiles and feedback sessions."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import logging
from typing import Any, Callable
import uuid

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    FEEDBACK_VALUES,
    MAX_OPEN_FEEDBACK,
    MAX_RECENT_SESSIONS,
    PHASE_ALL,
    PHASE_LATER,
    PHASE_START,
    PHASE_VALUES,
    SESSION_EXPIRY,
    SIGNAL_PROFILE_CREATED,
    SIGNAL_PROFILE_UPDATED,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
)
from .learning import PersonalModel, apply_feedback, should_request_feedback
from .models import Recommendation

_LOGGER = logging.getLogger(__name__)


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
        }

    def summaries(self) -> list[dict[str, Any]]:
        return [self.get_profile_summary(pid) for pid in self.profile_ids]

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

    async def async_open_session(
        self,
        profile_id: str,
        recommendation: Recommendation,
        *,
        weather_context: dict[str, Any],
        learning_contexts: dict[str, dict[str, Any]],
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
            if created is None or (now - created).total_seconds() > 600:
                break
            old_rec = session.get("recommendation", {})
            if (
                old_rec.get("jacket_now") == recommendation.jacket_now
                and old_rec.get("jacket_later") == recommendation.jacket_later
                and session.get("feedback") is None
            ):
                return deepcopy(session)

        model = self.get_model(profile_id)
        near_threshold = "near_threshold" in recommendation.reasons
        class_change = recommendation.jacket_now != recommendation.jacket_later
        unusual_weather = any(
            key in recommendation.reasons
            for key in ("wind", "wet", "rain", "work_location", "uncertain_conditions")
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

        horizon = max(1, int(recommendation.horizon_hours))
        ready_at = now + timedelta(hours=horizon)
        expires_at = now + SESSION_EXPIRY
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
        }
        sessions.append(session)
        self._cap_sessions(profile_id)
        self._schedule_save()
        return deepcopy(session)

    def feedback_candidates(self, profile_id: str) -> list[dict[str, Any]]:
        now = dt_util.now()
        self._cleanup_profile(profile_id, now)
        candidates: list[dict[str, Any]] = []
        for session in reversed(self._sessions(profile_id)):
            if session.get("feedback") is not None or not session.get("request_feedback"):
                continue
            ready = _parse_dt(session.get("ready_at"))
            expires = _parse_dt(session.get("expires_at"))
            if ready and expires and ready <= now < expires:
                candidates.append(_public_session(session))
            if len(candidates) >= MAX_OPEN_FEEDBACK:
                break
        return candidates

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
        expires = _parse_dt(session.get("expires_at"))
        if expires is not None and dt_util.now() >= expires:
            raise ValueError("feedback expired")

        model = self.get_model(profile_id)
        # Only the newest feedback needs an undo snapshot. Keeping one compact
        # snapshot instead of one per historical session keeps storage smaller.
        for old_session in self._sessions(profile_id):
            old_session["learning_before"] = None
        session["learning_before"] = model.to_dict()
        recommendation = session.get("recommendation", {})
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
        ) -> None:
            apply_feedback(
                model,
                rating=rating,
                jacket=str(target.get("jacket") or recommendation.get("jacket_now") or "none"),
                wind_kmh=_safe_float(target.get("wind_kmh")),
                transition_penalty_c=_safe_float(target.get("transition_penalty_c")) or 0.0,
                phase=target_phase,
                recommendation_used=recommendation_used,
                unusual_day=bool(unusual_day),
                voluntary=bool(voluntary),
                count_feedback=count_feedback,
                apply_general=apply_general,
            )

        if phase == PHASE_ALL and isinstance(later_context, dict):
            # "Throughout" carries one global signal, but can inform the
            # start-specific transition/boundary and the later weather/boundary.
            _learn_context(start_context, count_feedback=True, apply_general=True, target_phase=PHASE_START)
            if later_context != start_context:
                _learn_context(later_context, count_feedback=False, apply_general=False, target_phase=PHASE_LATER)
        else:
            target = later_context if phase == PHASE_LATER else start_context
            _learn_context(target, count_feedback=True, apply_general=True, target_phase=phase)
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
            before = session.get("learning_before")
            if not isinstance(feedback, dict) or feedback.get("undone"):
                continue
            if not isinstance(before, dict):
                continue
            self._profiles[profile_id]["model"] = before
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
            self._cleanup_profile(profile_id, now)

    def _cleanup_profile(self, profile_id: str, now: datetime) -> None:
        sessions = self._sessions(profile_id)
        kept: list[dict[str, Any]] = []
        for session in sessions:
            expires = _parse_dt(session.get("expires_at"))
            if session.get("feedback") is None and expires and now >= expires:
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
