"""WF471 - source-bound generic enemy AP debuff and real paid melee incoming."""
from dataclasses import replace
from pathlib import Path
import json, shutil, sqlite3
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_enemy_melee_ap_debuff import ingest
from src.game.runtime import ActorState,TargetState,CombatRuntime
from src.game.runtime.simulator import ActionNotEligibleError

DB=Path('data/forever/catalogue/forever_abilities.sqlite')
EVIDENCE=Path('evidence/wf471_enemy_melee_ap_debuff_source.json')

def source_ir(db=DB):
    return build_game_ir_slice(class_key='druid',level=20,ability_db_path=db)

def setup_runtime(ir):
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    actor.transition_mode('bear');actor.resources['rage']=40.
    return CombatRuntime(actor=actor,target=TargetState.with_health('enemy',100000.))

def test_data_values_and_source_based_compilation():
    ir=source_ir()
    action=next(a for a in ir.actions if a.id=='source_enemy_ap:1735')
    assert action.costs[0].resource_id=='rage' and action.costs[0].amount==10.
    assert action.requirements[1]=={'kind':'mode_is','value':'bear'}
    assert action.effects[0].target=='enemies' and action.effects[0].delta==-88.
    assert action.effects[0].duration_s==30.
    assert action.metadata['aoe_radius_yards']==10.
    assert action.metadata['geometry_status']=='CLASSIC_PROXY_NOT_FOREVER_VERIFIED'
    assert action.id not in next(m for m in ir.modes if m.id=='caster').enabled_action_ids
    assert action.id in next(m for m in ir.modes if m.id=='bear').enabled_action_ids
    assert all(a.id!='source_enemy_ap:1735' for a in build_game_ir_slice(class_key='druid',level=19,ability_db_path=DB).actions)

def test_real_incoming_damage_reduced_by_ap_and_recovers_after_expiry():
    ir=source_ir();action=next(a for a in ir.actions if a.id=='source_enemy_ap:1735')
    atk=ir.incoming_attacks[0]
    baseline=setup_runtime(ir)
    affected=setup_runtime(ir)
    before=affected.actor.resources['rage']
    affected.schedule_action(action)
    assert affected.actor.resources['rage']==before-10.
    base=baseline.resolve_incoming_attack(atk,at_time_s=1.,mitigation_rules=ir.mitigation_rules)
    reduced=affected.resolve_incoming_attack(atk,at_time_s=1.,mitigation_rules=ir.mitigation_rules)
    assert reduced['source_enemy_melee_ap_debuff_delta']==-88.
    assert reduced['post_mitigation_damage']<base['post_mitigation_damage']
    assert reduced['incoming_raw_damage_after_melee_ap_debuff']==pytest.approx(
        max(0.,atk.raw_damage-88.*2./14.))
    affected.advance_to(30.01)
    recovered=affected.resolve_incoming_attack(atk,at_time_s=31.,mitigation_rules=ir.mitigation_rules)
    assert recovered['post_mitigation_damage']==pytest.approx(base['post_mitigation_damage'])

def test_2d_area_targets_only_nearby_and_expires():
    ir=source_ir();action=next(a for a in ir.actions if a.id=='source_enemy_ap:1735')
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    actor.transition_mode('bear');actor.resources['rage']=40.
    mobs=[TargetState.with_health('m0',10000.),TargetState.with_health('m1',10000.),TargetState.with_health('m2',10000.)]
    rt=CombatRuntime(actor=actor,target=mobs[0],other_targets=mobs[1:],
                     spatial_positions_yards={'m0':(2.,0.),'m1':(8.,0.),'m2':(20.,0.)},
                     melee_radius_yards=5.,enemy_move_speed_yards_s=5.)
    rt.schedule_action(action)
    for t in mobs[:2]:
        assert t.active_stat_modifiers[action.effects[0].aura_id][1]==-88.
    assert not mobs[2].active_stat_modifiers
    assert {e.target_id for e in rt.trace if e.kind=='TargetStatDebuffApplied'}=={'m0','m1'}
    rt.advance_to(30.1)
    assert not any(t.active_stat_modifiers for t in mobs)

def test_source_identity_and_numbers_fail_closed(tmp_path):
    stage=tmp_path/'stage.sqlite';shutil.copy2(DB,stage)
    obs=json.loads(EVIDENCE.read_text()); obs['observations'][0]['name']='Other'
    fake=tmp_path/'bad.json';fake.write_text(json.dumps(obs))
    with pytest.raises(ValueError,match='PROVENANCE_IDENTITY_MISMATCH'):ingest(stage,fake)
    with sqlite3.connect(stage) as c:
        c.execute("UPDATE source_enemy_melee_ap_debuff_facts SET ap_reduction=999 WHERE spell_id=1735")
    with pytest.raises(ValueError,match='INDEX_OR_VALUE_DRIFT'):source_ir(stage)

def test_no_unqualified_incoming_damage_conversion():
    ir=source_ir();action=next(a for a in ir.actions if a.id=='source_enemy_ap:1735')
    rt=setup_runtime(ir);rt.schedule_action(action)
    unknown=replace(ir.incoming_attacks[0], metadata={'representative_swing_s':2.})
    with pytest.raises(ValueError,match='SOURCE_INCOMING_MELEE_AP_CONVERSION_MISSING'):
        rt.resolve_incoming_attack(unknown,at_time_s=1.)
