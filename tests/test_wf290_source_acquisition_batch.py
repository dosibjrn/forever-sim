"""Nine-class source acquisition batch; negative legal-world tests."""
import json
from pathlib import Path
import sqlite3

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_acquisition import (
    audit_learned_action_legality, read_acquisition_evidence,
)
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.level_legality import LevelState, validate_level_state
from tools.ingest_source_acquisition_evidence_sqlite import ingest

CLASSES = ('druid','hunter','mage','paladin','priest','rogue','shaman','warlock','warrior')


def test_all_nine_class_source_rows_and_hashes():
    with sqlite3.connect(DEFAULT_DB) as db:
        indexed = db.execute("SELECT COUNT(*) FROM spell_index WHERE kind='abilities'").fetchone()[0]
        evidence = db.execute('SELECT COUNT(*) FROM ability_acquisition_evidence').fetchone()[0]
        assert indexed == evidence == 2255
        assert db.execute('SELECT COUNT(DISTINCT class_key) FROM ability_acquisition_evidence').fetchone()[0] == 9
    for key in CLASSES:
        ir = build_game_ir_slice(class_key=key,level=20)
        assert ir is not None
        report = audit_learned_action_legality(ir, level=20, action_ids=(a.id for a in ir.actions))
        assert not report['complete']
        assert report['source_action_count'] == len(ir.actions)
        assert report['verified_world_acquisition_count'] == 0
        assert report['blockers']
        coverage = next(f for f in ir.source_facts if f.get('fact_kind')=='canonical_indexed_ability_coverage')
        assert all(r['acquisition_evidence_status'] not in
                   ('MISSING_ACQUISITION_EVIDENCE','STALE_SOURCE_REINGEST_REQUIRED')
                   for r in coverage['records'])


def test_claimed_learned_rank_still_needs_world_event():
    ir=build_game_ir_slice(class_key='mage',level=20)
    from src.game.data.forever.source_indexed_action_coverage import _source_spell_ids
    action=next(a for a in ir.actions if _source_spell_ids(a))
    ids=_source_spell_ids(action)
    result=audit_learned_action_legality(ir,level=20,action_ids=[action.id],
                                          acquired_spell_ids=ids)
    assert not result['complete']
    assert result['blockers'][0]['status'] in (
        'BLOCKED_ACQUISITION_EVENT_NOT_VERIFIED',
        'BLOCKED_MISSING_OR_STALE_SOURCE_ACQUISITION',
        'BLOCKED_AMBIGUOUS_SOURCE_RANK',
        'BLOCKED_SOURCE_LEVEL_UNKNOWN_OR_TOO_HIGH')


def test_world_route_cannot_inherit_bounded_scenario_legality():
    ir=build_game_ir_slice(class_key='druid',level=20)
    s=LevelState(class_key='druid',level=20,race_key=ir.actor.metadata['race_key'],
                 talents={},action_ids=(ir.actions[0].id,))
    assert validate_level_state(s)['status']=='LEGAL_SOURCE_SCENARIO'
    with pytest.raises(ValueError,match='world acquisition not verified'):
        validate_level_state(s,require_world_acquisition=True)


def test_data_only_stale_index_change_blocks(tmp_path):
    db=tmp_path/'ability.sqlite'
    import shutil
    shutil.copy2(DEFAULT_DB,db)
    with sqlite3.connect(db) as conn:
        sid=conn.execute("SELECT spell_id FROM ability_acquisition_evidence WHERE class_key='mage' LIMIT 1").fetchone()[0]
        conn.execute("UPDATE spell_index SET raw_listview_json='{}' WHERE class_key='mage' AND spell_id=?",(sid,))
    row=read_acquisition_evidence(class_key='mage',spell_ids=[sid],db_path=db)[sid]
    assert row['status']=='STALE_INDEX_EVIDENCE'


def test_ingest_replay_deterministic_and_transactional(tmp_path):
    db=tmp_path/'ability.sqlite'
    import shutil
    shutil.copy2(DEFAULT_DB,db)
    first=ingest(db)
    second=ingest(db)
    assert first==second
    assert first['indexed_abilities']==2255
    assert first['world_acquisition_verified']==0
    with sqlite3.connect(db) as conn:
        count=conn.execute('SELECT COUNT(*) FROM ability_acquisition_evidence').fetchone()[0]
        conn.execute("UPDATE spell_index SET raw_listview_json='not-json' WHERE spell_id=71 AND class_key='warrior'")
    with pytest.raises(json.JSONDecodeError):
        ingest(db)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT COUNT(*) FROM ability_acquisition_evidence').fetchone()[0]==count


def test_detail_snapshot_change_revokes_method_evidence(tmp_path):
    import shutil
    db=tmp_path/'ability.sqlite'
    shutil.copy2(DEFAULT_DB,db)
    with sqlite3.connect(db) as conn:
        key=conn.execute("SELECT class_key,spell_id,index_batch_id FROM ability_acquisition_evidence WHERE detail_html_sha256 IS NOT NULL LIMIT 1").fetchone()
        assert key
        before=read_acquisition_evidence(class_key=key[0],spell_ids=[key[1]],db_path=db)
        assert before[key[1]]['status']=='CURRENT_SOURCE_EVIDENCE'
        conn.execute('UPDATE spell_detail_snapshots SET html_sha256=? WHERE batch_id=? AND spell_id=?',
                     ('tampered',key[2],key[1]))
    after=read_acquisition_evidence(class_key=key[0],spell_ids=[key[1]],db_path=db)
    assert after[key[1]]['status']=='STALE_DETAIL_EVIDENCE'
