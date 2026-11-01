"""Source-driven four-axis joint search: legal frontier, hard deadlines, real 100mob."""
import json
from pathlib import Path
from time import monotonic,sleep

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import validate_talent_selection
import src.v2.source_bounded_joint_frontier as joint

ROOT=Path(__file__).resolve().parents[1]
DRUID=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite'
MAGE=ROOT/'data/forever/staged_mage_l30_talent_positions_70374.sqlite'


def test_source_legal_druid_full_point_frontier_is_fast_diverse_and_never_claims_exhaustion():
    ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=DRUID)
    compiled,coverage=compile_talent_runtime(ir)
    candidates,proof=joint.bounded_full_point_talent_frontier(
        compiled,level=30,max_frontier=6,beam_width=32)
    assert len(candidates)==6
    assert proof['method']=='legal_rank_beam' and not proof['exhaustive']
    assert proof['raw_cartesian_exceeded']>100000
    assert len({joint._key(a) for a in candidates})==6
    for a in candidates:
        assert sum(a.values())==21
        validate_talent_selection(compiled,a,level=30)


def test_mage_exact_supported_space_with_strict_budget_and_no_false_26_points():
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=MAGE)
    compiled,_=compile_talent_runtime(ir)
    allocations,proof=joint.bounded_full_point_talent_frontier(
        compiled,level=30,max_frontier=25)
    assert proof['method']=='exact_supported_subset' and proof['exhaustive']
    assert len(allocations)==21
    assert all(sum(x.values())==21 for x in allocations)
    none,extra=joint.bounded_full_point_talent_frontier(
        compiled,level=30,bonus_talent_points=5)
    assert none==[] and extra['exhaustive']


def test_recovery_source_mode_cycle_is_inferred_not_class_special_cased():
    ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=DRUID)
    stage=json.loads((ROOT/'evidence/wf351/WF351_L30_SEED_STAGE.json').read_text())
    policies=joint._recovery_variants(ir,stage,3)
    assert len(policies)==3
    assert policies[0]==('always',None)
    assert policies[1][1].exit_action_id=='cancel_mode:cat'
    assert policies[1][1].reentry_action_id=='cat_form:768'


def test_candidate_os_watchdog_terminates_stalled_recovery(monkeypatch):
    def stalled_child(*args):
        sleep(10)
    monkeypatch.setattr(joint,'_joint_eval_child',stalled_child)
    t=monotonic()
    result=joint.isolated_joint_evaluation(object(),level=30,mobs=100,timeout_s=.12)
    assert result['status']=='OS_TIMEOUT'
    assert monotonic()-t<2.0


def test_bonus_points_supported_and_invalid_search_budget():
    with pytest.raises(ValueError,match='INVALID_JOINT_SEARCH_BUDGET'):
        joint.search_bounded_joint_frontier(class_key='mage',level=30,
            source_ir=None,seed_stage={},max_paid_builds=0)
    assert joint.available_talent_points(30,bonus_talent_points=5)==26
    with pytest.raises(ValueError,match='INVALID_TALENTED_BONUS_POINTS'):
        joint.search_bounded_joint_frontier(class_key='mage',level=30,
            source_ir=None,seed_stage={},bonus_talent_points=6)


def test_mage_real_gear_talents_apl_recovery_100mob_no_acceptance():
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=MAGE)
    evidence=ROOT/'evidence/wf383/WF383_MAGE_L30_WAND_GEAR_100MOB.json'
    gear=json.loads(evidence.read_text())['baseline']['gear']
    seed=joint.source_gear_seed_stage(gear=gear,ir=ir,source_evidence=str(evidence))
    result=joint.search_bounded_joint_frontier(class_key='mage',level=30,
        source_ir=ir,seed_stage=seed,max_talents=2,max_gear_moves=1,max_policies=2,
        max_recovery_policies=2,max_paid_builds=8,max_cpu_s=18.,
        per_candidate_wall_s=3.)
    assert result['complete_100mob_candidates']>=2
    assert result['winner']['mobs']==100
    assert len({r['allocation'].__repr__() for r in result['rows']})>1
    assert {r['gear_move'] for r in result['rows']}!={'incumbent'}
    assert len({r['recovery'] for r in result['rows']})>1
    assert len({r['policy'] for r in result['rows']})>1
    assert result['enemy']['hp']==955
    assert not result['eligible_for_checkpoint_acceptance']
    assert not result['global_optimum_proven']
    assert not result['source_legal_gear_universe_verified']
