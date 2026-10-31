"""Source-backed conditional recovery, not a seventh checkpoint gate."""
import json,sqlite3,os
from pathlib import Path
import pytest
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.registry import build_game_ir_slice
from src.game.recovery_between_pulls import BetweenPullPolicy
from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate
from tools.wf321_ingest_control_observations import ingest as ingest_control
ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def source_context(tmp_path_factory):
    old=os.environ.get('WOW_FOREVER_BUILD_AS_OF')
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
    src=tmp_path_factory.mktemp('wf357')/'source.sqlite'
    with sqlite3.connect(f"file:{(ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite').resolve()}?mode=ro",uri=True) as a,sqlite3.connect(src) as b:
        a.backup(b)
    ingest_observations(src,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
    ingest_control(src,ROOT/'evidence/wf321/druid_l20_control_observations.json')
    with ability_source_scope(src):
        ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=src)
        stage=json.loads((ROOT/'evidence/wf353/WF353_L30_P3_BEST_JOINT_ITEM_STAGE.json').read_text())
        candidate=prepare_candidate(class_key='druid',level=30,stage=stage,source_ir=ir,strict_l2_item_effects=True)
        yield candidate
    if old is None:os.environ.pop('WOW_FOREVER_BUILD_AS_OF',None)
    else:os.environ['WOW_FOREVER_BUILD_AS_OF']=old

def test_threshold_recovery_is_paid_and_not_full_each_mob(source_context):
    candidate=source_context
    legacy=evaluate_persistent_candidate(candidate,level=30,mobs=25)
    conditional=evaluate_persistent_candidate(candidate,level=30,mobs=25,
        recovery_policy=BetweenPullPolicy(.25,.1,exit_action_id='cancel_mode:cat',reentry_action_id='cat_form:768'))
    assert legacy['status']==conditional['status']=='COMPLETE'
    assert conditional['mean_s_per_mob']<legacy['mean_s_per_mob']
    assert 1<=conditional['between_pull_full_recoveries']<25
    assert conditional['between_pull_runtime_events']>0
    assert conditional['recovery_s']>0
    assert conditional['continuous_actor_state']

def test_source_hot_is_cast_and_its_ticks_cross_real_mob_boundary(source_context):
    result=evaluate_persistent_candidate(source_context,level=30,mobs=25,
        recovery_policy=BetweenPullPolicy(.5,.2,'rejuvenation:rank@28','cancel_mode:cat','cat_form:768'))
    assert result['status']=='COMPLETE'
    assert result['between_pull_hot_casts']>0
    assert result['carried_hot_ticks_at_pull']>0
    assert result['carried_hot_heals_in_combat']>0
    assert result['between_pull_runtime_events']>0

def test_source_action_legality_and_threshold_fail_closed(source_context):
    with pytest.raises(ValueError,match='INVALID_BETWEEN_PULL_THRESHOLD'):
        BetweenPullPolicy(-.1,.1)
    illegal=evaluate_persistent_candidate(source_context,level=30,mobs=2,
        recovery_policy=BetweenPullPolicy(.5,.2,'claw:28','cancel_mode:cat','cat_form:768'))
    assert illegal['status']=='BLOCKED_SOURCE_BETWEEN_PULL_RECOVERY'
    assert 'RECOVERY_HOT_NOT_SOURCE_PERIODIC_HEAL' in illegal['reason']
    wrong=evaluate_persistent_candidate(source_context,level=30,mobs=2,
        recovery_policy=BetweenPullPolicy(.5,.2,exit_action_id='cat_form:768',reentry_action_id='cancel_mode:cat'))
    assert wrong['status']=='BLOCKED_SOURCE_BETWEEN_PULL_RECOVERY'

def test_event_cap_still_blocks_conditional_recovery(source_context):
    result=evaluate_persistent_candidate(source_context,level=30,mobs=25,max_total_events=10,
        recovery_policy=BetweenPullPolicy(.25,.1,exit_action_id='cancel_mode:cat',reentry_action_id='cat_form:768'))
    assert result['status']=='BLOCKED_EVALUATION_COMPUTE_BUDGET'
    assert result['events']<=10

def test_existing_joint_finalist_search_ranks_recovery_policy_axis(source_context):
    from src.v2.source_persistent_joint_finalists import select_persistent_finalists
    from src.game.data.forever.source_db_scope import ability_source_scope
    from src.game.data.forever.registry import build_game_ir_slice
    stage=json.loads((ROOT/'evidence/wf353/WF353_L30_BEST_INDEPENDENT_P3_STAGE.json').read_text())
    # A source-legal independently discovered stage; no legacy winner seed.
    with ability_source_scope(ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite'):
        result=select_persistent_finalists(class_key='druid',level=30,
            joint_result={'stages':[stage]},screen_mobs=2,finalist_mobs=5,
            max_screen_candidates=2,max_finalists=2,
            recovery_policies=(None,BetweenPullPolicy(.25,.1,exit_action_id='cancel_mode:cat',reentry_action_id='cat_form:768')),
            strict_l2_item_effects=True)
    assert result['status']=='PERSISTENT_VERIFIED_BOUNDED'
    assert result['screen_evaluated']==2
    assert result['finalists_evaluated']==2
    assert {r['recovery_policy'] is None for r in result['finalists']}=={True,False}
    assert all(r['persistent']['count']==5 for r in result['finalists'])
