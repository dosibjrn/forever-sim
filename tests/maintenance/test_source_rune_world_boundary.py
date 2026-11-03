"""Keep the transitional rune source reader independent of GameIR imports."""
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_rune_source_reader_does_not_eagerly_import_game_ir():
    source = """
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from src.game.data.forever.source_db_scope import DEFAULT_DB
from src.game.data.forever import source_rune_policy

assert source_rune_policy.DEFAULT_DB is DEFAULT_DB
assert 'src.game.data.forever.sqlite_talents' not in sys.modules
assert 'src.game.model.ir' not in sys.modules
assert 'src.game.runtime.simulator' not in sys.modules

with tempfile.TemporaryDirectory() as directory:
    database = Path(directory) / 'source.sqlite'
    import sqlite3
    with sqlite3.connect(database) as db:
        db.execute(
            'CREATE TABLE spell_index (class_key TEXT, kind TEXT, spell_id INTEGER, '
            'name TEXT, level_hint INTEGER, source_url TEXT, raw_listview_json TEXT)'
        )

    untouched = SimpleNamespace(actions=())
    result, disabled = source_rune_policy.filter_default_runes(
        untouched, class_key='druid', level=20, ability_db_path=database
    )
    assert result is untouched and disabled == set()

assert 'src.game.data.forever.sqlite_talents' not in sys.modules
assert 'src.game.model.ir' not in sys.modules
assert 'src.game.runtime.simulator' not in sys.modules

from src.game.data.forever.sqlite_talents import DEFAULT_DB as LEGACY_DEFAULT_DB
assert LEGACY_DEFAULT_DB is DEFAULT_DB
"""
    result = subprocess.run(
        [sys.executable, "-c", source], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, (
        f"rune source/GameIR boundary regression failed: "
        f"{result.stdout}\\n{result.stderr}"
    )
