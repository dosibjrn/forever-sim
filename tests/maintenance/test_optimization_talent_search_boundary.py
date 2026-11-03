"""Generic optimizer talent enumeration and scoring must not import game mechanics."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_optimizer_talent_scoring_is_game_model_independent():
    source = """
import sys
from src.optimization.talent_search import (
    TalentAllocationOption,
    enumerate_talent_allocations,
    score_talent_allocations,
    talent_candidate_id,
)

for module in (
    'src.game',
    'src.game.model.ir',
    'src.game.talents',
    'src.game.runtime.simulator',
    'src.rulesets',
):
    assert module not in sys.modules, module

assert talent_candidate_id({'z': 1, 'a': 1}) == 'talents:a=1;z=1'

# Pure rank-allocation enumeration receives source-derived options and a
# required legality callback; it does not import a second game-rules model.
options = (
    TalentAllocationOption('first', 2, frozenset({1, 2})),
    TalentAllocationOption('second', 1, frozenset({1})),
)

def validate_selection(selection):
    if selection.get('first') == 2:
        raise ValueError('test-only rejected allocation')

def rank_is_admissible(option, rank, selection, index):
    # The adapter owns the source-specific tier rule; this callback is a
    # generic partial-candidate admission hook.
    return option.talent_id != 'second' or selection.get('first', 0) >= 1

allocations, truncated = enumerate_talent_allocations(
    options,
    max_points=2,
    rank_is_admissible=rank_is_admissible,
    validate_selection=validate_selection,
    max_candidates=10,
)
assert allocations == ({}, {'first': 1}, {'first': 1, 'second': 1})
assert truncated is False

limited, truncated = enumerate_talent_allocations(
    options,
    max_points=2,
    rank_is_admissible=rank_is_admissible,
    validate_selection=lambda _: None,
    max_candidates=2,
)
assert limited == ({}, {'first': 1})
assert truncated is True

def evaluate(selection):
    if selection == {'blocked': 1}:
        return None, {'reason': 'unsupported'}
    if selection == {'a': 1} or selection == {'z': 1}:
        return 8.0, {'engine': 'callback'}
    return 9.0, {'engine': 'callback'}

rows, selected = score_talent_allocations(
    ({'z': 1}, {'a': 1}, {'a': 1, 'b': 1}, {'blocked': 1}),
    evaluate=evaluate,
)
assert len(rows) == 4
assert sum(row.valid for row in rows) == 3
assert selected is not None
assert selected.candidate_id == 'talents:a=1'
assert selected.seconds_per_mob == 8.0
assert rows[-1].valid is False
assert rows[-1].detail == {'reason': 'unsupported'}

for module in (
    'src.game',
    'src.game.model.ir',
    'src.game.talents',
    'src.game.runtime.simulator',
    'src.rulesets',
):
    assert module not in sys.modules, module
"""
    completed = subprocess.run(
        [sys.executable, "-c", source], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
