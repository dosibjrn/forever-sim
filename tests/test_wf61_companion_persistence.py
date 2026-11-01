"""Persistent 100-mob scorer: pet states must not reset between targets.

These are focused state-clock regressions for gsim, not native ACK evidence.
"""
from types import SimpleNamespace as N

import pytest

from src.game.runtime.state import ActorState
from src.v2.source_persistent_joint_finalists import (
    _carry_persistent_companion_clocks, _prepare_retained_companions,
    _persistent_companion_state_receipt, _source_persistent_companion_policies,
    _unpersisted_companion_periodics,
)


def _pet():
    return ActorState(
        id='source_companion_pet',
        current_time_s=5.,
        resources={'mana':10.,'health':75.},
        resource_capacity={'mana':100.,'health':100.},
        resource_active={'mana':True,'health':True},
        resource_regeneration_per_s={'mana':2.,'health':0.},
        cooldown_ready_s={'pet_spell':35.},
    )


def test_retained_companion_clock_and_cooldowns_survive_two_paid_downtimes():
    companion=_pet()
    first_id=id(companion)
    _carry_persistent_companion_clocks((companion,),actor_time_s=15.)
    assert id(companion)==first_id
    assert companion.current_time_s==15.
    assert companion.resources['mana']==30.
    assert companion.resources['health']==75.
    assert companion.cooldown_ready_s['pet_spell']==35.
    _carry_persistent_companion_clocks((companion,),actor_time_s=25.)
    assert companion.current_time_s==25.
    assert companion.resources['mana']==50.
    assert companion.cooldown_ready_s['pet_spell']==35.


def test_paid_regeneration_respects_capacity_and_equal_clock_is_noop():
    companion=_pet()
    _carry_persistent_companion_clocks((companion,),actor_time_s=80.)
    assert companion.current_time_s==80.
    assert companion.resources['mana']==100.
    first=dict(companion.resources)
    _carry_persistent_companion_clocks((companion,),actor_time_s=80.)
    assert companion.resources==first


def test_aura_expires_on_persistent_companion_downtime_not_respawn():
    companion=_pet()
    companion.apply_aura(
        aura_id='source_pet_aura',source_action_id='source_pet_spell',
        applied_at_s=5.,duration_s=5.,refresh_rule='replace')
    assert 'source_pet_aura' in companion.active_auras
    _carry_persistent_companion_clocks((companion,),actor_time_s=12.)
    assert companion.current_time_s==12.
    assert 'source_pet_aura' not in companion.active_auras
    assert companion.resources['mana']==24.


def test_pending_companion_periodic_events_are_not_silently_discarded():
    companion=_pet()
    companion.pending_actor_periodic_events=(N(kind='PeriodicTick'),)
    with pytest.raises(ValueError,match='PERSISTENT_COMPANION_CLOCK_OR_PERIODICS_UNSUPPORTED'):
        _carry_persistent_companion_clocks((companion,),actor_time_s=25.)
    assert companion.current_time_s==5.
    assert companion.resources['mana']==10.


def test_companion_clock_regression_fails_without_mutation():
    companion=_pet()
    with pytest.raises(ValueError,match='PERSISTENT_COMPANION_CLOCK_OR_PERIODICS_UNSUPPORTED'):
        _carry_persistent_companion_clocks((companion,),actor_time_s=4.)
    assert companion.current_time_s==5.
    assert companion.resources['mana']==10.


def test_multiple_companions_validate_all_before_mutating_any():
    first=_pet()
    second=_pet()
    second.current_time_s=100.
    with pytest.raises(ValueError,match='PERSISTENT_COMPANION_CLOCK_OR_PERIODICS_UNSUPPORTED'):
        _carry_persistent_companion_clocks((first,second),actor_time_s=15.)
    assert first.current_time_s==5.
    assert first.resources['mana']==10.


def test_no_companion_is_a_valid_class_neutral_case():
    _carry_persistent_companion_clocks((),actor_time_s=13.)


def test_real_sourced_hunter_pet_retains_focus_and_links_without_stacking():
    """Actual canonical Hunter L20 IR, not a pet-shaped stub."""
    from src.game.data.forever.registry import build_game_ir_slice
    ir=build_game_ir_slice(class_key='hunter',level=20)
    owner=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    # Controlled source-stat fixture avoids dependence on a specific item set.
    owner.stats['attack_power']=150.
    owner.stats['critical_strike_chance']=.2
    assert len(ir.companions)==1 and len(ir.actor_links)==2
    pet_def=ir.companions[0]
    baseline=ActorState.from_ir(pet_def,ir.resources)
    pets,receipts=_prepare_retained_companions(ir,owner)
    assert len(pets)==1 and len(receipts)==len(ir.actor_links)
    pet=pets[0]
    assert pet.resource_amount('focus')==baseline.resource_amount('focus')
    assert pet.resource_capacity['focus']==baseline.resource_capacity['focus']
    assert pet.resource_regeneration_per_s['focus']>0
    ap_link=next(x for x in ir.actor_links if x.target_stat_id=='attack_power')
    crit_link=next(x for x in ir.actor_links
        if x.target_stat_id=='critical_strike_chance')
    assert pet.stats['attack_power']==pytest.approx(
        baseline.stats['attack_power']+150.*ap_link.coefficient)
    assert pet.stats['critical_strike_chance']==pytest.approx(
        .2*crit_link.coefficient)
    linked_attack_power=pet.stats['attack_power']
    linked_crit=pet.stats['critical_strike_chance']
    focus_initial=pet.resource_amount('focus')
    pet.spend('focus',10.)
    _carry_persistent_companion_clocks(pets,actor_time_s=2.)
    assert pet.resource_amount('focus')==min(pet.resource_capacity['focus'],
        focus_initial-10.+2.*pet.resource_regeneration_per_s['focus'])
    assert pet.stats['attack_power']==linked_attack_power
    assert pet.stats['critical_strike_chance']==linked_crit
    _carry_persistent_companion_clocks(pets,actor_time_s=10.)
    assert pet.stats['attack_power']==linked_attack_power
    assert pet.current_time_s==10.
    # Reusing the same pets is the core production identity contract.
    assert pets[0] is pet


def test_real_class_without_companion_has_unchanged_source_owner_stats():
    from src.game.data.forever.registry import build_game_ir_slice
    ir=build_game_ir_slice(class_key='paladin',level=20)
    owner=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    original=dict(owner.stats)
    pets,receipts=_prepare_retained_companions(ir,owner)
    assert not pets and not receipts
    assert owner.stats==original


def test_real_combat_runtime_accepts_retained_pets_on_next_pull():
    """Guard the exact shared-clock constructor contract for consecutive mobs."""
    from src.game.data.forever.registry import build_game_ir_slice
    from src.game.runtime import CombatRuntime, TargetState
    ir=build_game_ir_slice(class_key='hunter',level=20)
    owner=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    pets,_=_prepare_retained_companions(ir,owner)
    first=CombatRuntime(actor=owner,companions=pets,
        target=TargetState.with_health('first',100.))
    first.advance_to(3.)
    assert pets[0].current_time_s==owner.current_time_s==3.
    # Advance the shared actor clock through paid downtime, retaining pet.
    offcombat=CombatRuntime(actor=owner, target=TargetState.with_health('rest',1.))
    offcombat.advance_to(5.)
    _carry_persistent_companion_clocks(pets,actor_time_s=owner.current_time_s)
    next_pull=CombatRuntime(actor=owner,companions=pets,
        target=TargetState.with_health('second',100.))
    assert next_pull.actors[pets[0].id] is pets[0]
    assert next_pull.actor.current_time_s==pets[0].current_time_s==5.


def test_per_pull_companion_receipt_is_snapshot_not_mutable_live_reference():
    pet=_pet()
    before=_persistent_companion_state_receipt((pet,))
    assert before[pet.id]['clock_s']==5.
    assert before[pet.id]['resources']['mana']==10.
    assert before[pet.id]['cooldown_ready_s']['pet_spell']==35.
    assert before[pet.id]['auras']==[]
    _carry_persistent_companion_clocks((pet,),actor_time_s=8.)
    after=_persistent_companion_state_receipt((pet,))
    assert after[pet.id]['clock_s']==8.
    assert after[pet.id]['resources']['mana']==16.
    assert before[pet.id]['clock_s']==5.
    assert before[pet.id]['resources']['mana']==10.
    assert _persistent_companion_state_receipt(())=={}


def test_exact_sourced_pet_focus_recovery_is_reflected_in_state_receipt():
    from src.game.data.forever.registry import build_game_ir_slice
    ir=build_game_ir_slice(class_key='hunter',level=20)
    owner=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    pets,links=_prepare_retained_companions(ir,owner)
    pet=pets[0]
    cap=pet.resource_capacity['focus']
    pet.spend('focus',min(20.,pet.resource_amount('focus')))
    before=_persistent_companion_state_receipt(pets)
    _carry_persistent_companion_clocks(pets,actor_time_s=5.)
    after=_persistent_companion_state_receipt(pets)
    assert before[pet.id]['resources']['focus']<cap
    assert after[pet.id]['resources']['focus']>=before[pet.id]['resources']['focus']
    assert after[pet.id]['clock_s']==5.
    assert len(links)==len(ir.actor_links)


@pytest.mark.parametrize('mobs',(1,2,100))
def test_actual_sourced_hunter_persistent_combat_and_pet_evidence(mobs):
    """Full real GameIR/CombatRuntime + paid recovery, NOT native action ACK.

    This is an intentionally unwaived full-source integration test. It must
    execute on exact PR HEAD before the production companion change is merged.
    """
    from src.game.data.forever.registry import build_game_ir_slice
    from src.game.gear import apply_gear_selection
    from src.v2.source_joint_discovery import _gear_envelope
    from src.v2.source_persistent_joint_finalists import (
        PreparedCandidate, evaluate_persistent_candidate)
    ir=build_game_ir_slice(class_key='hunter',level=20)
    gear=_gear_envelope('hunter',20,max_gear_candidates=256,
        required_level_policy='observed',include_melee_gear=True,
        ir_slice=ir)[0]['selection']
    geared,_=apply_gear_selection(ir,aggregate_stats=gear.aggregate_stats,
        selected_items=tuple(gear.slots.values()),source='sourced_named_gear')
    policy=next(p for p in geared.policies if not p.provenance.get('companion_policy'))
    candidate=PreparedCandidate(geared,policy,(),{}, {})
    result=evaluate_persistent_candidate(
        candidate,level=20,mobs=mobs,trace_pulls=True)
    assert result['status']=='COMPLETE',result
    assert result['count']==mobs
    assert result['continuous_actor_state']
    assert result['persistent_companion_count']==1
    assert len(result['persistent_source_actor_links_applied_once'])==2
    sourced_pet_actions={a.id for a in geared.actions
        if a.owner_actor_id==geared.companions[0].id}
    assert sourced_pet_actions
    assert sourced_pet_actions & set(result['source_action_counts']), (
        'Retained pet must execute real sourced spells, not only idle autoattacks')
    assert len(result['pull_trace'])==mobs
    pet_id=geared.companions[0].id
    for i,pull in enumerate(result['pull_trace']):
        assert pet_id in pull['companion_before']
        assert pet_id in pull['companion_at_kill']
        assert pet_id in pull['companion_after_recovery']
        assert pull['companion_before'][pet_id]['clock_s']==pytest.approx(
            pull['pull_started_s'])
        assert pull['companion_after_recovery'][pet_id]['clock_s']==pytest.approx(
            pull['recovery_finished_s'])
        if i:
            previous=result['pull_trace'][i-1]['companion_after_recovery'][pet_id]
            current=pull['companion_before'][pet_id]
            assert current['clock_s']>=previous['clock_s']
            assert current['resources']['focus']>=0
        assert len(pull['companion_before'][pet_id]['resources'])>=1
    assert result['pull_trace_audit']['distinct_targets']==mobs


def test_real_sourced_pet_policy_covers_exact_companion_actors():
    from src.game.data.forever.registry import build_game_ir_slice
    ir=build_game_ir_slice(class_key='hunter',level=20)
    owner=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    pets,_=_prepare_retained_companions(ir,owner)
    policies=_source_persistent_companion_policies(ir,pets)
    assert set(policies)=={pet.id for pet in pets}
    for pet in pets:
        assert policies[pet.id].provenance['companion_policy'] is True
        assert policies[pet.id].rules
        for rule in policies[pet.id].rules:
            action=next(a for a in ir.actions if a.id==rule.action_id)
            assert action.owner_actor_id==pet.id


def test_missing_sourced_pet_policy_rejected_before_any_paid_kill():
    from dataclasses import replace
    from src.game.data.forever.registry import build_game_ir_slice
    ir=build_game_ir_slice(class_key='hunter',level=20)
    owner=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    pets,_=_prepare_retained_companions(ir,owner)
    ir_without_pet_policy=replace(ir,policies=tuple(
        p for p in ir.policies if not p.provenance.get('companion_policy')))
    with pytest.raises(ValueError,match='PERSISTENT_COMPANION_SOURCE_POLICY_MISSING'):
        _source_persistent_companion_policies(ir_without_pet_policy,pets)


def test_companion_policy_rejects_duplicated_source_owner():
    from dataclasses import replace
    from src.game.data.forever.registry import build_game_ir_slice
    ir=build_game_ir_slice(class_key='hunter',level=20)
    owner=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    pets,_=_prepare_retained_companions(ir,owner)
    pet_policy=next(p for p in ir.policies if p.provenance.get('companion_policy'))
    ir_duplicated=replace(ir,policies=(*ir.policies,pet_policy))
    with pytest.raises(ValueError,match='PERSISTENT_COMPANION_SOURCE_POLICY_ID_MISMATCH'):
        _source_persistent_companion_policies(ir_duplicated,pets)


def test_live_pet_periodics_cannot_be_discarded_by_primary_only_boundary():
    pet=_pet()
    pet.apply_aura(aura_id='pet:hot',source_action_id='pet:heal',
                   applied_at_s=5.,duration_s=10.,refresh_rule='replace')
    aura=pet.active_auras['pet:hot']
    current=N(kind='PeriodicTick',actor_id=pet.id,time_s=8.,
              action_id='pet:heal',payload={
                  'aura_scope':'actor','aura_id':'pet:hot','generation':aura.generation})
    stale=N(kind='AuraExpired',actor_id=pet.id,time_s=12.,
            action_id='pet:heal',payload={
                'aura_scope':'actor','aura_id':'pet:hot','generation':aura.generation-1})
    enemy=N(kind='PeriodicTick',actor_id='enemy',time_s=8.,
            action_id='enemy:dot',payload={
                'aura_scope':'actor','aura_id':'enemy:aura','generation':1})
    runtime=N(queue=N(_heap=[(8.,1,current),(12.,2,stale),(8.,3,enemy)]))
    assert _unpersisted_companion_periodics(runtime,(pet,))==('pet:heal',)
    assert _unpersisted_companion_periodics(runtime,())==()
    pet.remove_aura('pet:hot')
    assert _unpersisted_companion_periodics(runtime,(pet,))==()


def test_target_scoped_pet_dot_does_not_persist_to_next_target():
    pet=_pet()
    pet.apply_aura(aura_id='pet:dot',source_action_id='pet:bite',
                   applied_at_s=5.,duration_s=10.,refresh_rule='replace')
    aura=pet.active_auras['pet:dot']
    event=N(kind='PeriodicTick',actor_id=pet.id,time_s=8.,
            action_id='pet:bite',payload={
                'aura_scope':'target','aura_id':'pet:dot',
                'generation':aura.generation})
    runtime=N(queue=N(_heap=[(8.,1,event)]))
    assert _unpersisted_companion_periodics(runtime,(pet,))==()
