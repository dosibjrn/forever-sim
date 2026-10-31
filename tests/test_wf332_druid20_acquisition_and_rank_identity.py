"""Druid L20 source-bound spell universe, no invented rune grants."""
import json
import sqlite3
from pathlib import Path

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_indexed_action_coverage import _source_spell_ids
from src.game.data.forever.source_checkpoint_acquisition import acquisition_frontier
from src.game.data.forever.source_checkpoint_l0 import action_frontier
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_index_rank_parity import indexed_rank_identity, IndexedRankParityError


def test_druid20_rank_identity_is_exact_not_legacy_url(monkeypatch):
    monkeypatch.setenv('WOW_FOREVER_BUILD_AS_OF','2026-10-13')
    ir=build_game_ir_slice(class_key='druid',level=20)
    a={x.family_key:x for x in ir.actions if x.id in ('healing_touch:rank@20','rejuvenation:rank@16')}
    assert _source_spell_ids(a['healing_touch'])=={5188}
    assert _source_spell_ids(a['rejuvenation'])=={1430}
    for action in a.values():
        p=action.provenance[0]
        assert p['identity_authority']=='canonical_source_index_identity_only'
        assert p['numeric_and_acquisition_verified'] is False
        assert p['source_url'].endswith('spell='+str(next(iter(_source_spell_ids(action)))))


def test_druid20_acquisition_counts_not_legal_denominator(monkeypatch):
    monkeypatch.setenv('WOW_FOREVER_BUILD_AS_OF','2026-10-13')
    a=acquisition_frontier(class_key='druid',level=20)
    assert a['source_rows_at_or_below_level']==124
    assert a['source_role_counts']=={
        'DETAIL_OBSERVED_NPC_TEACHING_NOT_POSSESSION':1,
        'SOURCE_INDEX_ACQUISITION_HINT_UNVERIFIED':40,
        'NO_ACQUISITION_HINT_POSSIBLE_INTERNAL_OR_GRANTED_ACTION':24,
        'REMOVED_PENDING_PATCH_APPLICABILITY':5,
        'PASSIVE_OR_TALENT_NOT_FREE_CAST':17,
        'EQUIPMENT_RUNE_SETUP_NOT_COMBAT_CAST':37}
    assert not a['legal_active_denominator_proven']
    assert all(not r['free_combat_action_granted_by_index'] for r in a['records'])
    r={x['spell_id']:x for x in a['records']}
    assert r[410025]['category']=='EQUIPMENT_RUNE_SETUP_NOT_COMBAT_CAST'
    assert r[417157]['category']=='NO_ACQUISITION_HINT_POSSIBLE_INTERNAL_OR_GRANTED_ACTION'
    assert r[99]['category']=='DETAIL_OBSERVED_NPC_TEACHING_NOT_POSSESSION'
    assert r[16979]['category']=='NO_ACQUISITION_HINT_POSSIBLE_INTERNAL_OR_GRANTED_ACTION'
    assert r[5188]['category']=='SOURCE_INDEX_ACQUISITION_HINT_UNVERIFIED'
    f=action_frontier(build_game_ir_slice(class_key='druid',level=20),class_key='druid',level=20)
    assert f['source_acquisition_frontier']['source_role_counts']==a['source_role_counts']
    assert f['PASS1'] is False


def test_identity_no_guess_when_absent_and_fail_on_stale(monkeypatch,tmp_path):
    monkeypatch.setenv('WOW_FOREVER_BUILD_AS_OF','2026-10-13')
    assert indexed_rank_identity(class_key='druid',name='Imaginary Spell',required_level=20) is None
    stage=tmp_path/'test.sqlite'
    with sqlite3.connect(DEFAULT_DB) as src,sqlite3.connect(stage) as dst:
        src.backup(dst)
    with sqlite3.connect(stage) as db:
        db.execute("UPDATE spell_index SET raw_listview_json='{}' WHERE class_key='druid' AND spell_id=1430")
    with pytest.raises(IndexedRankParityError,match='IDENTITY_DRIFT'):
        indexed_rank_identity(class_key='druid',name='Rejuvenation',required_level=16,db_path=stage)
    with pytest.raises(ValueError,match='SOURCE_LISTVIEW_SPELL_ID_MISMATCH'):
        acquisition_frontier(class_key='druid',level=20,db_path=stage)


def test_source_evidence_staleness_detected_without_identity_corruption(tmp_path):
    stage=tmp_path/'changed.sqlite'
    with sqlite3.connect(DEFAULT_DB) as src,sqlite3.connect(stage) as dst:
        src.backup(dst)
    with sqlite3.connect(stage) as db:
        row=db.execute("SELECT raw_listview_json FROM spell_index WHERE class_key='druid' AND spell_id=99").fetchone()[0]
        payload=json.loads(row)
        payload['envChange']['after']['text']+=' TEST-ONLY-MUTATION'
        db.execute("UPDATE spell_index SET raw_listview_json=? WHERE class_key='druid' AND spell_id=99",(json.dumps(payload),))
    result=acquisition_frontier(class_key='druid',level=20,db_path=stage)
    r=next(x for x in result['records'] if x['spell_id']==99)
    assert r['category']=='NO_ACQUISITION_HINT_POSSIBLE_INTERNAL_OR_GRANTED_ACTION' or r['category']=='SOURCE_INDEX_ACQUISITION_HINT_UNVERIFIED'
    assert r['acquisition_evidence_status']=='STALE_INDEX_ACQUISITION_EVIDENCE'
    assert r['source_acquisition_verified'] is False


def test_historical_build_does_not_import_future_index_identity(monkeypatch):
    monkeypatch.setenv('WOW_FOREVER_BUILD_AS_OF','2026-10-02')
    assert indexed_rank_identity(class_key='druid',name='Rejuvenation',required_level=16) is None
    ir=build_game_ir_slice(class_key='druid',level=20)
    action=next(a for a in ir.actions if a.id=='rejuvenation:rank@16')
    assert not _source_spell_ids(action)
