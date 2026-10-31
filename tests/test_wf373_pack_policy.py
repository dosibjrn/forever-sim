"""Druid L30 comparison needs a complete three-target policy encounter."""
from src.game.model import (ActorDefinition, ResourceDefinition, ActionDefinition,
                            DamageEffect, PolicyDefinition, PolicyRuleDefinition)
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.game.policy import execute_priority_policy


def test_apl_finishes_entire_three_target_pack_not_only_first_target():
    actor=ActorState.from_ir(ActorDefinition(id='hero',actor_type='player',base_stats={}),
        (ResourceDefinition('health','Health','hero',initial_amount=400,capacity=400),),())
    targets=[TargetState.with_health('m0',10),TargetState.with_health('m1',20),
             TargetState.with_health('m2',20)]
    runtime=CombatRuntime(actor=actor,target=targets[0],other_targets=tuple(targets[1:]),
        spatial_positions_yards={'m0':(0.,0.),'m1':(20.,0.),'m2':(10.,17.32050807568877)})
    for t in targets[1:]:runtime.engage_target(t.id)
    runtime.advance_to(3.)
    aoe=ActionDefinition(id='swipe',family_key='swipe',name='Swipe',owner_actor_id='hero',
        requirements=(),costs=(),cast_time_s=0.,gcd_s=1.5,cooldown_s=0.,
        effects=(DamageEffect(effect_type='damage',school='physical',target='enemy',
                              base_min=10.,base_max=10.),),
        provenance=({'fixture':'pack_apl'},),metadata={'max_targets':3})
    policy=PolicyDefinition(id='pack',label='Pack',rules=(PolicyRuleDefinition(id='swipe',action_id='swipe'),))
    result=execute_priority_policy(policy=policy,actions=(aoe,),runtime=runtime,max_actions=10)
    assert result.stopped_reason is None
    assert runtime.pack_summary()['all_defeated']
    assert all(not t.alive for t in targets)
    assert [v['action_id'] for v in result.selected_actions]==['swipe','swipe']
    assert result.timeline.target_defeated


def test_player_auto_swing_continues_through_all_three_live_pack_targets():
    from src.game.model import AutoAttackDefinition, AutoAttackDamageSource
    actor=ActorState.from_ir(ActorDefinition('hero','player',base_stats={}),(
        ResourceDefinition('health','Health','hero',initial_amount=400,capacity=400),),())
    targets=[TargetState.with_health(f'm{i}',10) for i in range(3)]
    attack=AutoAttackDefinition(id='hero:auto',name='Auto',owner_actor_id='hero',
        attack_type='melee',swing_time_s=2,school='physical',
        damage_source=AutoAttackDamageSource(kind='synthetic_gear_test',flat_dps=5),
        provenance=({'source':'test'},))
    rt=CombatRuntime(actor=actor,target=targets[0],other_targets=tuple(targets[1:]),
       spatial_positions_yards={'m0':(0,0),'m1':(20,0),'m2':(10,17.32050807568877)},
       auto_attacks=(attack,),enemy_move_speed_yards_s=5,melee_radius_yards=5)
    rt.engage_target('m1');rt.engage_target('m2')
    rt.advance_to(15)
    assert rt.pack_summary()['all_defeated']
    assert len(rt.pack_summary()['target_death_s'])==3


def test_sourced_three_target_aoe_hits_single_mob_in_final_partial_pack():
    """The final 100th mob may be alone even for a three-mob pull policy."""
    actor = ActorState.from_ir(
        ActorDefinition(id='hero', actor_type='player', base_stats={}),
        (ResourceDefinition('health', 'Health', 'hero', initial_amount=400, capacity=400),), ())
    target = TargetState.with_health('remaining_100th_mob', 15)
    runtime = CombatRuntime(actor=actor, target=target)
    swipe = ActionDefinition(
        id='swipe', family_key='swipe', name='Swipe', owner_actor_id='hero',
        requirements=(), costs=(), cast_time_s=0., gcd_s=1.5, cooldown_s=0.,
        effects=(DamageEffect(effect_type='damage', school='physical', target='enemy',
                              base_min=15., base_max=15.),),
        provenance=({'fixture':'source_max_targets'},),metadata={'max_targets':3})
    policy = PolicyDefinition(id='last_mob', label='Last mob',
        rules=(PolicyRuleDefinition(id='swipe',action_id='swipe'),))
    result = execute_priority_policy(policy=policy, actions=(swipe,), runtime=runtime)
    assert result.stopped_reason is None
    assert result.timeline.target_defeated
    assert runtime.total_damage == 15.
