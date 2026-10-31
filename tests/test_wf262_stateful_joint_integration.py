"""WF262: existing W260 talent/gear loop drives real W261 stateful executor."""
import pytest

from src.v2.source_stateful_adapter import stateful_policy_as_prefix
from src.v2.source_budgeted_gear import run_source_budgeted_gear
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents
from src.game.data.forever.registry import build_game_ir_slice


def test_adapt_real_l1_l2_and_paid_scratch_verification():
    ir=build_game_ir_slice(class_key='druid',level=10)
    r=stateful_policy_as_prefix(class_key='druid',level=10,
       max_evaluations=8,max_event_transitions=500,ir_slice=ir)
    assert r['attempted']==r['evaluated']+r['blocked']==8
    assert len(r['best_vs_budget'])==8
    assert [x['attempt'] for x in r['best_vs_budget']]==list(range(1,9))
    assert r['l1_attempts']>0 and r['event_transitions']<=500
    assert r['winner']['selected_actions']
    assert r['winner']['score_s_per_mob']>0
    assert any(x['source_tier']=='L2_scratch' for x in r['best_vs_budget'])


def test_shared_gear_event_budget_includes_stat_probes_and_l1():
    r=run_source_budgeted_gear(class_key='druid',level=10,
       max_evaluations=40,initial_search=8,search_per_gear=8,
       max_gear_states=2,probe_stats=('spell_power','intellect'),
       probe_deltas=(5.,),policy_search_backend='stateful',
       max_event_transitions=1600,stateful_use_l1=True)
    assert r['attempted']<=40
    assert r['attempted']==r['evaluated']+r['blocked']
    assert 0<r['event_transitions']<=1600
    assert r['stateful_l1_attempts']>0
    assert r['winner']['winner']['score_s_per_mob']<r['stages'][0]['winner']['score_s_per_mob']
    assert all(st['context_sha256'] for st in r['stages'])
    assert len({st['context_sha256'] for st in r['stages']})==len(r['stages'])


def test_real_druid_talent_change_fresh_stateful_gear_and_policy():
    r=run_source_budgeted_joint_talents(class_key='druid',level=10,
       max_evaluations=90,evaluations_per_talent=36,
       initial_search=8,search_per_gear=8,max_gear_states=2,
       policy_search_backend='stateful',max_event_transitions=2900,
       stateful_use_l1=True)
    assert r['status']=='EVALUATED_BOUNDED'
    assert r['attempted']==r['evaluated']+r['blocked']<=90
    assert r['event_transitions']<=2900 and r['stateful_l1_attempts']>0
    assert r['winner']['allocation']=={'improved_wrath':1}
    assert r['winner']['score_s_per_mob']<r['stages'][0]['score_s_per_mob']
    assert len({st['source_context_sha256'] for st in r['stages']})>=2
    assert all(st['fresh_gear_and_policy_search'] for st in r['stages'])
    assert r['complete_search'] is False


def test_real_mage_crossclass_switch_and_bounded_event_budget():
    r=run_source_budgeted_joint_talents(class_key='mage',level=20,
       max_evaluations=120,evaluations_per_talent=38,
       initial_search=10,search_per_gear=10,max_gear_states=2,
       policy_search_backend='stateful',max_event_transitions=8500)
    assert r['attempted']<=120 and r['event_transitions']<=8500
    assert r['winner']['allocation'] != r['stages'][0]['allocation']
    assert r['winner']['score_s_per_mob'] < r['stages'][0]['score_s_per_mob']
    assert all(s['gear_policy_result']['policy_search_backend']=='stateful' for s in r['stages'] if 'gear_policy_result' in s)


def test_event_negative_and_invalid_backend_fail_closed():
    with pytest.raises(ValueError,match='unknown policy'):
        run_source_budgeted_gear(class_key='druid',level=10,max_evaluations=1,
            policy_search_backend='magic')
    with pytest.raises(ValueError,match='positive event'):
        run_source_budgeted_gear(class_key='druid',level=10,max_evaluations=1,
            policy_search_backend='stateful',max_event_transitions=0)
    for cap in (1,15,80):
        r=run_source_budgeted_gear(class_key='druid',level=10,
           max_evaluations=24,initial_search=6,search_per_gear=6,
           max_gear_states=2,probe_stats=('spell_power',),probe_deltas=(5.,),
           policy_search_backend='stateful',max_event_transitions=cap)
        assert r['event_transitions']<=cap
        assert r['attempted']<=24


def test_missing_source_actions_yields_typed_block_not_runtime_crash():
    from dataclasses import replace
    ir=build_game_ir_slice(class_key='druid',level=10)
    no_actions=replace(ir,actions=())
    r=stateful_policy_as_prefix(class_key='druid',level=10,
        max_evaluations=8,max_event_transitions=100,ir_slice=no_actions)
    assert r['status']=='BLOCKED_NO_EXECUTABLE_ACTIONS'
    assert r['attempted']==0 and r['winner'] is None
