"""The source-only L0 frontier must not eagerly load legacy GameIR.

The existing proxy still resolves the real effect capabilities when called.
This is a dependency boundary, not native Rust source/legality migration.
"""
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_l0_frontier_import_does_not_eagerly_load_game_ir():
    source = """
import sys
from types import SimpleNamespace

from src.game.data.forever.source_db_scope import DEFAULT_DB
from src.game.data.forever import source_checkpoint_l0

assert source_checkpoint_l0.DEFAULT_DB is DEFAULT_DB
for module in (
    'src.game.data.forever.sqlite_talents',
    'src.game.model.ir',
    'src.game.runtime.effect_capabilities',
    'src.game.runtime.simulator',
):
    assert module not in sys.modules, module

features = source_checkpoint_l0._features_from_atoms([
    {'kind': 'school_damage_range', 'values': {'min': 4.0, 'max': 8.0}},
    {'kind': 'periodic_damage', 'values': {'amount': 12.0}},
])
assert features['direct_damage'] == 6.0
assert features['periodic_damage_total'] == 12.0

proxy = source_checkpoint_l0._ir_proxy(SimpleNamespace(
    effects=(), costs=(), gcd_s=1.5, cast_time_s=0.0
))
assert proxy['proxy_kind'] == 'IR_EFFECT_VECTOR_L0_NOT_100_MOB_SCORE'
assert proxy['effect_roles'] == []
assert proxy['gcd_s'] == 1.5
assert 'src.game.runtime.effect_capabilities' in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", source], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, (
        f"L0 frontier import/proxy boundary failed: {result.stdout}\n{result.stderr}"
    )
