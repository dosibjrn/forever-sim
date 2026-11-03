"""The shared source-stat conversion helper stays outside the game layer."""
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_shared_stat_conversion_is_game_independent_and_legacy_import_is_same():
    source = """
import math
import sys

from src.shared.stat_math import converted_stat_amount

# The arithmetic boundary must not pull in GameIR or any game package.
assert 'src.game' not in sys.modules
assert 'src.game.model.ir' not in sys.modules
assert converted_stat_amount({'operation': 'linear', 'coefficient': 2.0}, 3.0) == 6.0
assert converted_stat_amount({
    'operation': 'threshold_linear',
    'threshold': 10.0,
    'below_coefficient': 1.0,
    'coefficient': 2.0,
}, 12.0) == 14.0
assert converted_stat_amount({'operation': 'linear', 'coefficient': 2.0}, -3.0) == 0.0

try:
    converted_stat_amount({'operation': 'linear', 'coefficient': 2.0}, math.nan)
except ValueError as exc:
    assert str(exc) == 'NONFINITE_SOURCE_STAT_CONVERSION_INPUT'
else:
    raise AssertionError('non-finite input was accepted')

# The historical import path is retained as an identity-preserving re-export.
from src.game.stat_math import converted_stat_amount as legacy
assert legacy is converted_stat_amount
"""
    result = subprocess.run(
        [sys.executable, "-c", source],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
