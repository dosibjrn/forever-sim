"""Fixed-point orchestration belongs to the game-independent optimizer layer.

The tested state is a plain native-request-shaped object, not a game simulation.
The old game-module path remains a compatibility re-export only.
"""

from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def test_optimizer_fixed_point_import_is_game_independent_and_legacy_import_is_compatible():
    code = """
import importlib
import sys

module = importlib.import_module('src.optimization.fixed_point')
assert callable(module.run_optimizer_fixed_point)
assert 'src.game' not in sys.modules
assert 'src.game.model.ir' not in sys.modules
assert 'src.game.runtime.simulator' not in sys.modules

legacy = importlib.import_module('src.game.fixed_point')
assert legacy.run_optimizer_fixed_point is module.run_optimizer_fixed_point
assert legacy.FixedPointResult is module.FixedPointResult
assert 'src.game.model.ir' not in sys.modules
assert 'src.game.runtime.simulator' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT, text=True, capture_output=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@dataclass(frozen=True)
class NativeLikeRequest:
    engine_sha: str
    selected_gear: str

    def as_dict(self):
        return {"engine_sha": self.engine_sha, "selected_gear": self.selected_gear}


def test_fixed_point_accepts_plain_native_request_state_without_gameir():
    from src.optimization.fixed_point import run_optimizer_fixed_point

    request = NativeLikeRequest(engine_sha="immutable-test-revision", selected_gear="none")

    def evaluate_state(state):
        return {"seconds_per_mob": 10.0 if state.selected_gear == "none" else 9.0,
                "talent_candidate_id": None, "policy_candidate_id": None}

    def measure_weights(_state):
        return {"agility": 1.0}

    def select_gear(_weights):
        return {"candidate_id": "gear-a"}

    def apply_gear(state, gear):
        return NativeLikeRequest(state.engine_sha, gear["candidate_id"])

    def run():
        return run_optimizer_fixed_point(
            request, evaluate_state=evaluate_state,
            measure_weights=measure_weights,
            select_gear=select_gear, apply_gear=apply_gear,
            max_iterations=3,
        )

    first, second = run(), run()
    assert first.converged
    assert first.stop_reason == "exact_state_repeat"
    assert len(first.iterations) == 3
    assert first.selected.seconds_per_mob == 9.0
    assert first.selected.gear_candidate_id == "gear-a"
    assert first.as_dict() == second.as_dict()
    # Preserve the serialized identity key used by existing consumers/receipts.
    assert "source_game_ir_sha256" in first.selected.state_dimensions
