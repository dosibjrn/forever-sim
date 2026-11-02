"""Real W3 source-role exploration and independent old challenger regression."""
from copy import deepcopy
import json

import pytest

from src.v2.source_budgeted_gear import run_source_budgeted_gear
from tools.wf282_source_role_heldout_benchmark import frozen_heldout, FIXTURE


def _gear(**kwargs):
    args=dict(class_key='druid', level=20, max_evaluations=110,
        initial_search=24, search_per_gear=16, max_gear_states=3,
        policy_search_backend='stateful', stateful_use_l1=False,
        stateful_search_guarded_continuations=True,
        stateful_search_mode_paths=True,
        stateful_family_budget_mode='measured_balanced',
        probe_stats=('agility','strength','stamina'),
        required_level_policy='observed', max_event_transitions=15000)
    args.update(kwargs)
    return run_source_budgeted_gear(**args)


def test_real_role_exploration_is_paid_and_preserves_full_score_authority():
    plain=_gear(gear_role_exploration=False)
    diverse=_gear(gear_role_exploration=True)
    assert plain['source_roles_evaluated']==['druid_balance']
    assert len(diverse['source_roles_evaluated'])>len(plain['source_roles_evaluated'])
    assert plain['attempted']==diverse['attempted']==90
    assert plain['event_transitions']<=15000 and diverse['event_transitions']<=15000
    assert plain['winner']['winner']['score_s_per_mob']==pytest.approx(18.338119142532577)
    assert diverse['winner']['winner']['score_s_per_mob']==pytest.approx(18.338119142532577)
    assert diverse['stat_probe_attempts']>0 and diverse['stat_probe_cpu_ns']>0
    assert diverse['total_controller_cpu_ns']>diverse['stat_probe_cpu_ns']
    assert sum(s['attempted'] for s in diverse['stages'])+diverse['stat_probe_attempts']==diverse['attempted']
    assert len({tuple(sorted((k,v['item_id']) for k,v in s['gear']['slots'].items()))
                for s in diverse['stages'] if s['gear']})==diverse['named_gear_states_evaluated']
    assert all(s['source_gear_role'] in diverse['source_roles_evaluated']
               for s in diverse['stages'] if s['gear'])
    assert diverse['gear_role_exploration']
    assert not plain['gear_role_exploration']


def test_frozen_legacy_heldout_real_l2_is_better_but_not_a_source_complete_optimum():
    old=frozen_heldout()
    assert old['status']=='FULL_L2_VERIFIED'
    assert old['score_s_per_mob']==pytest.approx(17.887004619287094)
    assert old['events']>0 and old['cpu_ns']>0
    assert old['observed_required_level_only']
    assert not old['source_acquisition_route_proven']
    assert old['score_s_per_mob']<18.338119142532577
    assert old['talent_modifiers']>0
    assert frozen_heldout()['score_s_per_mob']==pytest.approx(old['score_s_per_mob'])


def test_heldout_mismatched_item_and_illegal_talent_fail_closed():
    fixture=json.loads(FIXTURE.read_text())
    bad=deepcopy(fixture)
    bad['gear_slots']['weapon']['item_id']=99999999
    with pytest.raises(ValueError,match='item IDs'):
        frozen_heldout(bad)
    bad=deepcopy(fixture)
    bad['talent_allocation']['ferocity']=6
    with pytest.raises(ValueError,match='illegal rank'):
        frozen_heldout(bad)
    bad=deepcopy(fixture)
    bad['policy']['rules'][1]['action_id']='unknown_action:999'
    with pytest.raises(ValueError,match='unavailable policy action'):
        frozen_heldout(bad)


def test_budget_exhaustion_cannot_invent_role_scores():
    r=_gear(max_evaluations=8,initial_search=8,gear_role_exploration=True)
    assert r['attempted']<=8
    assert r['status'] in ('EVALUATED_BOUNDED','BLOCKED_NO_NAKED_SUCCESS')
    assert not any(s['gear'] for s in r['stages'])


def test_same_talents_fresh_gear_policy_can_beat_frozen_challenger_without_old_gear_seed():
    from src.game.data.forever.registry import build_game_ir_slice
    from src.game.talents import apply_talent_selection
    fixture=json.loads(FIXTURE.read_text())
    ir=build_game_ir_slice(class_key='druid',level=20)
    talented,_=apply_talent_selection(ir,fixture['talent_allocation'],level=20)
    r=_gear(ir_slice=talented,gear_role_exploration=True)
    winner=r['winner']
    assert winner['winner']['score_s_per_mob']==pytest.approx(16.773330134932532)
    assert winner['winner']['score_s_per_mob']<frozen_heldout()['score_s_per_mob']
    assert winner['gear']['slots']['weapon']['item_id'] != 99999999
    assert r['event_transitions']<=15000
    assert r['attempted']<=110
    # This is NOT independent talent discovery: allocation is intentionally
    # held equal to the oracle while gear/policy are freshly optimized.
    assert talented.provenance['talent_application']['selection']==fixture['talent_allocation']


def test_joint_source_eligibility_policy_propagates_to_every_paid_gear_state():
    from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents
    args=dict(class_key='druid',level=20,max_evaluations=80,
        evaluations_per_talent=48,initial_search=18,search_per_gear=12,
        max_gear_states=1,policy_search_backend='stateful',
        stateful_use_l1=False,stateful_search_guarded_continuations=True,
        stateful_search_mode_paths=True,
        stateful_family_budget_mode='measured_balanced',
        max_event_transitions=13000,gear_role_exploration=True)
    with pytest.raises(ValueError,match='required_level_policy'):
        run_source_budgeted_joint_talents(**args,required_level_policy='invented')
    result=run_source_budgeted_joint_talents(**args,required_level_policy='observed')
    assert result['required_level_policy']=='observed'
    assert result['attempted']==80 and result['event_transitions']<=13000
    assert result['talent_states_evaluated']==2
    for talent_stage in result['stages']:
        for gear_stage in talent_stage['gear_policy_result']['stages']:
            gear=gear_stage.get('gear')
            if gear:
                assert all(row['required_level_origin']=='observed'
                           for row in gear['slots'].values())
