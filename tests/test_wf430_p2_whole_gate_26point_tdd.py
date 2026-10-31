"""Gate-level RED is a real 26-point source-bound P2 predicate, not test-count theater."""
from pathlib import Path
import json
import sqlite3
import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.checkpoint_p2_execution_gate import audit_checkpoint_p2_executor
from src.game.data.forever.source_checkpoint_p2 import P2Checkpoint

DB=Path(__file__).resolve().parents[1]/'data/forever/staged_druid_l30_talents_70338.sqlite'

def audit(db=DB,bonus=5):
    ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=db)
    return audit_checkpoint_p2_executor(ir,db_path=db,
        checkpoint=P2Checkpoint('druid',30,source_build='1.60.1.70338'),
        bonus_talent_points=bonus)

def test_current_p2_real_gate_is_red_and_counts_bonus_unlock_correctly():
    r=audit()
    assert r['available_points']==26
    assert r['source_rank_total']==148
    # WF438 implements three previously missing rank executors on the pinned source.
    assert r['reachable_without_executor']==10
    assert r['unreachable_without_executor']==11
    assert r['unreachable_rank_count']==19
    assert r['unresolved_reachability_count']==0
    assert r['rank_application_failure_count']==10
    assert r['source_prerequisite_or_curve_unverified_count']==2
    assert {v['talent_id'] for v in r['source_prerequisite_or_curve_unverified']} == {'natural_reaction','improved_regrowth'}
    assert 'REAL_COMBAT_RUNTIME_SEMANTIC_PARITY_NOT_CERTIFIED' in r['remaining_gate_fail_reasons']
    assert 'STRUCTURAL_WITHIN_PINNED_STAGED_SOURCE' in r['reachability_scope']
    assert not r['green'] and not r['certified_checkpoint']
    by_id={(row['talent_id'],row['rank']):row for row in r['structural_witnesses']}
    for tid in ('natural_reaction','improved_regrowth'):
        assert by_id[(tid,1)]['status']=='RED_NO_EXECUTOR'
        assert sum(by_id[(tid,1)]['witness'].values())==26
    assert ('moonkin_form',1) not in by_id
    assert ('natural_reaction',2) not in by_id
    assert ('improved_regrowth',2) not in by_id

def test_standard_21pt_differs_from_talented_on_26pt():
    r=audit(bonus=0)
    assert r['available_points']==21
    assert r['reachable_without_executor']==7
    assert r['unreachable_without_executor']==14
    assert r['unreachable_rank_count']==31
    assert r['unresolved_reachability_count']==0

def test_tampering_pinned_source_json_refuses_audit(tmp_path):
    altered=tmp_path/'tampered.sqlite'
    with sqlite3.connect(f'file:{DB.resolve()}?mode=ro',uri=True) as source,sqlite3.connect(altered) as dst:
        source.backup(dst)
    with sqlite3.connect(altered) as db:
        db.execute("UPDATE checkpoint_talent_source_catalogue SET source_json = source_json || ' '")
    with pytest.raises(ValueError,match='STAGED_TALENT_SOURCE_HASH_MISMATCH|P2_SOURCE_BUILD_OR_SHA_MISMATCH'):
        audit(altered)

def test_wrong_source_build_refuses_to_certify():
    ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=DB)
    with pytest.raises(ValueError,match='P2_SOURCE_BUILD_OR_SHA_MISMATCH'):
        audit_checkpoint_p2_executor(ir,db_path=DB,
            checkpoint=P2Checkpoint('druid',30,source_build='BAD_BUILD'),
            bonus_talent_points=5)
