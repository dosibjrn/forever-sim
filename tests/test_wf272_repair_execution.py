from pathlib import Path
import sqlite3
from types import SimpleNamespace
import pytest
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from tools.run_forever_ability_repair import execute

def test_never_edits_canonical_if_fetch_fails(tmp_path):
    original=tmp_path/'original.sqlite'; stage=tmp_path/'stage.sqlite'
    with sqlite3.connect(DEFAULT_DB) as src,sqlite3.connect(original) as dst:src.backup(dst)
    before=original.read_bytes()
    calls=[]
    def fail(command,**kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=2,stdout='',stderr='403 forbidden')
    r=execute(class_key='druid',level=20,canonical=original,staging=stage,runner=fail)
    assert calls and '--details-only' in calls[0] and '--spell-ids' in calls[0]
    assert calls[0][calls[0].index('--db')+1]==str(stage)
    assert r['status']=='SOURCE_FETCH_FAILED' and not r['promoted']
    assert original.read_bytes()==before
    with sqlite3.connect(stage) as conn:assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'

def test_existing_staging_refused(tmp_path):
    original=tmp_path/'original.sqlite'; original.write_bytes(b'unused')
    stage=tmp_path/'stage.sqlite';stage.write_bytes(b'existing')
    with pytest.raises(FileExistsError):
        execute(class_key='druid',level=20,canonical=original,staging=stage)
    assert stage.read_bytes()==b'existing'

def test_canonical_path_refused():
    with pytest.raises(ValueError,match='differ'):
        execute(class_key='druid',level=20,canonical=Path(DEFAULT_DB),staging=Path(DEFAULT_DB))
