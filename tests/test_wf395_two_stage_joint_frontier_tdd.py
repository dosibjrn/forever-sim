"""WF395 TDD: real source-bounded two-stage search with paid 100-mob finalists."""
from pathlib import Path
import json

from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_bounded_joint_frontier import (search_bounded_joint_frontier,
                                                  source_gear_seed_stage)

ROOT=Path(__file__).resolve().parents[1]


def _scenario(class_key):
    db=ROOT / ('data/forever/staged_mage_l30_talent_positions_70374.sqlite'
               if class_key=='mage' else 'data/forever/staged_druid_l30_talents_70338.sqlite')
    ir=build_game_ir_slice(class_key=class_key,level=30,ability_db_path=db)
    if class_key=='mage':
        evidence=ROOT/'evidence/wf383/WF383_MAGE_L30_WAND_GEAR_100MOB.json'
        gear=json.loads(evidence.read_text())['baseline']['gear']
        stage=source_gear_seed_stage(gear=gear,ir=ir,source_evidence=str(evidence))
    else:
        stage=json.loads((ROOT/'evidence/wf351/WF351_L30_SEED_STAGE.json').read_text())
    return ir,stage


def _assert_real_finalists(result):
    assert result['search_strategy']=='screen_then_full'
    assert result['paid_candidates']>=result['complete_100mob_candidates']+2
    assert result['screen_complete_candidates']>result['complete_100mob_candidates']
    assert result['complete_100mob_candidates']>=1
    assert result['events']>0
    assert result['winner']['status']=='COMPLETE'
    assert result['winner']['mobs']==100
    assert result['winner']['full_events']>0
    assert result['winner']['seconds_per_mob']>0
    assert result['unique_full_builds']<=result['paid_candidates']
    assert result['winner']['seconds_per_mob']==min(
        r['seconds_per_mob'] for r in result['rows'] if r['status']=='COMPLETE')
    assert all(r.get('seconds_per_mob') is None for r in result['rows']
               if r['status']!='COMPLETE')
    assert result['screen_phase_wall_s']>0
    assert result['finalist_phase_wall_s']>0
    assert not result['eligible_for_checkpoint_acceptance']


def test_mage_two_stage_paid_search_reaches_many_screens_and_real_100mob_finalists():
    ir,stage=_scenario('mage')
    result=search_bounded_joint_frontier(class_key='mage',level=30,
        source_ir=ir,seed_stage=stage,max_talents=1,max_gear_moves=1,
        max_policies=12,max_recovery_policies=2,max_paid_builds=24,
        max_cpu_s=14.,per_candidate_wall_s=3.,screen_then_finalists=True,
        max_finalists=3)
    _assert_real_finalists(result)
    assert result['screen_complete_candidates']>=6
    assert len({r['policy_signature'] for r in result['rows']})>=4
    assert any(r['gear_move']!='incumbent' for r in result['rows'])
    assert any(r['recovery']!='incumbent' for r in result['rows'])


def test_druid_two_stage_search_preserves_full_100mob_and_reports_four_axes():
    ir,stage=_scenario('druid')
    result=search_bounded_joint_frontier(class_key='druid',level=30,
        source_ir=ir,seed_stage=stage,max_talents=2,max_gear_moves=1,
        max_policies=5,max_recovery_policies=2,max_paid_builds=25,
        max_cpu_s=25.,per_candidate_wall_s=5.,screen_then_finalists=True,
        max_finalists=3)
    _assert_real_finalists(result)
    assert result['talent_allocations_proposed']>=2
    assert result['policy_variants']>=2
    assert result['recovery_variants']>=2
    assert result['full_evaluated_candidates']<=3
    assert result['screen_complete_candidates']>=result['full_evaluated_candidates']


def test_two_stage_finalist_budget_must_be_positive():
    ir,stage=_scenario('mage')
    try:
        search_bounded_joint_frontier(class_key='mage',level=30,
            source_ir=ir,seed_stage=stage,max_cpu_s=2.,
            screen_then_finalists=True,max_finalists=0)
    except ValueError as e:
        assert 'INVALID_JOINT_SEARCH_BUDGET' in str(e)
    else:
        raise AssertionError('zero finalist budget must not silently run a screen-only search')
