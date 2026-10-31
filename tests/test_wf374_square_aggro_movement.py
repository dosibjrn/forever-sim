"""WF374 RED: infinite square field, 10yd aggro and moving casts."""
from math import hypot, isclose
from dataclasses import replace
import pytest

from src.shared.leveling.spaced_pulls import SpacedPullLayout
from src.game.model import ActorDefinition, ResourceDefinition, IncomingAttackDefinition, ActionDefinition, DamageEffect
from src.game.runtime import ActorState, CombatRuntime, TargetState


def _runtime(n=2):
    actor = ActorState.from_ir(ActorDefinition(id='hero', actor_type='player', base_stats={}), (
        ResourceDefinition(id='health', name='Health', owner_actor_id='hero', initial_amount=500, capacity=500),), ())
    layout = SpacedPullLayout(n, 20.)
    targets = [TargetState.with_health(f'm{i}', 100) for i in range(n)]
    attacks = tuple(IncomingAttackDefinition(id=f'swing{i}', name='Swing',source_actor_id=t.id,
        target_actor_id='hero',school='physical', raw_damage=10.,hit_chance=1.,health_resource_id='health',
        provenance=({'test':'WF374'},), metadata={'representative_swing_s':2.}) for i,t in enumerate(targets))
    runtime = CombatRuntime(actor=actor, target=targets[0], other_targets=tuple(targets[1:]),
        spatial_positions_yards={t.id:xy for t,xy in zip(targets,layout.positions_yards)},
        incoming_attacks=attacks)
    return runtime,targets,layout


def test_ten_plus_enemies_are_unbounded_square_grid_20yd_spacing():
    for n in (3, 10, 30, 100):
        layout=SpacedPullLayout(n)
        xy=layout.positions_yards
        assert len(xy)==len(set(xy))==n
        assert xy[0]==(0.,0.)
        assert xy[1]==(20.,0.)
        assert all(isclose(x/20,round(x/20)) and isclose(y/20,round(y/20)) for x,y in xy)
        assert all(hypot(x-a,y-b)>=20.-1e-8 for i,(x,y) in enumerate(xy) for a,b in xy[i+1:])
        assert layout.as_dict()['coordinate_system']=='2D_EUCLIDEAN_SQUARE_LATTICE'


def test_20yd_enemy_remains_unengaged_and_stationary_until_aggro():
    rt,targets,layout=_runtime()
    assert rt.spatial_context['enemy_count_engaged']==1
    rt.advance_to(12.)
    assert targets[1].id not in rt.pack_summary()['engaged_targets']
    assert rt.enemy_positions_yards[targets[1].id]==(20.,0.)
    assert rt.actor.resource_amount('health')==pytest.approx(440.) # six swings, first enemy only


def test_10yd_proximity_aggro_while_moving_and_source_cast_during_movement():
    rt,targets,_=_runtime()
    rt.begin_player_move((20.,0.), speed_yards_s=5., step_yards=2.)
    rt.advance_to(1.8) # 9yd: outside aggro; 2yd steps leave player at 8yd
    assert targets[1].id not in rt.pack_summary()['engaged_targets']
    assert rt.player_position_yards==(8.,0.)
    attack=ActionDefinition(id='ranged', family_key='ranged',name='Spell',owner_actor_id='hero',
        requirements=(),costs=(),cast_time_s=0,gcd_s=0,cooldown_s=0,
        effects=(DamageEffect(effect_type='damage',school='nature',target='enemy',base_min=15,base_max=15),),
        provenance=({'source':'synthetic_movement_smoke'},),metadata={'range_yards':30.})
    rt.select_target('m1')
    rt.schedule_action(attack)
    assert targets[1].health==pytest.approx(85.)
    rt.advance_to(2.0) # at 10yd, aggro fires (even if spell didn't tag)
    assert rt.player_position_yards==(10.,0.)
    assert targets[1].id in rt.pack_summary()['engaged_targets']
    rt.advance_to(4.)
    assert rt.player_position_yards==(20.,0.)


def test_multi_pull_scorer_does_not_instant_tag_distant_square_field():
    # A pack cannot claim it assembled 10 mobs by tagging all enemies at zero time.
    from src.game.multi_pull import _encounter_pack
    targets, positions, incoming = _encounter_pack(mob_start=0,mob_count=10,target_health=100.,target_metadata={},incoming_attacks=())
    assert len(targets)==10
    assert (20.,0.) in positions.values()
    assert all(isclose(x/20.,round(x/20.)) and isclose(y/20.,round(y/20.)) for x,y in positions.values())


def test_sourced_ranged_tag_starts_aggro_at_20yd_without_free_movement():
    rt,targets,_=_runtime()
    ranged=ActionDefinition(id='tag',family_key='tag',name='Source ranged pull',owner_actor_id='hero',
        requirements=(),costs=(),cast_time_s=0,gcd_s=0,cooldown_s=0,
        effects=(DamageEffect(effect_type='damage',school='nature',target='enemy',base_min=10,base_max=10),),
        provenance=({'source':'synthetic_range_contract'},),metadata={'range_yards':30.})
    rt.select_target('m1')
    assert targets[1].id not in rt.pack_summary()['engaged_targets']
    rt.schedule_action(ranged)
    assert targets[1].id in rt.pack_summary()['engaged_targets']
    assert targets[1].health == pytest.approx(90.)
    assert rt.enemy_positions_yards['m1']==(20.,0.)
    rt.advance_to(4.)
    assert rt.enemy_positions_yards['m1'] != (20.,0.)  # AI approaches AFTER being tagged


def test_sourced_range_gate_prevents_free_distant_melee_tag():
    rt,targets,_=_runtime()
    short=ActionDefinition(id='short',family_key='strike',name='Short range',owner_actor_id='hero',
        requirements=(),costs=(),cast_time_s=0,gcd_s=0,cooldown_s=0,
        effects=(DamageEffect(effect_type='damage',school='physical',target='enemy',base_min=10,base_max=10),),
        provenance=({'source':'synthetic_range_contract'},),metadata={'range_yards':5.})
    rt.select_target('m1')
    with pytest.raises(ValueError,match='OUT_OF_RANGE'):
        rt.schedule_action(short)
    assert targets[1].health==pytest.approx(100.)
    assert targets[1].id not in rt.pack_summary()['engaged_targets']


def test_movement_path_can_aggro_ten_spawns_without_pre_engaging():
    rt,targets,layout=_runtime(10)
    # Geometry probe must not die before reaching waypoint 10.
    rt.actor.resources['health'] = 10000.
    rt.actor.resource_capacity['health'] = 10000.
    # High-level route must move the player across a finite number of squares.
    duration=rt.begin_player_route(layout.positions_yards[1:], speed_yards_s=7.)
    assert duration>0
    assert rt.spatial_context['enemy_count_engaged']==1
    rt.advance_to(duration)
    assert len(rt.pack_summary()['engaged_targets'])==10
    assert rt.player_position_yards==layout.positions_yards[-1]
    assert duration>=layout.sequential_travel_total_s


def test_two_mob_100mob_evaluator_pays_square_field_approach_not_free_tag():
    from src.game.data.forever import build_game_ir_slice
    from src.game.model import PolicyDefinition,PolicyRuleDefinition
    from src.game.multi_pull import evaluate_repeated_pulls
    ir=build_game_ir_slice(class_key='druid',level=30)
    source=next(a for a in ir.actions if a.family_key=='wrath')
    strike=replace(source, costs=(),cast_time_s=0,gcd_s=0,cooldown_s=0,
        effects=(DamageEffect(effect_type='damage',school='nature',target='enemy',base_min=100,base_max=100),),
        metadata={'range_yards':5.})
    policy=PolicyDefinition(id='test:square:melee',label='Melee only',rules=(PolicyRuleDefinition(id='m',action_id=strike.id),))
    ir=replace(ir,actions=(strike,),policies=(policy,),auto_attacks=(),incoming_attacks=(),
        companions=(),timed_summons=(),triggers=())
    result=evaluate_repeated_pulls(ir_slice=ir,policy=policy,level=30,target_health=100,
        count=2,pack_size=2,schedule_incoming_attacks=False)
    assert len(result.pulls)==1
    assert result.pulls[0]['pack_all_defeated']
    assert len(result.pulls[0]['selected_actions'])==2
    assert result.pulls[0]['selected_actions'][1]['start_time_s']>1.0  # must walk 20yd into range
    assert result.pulls[0]['kill_s']>1.0
