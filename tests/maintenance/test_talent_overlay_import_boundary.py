"""Talent source overlay remains importable without the retiring GameIR stack.

This is an import boundary, not a replacement legality or combat authority.
The live source-talent builder must continue using its original compiler.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_talent_overlay_source_only_import_and_none_short_circuit_are_light():
    code = """
import sys
from src.game.data.forever.source_db_scope import DEFAULT_DB
from src.shared.identifiers import source_slug
from src.game.data.forever import source_talent_overlay as overlay

assert overlay.DEFAULT_DB is DEFAULT_DB
assert overlay._slug is source_slug
assert overlay._slug("Nature's Grasp") == "natures_grasp"
assert overlay.source_enrich_indexed_talents(None) is None

for name in ('src.game.data.forever.sqlite_talents',
             'src.game.model.ir', 'src.game.runtime.simulator'):
    assert name not in sys.modules, name

from src.game.data.forever.sqlite_talents import DEFAULT_DB as OLD_DB
from src.game.data.forever.sqlite_talents import _slug as OLD_SLUG
assert OLD_DB is DEFAULT_DB
assert OLD_SLUG is source_slug
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, text=True,
        capture_output=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_talent_overlay_live_hunter_source_builder_still_works():
    # The real GameIR consumer is deliberately retained until a tested
    # MythicSim Rust-native request replaces it (#357/#359).
    from src.game.data.forever.registry import build_game_ir_slice

    result = build_game_ir_slice(class_key="hunter", level=10)
    assert result is not None
    assert result.actor.metadata["class_key"] == "hunter"
    assert result.talents is not None
