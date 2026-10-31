"""One structurally unusual detail must not erase the other verified pages."""
from __future__ import annotations
from hashlib import sha256
from pathlib import Path
import sqlite3,zlib
import pytest

from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.v2.source_sqlite_detail_snapshots import read_verified_spell_detail_snapshot
from src.game.data.forever.source_verified_detail_effects import ingest as ingest_effects,read_current_effects
from src.game.data.forever.source_verified_detail_headers import read_current_header
from tools.wf292_ingest_verified_detail_headers_sqlite import ingest as ingest_headers


def stage(tmp_path):
    p=tmp_path/'stage.sqlite'
    with sqlite3.connect(DEFAULT_DB) as src,sqlite3.connect(p) as dst:src.backup(dst)
    return p


def _replace_html(db, batch, sid, html):
    raw=html.encode();h=sha256(raw).hexdigest()
    db.execute('UPDATE spell_details SET html_sha256=? WHERE batch_id=? AND spell_id=?',(h,batch,sid))
    db.execute('''UPDATE spell_detail_snapshots SET html_sha256=?,html_bytes=?,html_zlib=?
        WHERE batch_id=? AND spell_id=?''',(h,len(raw),zlib.compress(raw),batch,sid))
    db.commit()


def test_structural_drift_quarantines_only_one_verified_page(tmp_path):
    p=stage(tmp_path)
    with sqlite3.connect(p) as db:
        batch=db.execute("SELECT batch_id FROM spell_index WHERE class_key='mage' AND spell_id=133").fetchone()[0]
        original=read_verified_spell_detail_snapshot(db,batch_id=batch,spell_id=133)['html']
        assert 'id="spelldetails"' in original
        _replace_html(db,batch,133,original.replace('id="spelldetails"','id="unknown-detail-grid"',1))
        # The page remains an identity-verified HTML source; its structured
        # effect layout is unknown. It must NOT be treated as a zero-effect cast.
        read_verified_spell_detail_snapshot(db,batch_id=batch,spell_id=133)
    with pytest.raises(ValueError,match='STRUCTURED_SPELL_DETAILS'):
        ingest_effects(p)
    result=ingest_effects(p,quarantine_structural_errors=True)
    assert result['verified_pages']==19 and result['quarantined_source_pages']==1
    assert result['effect_slots']<36
    with sqlite3.connect(p) as db:
        assert db.execute("SELECT COUNT(*) FROM verified_source_ingest_blockers WHERE stage='effects'").fetchone()[0]==1
        assert db.execute('SELECT COUNT(*) FROM verified_spell_detail_effect_headers WHERE class_key=? AND spell_id=?',('mage',133)).fetchone()[0]==0
        with pytest.raises(ValueError,match='QUARANTINED'):
            read_current_effects(db,class_key='mage',spell_id=133)
        assert read_current_effects(db,class_key='priest',spell_id=139)['effects']
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        _replace_html(db,batch,133,original)
    result=ingest_effects(p,quarantine_structural_errors=True)
    assert result['verified_pages']==20 and result['quarantined_source_pages']==0
    with sqlite3.connect(p) as db:
        assert db.execute("SELECT COUNT(*) FROM verified_source_ingest_blockers WHERE stage='effects'").fetchone()[0]==0
        assert len(read_current_effects(db,class_key='mage',spell_id=133)['effects'])==2


def test_header_level_drift_is_explicit_not_a_silent_rank(tmp_path):
    p=stage(tmp_path)
    with sqlite3.connect(p) as db:
        db.execute("UPDATE spell_index SET level_hint=level_hint+1 WHERE class_key='mage' AND spell_id=133 AND kind='abilities'")
        db.commit()
    with pytest.raises(ValueError,match='LEVEL_DRIFT'):
        ingest_headers(p)
    result=ingest_headers(p,quarantine_structural_errors=True)
    assert result['indexed_source_verified_headers']==19
    assert result['quarantined_source_pages']==1
    with sqlite3.connect(p) as db:
        with pytest.raises(ValueError,match='QUARANTINED'):
            read_current_header(db,class_key='mage',spell_id=133)
        assert read_current_header(db,class_key='priest',spell_id=139) is not None
        db.execute("UPDATE spell_index SET level_hint=level_hint-1 WHERE class_key='mage' AND spell_id=133 AND kind='abilities'")
        db.commit()
    result=ingest_headers(p,quarantine_structural_errors=True)
    assert result['indexed_source_verified_headers']==20
    assert result['quarantined_source_pages']==0


def test_corrupt_html_does_not_enter_typed_ledger(tmp_path):
    p=stage(tmp_path)
    with sqlite3.connect(p) as db:
        batch=db.execute("SELECT batch_id FROM spell_index WHERE class_key='mage' AND spell_id=133").fetchone()[0]
        db.execute('UPDATE spell_detail_snapshots SET html_sha256=? WHERE batch_id=? AND spell_id=?',('0'*64,batch,133))
        db.commit()
    result=ingest_effects(p,quarantine_structural_errors=True)
    assert result['verified_pages']==19 and result['quarantined_source_pages']==1
    with sqlite3.connect(p) as db:
        with pytest.raises(ValueError,match='QUARANTINED'):
            read_current_effects(db,class_key='mage',spell_id=133)


def test_full_existing_typed_pipeline_keeps_good_pages_after_bad_one(tmp_path):
    from tools.wf292_batch_verified_source_recovery import typed_ingest_stage
    p=stage(tmp_path);q=tmp_path/'typed.sqlite'
    with sqlite3.connect(p) as db:
        batch=db.execute("SELECT batch_id FROM spell_index WHERE class_key='mage' AND spell_id=133").fetchone()[0]
        html=read_verified_spell_detail_snapshot(db,batch_id=batch,spell_id=133)['html']
        _replace_html(db,batch,133,html.replace('id="spelldetails"','id="unknown-detail-grid"',1))
    result=typed_ingest_stage(source_stage=p,typed_stage=q)
    assert result['ingested']['verified_detail_effect_slots']['verified_pages']==19
    assert result['ingested']['verified_detail_effect_slots']['quarantined_source_pages']==1
    assert result['executable_promotions']==0 and result['accepted_checkpoints']==0
    with sqlite3.connect(q) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute("SELECT COUNT(*) FROM verified_source_ingest_blockers WHERE stage='effects'").fetchone()[0]==1
        assert read_current_effects(db,class_key='priest',spell_id=139)['effects']
    # Fetch stage itself is unchanged by typed ingestion.
    with sqlite3.connect(p) as db:
        assert db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='verified_source_ingest_blockers'").fetchone()[0]==0


def test_quarantine_reaches_nine_class_source_coverage_gate(tmp_path):
    from src.game.data.forever.registry import build_game_ir_slice
    from src.game.data.forever.source_indexed_action_coverage import indexed_ability_coverage
    p=stage(tmp_path)
    with sqlite3.connect(p) as db:
        batch=db.execute("SELECT batch_id FROM spell_index WHERE class_key='mage' AND spell_id=133").fetchone()[0]
        html=read_verified_spell_detail_snapshot(db,batch_id=batch,spell_id=133)['html']
        _replace_html(db,batch,133,html.replace('id="spelldetails"','id="bad-detail-grid"',1))
    from tools.wf292_batch_verified_source_recovery import typed_ingest_stage
    typed=tmp_path/'typed.sqlite'
    typed_ingest_stage(source_stage=p,typed_stage=typed)
    ir=build_game_ir_slice(class_key='mage',level=20)
    report=indexed_ability_coverage(ir,class_key='mage',level=20,db_path=typed)
    assert report['source_verified_quarantined_rank_count']==1
    row=next(x for x in report['records'] if x['spell_id']==133)
    assert row['status']=='BLOCKED_SOURCE_DETAIL_QUARANTINED'
    assert row['verified_source_quarantine'][0]['stage']=='effects'
    assert report['not_proof_of_legal_action_coverage']
