"""WF436 gate TDD: bounded quick search, independent full-horizon comparison."""
from pathlib import Path
from collections import Counter
from unittest.mock import patch
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_bounded_joint_frontier import search_bounded_joint_frontier, source_cold_start_stage

DB = Path(__file__).resolve().parents[1] / 'data/forever/staged_druid_l30_talents_70338.sqlite'

def fixture():
    ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=DB)
    return ir,source_cold_start_stage(class_key='druid',level=30,source_ir=ir,gear_role='druid_feral')

def test_search_only_never_calls_100mob_and_returns_shortlist_for_outside_validation():
    ir,stage=fixture()
    called=Counter()
    def score(candidate, *, mobs, **kw):
        called[mobs]+=1
        assert mobs<=4,'100MOB_INSIDE_SEARCH_BUDGET'
        return {'status':'COMPLETE','mean_s_per_mob':10.+called[mobs]/100.,
                'events':10,'elapsed_cpu_s':0.0001,'mob_completed':mobs}
    with patch('src.v2.source_bounded_joint_frontier.isolated_joint_evaluation',side_effect=score):
        report=search_bounded_joint_frontier(class_key='druid',level=30,source_ir=ir,
            seed_stage=stage,max_talents=2,max_gear_moves=0,max_policies=2,
            max_recovery_policies=1,max_paid_builds=4,max_cpu_s=5.,
            screen_mobs=4,search_only=True,refinement_top_n=2,refinement_rounds=0)
    assert called[100]==0
    assert report['complete_100mob_candidates']==0
    assert report['search_winner']['screen_status']=='COMPLETE'
    assert report['search_only'] is True
    assert 1<=len(report['validation_shortlist'])<=2
    assert report['winner'] is None  # 100mob evidence not invented


def test_refinement_parameter_contract_rejects_invalid_or_unbudgeted_configuration():
    ir,stage=fixture()
    with pytest.raises(ValueError,match='REFINEMENT'):
        search_bounded_joint_frontier(class_key='druid',level=30,source_ir=ir,
            seed_stage=stage,search_only=True,refinement_top_n=0)
    with pytest.raises(ValueError,match='REFINEMENT'):
        search_bounded_joint_frontier(class_key='druid',level=30,source_ir=ir,
            seed_stage=stage,search_only=True,refinement_rounds=-1)


def test_independent_full_horizon_validation_detects_search_ranking_reversal():
    from src.v2.source_bounded_joint_frontier import independently_compare_shortlist
    rows=[{'id':'fast','screen_s_per_mob':2.0}, {'id':'slow','screen_s_per_mob':3.0}]
    calls=[]
    def replay(row):
        calls.append(row['id'])
        return {'status':'COMPLETE','count':100,'events':1000,
                'mean_s_per_mob':12.0 if row['id']=='fast' else 9.0}
    result=independently_compare_shortlist(rows,replay,max_mobs=100)
    assert calls==['fast','slow']
    assert result['search_winner_id']=='fast'
    assert result['validated_winner_id']=='slow'
    assert result['ranking_reversal'] is True
    assert result['status']=='SEARCH_RANKING_REVERSAL'
    assert result['100mob_replays']==2


def test_shortlist_serializes_source_gear_policy_and_independent_real_replay():
    from src.v2.source_bounded_joint_frontier import replay_joint_shortlist_100mob
    ir,stage=fixture()
    report=search_bounded_joint_frontier(class_key='druid',level=30,
        source_ir=ir,seed_stage=stage,bonus_talent_points=5,
        max_talents=2,max_gear_moves=2,max_policies=2,max_recovery_policies=1,
        max_paid_builds=5,max_cpu_s=8.,screen_mobs=2,
        per_candidate_wall_s=2.,search_only=True,
        refinement_top_n=2,refinement_rounds=1,
        refinement_stat_axes=('spell_power','intellect'),
        refinement_probe_delta=20.,refinement_gear_candidates=2,
        refinement_policy_candidates=2)
    assert report['refinement']['stat_probes'] >= 2
    assert report['refinement']['gear_probes'] >= 1
    assert report['refinement']['policy_probes'] >= 1
    assert report['complete_100mob_candidates']==0
    assert all('equipped_gear' in x and 'opening_action_ids' in x for x in report['validation_shortlist'])
    # Running 100 mobs is a separate acceptance action, with its own timer.
    replay=replay_joint_shortlist_100mob(report,source_ir=ir,seed_stage=stage,
        class_key='druid',level=30,bonus_talent_points=5,
        max_per_candidate_wall_s=25.)
    assert replay['100mob_replays']==len(report['validation_shortlist'])
    assert replay['complete_100mob_replays']==len(report['validation_shortlist'])
    assert replay['wall_s_outside_search_budget']>0
    assert replay['search_wall_s']<=8.5
    assert replay['total_100mob_events']>100


def test_p6_two_independent_winners_have_saturation_comparison_after_search():
    from src.v2.source_bounded_joint_frontier import compare_30_300_independent_100mob
    p30={'winner':{'id':'a'}, 'search_wall_s':29.9}
    p300={'winner':{'id':'b'},'search_wall_s':299.5}
    replay=lambda record: {'status':'COMPLETE','count':100,'events':1200,
                           'mean_s_per_mob':10.04 if record['id']=='a' else 10.00}
    result=compare_30_300_independent_100mob(p30,p300,replay)
    assert result['status']=='P6_PASS'
    assert result['T30_s_per_mob']==10.04
    assert result['T300_s_per_mob']==10.00
    assert result['validation_outside_search_budgets'] is True
    p30['winner']['id']='c'
    replay2=lambda record: {'status':'COMPLETE','count':100,'events':1200,
                            'mean_s_per_mob':10.2 if record['id']=='c' else 10.0}
    assert compare_30_300_independent_100mob(p30,p300,replay2)['status']=='P6_FAIL'


def test_quick_direct_backend_runs_canonical_runtime_without_child_process_and_never_100mob():
    ir,stage=fixture()
    with patch('src.v2.source_bounded_joint_frontier.isolated_joint_evaluation',
               side_effect=AssertionError('SPAWNED_WORKER_IN_QUICK_DIRECT_SEARCH')):
        r=search_bounded_joint_frontier(class_key='druid',level=30,
            source_ir=ir,seed_stage=stage,bonus_talent_points=5,
            max_talents=2,max_gear_moves=0,max_policies=2,
            max_recovery_policies=1,max_paid_builds=4,max_cpu_s=4.,
            screen_mobs=2,per_candidate_wall_s=1.,search_only=True,
            screen_evaluator_backend='direct',refinement_rounds=0)
    assert r['search_only'] is True
    assert r['screen_evaluator_backend']=='direct'
    assert r['complete_100mob_candidates']==0
    assert r['screen_complete_candidates']>0
    assert r['events']>0


def test_direct_backend_refuses_full_horizon_or_legacy_full_search():
    ir,stage=fixture()
    for kwargs in ({'search_only':False},{'search_only':True,'screen_mobs':100}):
        with pytest.raises(ValueError,match='QUICK_DIRECT'):
            search_bounded_joint_frontier(class_key='druid',level=30,
                source_ir=ir,seed_stage=stage,screen_evaluator_backend='direct',
                **kwargs)


def test_real_source_paid_shortlist_never_replays_same_full_build_twice():
    """A repeated paid source configuration must not consume two 100-mob slots."""
    from copy import deepcopy
    from src.v2.source_bounded_joint_frontier import _select_screen_finalists
    ir,stage=fixture()
    report=search_bounded_joint_frontier(
        class_key='druid',level=30,source_ir=ir,seed_stage=stage,
        bonus_talent_points=5,max_talents=2,max_gear_moves=0,
        max_policies=2,max_recovery_policies=1,max_paid_builds=4,
        max_cpu_s=5.,screen_mobs=2,per_candidate_wall_s=1.,
        search_only=True,screen_evaluator_backend='direct',
        refinement_top_n=1,refinement_rounds=0)
    assert report['validation_shortlist'], report['status']
    actual_paid_row=report['validation_shortlist'][0]
    assert actual_paid_row['screen_status']=='COMPLETE'
    # The search can reach one identical build through two frontier paths.
    # Both entries are backed by the SAME real paid CombatRuntime screen.
    shortlisted=_select_screen_finalists([
        (actual_paid_row,None,None),
        (deepcopy(actual_paid_row),None,None),
    ],max_finalists=2)
    assert len(shortlisted)==1, 'DUPLICATE_FULL_BUILD_WOULD_REPLAY_100_MOBS_TWICE'
