from __future__ import annotations

import copy
import importlib.util
import math
from pathlib import Path
import sys
import types

ROOT = Path(__file__).parents[1] / "custom_components" / "jackenberater"
PKG = "jackenberater_diagnostics_testpkg"

package = types.ModuleType(PKG)
package.__path__ = [str(ROOT)]
sys.modules.setdefault(PKG, package)


def load(name: str):
    fullname = f"{PKG}.{name}"
    if fullname in sys.modules:
        return sys.modules[fullname]
    spec = importlib.util.spec_from_file_location(fullname, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[fullname] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


load("const")
learning = load("learning")
diagnostics = load("diagnostics")


def test_simulation_clones_and_never_mutates_the_real_model():
    real = learning.PersonalModel.from_answers(3, 3, 3, 3)
    before = copy.deepcopy(real.to_dict())
    simulated = diagnostics.simulation_from_state(
        real,
        "42",
        {"general_offset_c": 3.5, "wind_bias_c": -1.25},
    )
    assert simulated is not None
    assert simulated is not real
    assert simulated.total_feedback == 42
    assert simulated.general_offset_c == 3.5
    assert simulated.wind_bias_c == -1.25
    assert real.to_dict() == before


def test_simulation_sanitizes_invalid_and_extreme_values():
    real = learning.PersonalModel.from_answers(3, 3, 3, 3)
    simulated = diagnostics.simulation_from_state(
        real,
        "999999999999",
        {
            "general_offset_c": float("inf"),
            "wind_bias_c": -999,
            "transient_tolerance": "not-a-number",
            "cold_answer": 99,
        },
    )
    assert simulated is not None
    assert math.isfinite(simulated.general_offset_c)
    assert simulated.general_offset_c == 0.0
    assert simulated.wind_bias_c == -2.0
    assert simulated.transient_tolerance == 1.0
    assert simulated.cold_answer == 5


def test_diagnostics_are_complete_fixed_size_values_without_history():
    model = learning.PersonalModel.from_answers(3, 4, 2, 5)
    first = diagnostics.model_diagnostics(model)
    second = diagnostics.model_diagnostics(model)
    assert first == second
    assert set(model.to_dict()).issubset(first)
    assert first["simulation_active"] is False
    assert 0.0 <= first["confidence"] <= 1.0
    assert "sessions" not in first
    assert "history" not in first
