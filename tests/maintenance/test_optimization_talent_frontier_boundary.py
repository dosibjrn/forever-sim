"""Optimizer talent-frontier values stay independent of game mechanics."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_optimizer_talent_frontier_is_game_independent_and_legacy_api_is_preserved():
    source = """
import sys
from src.optimization.talent_frontier import (
    Neighbor as OptimizerNeighbor, allocation_key as optimizer_allocation_key,
)

for module in (
    'src.game',
    'src.game.model.ir',
    'src.game.talents',
    'src.game.runtime.simulator',
    'src.rulesets',
):
    assert module not in sys.modules, module

assert optimizer_allocation_key({'root': 0, 'arcane': 2, 'feral': 1}) == (
    ('arcane', 2), ('feral', 1))
neighbor = OptimizerNeighbor((('arcane', 2),), 'rank_up', ('arcane',))
assert neighbor.as_dict() == {
    'allocation': {'arcane': 2}, 'operation': 'rank_up',
    'changed_ids': ['arcane'],
}

# The former game-module import path remains an exact compatibility re-export.
from src.game.talent_frontier import (
    Neighbor, allocation_key, source_legal_talent_neighbors,
)
assert Neighbor is OptimizerNeighbor
assert allocation_key is optimizer_allocation_key
assert callable(source_legal_talent_neighbors)

# The production P2 entry point also consumes the optimizer-owned identity.
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
spec = spec_from_file_location('wf_gate_p2_live', Path('tools/wf_gate_p2_live.py'))
p2_gate = module_from_spec(spec)
spec.loader.exec_module(p2_gate)
assert p2_gate.allocation_key is optimizer_allocation_key
"""
    completed = subprocess.run(
        [sys.executable, "-c", source], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
