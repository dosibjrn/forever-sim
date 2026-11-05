"""WF414 TDD: independent P4 must not require a previous optimizer winner."""
import json
from pathlib import Path

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_named_gear_proof import audit_named_gear_source
from src.v2.source_bounded_joint_frontier import (
    source_cold_start_stage, bounded_full_point_talent_frontier,
)
from src.v2.source_persistent_joint_finalists import prepare_candidate, evaluate_persistent_candidate


def test_cold_start_is_deterministic_sqlite_only_and_source_legal():
    ir=build_game_ir_slice(class_key='druid',level=20)
    a=source_cold_start_stage(class_key='druid',level=20,source_ir=ir,gear_role='druid_feral')
    b=source_cold_start_stage(class_key='druid',level=20,source_ir=ir,gear_role='druid_feral')
    assert a==b
    assert a['allocation']=={}
    assert a['paid_candidate_origin']=='COLD_SQLITE_SOURCE_NO_PREVIOUS_WINNER'
    assert 'historical' not in json.dumps(a).lower()
    gear=a['gear_policy_result']['winner']['gear']
    assert len(gear['slots'])>=12
    assert audit_named_gear_source(class_key='druid',level=20,gear=gear)['equipment_legality_complete']
    ids={int(item['item_id']) for item in gear['slots'].values()}
    assert len(ids)==len(gear['slots'])


def test_cold_start_produces_a_real_paid_combat_candidate():
    ir=build_game_ir_slice(class_key='druid',level=20)
    stage=source_cold_start_stage(class_key='druid',level=20,source_ir=ir,gear_role='druid_feral')
    talents,proof=bounded_full_point_talent_frontier(ir,level=20,max_frontier=4)
    assert talents and sum(talents[0].values())==11
    candidate=prepare_candidate(class_key='druid',level=20,stage=stage,
        allocation_override=talents[0],source_ir=ir)
    result=evaluate_persistent_candidate(candidate,level=20,mobs=4,max_total_events=100000)
    assert result['status']=='COMPLETE',result
    assert result['count']==4
    assert result['events']>0


def test_cold_start_is_generic_for_mage_l30_with_source_equipment():
    root=Path(__file__).resolve().parents[1]
    ir=build_game_ir_slice(class_key='mage',level=30,
        ability_db_path=root/'data/forever/staged_mage_l30_talent_positions_70374.sqlite')
    stage=source_cold_start_stage(class_key='mage',level=30,source_ir=ir,gear_role='mage')
    assert stage['paid_candidate_origin']=='COLD_SQLITE_SOURCE_NO_PREVIOUS_WINNER'
    gear=stage['gear_policy_result']['winner']['gear']
    assert 'wand' in gear['slots']
    assert len(gear['slots'])>=12
    assert audit_named_gear_source(class_key='mage',level=30,gear=gear)['equipment_legality_complete']
