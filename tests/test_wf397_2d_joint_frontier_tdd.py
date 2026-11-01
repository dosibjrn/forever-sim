"""WF397: same sourced joint search must pay a real 20yd concurrent pack objective."""
import json
from pathlib import Path

from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_persistent_joint_finalists import prepare_candidate
from src.v2.source_bounded_joint_frontier import (
    isolated_joint_evaluation, search_bounded_joint_frontier)

ROOT=Path(__file__).resolve().parents[1]


def _scenario():
    ir=build_game_ir_slice(class_key='druid',level=30,
        ability_db_path=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite')
    stage=json.loads((ROOT/'evidence/wf351/WF351_L30_SEED_STAGE.json').read_text())
    return ir,stage


def test_same_prepared_source_candidate_runs_100_real_2d_mobs_with_incoming_and_recovery():
    ir,stage=_scenario()
    candidate=prepare_candidate(class_key='druid',level=30,stage=stage,
        source_ir=ir,allow_partial_gear_stats=True)
    result=isolated_joint_evaluation(candidate,level=30,mobs=100,
        pack_size=2,timeout_s=12.)
    assert result['status']=='COMPLETE'
    assert result['mob_completed']==100
    assert result['packs']==50
    assert result['pack_size']==2
    assert result['spatial_mode']=='simultaneous_2d_pack'
    assert result['incoming_attacks_scheduled'] is True
    assert result['recovery_s']>0
    assert result['events']>0
    assert result['mean_s_per_mob']>0


def test_source_pack_actions_are_proven_by_executed_runtime_events():
    # Actual sourced Druid + 2D CombatRuntime, not a mock or proxy policy.
    from src.v2.source_persistent_joint_finalists import evaluate_persistent_candidate
    ir,stage=_scenario()
    candidate=prepare_candidate(class_key='druid',level=30,stage=stage,
        source_ir=ir,allow_partial_gear_stats=True)
    result=evaluate_persistent_candidate(candidate,level=30,mobs=2,pack_size=2)
    assert result['status']=='COMPLETE', result
    assert result['count']==2
    # A completed pack must expose the executed source actions; otherwise
    # independent spec-mode validation falsely rejects a legal 100-mob replay.
    assert sum(result['source_action_counts'].values())>0


def test_2d_four_axis_joint_search_uses_real_100mob_finalists_not_only_screens():
    ir,stage=_scenario()
    result=search_bounded_joint_frontier(class_key='druid',level=30,
        source_ir=ir,seed_stage=stage,max_talents=1,max_gear_moves=0,
        max_policies=2,max_recovery_policies=1,max_paid_builds=3,
        max_cpu_s=22.,per_candidate_wall_s=9.,screen_then_finalists=True,
        max_finalists=1,pack_size=2)
    assert result['pack_size']==2
    assert result['spatial_mode']=='simultaneous_2d_pack'
    assert result['screen_complete_candidates']>=1
    assert result['complete_100mob_candidates']>=1
    assert result['winner']['status']=='COMPLETE'
    assert result['winner']['mobs']==100
    assert result['winner']['seconds_per_mob']>0
    assert result['winner']['full_events']>0
    assert not result['eligible_for_checkpoint_acceptance']


def test_invalid_2d_pack_size_does_not_fall_back_to_sequential():
    ir,stage=_scenario()
    try:
        search_bounded_joint_frontier(class_key='druid',level=30,
            source_ir=ir,seed_stage=stage,pack_size=0)
    except ValueError as e:
        assert 'INVALID_JOINT_SEARCH_BUDGET' in str(e)
    else:
        raise AssertionError('invalid pack size must not be silently treated as 1')
