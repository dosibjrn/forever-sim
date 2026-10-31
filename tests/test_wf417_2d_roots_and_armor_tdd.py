"""WF418: generic source-school mitigation and paid spatial root behavior."""
from __future__ import annotations
from dataclasses import replace

from src.game.model import (ActorDefinition, ResourceDefinition, IncomingAttackDefinition,
                            ActionDefinition, DamageEffect, ControlEffect)
from src.game.runtime import ActorState, CombatRuntime, TargetState
import pytest


def runtime(*, ranged_enemy=True, enemy_speed=5):
    actor = ActorState.from_ir(ActorDefinition('hero','player',base_stats={}),
        (ResourceDefinition('health','Health','hero',initial_amount=500,capacity=500),),())
    targets = [TargetState.with_health('m0',500),TargetState.with_health('m1',500)]
    incoming = tuple(IncomingAttackDefinition(id=f'swing{i}', name='Swing',
        source_actor_id=t.id,target_actor_id='hero',school='physical',raw_damage=10,
        hit_chance=1.,health_resource_id='health',provenance=({'fixture':'wf418'},),
        metadata={'representative_swing_s':2.}) for i,t in enumerate(targets))
    rt=CombatRuntime(actor=actor,target=targets[0],other_targets=(targets[1],),
        spatial_positions_yards={'m0':(0,0),'m1':(20 if ranged_enemy else 4,0)},
        enemy_move_speed_yards_s=enemy_speed,melee_radius_yards=5.,incoming_attacks=incoming)
    return rt


def cc(duration=4, break_on_damage=False, control_id='root'):
    return ActionDefinition(id='control',family_key='control',name='Sourced control',
        owner_actor_id='hero',requirements=(),costs=(),cast_time_s=0,gcd_s=0,cooldown_s=0,
        effects=(ControlEffect('control',control_id,'enemy',duration,
                               breaks_on_damage=break_on_damage),),
        provenance=({'fixture':'wf418'},),metadata={'range_yards':30})


def damage(school='arcane',amount=10):
    return ActionDefinition(id=f'{school}:hit',family_key='hit',name='Hit',owner_actor_id='hero',
        requirements=(),costs=(),cast_time_s=0,gcd_s=0,cooldown_s=0,
        effects=(DamageEffect('damage',school,'enemy',amount,amount),),
        provenance=({'fixture':'wf418'},),metadata={'range_yards':30})


def engaged_rooted(duration=4,break_on_damage=False):
    rt=runtime()
    rt.engage_target('m1');rt.select_target('m1')
    rt.schedule_action(cc(duration,break_on_damage))
    assert rt.targets['m1'].active_controls.get('root',0) >= duration
    return rt


def test_root_stops_distant_enemy_until_expiry_then_resumes_paid_travel_and_swings():
    rt=engaged_rooted(duration=4)
    rt.advance_to(3.1)
    assert 'm1' not in rt._melee_targets
    assert rt._enemy_distance('m1')==pytest.approx(20.)
    rt.advance_to(5.)
    assert 'm1' not in rt._melee_targets
    rt.advance_to(7.)
    assert 'm1' in rt._melee_targets  # movement at 4+3, not at original time 3
    rt.advance_to(9.)
    assert len([e for e in rt.result().events if e.kind=='IncomingAttackResolved' and e.actor_id=='m1'])==1


def test_root_applied_mid_approach_freezes_at_actual_position_and_no_teleport():
    rt=runtime()
    rt.engage_target('m1');rt.select_target('m1')
    rt.advance_to(1.)
    assert rt._enemy_distance('m1')==pytest.approx(15.)
    rt.schedule_action(cc(duration=3))
    rt.advance_to(3.5)
    assert rt._enemy_distance('m1')==pytest.approx(15.)
    rt.advance_to(5.9)
    assert 'm1' not in rt._melee_targets
    rt.advance_to(6.)
    assert 'm1' in rt._melee_targets  # 1s partial + 3s rooted + 2s remaining


def test_damage_broken_root_resumes_remaining_travel_immediately():
    rt=engaged_rooted(duration=10,break_on_damage=True)
    rt.advance_to(1.)
    rt.schedule_action(damage('arcane',10))
    assert 'root' not in rt.targets['m1'].active_controls
    rt.advance_to(4.1)
    assert 'm1' in rt._melee_targets


def test_rooted_target_already_in_melee_still_attacks():
    rt=runtime(ranged_enemy=False)
    rt.select_target('m1');rt.schedule_action(cc(duration=10))
    rt.advance_to(2.1)
    assert any(e.kind=='IncomingAttackResolved' and e.actor_id=='m1'
               for e in rt.result().events)


def test_stun_with_source_action_suppression_also_stops_spatial_approach():
    rt=runtime()
    rt.engage_target('m1');rt.select_target('m1')
    action=cc(9,control_id='stun')
    action=replace(action,effects=(
        replace(action.effects[0],prevents_enemy_actions=True),))
    rt.schedule_action(action)
    rt.advance_to(3.1)
    assert 'm1' not in rt._melee_targets
    rt.advance_to(12.1)
    assert 'm1' in rt._melee_targets


@pytest.mark.parametrize('school,physical', [('arcane',False),('frost',False),('fire',False),
                        ('nature',False),('shadow',False),('holy',False),('physical',True)])
def test_sourced_armor_only_reduces_physical_school(school,physical):
    actor=ActorState.from_ir(ActorDefinition('hero','player',base_stats={}),(),())
    target=TargetState.with_health('mob',500,combat_capture_id='wf418',armor=200.,
        armor_constant=100.,armor_reduction_cap=.75,melee_hit=1.,spell_hit=1.)
    rt=CombatRuntime(actor=actor,target=target)
    rt.schedule_action(damage(school,90))
    events=[e for e in rt.result().events if e.kind=='Damage' and e.payload.get('applied')]
    assert len(events)==1
    assert events[0].payload['amount']==pytest.approx(30. if physical else 90.)
    assert events[0].payload['target_armor_reduction']==pytest.approx(2./3 if physical else 0.)


def test_real_druid_entangling_roots_stops_2d_approach_even_with_unmodeled_break_chance():
    # Source-verified control is physically executable in CombatRuntime.
    # Missing heartbeat/break-chance source fidelity is an explicit P4 blocker,
    # not a reason to pretend the root cannot stop movement.
    from src.game.data.forever.registry import build_game_ir_slice
    from src.v2.source_bounded_joint_frontier import source_cold_start_stage, source_joint_policy_frontier
    ir=build_game_ir_slice(class_key='druid',level=20)
    root=next(a for a in ir.actions if a.family_key=='entangling_roots')
    stage=source_cold_start_stage(class_key='druid',level=20,source_ir=ir,gear_role='druid_balance')
    frontier=source_joint_policy_frontier(ir,stage,max_policies=5)
    assert all(root.id not in [rule.action_id for rule in policy.rules]
               for _,policy in frontier)  # source fidelity still blocked
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    targets=[TargetState.with_health('m0',2000),TargetState.with_health('m1',2000)]
    incoming=tuple(IncomingAttackDefinition(id=f'druid:swing{i}',name='enemy swing',
        source_actor_id=t.id,target_actor_id=actor.id,school='physical',raw_damage=10,
        hit_chance=1.,health_resource_id='health',provenance=({'fixture':'wf418'},),
        metadata={'representative_swing_s':2.}) for i,t in enumerate(targets))
    rt=CombatRuntime(actor=actor,target=targets[0],other_targets=(targets[1],),
        spatial_positions_yards={'m0':(0,0),'m1':(20,0)},
        incoming_attacks=incoming)
    rt.engage_target('m1');rt.select_target('m1');rt.schedule_action(root)
    assert rt.targets['m1'].active_controls.get('root',0) > rt.actor.current_time_s
    frozen_distance=rt._enemy_distance('m1')
    assert frozen_distance > 5.
    rt.advance_to(rt.actor.current_time_s+3)
    assert rt._enemy_distance('m1') == pytest.approx(frozen_distance)
    assert 'm1' not in rt._melee_targets


def test_generic_source_policy_frontier_auto_proposes_real_mage_frost_nova():
    from src.game.data.forever.registry import build_game_ir_slice
    from src.v2.source_bounded_joint_frontier import source_cold_start_stage, source_joint_policy_frontier
    ir=build_game_ir_slice(class_key='mage',level=20)
    nova=next(a for a in ir.actions if a.family_key=='frost_nova')
    stage=source_cold_start_stage(class_key='mage',level=20,source_ir=ir,gear_role='mage_frost')
    frontier=source_joint_policy_frontier(ir,stage,max_policies=5)
    witness=next((p for origin,p in frontier if origin=='control_opening'),None)
    assert witness is not None
    assert witness.rules[0].action_id==nova.id
    assert any(c.kind=='target_control_missing' and c.value=='root'
               for c in witness.rules[0].conditions)


def test_bleed_periodic_physical_school_bypasses_armor_but_direct_hit_does_not():
    from src.game.model import PeriodicEffect
    actor=ActorState.from_ir(ActorDefinition('hero','player',base_stats={}),(),())
    target=TargetState.with_health('mob',500,combat_capture_id='wf418',armor=200.,
        armor_constant=100.,armor_reduction_cap=.75,melee_hit=1.,spell_hit=1.)
    rt=CombatRuntime(actor=actor,target=target)
    bleed=ActionDefinition(id='bleed',family_key='bleed',name='Bleed',
        owner_actor_id='hero',requirements=(),costs=(),cast_time_s=0,gcd_s=0,cooldown_s=0,
        effects=(PeriodicEffect('periodic_damage','physical','enemy','bleed:test',90.,3.,1.),),
        provenance=({'fixture':'wf418'},))
    rt.schedule_action(bleed)
    rt.advance_to(3.1)
    events=[e for e in rt.result().events if e.kind=='Damage' and e.payload.get('applied')]
    assert len(events)==3
    assert sum(e.payload['amount'] for e in events)==pytest.approx(90.)
    assert all(e.payload['target_armor_reduction']==0 for e in events)


def test_incoming_magic_does_not_accept_an_armor_curve_in_sourced_ir():
    from src.game.model import ArmorMitigationDefinition
    from src.game.runtime.simulator import expected_incoming_attack
    actor=ActorState.from_ir(ActorDefinition('hero','player',base_stats={'armor':200.}),
        (ResourceDefinition('health','Health','hero',initial_amount=500,capacity=500),),())
    attack=IncomingAttackDefinition(id='fire',name='Fire spell',source_actor_id='enemy',
        target_actor_id='hero',school='fire',raw_damage=90,hit_chance=1.,
        health_resource_id='health',mitigation_rule_id='wrong_armor',
        provenance=({'fixture':'wf417'},),metadata={'representative_swing_s':2.})
    wrong=ArmorMitigationDefinition('wrong_armor','fire','armor',100.,
        provenance=({'fixture':'wf417'},))
    with pytest.raises(ValueError,match='ARMOR_MITIGATION_ON_NONPHYSICAL_DAMAGE'):
        expected_incoming_attack(attack,actor=actor,mitigation_rules=(wrong,))
    from dataclasses import replace
    safe=replace(attack,mitigation_rule_id=None)
    assert expected_incoming_attack(safe,actor=actor)['post_mitigation_damage']==pytest.approx(90.)
