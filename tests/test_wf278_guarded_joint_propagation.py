"""WF278: real-source conditional policies must survive existing joint adapters.

No Eviscerate AP coefficient is invented; its source blocker remains intact.
"""
import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.model import PolicyCondition
from src.v2.generic_backend import _policy_combat_evaluation
from src.v2.source_stateful_adapter import stateful_policy_as_prefix
from src.v2.source_budgeted_gear import _fixed_opening_score, run_source_budgeted_gear
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents
from src.v2.source_stateful_budgeted import _make_policy


def test_adapter_records_paid_source_guarded_l2_and_keeps_blocked_effects():
    ir = build_game_ir_slice(class_key='druid', level=10)
    r = stateful_policy_as_prefix(class_key='druid', level=10, ir_slice=ir,
        max_evaluations=20, max_event_transitions=1500, use_l1=False,
        use_prefix_cache=False, search_guarded_continuations=True)
    assert r['guarded_continuations_searched']
    assert r['guarded_l2_attempts'] > 0
    assert r['guarded_l2_verified'] > 0
    assert all(x['guarded_conditions'] and x['guarded_action'] == 'moonfire:8924'
               for x in r['guarded_l2_evidence'])
    assert any(x['score_s_per_mob'] == 16.129032258064516
               for x in r['guarded_l2_evidence'])
    assert r['attempted'] == r['evaluated'] + r['blocked'] <= 20
    assert r['event_transitions'] <= 1500
    rogue = stateful_policy_as_prefix(class_key='rogue', level=20,
        ir_slice=build_game_ir_slice(class_key='rogue', level=20),
        max_evaluations=8, max_event_transitions=500, use_l1=False,
        search_guarded_continuations=True)
    assert any(x['id']=='eviscerate:6761' for x in rogue['source_blockers'])
    assert rogue['guarded_l2_attempts'] == 0


def test_fixed_policy_stat_probe_reexecutes_guard_not_only_fallback():
    ir = build_game_ir_slice(class_key='druid', level=10)
    record = {'prefix':['wrath:5177'], 'fallback':'wrath:5177',
              'guarded_action':'moonfire:8924',
              'guarded_conditions':[{'kind':'aura_missing','scope':'target',
                                     'aura_id':'moonfire:8924:aura'}]}
    events=[]
    actual = _fixed_opening_score(ir,record,10,True,meter=events.append,max_events=300)
    expected, execution, details = _policy_combat_evaluation(ir,level=10,
        policy_override=_make_policy(ir,'wrath:5177',
            guarded_action='moonfire:8924',
            guarded_conditions=(PolicyCondition(**record['guarded_conditions'][0]),)),
        opening_action_ids=('wrath:5177',),schedule_incoming_attacks=True)
    assert actual == expected.seconds_per_mob == 16.129032258064516
    assert execution.selected_actions[1]['action_id']=='moonfire:8924'
    assert events == [details['event_transitions_new']]
    # The unguarded fallback is observably different on the same real executor.
    assert _fixed_opening_score(ir,{**record,'guarded_action':None},10,True) != actual


def test_gear_restarts_real_guarded_search_and_charges_stat_probes():
    r = run_source_budgeted_gear(class_key='druid',level=10,
        max_evaluations=38,initial_search=20,search_per_gear=6,
        max_gear_states=1,probe_stats=('spell_power',),probe_deltas=(5.,),
        policy_search_backend='stateful',max_event_transitions=1800,
        stateful_use_l1=False,stateful_search_guarded_continuations=True)
    assert r['status']=='EVALUATED_BOUNDED'
    assert r['attempted']==r['evaluated']+r['blocked']<=38
    assert r['event_transitions']<=1800
    assert r['stateful_search_guarded_continuations']
    assert r['stages'][0]['guarded_l2_verified'] > 0
    assert r['stages'][0]['guarded_l2_evidence']
    assert r['sensitivity_history'][0]['baseline_seconds_per_mob']==r['stages'][0]['winner']['score_s_per_mob']
    assert r['named_gear_states_evaluated']>=1
    assert r['winner']['winner']['score_s_per_mob'] < r['stages'][0]['winner']['score_s_per_mob']


def test_joint_talent_state_inherits_guarded_search_option_without_fake_optimum():
    r = run_source_budgeted_joint_talents(class_key='druid',level=10,
        max_evaluations=46,evaluations_per_talent=23,
        initial_search=20,search_per_gear=2,max_gear_states=1,
        policy_search_backend='stateful',max_event_transitions=1800,
        stateful_use_l1=False,stateful_search_guarded_continuations=True)
    assert r['stateful_search_guarded_continuations']
    assert r['attempted']==r['evaluated']+r['blocked']<=46
    assert r['event_transitions']<=1800
    assert r['stages'][0]['gear_policy_result']['stages'][0]['guarded_l2_verified'] > 0
    assert r['complete_search'] is False


def test_guarded_request_cannot_silently_fall_back_to_unguarded_prefix_search():
    with pytest.raises(ValueError, match='requires stateful'):
        run_source_budgeted_gear(class_key='druid', level=10,
            max_evaluations=4, stateful_search_guarded_continuations=True)
    with pytest.raises(ValueError, match='requires stateful'):
        run_source_budgeted_joint_talents(class_key='druid', level=10,
            max_evaluations=4, stateful_search_guarded_continuations=True)
