"""TDD: Mage L30 resource channel and real one-target sheep control."""
import pytest

from src.game.data.forever.mage import build_source_slice
from src.game.data.forever.source_checkpoint_l0 import _ir_proxy
from src.game.model import (ActionDefinition,ActorDefinition,ControlEffect,DamageEffect,
                            IncomingAttackDefinition,ResourceDefinition)
from src.game.runtime import ActorState, CombatRuntime, TargetState


def test_4_spirit_ticks_enter_source_l0_resource_gain_with_actor_cap_left_to_runtime():
    ir=build_source_slice(30)
    evo=next(a for a in ir.actions if a.family_key=='evocation')
    assert evo.cooldown_s == 480
    assert evo.cast_time_s == 8
    assert _ir_proxy(evo)['features']['resource_gain'] == pytest.approx(4 * 16 * (12.5 + 60/4))


def test_mage_polymorph_source_action_has_measured_cast_cost_and_control():
    ir=build_source_slice(30)
    poly=next(a for a in ir.actions if a.family_key=='polymorph')
    assert poly.id=='polymorph:118'
    assert poly.cast_time_s==pytest.approx(1.5)
    assert poly.metadata['range_yards']==pytest.approx(30)
    assert [(c.resource_id,c.amount) for c in poly.costs]==[('mana',60.)]
    assert any(isinstance(e,ControlEffect) and e.duration_s==pytest.approx(20) for e in poly.effects)
    assert _ir_proxy(poly)['effect_roles']==['control']


def test_incapacitated_enemy_cannot_hit_player_until_control_expires():
    ir=build_source_slice(30)
    poly=next(a for a in ir.actions if a.family_key=='polymorph')
    actor=ActorState.from_ir(ActorDefinition('player','player',base_stats={}),(
        ResourceDefinition('health','Health','player',initial_amount=250,capacity=250),
        ResourceDefinition('mana','Mana','player',initial_amount=500,capacity=500),),())
    enemy=TargetState.with_health('mob',100)
    swing=IncomingAttackDefinition(id='mob:swing',name='Swing',source_actor_id='mob',
        target_actor_id='player',school='physical',raw_damage=10.,hit_chance=1.,
        health_resource_id='health',provenance=({'source':'synthetic_test'},),
        metadata={'representative_swing_s':2.})
    rt=CombatRuntime(actor=actor,target=enemy,incoming_attacks=(swing,))
    rt.enqueue_action(poly)
    rt.advance_to(5.)
    assert actor.resource_amount('health')==pytest.approx(250.)
    assert rt.target.active_controls.get('polymorph',0)>5
    rt.advance_to(23.)
    assert actor.resource_amount('health')<250.


def test_polymorph_breaks_on_actual_damage():
    ir=build_source_slice(30)
    polymorph=next(a for a in ir.actions if a.family_key=='polymorph')
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    enemy=TargetState.with_health('mob',100)
    rt=CombatRuntime(actor=actor,target=enemy)
    rt.enqueue_action(polymorph)
    rt.advance_to(1.5)
    assert enemy.active_controls['polymorph']>1.5
    bolt=ActionDefinition(id='probe:bolt',family_key='probe',name='Probe',
        owner_actor_id=actor.id,requirements=(),costs=(),cast_time_s=0,gcd_s=0,cooldown_s=0,
        effects=(DamageEffect(
            'damage','arcane','enemy',10.,10.),),
        provenance=({'status':'synthetic_test'},))
    rt.advance_to(2)
    rt.schedule_action(bolt)
    assert enemy.health==pytest.approx(90)
    assert 'polymorph' not in enemy.active_controls


def test_evocation_channel_and_cooldown_persist_across_encounters():
    from src.game.runtime import action_eligibility
    ir=build_source_slice(30)
    evo=next(a for a in ir.actions if a.family_key=='evocation')
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    actor.resources['mana']=0.
    rt=CombatRuntime(actor=actor,target=TargetState.with_health('m1',100))
    rt.enqueue_action(evo)
    rt.advance_to(8.1)
    assert actor.resource_amount('mana') >= 384.
    assert actor.cooldown_ready_s[evo.id]==pytest.approx(480.)
    rt.persist_actor_periodics()
    rt2=CombatRuntime(actor=actor,target=TargetState.with_health('m2',100))
    gate=action_eligibility(action=evo,actor=actor,target=rt2.target)
    assert not gate.eligible and gate.next_ready_s >= 480.


def test_100mob_evocation_competes_with_recovery_and_keeps_cooldown():
    from src.game.data.forever import build_game_ir_slice
    from src.game.model import PolicyCondition, PolicyDefinition, PolicyRuleDefinition
    from src.game.multi_pull import evaluate_repeated_pulls
    ir=build_game_ir_slice(class_key='mage',level=30)
    evo=next(a for a in ir.actions if a.family_key=='evocation')
    frost=next(a for a in ir.actions if a.family_key=='frostbolt')
    rules=(PolicyRuleDefinition('evo',evo.id,conditions=(PolicyCondition(
                kind='resource_threshold',resource_id='mana',operator='lte',value=330.),)),
           PolicyRuleDefinition('frostbolt',frost.id))
    policy=PolicyDefinition(id='mage:conditional_evo',label='Frost + Evo',rules=rules)
    result=evaluate_repeated_pulls(ir_slice=ir,policy=policy,level=30,target_health=300,
        count=100,pack_size=1,schedule_incoming_attacks=False,
        recovery_mode='threshold',recovery_mana_fraction=.05,max_actions=150)
    times=[float(a['start_time_s']) for p in result.pulls
           for a in p['selected_actions'] if a['action_id']==evo.id]
    assert len(result.pulls)==100
    assert all(p['pack_all_defeated'] for p in result.pulls)
    assert len(times)>=2
    assert all(b-a >= 480.-1e-8 for a,b in zip(times,times[1:]))
    assert result.seconds_per_mob>0
