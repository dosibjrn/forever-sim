"""Optimizer talent-frontier generation stays independent of game mechanics."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_optimizer_talent_frontier_is_game_independent_and_legacy_api_is_preserved():
    source = """
import sys
from src.optimization.talent_frontier import (
    Neighbor as OptimizerNeighbor,
    TalentNeighborOption,
    allocation_key as optimizer_allocation_key,
    generate_talent_neighbors,
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

# The generic mutation walk consumes only ordered option values and a caller
# validator; it must not import a game model or encode talent-tree rules.
options = (
    TalentNeighborOption('first', 3, frozenset({1, 2, 3})),
    TalentNeighborOption('second', 2, frozenset({1, 2})),
)

def validate_selection(selection):
    if selection.get('second') == 2:
        raise ValueError('SECOND_RANK_TWO_REJECTED')

frontier = generate_talent_neighbors(
    options,
    {'first': 1},
    max_points=3,
    validate_selection=validate_selection,
)
neighbors = {(n.operation, n.allocation) for n in frontier['neighbors']}
assert ('rank_sweep', (('first', 3),)) in neighbors
assert ('rank_down', ()) in neighbors
assert ('point_transfer', (('second', 1),)) in neighbors
assert frontier['rejected_by_reason']['SECOND_RANK_TWO_REJECTED'] == 1
assert frontier['unsupported_option_ids'] == ()
assert frontier['option_count'] == 2
assert frontier['supported_option_count'] == 2
assert 'src.game.model.ir' not in sys.modules
assert 'src.game.talents' not in sys.modules

# The former game-module import path remains an exact compatibility re-export.
from src.game.talent_frontier import (
    Neighbor, allocation_key, source_legal_talent_neighbors,
)
assert Neighbor is OptimizerNeighbor
assert allocation_key is optimizer_allocation_key
assert callable(source_legal_talent_neighbors)

"""
    completed = subprocess.run(
        [sys.executable, "-c", source], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
