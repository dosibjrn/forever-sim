"""Source recovery is explicit and failed recaptures cannot damage good data."""
import json
import shutil
import sqlite3
import hashlib
import zlib

import pytest

from src.game.data.forever.sqlite_talents import DEFAULT_DB
from tools import capture_forever_abilities_sqlite as capture


def temp_db(tmp_path):
    path=tmp_path/'abilities.sqlite'
    with sqlite3.connect(DEFAULT_DB) as source, sqlite3.connect(path) as destination:
        source.backup(destination)
    return path


def test_failed_detail_refetch_never_overwrites_existing_evidence(tmp_path,monkeypatch):
    db_path=temp_db(tmp_path)
    batch='20261008T145657Z'; sid=2912
    old_markup=b'<html><body>previously verified source evidence</body></html>'
    hash_value=hashlib.sha256(old_markup).hexdigest()
    with sqlite3.connect(db_path) as conn:
        # Construct an existing pair, then force a refresh to exercise protection.
        conn.execute('INSERT OR REPLACE INTO spell_details VALUES (?,?,?,?,?,?,?,?)',
            (batch,sid,f'https://www.wowhead.com/forever/spell={sid}','Starfire',
             'Starfire spell details',hash_value,'2026-10-11T00:00:00Z',1))
        conn.execute('INSERT OR REPLACE INTO spell_detail_snapshots VALUES (?,?,?,?,?,?,?)',
            (batch,sid,f'https://www.wowhead.com/forever/spell={sid}',200,hash_value,
             len(old_markup),zlib.compress(old_markup)))
        before=conn.execute('SELECT * FROM spell_detail_snapshots WHERE batch_id=? AND spell_id=?',(batch,sid)).fetchone()
        before_details=conn.execute('SELECT * FROM spell_details WHERE batch_id=? AND spell_id=?',(batch,sid)).fetchone()
        # Simulate an explicitly forced recapture; normal resume would skip a
        # valid snapshot, which is separately tested by the existing suite.
        def forced_refresh(*args,**kwargs):
            if kwargs.get('spell_id')==sid:
                raise capture.MissingVerifiedSpellDetail('forced recapture')
            raise capture.MissingVerifiedSpellDetail('not required')
        monkeypatch.setattr(capture,'read_verified_spell_detail_snapshot',forced_refresh)
        class Response:status=403
        class Locator:
            def inner_text(self,timeout=None):return 'Access denied'
        class Page:
            url=f'https://www.wowhead.com/forever/spell={sid}'
            def goto(self,*args,**kwargs):return Response()
            def wait_for_timeout(self,*args):return None
            def title(self):return '403 Forbidden'
            def locator(self,*args):return Locator()
            def content(self):return '<html><body>Access denied</body></html>'
        stats=capture.capture_details(Page(),batch_id=batch,db=conn,timeout_ms=1000,
                         settle_ms=0,max_details=1,spell_ids=[sid])
        assert stats['captured']==0 and stats['failed']==1
        assert before==conn.execute('SELECT * FROM spell_detail_snapshots WHERE batch_id=? AND spell_id=?',(batch,sid)).fetchone()
        assert before_details==conn.execute('SELECT * FROM spell_details WHERE batch_id=? AND spell_id=?',(batch,sid)).fetchone()
