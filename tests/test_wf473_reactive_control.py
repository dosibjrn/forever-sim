"""WF473: source-derived single-charge reactive control; production runtime."""
from dataclasses import replace
from pathlib import Path
import json
import shutil
import sqlite3

import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.runtime import ActorState, TargetState, CombatRuntime

DB=Path('data/forever/catalogue/forever_abilities.sqlite')

def setup(db=DB):
    ir=build_game_ir_slice(class_key='druid',level=20,ability_db_path=db)
    action=next(a for a in ir.actions if a.id=='source_spell:16810')
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    rt=CombatRuntime(actor=actor,target=TargetState.with_health('enemy',10000.),triggers=ir.triggers)
    return ir,action,rt

def test_source_compiles_exact_rank_cost_trigger_and_root_duration():
    ir,action,rt=setup()
    assert action.costs[0].amount==65 and action.cooldown_s==60.
    assert action.effects[0].duration_s==45.
    assert action.provenance[0]['child_spell_id']==1062
    trigger=next(t for t in ir.triggers if t.required_aura_id==action.effects[0].aura_id)
    assert trigger.filters=={'school':'physical','attack_delivery':'melee'}
    assert trigger.effects[0].duration_s==15.
    assert trigger.metadata['consume_required_aura_on_trigger'] is True
    assert action.id not in {a.id for a in build_game_ir_slice(class_key='druid',level=17,ability_db_path=DB).actions}

def test_melee_hit_roots_and_consumes_only_one_charge():
    ir,action,rt=setup()
    mana=float(rt.actor.resources['mana'])
    rt.schedule_action(action)
    assert rt.actor.resources['mana']==mana-65
    assert action.effects[0].aura_id in rt.actor.active_auras
    rt.resolve_incoming_attack(ir.incoming_attacks[0],at_time_s=2.,mitigation_rules=ir.mitigation_rules)
    assert rt.target.active_controls['root']==pytest.approx(17.)
    assert action.effects[0].aura_id not in rt.actor.active_auras
    assert 'source_periodic:1062' in rt.target.active_auras
    rt.advance_to(5.01)
    assert any(e.kind=='Damage' and e.action_id.endswith(':trigger') and
               e.payload.get('periodic') for e in rt.trace)
    assert sum(e.kind=='ControlApplied' and e.payload['applied'] for e in rt.trace)==1
    rt.resolve_incoming_attack(ir.incoming_attacks[0],at_time_s=6.,mitigation_rules=ir.mitigation_rules)
    assert sum(e.kind=='ControlApplied' and e.payload['applied'] for e in rt.trace)==1
    rt.advance_to(17.1)
    assert 'root' not in rt.target.active_controls

def test_no_root_from_magic_hit_or_expired_aura():
    ir,action,rt=setup();rt.schedule_action(action)
    rt._queue_event_triggers(event_kind='damage_taken',time_s=1.,
        source_action_id='magic_hit',payload={'school':'frost','hit_chance':1.,'amount':50.})
    rt.advance_to(1.)
    assert 'root' not in rt.target.active_controls
    assert action.effects[0].aura_id in rt.actor.active_auras
    rt.advance_to(45.1)
    assert action.effects[0].aura_id not in rt.actor.active_auras
    rt.resolve_incoming_attack(ir.incoming_attacks[0],at_time_s=46.,mitigation_rules=ir.mitigation_rules)
    assert 'root' not in rt.target.active_controls

def test_cross_references_root_rank_must_parse(tmp_path):
    stage=tmp_path/'mutated.sqlite';shutil.copy2(DB,stage)
    with sqlite3.connect(stage) as db:
        row=db.execute('SELECT raw_listview_json FROM spell_index WHERE spell_id=1062').fetchone()
        data=json.loads(row[0]);data['envChange']['after']['text']='Unknown root effect'
        db.execute('UPDATE spell_index SET raw_listview_json=? WHERE spell_id=1062',(json.dumps(data),))
    with pytest.raises(ValueError,match='REACTIVE_CONTROL_CHILD_DURATION_UNRESOLVED'):
        setup(stage)

def test_rank2_is_used_on_l20_not_downrank():
    ir,action,rt=setup()
    assert len([a for a in ir.actions if a.family_key==action.family_key])==1
    assert action.provenance[0]['source_spell_id']==16810


def test_multitarget_reactive_root_hits_actual_attacker_not_selected_enemy():
    ir,action,_=setup()
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    m0=TargetState.with_health('m0',10000.)
    m1=TargetState.with_health('m1',10000.)
    rt=CombatRuntime(actor=actor,target=m0,other_targets=[m1],
        spatial_positions_yards={'m0':(2.,0.),'m1':(3.,0.)},
        melee_radius_yards=5.,enemy_move_speed_yards_s=5.,triggers=ir.triggers)
    rt.schedule_action(action)
    atk=replace(ir.incoming_attacks[0],source_actor_id='m1')
    rt.resolve_incoming_attack(atk,at_time_s=2.,mitigation_rules=ir.mitigation_rules)
    assert 'root' in m1.active_controls
    assert 'root' not in m0.active_controls


def test_ranged_physical_hit_does_not_consume_melee_only_charge():
    ir,action,rt=setup();rt.schedule_action(action)
    ranged=replace(ir.incoming_attacks[0],metadata={**ir.incoming_attacks[0].metadata,'attack_delivery':'ranged'})
    rt.resolve_incoming_attack(ranged,at_time_s=1.,mitigation_rules=ir.mitigation_rules)
    assert action.effects[0].aura_id in rt.actor.active_auras
    assert 'root' not in rt.target.active_controls
