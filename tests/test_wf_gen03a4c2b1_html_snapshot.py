"""W .210: source HTML must be durable, identifiable and hash-verifiable."""
from pathlib import Path
import sqlite3

import pytest

from tools.capture_forever_abilities_sqlite import initialize_db, capture_details
from src.v2.source_sqlite_detail_snapshots import (
    materialize_spell_detail_snapshot, MissingVerifiedSpellDetail, verified_spell_page,
)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / 'source.sqlite'
    with sqlite3.connect(path) as conn:
        initialize_db(conn)
        conn.execute('INSERT INTO capture_batches VALUES (?,?,?,?,?,?)',
                     ('batch', '2026-10-09T00:00:00Z', 'https://www.wowhead.com/forever', None, 'complete', None))
        for klass, spell, name in [('druid', 5176, 'Wrath'), ('mage', 116, 'Frostbolt')]:
            conn.execute('INSERT INTO capture_lists VALUES (?,?,?,?,?,?,?,?,?)',
                         ('batch', klass, 'abilities', f'https://www.wowhead.com/forever/spells/abilities/{klass}',
                          1, 1, 1, None, 'list-sha'))
            conn.execute('INSERT INTO spell_index VALUES (?,?,?,?,?,?,?,?,?)',
                         ('batch', klass, 'abilities', spell, name, 1, 1,
                          f'https://www.wowhead.com/forever/spell={spell}', '{}'))
        conn.commit()
    return path


class Page:
    def __init__(self, name_by_id, *, status=200, bad_id=False, blocked=False):
        self.name_by_id = name_by_id
        self.status = status
        self.bad_id = bad_id
        self.blocked = blocked
    def goto(self, url, **kwargs):
        self.url = url if not self.bad_id else 'https://www.wowhead.com/forever/spell=99999'
        return type('Response', (), {'status': self.status})()
    def wait_for_timeout(self, n): pass
    def _name(self):
        return self.name_by_id.get(int(self.url.split('=')[-1]), 'Unrelated Spell')
    def title(self): return f'{self._name()} - Wowhead'
    def locator(self, s):
        text = 'Access denied' if self.blocked else f'{self._name()} is a spell'
        return type('Body', (), {'inner_text': lambda _self, **kw: text})()
    def content(self): return f'<html><body><h1>{self._name()}</h1><p>Raw page snapshot</p></body></html>'


def test_valid_cross_class_capture_and_readback(db):
    with sqlite3.connect(db) as conn:
        result = capture_details(Page({5176: 'Wrath', 116: 'Frostbolt'}),
                                 batch_id='batch', db=conn, timeout_ms=1000, settle_ms=0, max_details=2)
        assert result['captured'] == 2 and result['failed'] == 0
        assert conn.execute('SELECT count(*) FROM spell_detail_snapshots').fetchone()[0] == 2
    for spell, name in [(5176, 'Wrath'), (116, 'Frostbolt')]:
        fact = materialize_spell_detail_snapshot(db, batch_id='batch', spell_id=spell)
        assert f'<h1>{name}</h1>' in fact['html']
        assert fact['lineage']['row_key'] == {'batch_id': 'batch', 'spell_id': spell}
        assert 'not_verified_executable' in fact['scope']


def test_capture_rejects_wrong_page_and_blocked_page(db):
    with sqlite3.connect(db) as conn:
        assert capture_details(Page({5176: 'Wrath'}, bad_id=True), batch_id='batch', db=conn,
                               timeout_ms=1000, settle_ms=0, max_details=1)['failed'] == 1
        assert conn.execute('SELECT count(*) FROM spell_detail_snapshots').fetchone()[0] == 0
        assert capture_details(Page({5176: 'Wrath'}, blocked=True), batch_id='batch', db=conn,
                               timeout_ms=1000, settle_ms=0, max_details=1)['failed'] == 1
    with pytest.raises(MissingVerifiedSpellDetail):
        materialize_spell_detail_snapshot(db, batch_id='batch', spell_id=5176)


def test_snapshot_tampering_detected(db):
    with sqlite3.connect(db) as conn:
        capture_details(Page({116: 'Frostbolt'}), batch_id='batch', db=conn,
                        timeout_ms=1000, settle_ms=0, max_details=1)
        conn.execute("UPDATE spell_detail_snapshots SET html_sha256='tampered' WHERE spell_id=116")
        conn.commit()
    with pytest.raises(MissingVerifiedSpellDetail, match='integrity'):
        materialize_spell_detail_snapshot(db, batch_id='batch', spell_id=116)


def test_old_text_only_detail_recaptured(db):
    with sqlite3.connect(db) as conn:
        conn.execute('INSERT INTO spell_details VALUES (?,?,?,?,?,?,?,?)',
                     ('batch', 116, 'https://www.wowhead.com/forever/spell=116', 'Frostbolt',
                      'Frostbolt', 'old-sha', '2026-10-08T00:00:00Z', 1))
        conn.commit()
        assert capture_details(Page({116: 'Frostbolt'}), batch_id='batch', db=conn,
                               timeout_ms=1000, settle_ms=0, max_details=1)['captured'] == 1
        assert conn.execute('SELECT spell_id FROM spell_detail_snapshots').fetchone()[0] == 116


def test_missing_and_cross_batch_fail_closed(db):
    with pytest.raises(MissingVerifiedSpellDetail):
        materialize_spell_detail_snapshot(db, batch_id='batch', spell_id=116)
    with pytest.raises(MissingVerifiedSpellDetail):
        materialize_spell_detail_snapshot(db, batch_id='other', spell_id=5176)


@pytest.mark.parametrize('kwargs', [
    {'status': 403}, {'final_url': 'https://evil.example/forever/spell=116'},
    {'final_url': 'https://www.wowhead.com/forever/spell=1167'},
    {'title': 'Unrelated', 'body': 'Unrelated'},
    {'body': 'Checking your browser - Frostbolt'},
])
def test_identity_fail_closed(kwargs):
    args = dict(spell_id=116, names=['Frostbolt'], final_url='https://www.wowhead.com/forever/spell=116',
                title='Frostbolt - Wowhead', body='Frostbolt', status=200, html_length=100)
    args.update(kwargs)
    assert verified_spell_page(**args) is False


def test_bundled_database_remains_unverified():
    source = Path(__file__).resolve().parents[1] / 'data/forever/catalogue/forever_abilities.sqlite'
    with pytest.raises(MissingVerifiedSpellDetail):
        materialize_spell_detail_snapshot(source, batch_id='20261008T145657Z', spell_id=5176)


def test_service_status_does_not_count_legacy_text_as_verified(db):
    from src.service.abilities_refresh import catalogue_status
    with sqlite3.connect(db) as conn:
        capture_details(Page({116: 'Frostbolt'}), batch_id='batch', db=conn,
                        timeout_ms=1000, settle_ms=0, max_details=1)
        conn.execute('INSERT INTO spell_details VALUES (?,?,?,?,?,?,?,?)',
                     ('batch', 5176, 'https://www.wowhead.com/forever/spell=5176', 'Wrath',
                      'Wrath', 'legacy', '2026-10-08T00:00:00Z', 1))
        conn.commit()
    stat = catalogue_status(db)
    assert stat['details_verified'] == 1
    assert stat['legacy_details_without_snapshot'] == 1


def test_capture_failure_is_retryable(db):
    with sqlite3.connect(db) as conn:
        assert capture_details(Page({116: 'Frostbolt'}, status=403), batch_id='batch', db=conn,
                               timeout_ms=1000, settle_ms=0, max_details=1)['failed'] == 1
        assert capture_details(Page({116: 'Frostbolt'}), batch_id='batch', db=conn,
                               timeout_ms=1000, settle_ms=0, max_details=1)['captured'] == 1
    assert 'Frostbolt' in materialize_spell_detail_snapshot(db, batch_id='batch', spell_id=116)['html']


def test_staging_gate_verifies_bytes_not_just_row_count(db, monkeypatch):
    from src.service import abilities_refresh as ar
    monkeypatch.setattr(ar, 'CLASSES', ('druid', 'mage'))
    monkeypatch.setattr(ar, 'KINDS', ('abilities',))
    with sqlite3.connect(db) as conn:
        assert capture_details(Page({116: 'Frostbolt'}), batch_id='batch', db=conn,
                               timeout_ms=1000, settle_ms=0, max_details=1)['captured'] == 1
    assert ar._check_staging(db, 'batch', 'details', previous_details=0)['details_verified'] == 1
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE spell_detail_snapshots SET html_sha256='bad' WHERE spell_id=116")
        conn.commit()
    with pytest.raises(ValueError, match='independent verification'):
        ar._check_staging(db, 'batch', 'details', previous_details=0)


def test_valid_slugged_url_and_rank_label():
    assert verified_spell_page(spell_id=116, names=['Frostbolt (Rank 1)'],
        final_url='https://www.wowhead.com/forever/spell=116/frostbolt',
        title='Frostbolt - Wowhead', body='Frostbolt', status=200, html_length=100)
