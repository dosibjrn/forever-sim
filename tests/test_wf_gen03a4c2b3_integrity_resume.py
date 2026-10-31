"""W .212: resume must verify existing HTML, not trust row presence."""
import sqlite3

import pytest

from tools.capture_forever_abilities_sqlite import initialize_db, capture_details
from src.v2.source_sqlite_detail_snapshots import (
    read_verified_spell_detail_snapshot, MissingVerifiedSpellDetail,
)


class Page:
    def __init__(self):
        self.visited = []
        self.url = ''
    def goto(self, url, **kwargs):
        self.url = url
        self.visited.append(url)
        return type('Response', (), {'status': 200})()
    def wait_for_timeout(self, n): pass
    def title(self):
        return f'Spell {self.url.rsplit("=", 1)[-1]} - Wowhead'
    def locator(self, selector):
        return type('Body', (), {'inner_text': lambda _self, **kw: self.title()})()
    def content(self):
        return f'<html><body><h1>{self.title()}</h1></body></html>'


@pytest.fixture
def db():
    conn = sqlite3.connect(':memory:')
    initialize_db(conn)
    conn.execute("INSERT INTO capture_batches VALUES ('b','now','src',NULL,'complete',NULL)")
    conn.execute("INSERT INTO capture_lists VALUES ('b','mage','abilities','src',2,2,1,NULL,NULL)")
    for spell in (101, 202):
        conn.execute('INSERT INTO spell_index VALUES (?,?,?,?,?,?,?,?,?)',
                     ('b','mage','abilities',spell,f'Spell {spell}',None,None,
                      f'https://www.wowhead.com/forever/spell={spell}','{}'))
    conn.commit()
    yield conn
    conn.close()


def capture(db, page, max_details=None, spell_ids=None):
    return capture_details(page,batch_id='b',db=db,timeout_ms=1000,
                           settle_ms=0,max_details=max_details,spell_ids=spell_ids)


def test_valid_snapshot_skipped_without_browser_and_row_factory_restored(db):
    page=Page()
    assert capture(db,page,spell_ids=[101])['captured']==1
    assert db.row_factory is None
    fresh=Page()
    assert capture(db,fresh,spell_ids=[101]) == {
        'found':0,'captured':0,'skipped':1,'failed':0}
    assert fresh.visited == []
    assert read_verified_spell_detail_snapshot(db,batch_id='b',spell_id=101)['html_sha256']


@pytest.mark.parametrize('column,value',[
    ('html_sha256','wrong-hash'),
    ('html_zlib',b'broken zlib'),
    ('final_url','https://www.wowhead.com/forever/spell=999'),
])
def test_corrupted_snapshot_is_recaptured(db,column,value):
    page=Page()
    assert capture(db,page,spell_ids=[101])['captured']==1
    db.execute(f'UPDATE spell_detail_snapshots SET {column}=? WHERE batch_id=? AND spell_id=?',
               (value,'b',101))
    db.commit()
    with pytest.raises(MissingVerifiedSpellDetail):
        read_verified_spell_detail_snapshot(db,batch_id='b',spell_id=101)
    fresh=Page()
    result=capture(db,fresh,spell_ids=[101])
    assert result == {'found':1,'captured':1,'skipped':0,'failed':0}
    assert fresh.visited == ['https://www.wowhead.com/forever/spell=101']
    assert read_verified_spell_detail_snapshot(db,batch_id='b',spell_id=101)['html_sha256']
    assert db.execute("SELECT status FROM capture_batches WHERE batch_id='b'").fetchone()[0]=='complete'


def test_limit_applies_to_missing_after_skipping_valid(db):
    assert capture(db,Page(),spell_ids=[101])['captured']==1
    page=Page()
    result=capture(db,page,max_details=1)
    assert result == {'found':1,'captured':1,'skipped':1,'failed':0}
    assert page.visited == ['https://www.wowhead.com/forever/spell=202']


def test_missing_list_authority_forces_recapture_attempt(db):
    assert capture(db,Page(),spell_ids=[101])['captured']==1
    db.execute("UPDATE capture_lists SET complete=0 WHERE batch_id='b'")
    db.commit()
    with pytest.raises(MissingVerifiedSpellDetail):
        read_verified_spell_detail_snapshot(db,batch_id='b',spell_id=101)
    page=Page()
    result=capture(db,page,spell_ids=[101])
    assert result['found']==1 and result['captured']==1
    # Page identity alone does not make a fact executable without complete list authority.
    with pytest.raises(MissingVerifiedSpellDetail):
        read_verified_spell_detail_snapshot(db,batch_id='b',spell_id=101)
