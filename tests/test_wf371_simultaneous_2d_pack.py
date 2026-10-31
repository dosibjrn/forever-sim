"""RED/behavioral specification for one-clock, concurrent 2D enemies."""
from __future__ import annotations

import pytest
from src.game.model import ActorDefinition, ResourceDefinition, IncomingAttackDefinition, ActionDefinition, DamageEffect
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.shared.leveling.spaced_pulls import SpacedPullLayout


def pack(*, count=2, health=200, monster_health=100, damage=10, enemy_speed=5):
    actor = ActorState.from_ir(ActorDefinition(id='hero',actor_type='player',base_stats={}),(
        ResourceDefinition(id='health',name='Health',owner_actor_id='hero',initial_amount=health,capacity=health),),())
    layout=SpacedPullLayout(count,spacing_yards=20)
    targets=[TargetState.with_health(f'm{i}',monster_health) for i in range(count)]
    incoming=tuple(IncomingAttackDefinition(id=f'swing{i}',name='swings',source_actor_id=t.id,
                target_actor_id='hero',school='physical',raw_damage=damage,hit_chance=1.,
                health_resource_id='health',provenance=({'source':'synthetic_2d_regression'},),
                metadata={'representative_swing_s':2.}) for i,t in enumerate(targets))
    rt=CombatRuntime(actor=actor,target=targets[0],other_targets=tuple(targets[1:]),
          spatial_positions_yards={t.id:pos for t,pos in zip(targets,layout.positions_yards)},
          enemy_move_speed_yards_s=enemy_speed, melee_radius_yards=5.,
          incoming_attacks=incoming)
    return rt,targets,layout


def hit_action(*, target='enemy', amount=15):
    return ActionDefinition(id='a',family_key='damage',name='Hit',owner_actor_id='hero',
            requirements=(),costs=(),cast_time_s=0,gcd_s=0,cooldown_s=0,
            effects=(DamageEffect(effect_type='damage',school='physical',target=target,
                    base_min=amount,base_max=amount),),provenance=({'test':'mechanics'},),
            metadata=({'max_targets':3,'aoe_radius_yards':5.} if target=='enemies' else {}))


def test_two_enemies_share_clock_and_distant_enemy_must_approach_before_swing():
    runtime,targets,layout=pack()
    assert layout.distance_yards(0,1)==20
    runtime.engage_target(targets[1].id)
    runtime.advance_to(2)
    assert runtime.actor.resource_amount('health')==pytest.approx(190.)
    runtime.advance_to(4)
    assert runtime.actor.resource_amount('health')==pytest.approx(180.)
    runtime.advance_to(5)
    assert runtime.actor.resource_amount('health')==pytest.approx(170.)
    assert len([e for e in runtime.result().events if e.kind=='IncomingAttackResolved'])==3
    assert set(e.actor_id for e in runtime.result().events if e.kind=='IncomingAttackResolved')=={'m0','m1'}


def test_aoe_uses_real_range_and_applies_one_paid_action_to_two_live_targets():
    rt, targets, _=pack()
    rt.engage_target('m1')
    rt.schedule_action(hit_action(target='enemies'))
    assert [round(t.health) for t in targets]==[85,100]
    rt.advance_to(3)
    rt.schedule_action(hit_action(target='enemies'))
    assert [round(t.health) for t in targets]==[70,85]
    events=[e for e in rt.result().events if e.kind=='ActionStarted']
    assert len(events)==2  # no double resource/cooldown cost for two AoE victims


def test_enemy_death_stops_only_its_swing_without_ending_other_enemy_combat():
    rt,targets,_=pack(monster_health=15)
    rt.engage_target('m1')
    rt.schedule_action(hit_action())
    assert targets[0].alive is False
    rt.advance_to(5)
    assert rt.actor.resource_amount('health')==pytest.approx(190)
    assert targets[1].alive is True
    assert rt.pack_summary()['all_defeated'] is False


def test_spatial_policy_context_reports_only_actual_concurrent_targets():
    rt,targets,_=pack()
    assert rt.spatial_context['simultaneous_2d'] is True
    assert rt.spatial_context['enemy_count_in_range']==1
    rt.engage_target('m1')
    assert rt.spatial_context['enemy_count_engaged']==2
    rt.advance_to(3)
    assert rt.spatial_context['enemy_count_in_range']==2


def test_source_max_target_cap_prevents_three_victims_even_when_all_engaged():
    from dataclasses import replace
    rt,targets,layout=pack(count=3)
    assert layout.distance_yards(1,2)==pytest.approx(20.)
    rt.engage_target('m1');rt.engage_target('m2');rt.advance_to(3)
    rt.schedule_action(replace(hit_action(target='enemy'),metadata={'max_targets':2}))
    assert [t.health for t in targets]==pytest.approx([85.,85.,100.])
    assert len([e for e in rt.result().events if e.kind=='ActionStarted'])==1


def test_explicit_aoe_range_uses_yard_distance_not_engaged_count():
    from dataclasses import replace
    rt,targets,_=pack()
    rt.engage_target('m1');rt.advance_to(3)
    rt.schedule_action(replace(hit_action(target='enemies'),metadata={'max_targets':3,'aoe_radius_yards':4.}))
    assert [t.health for t in targets]==pytest.approx([85.,100.])



def test_real_forever_druid_level30_swipe_uses_sourced_cap_on_one_runtime_clock():
    from dataclasses import replace
    from src.game.data.forever import build_game_ir_slice
    ir=build_game_ir_slice(class_key='Druid',level=30)
    swipe=next(a for a in ir.actions if a.family_key=='swipe')
    assert swipe.metadata['max_targets']==3
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    actor.transition_mode('bear')
    actor.resources['rage']=90.
    layout=SpacedPullLayout(3)
    targets=[TargetState.with_health(f'forever:m{i}',200.) for i in range(3)]
    incoming=tuple(replace(ir.incoming_attacks[0],id=f'forever:incoming:{i}',
                      source_actor_id=t.id) for i,t in enumerate(targets))
    rt=CombatRuntime(actor=actor,target=targets[0],other_targets=tuple(targets[1:]),
             spatial_positions_yards={t.id:pos for t,pos in zip(targets,layout.positions_yards)},
             incoming_attacks=incoming,mitigation_rules=ir.mitigation_rules)
    for target in targets[1:]:
        rt.engage_target(target.id)
    rt.advance_to(4.)
    rage_before=float(actor.resources['rage'])
    rt.schedule_action(swipe)
    damages=[e for e in rt.result().events if e.kind=='Damage' and e.action_id==swipe.id and e.payload.get('applied')]
    assert len(damages)==3
    assert {e.target_id for e in damages}=={t.id for t in targets}
    assert [t.health for t in targets]==pytest.approx([175.]*3)
    assert actor.resources['rage']==pytest.approx(rage_before-20.)
    assert len([e for e in rt.result().events if e.kind=='ActionStarted' and e.action_id==swipe.id])==1


def test_melee_autoattack_cannot_hit_20yard_target_before_enemy_arrives():
    from src.game.model import AutoAttackDefinition, AutoAttackDamageSource
    from dataclasses import replace
    actor = ActorState.from_ir(ActorDefinition('hero','player',base_stats={}),(
       ResourceDefinition('health','Health','hero',initial_amount=200,capacity=200),),())
    targets=[TargetState.with_health('m0',200),TargetState.with_health('m1',200)]
    attack=AutoAttackDefinition(id='hero:auto',name='Auto',owner_actor_id='hero',
         attack_type='melee',swing_time_s=2,school='physical',
         damage_source=AutoAttackDamageSource(kind='regression_fixture',flat_dps=5),
         provenance=({'status':'synthetic_mechanics_probe'},))
    rt=CombatRuntime(actor=actor,target=targets[0],other_targets=(targets[1],),
       spatial_positions_yards={'m0':(0,0),'m1':(20,0)},enemy_move_speed_yards_s=5,
       auto_attacks=(attack,))
    rt.engage_target('m1')
    rt.select_target('m1')
    rt.advance_to(2)
    assert [t.health for t in targets]==pytest.approx([200,200])
    rt.advance_to(5)
    assert targets[1].health==pytest.approx(190)
    assert targets[0].health==pytest.approx(200)


def test_timeline_result_accounts_for_whole_pack_not_just_first_target():
    rt,targets,_=pack(monster_health=100)
    initial=rt.result()
    assert initial.target_start_health==pytest.approx(200.)
    assert initial.target_end_health==pytest.approx(200.)
    assert initial.target_defeated is False
    rt.schedule_action(hit_action(amount=100.))
    partial=rt.result()
    assert partial.target_end_health==pytest.approx(100.)
    assert partial.target_defeated is False
    assert partial.target_death_s is None
    assert rt.pack_summary()['target_health']=={'m0':0.,'m1':100.}
