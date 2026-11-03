"""Keep transitional rune/world source readers independent of GameIR imports.

The substantive native Rust replacement is tracked by #357/#359; this test
only protects an import boundary and existing source-fail-closed behavior.
"""
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_rune_and_world_source_readers_do_not_eagerly_import_game_ir():
    source = """
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from src.game.data.forever.source_db_scope import DEFAULT_DB
from src.game.data.forever import source_rune_policy, source_world_acquisition

assert source_rune_policy.DEFAULT_DB is DEFAULT_DB
assert source_world_acquisition.DEFAULT_DB is DEFAULT_DB
assert 'src.game.data.forever.sqlite_talents' not in sys.modules
assert 'src.game.model.ir' not in sys.modules
assert 'src.game.runtime.simulator' not in sys.modules

with tempfile.TemporaryDirectory() as directory:
    database = Path(directory) / 'source.sqlite'
    with sqlite3.connect(database) as db:
        db.execute(
            'CREATE TABLE spell_index (class_key TEXT, kind TEXT, spell_id INTEGER, '
            'name TEXT, level_hint INTEGER, source_url TEXT, raw_listview_json TEXT)'
        )

    # Empty, explicitly scoped source evidence must never create a legal rune.
    untouched = SimpleNamespace(actions=())
    result, disabled = source_rune_policy.filter_default_runes(
        untouched, class_key='druid', level=20, ability_db_path=database
    )
    assert result is untouched and disabled == set()

    # A missing source-attested origin is rejected, not inferred from input.
    try:
        source_world_acquisition.verify_acquisition_trace(
            class_key='druid', level=20, anchor_id='UNVERIFIED',
            events=(), db_path=database
        )
    except source_world_acquisition.UnverifiedWorldEvent as exc:
        assert str(exc) == 'BLOCKED_NO_CANONICAL_WORLD_ORIGIN'
    else:
        raise AssertionError('unsourced world origin was accepted')

assert 'src.game.data.forever.sqlite_talents' not in sys.modules
assert 'src.game.model.ir' not in sys.modules
assert 'src.game.runtime.simulator' not in sys.modules

# The original public compatibility spelling still exposes the exact path.
from src.game.data.forever.sqlite_talents import DEFAULT_DB as LEGACY_DEFAULT_DB
assert LEGACY_DEFAULT_DB is DEFAULT_DB
"""
    result = subprocess.run(
        [sys.executable, "-c", source], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, (
        f"source rune/world boundary regression failed: "
        f"{result.stdout}\n{result.stderr}"
    )
