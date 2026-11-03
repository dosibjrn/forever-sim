"""Prove the rank reader's source-only boundary without retiring live GameIR.

Legacy source rank promotion still runs for real build requests until a tested
MythicSim-native consumer can replace it (#357/#359).
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_rank_overlay_source_only_import_and_none_path_skip_game_ir():
    code = """
import sys
from src.game.data.forever.source_db_scope import DEFAULT_DB
from src.game.data.forever import source_rank_overlay as overlay

assert overlay.DEFAULT_DB is DEFAULT_DB
assert overlay._seconds('Instant', instant=True) == 0.0
assert overlay._seconds('2 sec cast') == 2.0
assert overlay._source_range_match('30 yd range').group(1) == '30'
assert overlay._source_range_match('unknown range') is None
assert overlay.source_enrich_action_ranks(None) is None

for name in ('src.game.model.ir',
             'src.game.data.forever.sqlite_talents',
             'src.game.runtime.simulator'):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, text=True,
        capture_output=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_rank_overlay_real_build_still_uses_original_legacy_execution():
    # Both classes exercise the real source assembly (including rank overlay),
    # not a stub, new rules engine or invented gate PASS.
    from src.game.data.forever.registry import build_game_ir_slice

    for class_key, level in (("hunter", 10), ("paladin", 20)):
        ir = build_game_ir_slice(class_key=class_key, level=level)
        assert ir is not None
        assert ir.actor.metadata["class_key"] == class_key
        assert ir.actions
