"""WF279: real source talent marginal uses paid child L2, not a proxy."""
from dataclasses import replace
import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talents import apply_talent_selection
from src.game.gear import apply_gear_selection
from src.v2.source_budgeted_gear import _fixed_opening_score
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents


def run(probes, events=2600, budget=54):
    return run_source_budgeted_joint_talents(class_key='druid',level=10,
        max_evaluations=budget,evaluations_per_talent=27,
        initial_search=20,search_per_gear=2,max_gear_states=1,
        policy_search_backend='stateful',max_event_transitions=events,
        stateful_use_l1=False,stateful_search_guarded_continuations=True,
        measure_parent_fixed_policy=probes)


def test_child_talent_fixed_policy_paid_l2_and_independently_reproducible():
    r=run(True)
    assert r['status']=='EVALUATED_BOUNDED'
    assert r['attempted']==r['evaluated']+r['blocked']==54
    assert len(r['best_vs_budget'])==r['attempted']
    assert [x['attempt'] for x in r['best_vs_budget']]==list(range(1,r['attempted']+1))
    assert r['fixed_policy_attempts']==2
    assert r['fixed_policy_event_transitions']==sum(
        s['parent_fixed_policy_marginal']['event_transitions']
        for s in r['stages'] if s['parent_fixed_policy_marginal'])
    assert r['fixed_policy_event_transitions']>0
    assert r['fixed_policy_cpu_ns']>0
    assert r['event_transitions']<=2600
    root, child=r['stages'][:2]
    assert root['allocation']=={}
    assert child['allocation']=={'improved_wrath':1}
    fixed=child['parent_fixed_policy_marginal']
    assert fixed['status']=='FULL_L2_VERIFIED'
    assert fixed['fresh_child_executor_no_cross_talent_cache']
    assert fixed['fixed_policy_delta_s_per_mob']==pytest.approx(
        fixed['score_s_per_mob']-root['score_s_per_mob'])
    assert child['reoptimized_marginal_s_per_mob']==pytest.approx(
        child['score_s_per_mob']-root['score_s_per_mob'])
    assert child['source_context_sha256']!=root['source_context_sha256']
    ir=build_game_ir_slice(class_key='druid',level=10)
    talented,_=apply_talent_selection(replace(ir,policies=()),child['allocation'],level=10)
    if fixed['parent_named_gear']:
        g=fixed['parent_named_gear']
        talented,_=apply_gear_selection(talented,aggregate_stats=g['aggregate_stats'],
            selected_items=tuple(g['slots'].values()),source='canonical_sqlite_forever_catalogue')
    events=[]
    score=_fixed_opening_score(talented,fixed['parent_policy'],10,True,meter=events.append)
    assert score==pytest.approx(fixed['score_s_per_mob'])
    assert events==[fixed['event_transitions']]


def test_same_attempt_budget_ablation_is_not_free_probe():
    base=run(False)
    paid=run(True)
    assert base['attempted']==paid['attempted']==54
    assert base['fixed_policy_attempts']==0
    assert paid['fixed_policy_attempts']==2
    assert paid['attempted']==sum(s['attempted'] for s in paid['stages'])
    assert paid['event_transitions']==sum(s['event_transitions'] for s in paid['stages'])+paid['fixed_policy_event_transitions']
    assert all(s['attempted']==s['evaluated']+s['blocked'] for s in paid['stages'])
    assert paid['best_verified_fixed_policy_challenger']['score_s_per_mob']>0
    assert paid['complete_search'] is False


def test_no_uncharged_fixed_probe_when_only_one_attempt_or_no_events():
    one=run(True,budget=1)
    assert one['attempted']==1 and one['fixed_policy_attempts']==0
    exhausted=run(True,budget=54,events=1)
    assert exhausted['event_transitions']<=1
    assert exhausted['fixed_policy_attempts']==0


def test_rogue_unknown_server_formula_remains_explicitly_blocked():
    from src.v2.source_stateful_adapter import stateful_policy_as_prefix
    ir=build_game_ir_slice(class_key='rogue',level=20)
    r=stateful_policy_as_prefix(class_key='rogue',level=20,ir_slice=ir,
        max_evaluations=6,max_event_transitions=300,use_l1=False,
        search_guarded_continuations=True)
    assert any(x['id']=='eviscerate:6761' for x in r['source_blockers'])
    assert r['guarded_l2_attempts']==0


def test_druid_l20_named_gear_fixed_marginal_differs_from_reoptimized_marginal():
    r=run_source_budgeted_joint_talents(class_key='druid',level=20,
        max_evaluations=110,evaluations_per_talent=55,
        initial_search=20,search_per_gear=8,max_gear_states=2,
        policy_search_backend='stateful',max_event_transitions=9000,
        stateful_use_l1=False,stateful_search_guarded_continuations=True,
        measure_parent_fixed_policy=True)
    root, improved=r['stages'][:2]
    assert root['gear_policy_result']['winner']['gear']['slots']
    fixed=improved['parent_fixed_policy_marginal']
    assert fixed['parent_named_gear']['slots']==root['gear_policy_result']['winner']['gear']['slots']
    assert fixed['status']=='FULL_L2_VERIFIED'
    assert fixed['score_s_per_mob']==pytest.approx(14.291666666666664)
    assert improved['score_s_per_mob']==pytest.approx(12.564197514146144)
    assert improved['score_s_per_mob'] < fixed['score_s_per_mob']
    assert improved['reoptimized_marginal_s_per_mob'] < fixed['fixed_policy_delta_s_per_mob']
    assert r['attempted']==r['evaluated']+r['blocked']<=110
    assert r['event_transitions']<=9000
    assert r['fixed_policy_attempts']>=1
    assert r['complete_search'] is False
