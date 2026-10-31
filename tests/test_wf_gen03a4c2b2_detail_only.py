"""Fail-closed detail-only batch source selection regression."""
import sqlite3
from pathlib import Path
import pytest
from tools.capture_forever_abilities_sqlite import capture_details, initialize_db

class FakePage:
    def __init__(self): self.visited=[];self.url=''
    def goto(self, url, **kwargs):
        self.visited.append(url);self.url=url
        class Resp: status=200
        return Resp()
    def wait_for_timeout(self, milliseconds): pass
    def title(self): return 'Wrong page'
    class _Body:
        def inner_text(self, **kw): return 'not verified'
    def locator(self, what): return self._Body()
    def content(self): return '<html><body>not verified</body></html>'

def setup(db):
    initialize_db(db)
    db.execute("INSERT INTO capture_batches VALUES ('b','now','src',NULL,'complete',NULL)")
    db.execute("INSERT INTO capture_lists VALUES ('b','mage','abilities','src',2,2,1,NULL,NULL)")
    for i in (101, 202):
        db.execute('INSERT INTO spell_index VALUES (?,?,?,?,?,?,?,?,?)', ('b','mage','abilities',i, f'Test {i}',None,None,f'https://www.wowhead.com/forever/spell={i}','{}'))
    db.commit()

def test_only_requested_indexed_id_is_visited_and_invalid_page_rejected():
    db=sqlite3.connect(':memory:');setup(db);page=FakePage()
    stats=capture_details(page,batch_id='b',db=db,timeout_ms=500,settle_ms=0,max_details=20,spell_ids=[202])
    assert stats == dict(found=1,captured=0,skipped=0,failed=1)
    assert page.visited == ['https://www.wowhead.com/forever/spell=202']
    assert db.execute('SELECT count(*) FROM spell_detail_snapshots').fetchone()[0] == 0
    assert db.execute('SELECT status FROM capture_batches').fetchone()[0] == 'complete'

def test_missing_spell_id_fails_before_any_navigation():
    db=sqlite3.connect(':memory:');setup(db);page=FakePage()
    with pytest.raises(ValueError,match='not indexed'):
        capture_details(page,batch_id='b',db=db,timeout_ms=500,settle_ms=0,max_details=20,spell_ids=[999])
    assert not page.visited

def test_unfiltered_small_batch_cap():
    db=sqlite3.connect(':memory:');setup(db);page=FakePage()
    stats=capture_details(page,batch_id='b',db=db,timeout_ms=500,settle_ms=0,max_details=1)
    assert stats['found'] == 1
    assert len(page.visited)==1
