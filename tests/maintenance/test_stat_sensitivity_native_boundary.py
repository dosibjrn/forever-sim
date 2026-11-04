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


def test_optimizer_stat_sensitivity_is_game_independent_and_legacy_api_is_preserved():
    code = """
from dataclasses import dataclass, replace
import sys

from src.optimization import stat_sensitivity as optimizer

for module in ("src.game", "src.game.model.ir", "src.game.gear",
               "src.game.runtime.simulator", "src.rulesets"):
    assert module not in sys.modules, module

@dataclass(frozen=True)
class NativeRequest:
    engine_sha: str
    delta: float = 0.0

request = NativeRequest("selected-engine-sha")
def mutate(state, stat, amount):
    assert stat == "agility"
    return replace(state, delta=amount)

def score(state):
    return {0.0: 10.0, 1.0: 11.0, 2.0: 8.0}[state.delta]

result = optimizer.measure_stat_sensitivities(
    request, stats=("agility",), score=score, apply_delta=mutate,
    probe_deltas=(1.0, 2.0),
)
row = result.rows[0]
assert row.first_effective_delta == 2.0
assert row.value == 1.0
assert [probe["seconds_per_mob"] for probe in row.probes] == [11.0, 8.0]
assert result.as_dict()["ranked"][0]["stat"] == "agility"

# The optimizer must not silently fall back to a GameIR mutation path.
try:
    optimizer.measure_stat_sensitivities(request, stats=("agility",), score=score)
except TypeError as exc:
    assert "apply_delta" in str(exc)
else:
    raise AssertionError("optimizer unexpectedly accepted an implicit game mutator")

from src.game.stat_sensitivity import StatSensitivity as LegacyStatSensitivity, PROBE_STEPS
assert LegacyStatSensitivity is optimizer.StatSensitivity
assert PROBE_STEPS["agility"] == 20.0
assert "src.game.gear" not in sys.modules
assert "src.game.model.ir" not in sys.modules
"""
    completed = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
