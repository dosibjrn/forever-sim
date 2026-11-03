"""The shared stat probe works with native request objects without legacy GameIR.

This is a scorer/mutation boundary regression, not P3 gate acceptance.
Existing real GameIR gear regressions are tested separately.
"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def test_native_request_stat_probe_does_not_import_python_game_model():
    code = """
from dataclasses import dataclass, replace
import importlib
import sys

sensitivity = importlib.import_module("src.game.stat_sensitivity")
assert "src.game.gear" not in sys.modules
assert "src.game.model.ir" not in sys.modules

@dataclass(frozen=True)
class NativeRequest:
    engine_sha: str
    armor_delta: float = 0.0

request = NativeRequest(engine_sha="pinned-native-test-sha")
mutations = []
def apply_delta(state, stat, amount):
    assert stat == "armor"
    mutations.append((state.engine_sha, amount))
    return replace(state, armor_delta=amount)

def scorer(state):
    return {0.0: 10.0, 5.0: 11.0, 20.0: 8.0}[state.armor_delta]

result = sensitivity.measure_stat_sensitivities(
    request, stats=("armor",), score=scorer, probe_deltas=(5.0, 20.0),
    apply_delta=apply_delta,
)
row = result.rows[0]
assert row.first_effective_delta == 20.0
assert abs(row.value - 0.1) < 1e-12
assert row.baseline_seconds_per_mob == 10.0
assert [p["seconds_per_mob"] for p in row.probes] == [11.0, 8.0]
assert mutations == [("pinned-native-test-sha", 5.0), ("pinned-native-test-sha", 20.0)]
assert "src.game.gear" not in sys.modules
assert "src.game.model.ir" not in sys.modules
assert "src.game.runtime.simulator" not in sys.modules
"""
    completed = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_custom_native_mutator_preserves_invalid_score_rejection():
    from dataclasses import dataclass, replace
    from src.game.stat_sensitivity import measure_stat_sensitivities

    @dataclass(frozen=True)
    class State:
        delta: float = 0.0

    result = measure_stat_sensitivities(
        State(), stats=("agility",),
        score=lambda state: {0.0: 10.0, 1.0: float("nan"), 2.0: 8.0}[state.delta],
        probe_deltas=(1.0, 2.0),
        apply_delta=lambda state, _stat, amount: replace(state, delta=amount),
    )
    row = result.rows[0]
    assert row.first_effective_delta == 2.0
    assert row.value == 1.0
    assert [probe["seconds_per_mob"] for probe in row.probes] == [None, 8.0]


def test_p3_curve_audit_runs_without_legacy_game_model_imports():
    """The real P3 curve auditor consumes sampling knobs, not the old 100-mob evaluator."""
    code = """
import sys
from src.game.stat_sensitivity import PROBE_STEPS
from src.game.data.forever.source_checkpoint_p3_consistency import audit_stat_weight_curves

assert PROBE_STEPS["agility"] == 20.0
assert PROBE_STEPS["weapon_dps"] == 10.0
legacy_modules = (
    "src.game.model.ir",
    "src.game.gear",
    "src.game.runtime.simulator",
    "src.v2.source_persistent_joint_finalists",
    "src.game.data.forever.source_checkpoint_p3_weights",
)
for module in legacy_modules:
    assert module not in sys.modules, module

# The same source-agnostic curve checks work on native-paid scorer output.
report = {
    "stat_weights": {
        "base_s_per_mob": 10.0,
        "weights": {"agility": {"weight_s_saved_per_mob_per_unit": 0.04}},
    },
    "build_identity_sha256": "pinned-native-engine",
    "catalogue_sha256": "source-catalogue",
}
curves = {
    "build_identity_sha256": "pinned-native-engine",
    "catalogue_sha256": "source-catalogue",
    "mobs": 100,
    "base_s_per_mob": 10.0,
    "axes": {"agility": {"probes": [
        {"delta": 20.0, "s_per_mob": 9.2, "status": "COMPLETE"},
        {"delta": 40.0, "s_per_mob": 8.6, "status": "COMPLETE"},
    ]}},
}
valid = audit_stat_weight_curves(report=report, curves=curves)
assert valid["pass"] and not valid["failures"]
assert valid["axes"]["agility"]["safe_scalar_weight"]

# Moving probe configuration must not relax discrete coarse-step checks.
curves["axes"]["agility"]["probes"] = [
    {"delta": 5.0, "s_per_mob": 9.8, "status": "COMPLETE"},
    {"delta": 10.0, "s_per_mob": 9.6, "status": "COMPLETE"},
]
invalid = audit_stat_weight_curves(report=report, curves=curves)
assert not invalid["pass"]
assert "agility:NO_TWO_ITEM_RELEVANT_COARSE_STEPS" in invalid["failures"]
for module in legacy_modules:
    assert module not in sys.modules, module
"""
    completed = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
