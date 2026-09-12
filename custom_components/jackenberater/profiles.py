"""Persistent compact per-Home-Assistant-user profiles and feedback sessions."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
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
    FEEDBACK_PERFECT,
    FEEDBACK_TOO_COLD,
    FEEDBACK_TOO_WARM,
    FEEDBACK_VALUES,
    MAX_OPEN_FEEDBACK,
    MAX_RECENT_SESSIONS,
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

_SESSION_SCHEMA_VERSION = 5


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
    "winter_season_initialized",
    "spring_season_initialized",
    "summer_season_initialized",
    "autumn_season_initialized",
    "winter_seeded_from",
    "spring_seeded_from",
    "summer_seeded_from",
    "autumn_seeded_from",
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


def _feedback_policy_signature(
    model: PersonalModel,
    recommendation: Recommendation,
    *,
    near_threshold: bool,
    class_change: bool,
    unusual_weather: bool,
) -> dict[str, Any]:
    """Return the session-reuse fields that define feedback/learning semantics.

    A recent session may only be reused when reopening it would ask the same
    feedback question and later train the same seasonal/model context.  The
    exact clock time is intentionally not part of the signature so repeated
    taps within a few minutes still deduplicate; calendar dates are included
    because season weights are date based.
    """

    def _day(value: datetime | None) -> str | None:
        return value.date().isoformat() if isinstance(value, datetime) else None

    return {
        "learning_enabled": bool(model.learning_enabled),
        "confidence": round(float(recommendation.confidence), 3),
        "near_threshold": bool(near_threshold),
        "class_change": bool(class_change),
        "unusual_weather": bool(unusual_weather),
        # The opportunity counter controls cadence for a *new* opportunity,
        # but is deliberately not part of session identity. Otherwise an
        # unrelated session opened between A and a repeated A would defeat
        # profile-wide 10-minute deduplication of the same real decision.
        "observed_date": _day(recommendation.observed_at),
        "later_date": _day(recommendation.later_at),
    }


def _normalize_feedback_learning_snapshot(raw: Any) -> dict[str, Any] | None:
    """Normalize old undo snapshots to the compact current learning format.

    v0.2.x stored the complete model; v0.3 stored a compact learning-only snapshot
    but did not yet include season-initialization metadata. Both forms must pass
    through the current ``PersonalModel`` migration before an undo can restore
    them into the independent v0.3.1 seasonal model.
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

    season_metadata = {
        f"{season}_season_initialized"
        for season in ("winter", "spring", "summer", "autumn")
    }
    if not season_metadata.issubset(raw):
        # Compact v0.3 snapshot: reconstruct only enough model shape to let the
        # v3 -> v4 seasonal migration use the snapshot's own biases and evidence.
        reconstructed = PersonalModel().to_dict()
        reconstructed.update(deepcopy(raw))
        reconstructed["seasonal_model_version"] = 3
        return _feedback_learning_snapshot(PersonalModel.from_dict(reconstructed))

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
        self._revision = 0
        self._directory_revision = 0
        self._profile_revisions: dict[str, int] = {}
        # A fresh token for every loaded ProfileManager makes cross-device
        # revision polling detect config-entry reloads even when integer
        # revisions happen to restart at the same value.
        self._runtime_generation = uuid.uuid4().hex

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

    @property
    def revision(self) -> int:
        """Monotonic revision inside this ProfileManager runtime."""
        return int(getattr(self, "_revision", 0))

    @property
    def revision_token(self) -> str:
        """Backward-compatible global runtime token."""
        return f"{self._runtime_generation}:{self.revision}"

    @property
    def directory_revision(self) -> int:
        """Revision for profile-directory changes (create/delete/rename)."""
        return int(getattr(self, "_directory_revision", 0))

    @property
    def directory_revision_token(self) -> str:
        return f"{self._runtime_generation}:d:{self.directory_revision}"

    def profile_revision(self, profile_id: str) -> int:
        revisions = getattr(self, "_profile_revisions", None)
        if not isinstance(revisions, dict):
            revisions = {}
            self._profile_revisions = revisions
        return int(revisions.get(profile_id, 0))

    def profile_revision_token(self, profile_id: str) -> str:
        return f"{self._runtime_generation}:p:{self.profile_revision(profile_id)}"

    def _session_revision_digest(
        self, profile_id: str, now: datetime | None = None
    ) -> str:
        """Return a tiny dynamic digest for user-visible session state.

        Session creation does not belong to the learned-model revision, and a
        requested session becomes due merely because wall-clock time crosses
        ``ready_at``.  Build the card-visible session marker from the bounded
        session ring itself so another device notices both structural changes
        and the pending->due transition without a background timer or store write.
        """
        current = now or dt_util.now()
        parts: list[str] = []
        raw = self._profiles.get(profile_id)
        sessions = raw.get("sessions") if isinstance(raw, dict) else None
        if not isinstance(sessions, list):
            sessions = []
        for session in sessions:
            if session.get("feedback") is not None:
                continue
            if not _session_policy_is_current(session):
                continue
            expires = _parse_dt(session.get("expires_at"))
            if expires is None or is_at_or_after(current, expires):
                continue
            ready = _parse_dt(session.get("ready_at"))
            due = bool(
                session.get("request_feedback")
                and ready is not None
                and is_at_or_after(current, ready)
            )
            parts.append(
                f"{session.get('id', '')}:{int(bool(session.get('request_feedback')))}:{int(due)}"
            )
        payload = "|".join(parts).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:12]

    def session_revision_token(
        self, profile_id: str, now: datetime | None = None
    ) -> str:
        return f"{self._runtime_generation}:s:{self._session_revision_digest(profile_id, now)}"

    def card_revision_token(
        self, profile_id: str | None, *, include_directory: bool = False
    ) -> str:
        """Return the smallest reload-safe token relevant to one full card snapshot."""
        parts = [self._runtime_generation]
        if include_directory:
            parts.append(f"d{self.directory_revision}")
        if profile_id is not None:
            parts.append(f"p{self.profile_revision(profile_id)}")
            parts.append(f"s{self._session_revision_digest(profile_id)}")
        return ":".join(parts)

    @callback
    def bump_volatile_profile_revision(self, profile_id: str) -> None:
        """Notify cards about volatile per-profile state without persisting it.

        Diagnostic simulation is intentionally runtime-only and must not emit a
        normal profile-updated signal, because that signal clears simulations.
        It still changes the preview, so bump only the in-memory revision token.
        """
        self._bump_scoped_revisions(profile_id=profile_id)

    def profile_name(self, profile_id: str) -> str:
        raw = self._profiles.get(profile_id, {})
        return str(raw.get("name") or "Home-Assistant-Nutzer")

    def get_model(self, profile_id: str) -> PersonalModel:
        """Return the persisted model without causing any model mutation.

        Reads such as profile lists, diagnostics and exports must be pure. In
        particular, an admin/wall-tablet listing somebody else's profile must
        never initialize or seed that person's seasons. Advice paths explicitly
        call :meth:`prepare_model_for_advice` instead.
        """
        raw = self._profiles.get(profile_id)
        if not isinstance(raw, dict):
            return PersonalModel()
        return PersonalModel.from_dict(raw.get("model"))

    def prepare_model_for_advice(
        self, profile_id: str, when: datetime | None = None
    ) -> PersonalModel:
        """Prepare exactly one actively advised profile for the current season."""
        raw = self._profiles.get(profile_id)
        if not isinstance(raw, dict):
            return PersonalModel()
        model = PersonalModel.from_dict(raw.get("model"))
        if model.prepare_seasons_for(when or dt_util.now()):
            raw["model"] = model.to_dict()
            self._schedule_save()
            self._updated(profile_id)
        return model

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
                getattr(self, "_profile_revisions", {}).pop(profile_id, None)
                changed = True
                self._bump_scoped_revisions(directory=True)
                async_dispatcher_send(
                    self.hass,
                    SIGNAL_PROFILE_DELETED.format(entry_id=self.entry.entry_id),
                    profile_id,
                )
                continue
            if self._profiles[profile_id].get("name") != directory[profile_id]:
                self._profiles[profile_id]["name"] = directory[profile_id]
                changed = True
                self._bump_scoped_revisions(profile_id=profile_id, directory=True)
                async_dispatcher_send(
                    self.hass,
                    SIGNAL_PROFILE_UPDATED.format(entry_id=self.entry.entry_id),
                    profile_id,
                )
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
            self._bump_scoped_revisions(profile_id=profile_id, directory=True)
            async_dispatcher_send(
                self.hass,
                SIGNAL_PROFILE_CREATED.format(entry_id=self.entry.entry_id),
                profile_id,
            )
        elif changed:
            # A Home Assistant user rename affects both this profile's own card
            # and shared profile selectors, so bump both scopes.
            self._bump_scoped_revisions(profile_id=profile_id, directory=True)
            async_dispatcher_send(
                self.hass,
                SIGNAL_PROFILE_UPDATED.format(entry_id=self.entry.entry_id),
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
        fresh.prepare_seasons_for(dt_util.now())
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
        if not model.learning_enabled:
            # Pausing learning invalidates every unanswered feedback context.
            # Merely muting request_feedback is not enough: after resume the old
            # policy signature could otherwise match again inside the 10-minute
            # reuse window and silently consume a fresh feedback opportunity.
            for session in self._sessions(profile_id):
                if session.get("feedback") is None:
                    session["request_feedback"] = False
                    session["policy_signature"] = None
                    session["trainable"] = False
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
        prepared_model: PersonalModel | None = None,
    ) -> dict[str, Any]:
        now = dt_util.now()
        raw = self._profiles[profile_id]
        if self._cleanup_profile(profile_id, now):
            # Persist expiry cleanup even when the function reuses an existing
            # fresh session and returns early below.
            self._schedule_save()
        # Cleanup replaces the stored list, so reacquire it afterwards.
        sessions = self._sessions(profile_id)
        # Opening feedback for a real recommendation is an explicit use of this
        # profile, so season bootstrap belongs here as well. This also keeps the
        # persisted seed in place before any learning-before snapshot is taken.
        model = (
            prepared_model
            if prepared_model is not None
            else self.prepare_model_for_advice(profile_id, recommendation.observed_at)
        )
        # ``prepared_model`` intentionally freezes the recommendation-relevant
        # learning state across forecast/calendar awaits.  Session cadence is a
        # different concern: ``feedback_opportunities`` can change when another
        # device opens an otherwise unrelated session without bumping the model
        # revision.  Rebase only that session-local counter from persisted state
        # immediately before policy/reuse evaluation.  ``async_open_session`` has
        # no awaits after this point, so the merge/increment/store sequence stays
        # atomic in the HA event loop and parallel stale snapshots cannot lose an
        # opportunity or create duplicate identical sessions.
        current_model = self.get_model(profile_id)
        model.feedback_opportunities = current_model.feedback_opportunities
        near_threshold = "near_threshold" in recommendation.reasons
        class_change = recommendation.jacket_now != recommendation.jacket_later
        unusual_weather = any(
            key in recommendation.reasons
            for key in ("wind", "wet", "work_location", "uncertain_conditions")
        )
        current_policy = _feedback_policy_signature(
            model,
            recommendation,
            near_threshold=near_threshold,
            class_change=class_change,
            unusual_weather=unusual_weather,
        )

        # Reuse one recent real-world decision profile-wide.  Answered current-
        # schema sessions remain dedupe anchors so the same weather/jacket
        # decision cannot be learned twice merely because the user closes and
        # reopens the card.  If the decision is the same but feedback policy has
        # changed, the old *unanswered* session is explicitly superseded before
        # a fresh policy session is created; two trainable versions of one real
        # decision must never coexist.
        superseded_changed = False
        for session in reversed(sessions):
            created = _parse_dt(session.get("created_at"))
            if created is None:
                continue
            age_seconds = elapsed(created, now).total_seconds()
            if age_seconds < 0:
                continue
            if age_seconds > 600:
                break

            answered = session.get("feedback") is not None
            if answered and session.get("session_schema_version") != _SESSION_SCHEMA_VERSION:
                continue

            same_decision = _session_context_matches(
                session,
                recommendation,
                weather_context,
                learning_contexts,
                current_policy,
                require_policy=False,
            )
            if not same_decision:
                continue

            if answered:
                if superseded_changed:
                    self._schedule_save()
                return _public_session(session)

            if _session_policy_is_current(session) and session.get("policy_signature") == current_policy:
                if superseded_changed:
                    self._schedule_save()
                return _public_session(session)

            # Same real decision, but stale/changed policy.  Kill the old
            # unanswered learning ticket before creating the replacement.
            session["request_feedback"] = False
            session["policy_signature"] = None
            session["trainable"] = False
            session["superseded"] = True
            superseded_changed = True

        if model.learning_enabled:
            model.feedback_opportunities += 1
        requested = should_request_feedback(
            model,
            near_threshold=near_threshold,
            class_change=class_change,
            unusual_weather=unusual_weather,
            decision_confidence=recommendation.confidence,
            opportunity_count=model.feedback_opportunities,
        )
        raw["model"] = model.to_dict()
        stored_policy = _feedback_policy_signature(
            model,
            recommendation,
            near_threshold=near_threshold,
            class_change=class_change,
            unusual_weather=unusual_weather,
        )

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
            "session_schema_version": _SESSION_SCHEMA_VERSION,
            "created_at": now.isoformat(),
            "ready_at": ready_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "request_feedback": requested,
            "policy_signature": stored_policy,
            "trainable": bool(model.learning_enabled),
            "superseded": False,
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
        raw = self._profiles.get(profile_id, {})
        model = PersonalModel.from_dict(raw.get("model") if isinstance(raw, dict) else None)
        if not model.learning_enabled:
            return []
        now = dt_util.now()
        if self._cleanup_profile(profile_id, now):
            self._schedule_save()
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
        model = self.get_model(profile_id)
        if not model.learning_enabled:
            raise ValueError("learning_paused")
        if session.get("trainable") is not True:
            # A context created while learning was paused is permanently
            # display-only. Resuming learning later must not retroactively turn
            # that historic decision into training evidence.
            raise ValueError("feedback_session_incompatible")
        if not _session_policy_is_current(session):
            # Temporary sessions from an older semantic/schema generation,
            # superseded policy variants or explicitly invalidated sessions must
            # never train the current model, even when an old client still holds
            # their id.
            raise ValueError("feedback_session_incompatible")
        now = dt_util.now()
        expires = _parse_dt(session.get("expires_at"))
        if expires is None:
            raise ValueError("feedback_session_incompatible")
        if is_at_or_after(now, expires):
            raise ValueError("feedback expired")
        if not voluntary:
            ready = _parse_dt(session.get("ready_at"))
            if not session.get("request_feedback") or ready is None or is_before(now, ready):
                raise ValueError("feedback_not_ready")

        recommendation = session.get("recommendation", {})
        # “Perfect” on a recommendation that deliberately changed jacket class is
        # confirmation of the whole recommendation. Do not ask an extra question;
        # use the existing PHASE_ALL path so both relevant boundaries are learned.
        class_change = recommendation.get("jacket_now") != recommendation.get("jacket_later")
        later_at = _parse_dt(recommendation.get("later_at"))
        future_change_unexperienced = bool(
            voluntary
            and class_change
            and later_at is not None
            and is_before(now, later_at)
        )
        # Voluntary feedback means “rate what I am seeing now”. A future jacket
        # switch cannot be confirmed before its timestamp has actually occurred.
        # Normalize even direct API callers to the start context; the frontend
        # mirrors this by not presenting later/all choices for such sessions.
        if future_change_unexperienced:
            phase = PHASE_START

        # ``later``/``all`` only have semantic meaning when the recommendation
        # actually crosses a jacket boundary. The normal card already enforces
        # this; normalize direct WebSocket callers too so one stable recommendation
        # can never be trained through two contexts by one feedback interaction.
        if not class_change and phase in {PHASE_LATER, PHASE_ALL}:
            phase = PHASE_START

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

            # Unanswered sessions are intentionally short-lived. Do not carry an
            # old feedback/session semantic across an upgrade: legacy sessions
            # without the current policy signature/schema could otherwise still
            # appear as due feedback and train a model under stale context rules.
            raw["sessions"] = [
                session
                for session in self._sessions(profile_id)
                if session.get("feedback") is not None
                or _session_policy_is_current(session)
            ]

            self._cleanup_profile(profile_id, now)

    def _cleanup_profile(self, profile_id: str, now: datetime) -> bool:
        sessions = self._sessions(profile_id)
        before = list(sessions)
        kept: list[dict[str, Any]] = []
        for session in sessions:
            unanswered = session.get("feedback") is None
            if unanswered and not _session_policy_is_current(session):
                continue
            expires = _parse_dt(session.get("expires_at"))
            # An unanswered session without a valid expiry is incompatible
            # storage, not an immortal feedback opportunity.
            if unanswered and expires is None:
                continue
            if unanswered and is_at_or_after(now, expires):
                continue
            kept.append(session)
        bounded = _bounded_sessions(kept)
        changed = bounded != before
        self._profiles[profile_id]["sessions"] = bounded
        return changed

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
    def _bump_revision(self) -> None:
        """Backward-compatible global revision for tests/diagnostics."""
        self._revision = self.revision + 1

    @callback
    def _bump_scoped_revisions(
        self, *, profile_id: str | None = None, directory: bool = False
    ) -> None:
        self._bump_revision()
        if profile_id is not None:
            revisions = getattr(self, "_profile_revisions", None)
            if not isinstance(revisions, dict):
                revisions = {}
                self._profile_revisions = revisions
            revisions[profile_id] = int(revisions.get(profile_id, 0)) + 1
        if directory:
            self._directory_revision = self.directory_revision + 1

    @callback
    def _updated(self, profile_id: str) -> None:
        self._bump_scoped_revisions(profile_id=profile_id)
        async_dispatcher_send(
            self.hass,
            SIGNAL_PROFILE_UPDATED.format(entry_id=self.entry.entry_id),
            profile_id,
        )


def _public_session(session: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(session)
    result.pop("learning_before", None)
    result.pop("learning_contexts", None)
    result.pop("policy_signature", None)
    result.pop("session_schema_version", None)
    result.pop("opened_by_user_id", None)
    result.pop("trainable", None)
    result.pop("superseded", None)
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


def _session_policy_is_current(session: dict[str, Any]) -> bool:
    """Return whether an unanswered session is safe for current feedback rules.

    Sessions opened while learning was paused are display-only snapshots. They
    must never become trainable later merely because learning was resumed.
    """
    return (
        session.get("session_schema_version") == _SESSION_SCHEMA_VERSION
        and isinstance(session.get("policy_signature"), dict)
        and session.get("trainable") is True
        and not session.get("superseded")
    )


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
    policy_signature: dict[str, Any],
    *,
    require_policy: bool = True,
) -> bool:
    """Return whether reusing a recent session would train the same conditions."""
    old_rec = session.get("recommendation")
    old_learning = session.get("learning_contexts")
    if not isinstance(old_rec, dict) or not isinstance(old_learning, dict):
        return False
    if require_policy and session.get("policy_signature") != policy_signature:
        # Legacy/unanswered sessions without the exact current feedback policy
        # are deliberately not reused. Answered current-schema sessions use only
        # decision context here: their role is to suppress duplicate learning,
        # not to reopen the old feedback policy.
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
        "later_work_period",
        "later_change_confirmed",
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
    try:
        parsed = dt_util.parse_datetime(value)
    except (TypeError, ValueError):
        return None
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
