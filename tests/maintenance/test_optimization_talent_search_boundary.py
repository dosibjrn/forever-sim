"""Generic optimizer candidate scoring must not import game mechanics."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_optimizer_talent_scoring_is_game_model_independent():
    source = """
import sys
from src.optimization.talent_search import (
    score_talent_allocations, talent_candidate_id,
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
