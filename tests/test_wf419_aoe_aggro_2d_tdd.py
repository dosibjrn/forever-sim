"""AoE application must tag victims outside idle proximity aggro, source-neutral."""
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.model import ActionDefinition,ControlEffect
from src.game.runtime import ActorState,CombatRuntime,TargetState


def _scene():
    ir=build_game_ir_slice(class_key='mage',level=30)
    nova=next(a for a in ir.actions if a.family_key=='frost_nova')
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    mobs=[TargetState.with_health(f'm{i}',1000) for i in range(3)]
    rt=CombatRuntime(actor=actor,target=mobs[0],other_targets=mobs[1:],
         spatial_positions_yards={'m0':(4,0),'m1':(8,0),'m2':(12,0)},
         aggro_radius_yards=5.,enemy_move_speed_yards_s=5.,melee_radius_yards=5.)
    assert rt._engaged_targets == {'m0'}
    return rt,nova


def test_sourced_nova_tags_all_hit_mobs_even_when_outside_proximity_aggro():
    rt,nova=_scene()
    rt.schedule_action(nova)
    assert rt._engaged_targets == {'m0','m1'}
    assert rt.targets['m1'].active_controls['root'] == pytest.approx(8.)
    assert rt._enemy_distance('m1') == pytest.approx(8.)
    assert 'm2' not in rt._engaged_targets
    rt.advance_to(7.99)
    assert rt._enemy_distance('m1') == pytest.approx(8.)
    rt.advance_to(8.5)
    assert rt._enemy_distance('m1') < 8.
    rt.advance_to(8.7)
    assert 'm1' in rt._melee_targets


def test_source_area_control_without_damage_still_tags_victim():
    rt,nova=_scene()
    cc=ActionDefinition(id='source:test:control', family_key='control',name='Control area',
        owner_actor_id=rt.actor.id,requirements=(),costs=(),cast_time_s=0.,gcd_s=0.,cooldown_s=0.,
        effects=(ControlEffect('control','root','enemies',3.),),
        provenance=({'fixture':'wf419'},),
        metadata={'aoe_center':'actor','aoe_radius_yards':10.,'aoe_source':{'source_url':'fixture'}})
    rt.schedule_action(cc)
    assert 'm1' in rt._engaged_targets
    rt.advance_to(3.7)
    assert 'm1' in rt._melee_targets


def test_sourced_incoming_swing_resumes_after_newly_tagged_aoe_root():
    from src.game.model import IncomingAttackDefinition
    ir=build_game_ir_slice(class_key='mage',level=30)
    nova=next(a for a in ir.actions if a.family_key=='frost_nova')
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    mobs=[TargetState.with_health(f'm{i}',1000) for i in range(3)]
    incoming=IncomingAttackDefinition(id='m1:swing',name='Sourced 2D test hit',
        source_actor_id='m1',target_actor_id=actor.id,school='physical',raw_damage=10.,
        hit_chance=1.,health_resource_id='health',provenance=({'scenario':'wf419'},),
        metadata={'representative_swing_s':2.})
    rt=CombatRuntime(actor=actor,target=mobs[0],other_targets=mobs[1:],
         spatial_positions_yards={'m0':(4,0),'m1':(8,0),'m2':(12,0)},
         aggro_radius_yards=5.,enemy_move_speed_yards_s=5.,melee_radius_yards=5.,
         incoming_attacks=(incoming,))
    initial_hp=rt.actor.resource_amount('health')
    rt.schedule_action(nova)
    rt.advance_to(7.5)
    before=[e for e in rt.result().events if e.kind=='IncomingAttackResolved' and e.actor_id=='m1']
    assert len(before)==0
    assert rt.actor.resource_amount('health')==pytest.approx(initial_hp)
    rt.advance_to(11.)
    after=[e for e in rt.result().events if e.kind=='IncomingAttackResolved' and e.actor_id=='m1']
    assert len(after)==1
    assert rt.actor.resource_amount('health')<initial_hp
