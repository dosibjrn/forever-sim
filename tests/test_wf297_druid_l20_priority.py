"""First v4.2 named 36-checkpoint order is Druid L20, never L10-first."""
from __future__ import annotations
import pytest
from tools.wf297_druid_l20_checkpoint import JOINT_ARGS, run


def test_first_checkpoint_is_druid_l20_and_allocates_real_named_gear_budget():
    assert JOINT_ARGS['class_key']=='druid' and JOINT_ARGS['level']==20
    assert JOINT_ARGS['max_evaluations']>=JOINT_ARGS['evaluations_per_talent']
    assert JOINT_ARGS['required_level_policy']=='observed'
    assert JOINT_ARGS['max_gear_states']>0
    assert JOINT_ARGS['initial_search']+1+len(JOINT_ARGS['probe_stats'])*len(JOINT_ARGS['probe_deltas'])+JOINT_ARGS['search_per_gear']<=JOINT_ARGS['evaluations_per_talent']


def test_live_first_milestone_new_versus_frozen_old_scratch_l2_and_blockers():
    x=run()
    assert x['prioritized_case']=='druid:L20'
    assert x['comparison']['same_engine_L2'] and x['comparison']['held_out_not_seeded']
    assert x['comparison']['new_beats_old']
    assert x['comparison']['new_minus_old_s_per_mob']<0
    assert x['comparison']['winner_independent_scratch_replay_s_per_mob']==pytest.approx(x['comparison']['new_score_s_per_mob'],abs=1e-9)
    assert x['search']['winner']['gear_policy_result']['winner']['gear'] is not None
    assert x['comparison']['search_l2_attempts']<=JOINT_ARGS['max_evaluations']
    assert x['comparison']['search_executor_events']<=JOINT_ARGS['max_event_transitions']
    assert not x['formal_validated_checkpoint'] and x['new_checkpoint_count']==0
    assert x['source_completeness']['unrepresented']>0
    assert not x['wall_or_XP_routes_required']
