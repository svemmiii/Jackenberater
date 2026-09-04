"""Pure helpers for compact profile diagnostics and volatile simulations."""
from __future__ import annotations

from typing import Any

from .learning import PersonalModel


def model_diagnostics(model: PersonalModel, *, simulation_active: bool = False) -> dict[str, Any]:
    """Return the complete fixed-size model as Home Assistant-safe attributes."""
    result = model.to_dict()
    result["confidence"] = round(model.confidence(), 3)
    result["simulation_active"] = simulation_active
    return result


def simulation_from_state(
    real_model: PersonalModel,
    state: str | None,
    attributes: dict[str, Any] | None,
) -> PersonalModel | None:
    """Build a sanitized volatile model from a manually changed HA state.

    Returning ``None`` means the state still represents the real model. This
    helper never mutates ``real_model`` and has no access to persistent storage.
    """
    raw = real_model.to_dict()
    supplied = False
    attributes = attributes if isinstance(attributes, dict) else {}
    for key in tuple(raw):
        if key in attributes:
            raw[key] = attributes[key]
            supplied = True

    if state is not None:
        try:
            total_feedback = int(state)
        except (TypeError, ValueError, OverflowError):
            total_feedback = real_model.total_feedback
        else:
            if total_feedback >= 0:
                raw["total_feedback"] = total_feedback
                supplied = True

    if not supplied:
        return None
    simulated = PersonalModel.from_dict(raw)
    return simulated if simulated.to_dict() != real_model.to_dict() else None
