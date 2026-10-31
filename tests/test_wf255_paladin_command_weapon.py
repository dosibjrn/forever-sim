"""WF255: sourced talent-granted timed weapon proc and real equipped swing speed."""
import json,sqlite3
from dataclasses import replace
import pytest
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_timed_auras import compile_granted_timed_aura
from src.game.gear import apply_gear_selection
from src.game.talents import apply_talent_selection,validate_talent_selection
from src.game.runtime import ActorState,CombatRuntime,TargetState,action_eligibility
from src.game.runtime.simulator import expected_weapon_damage
from src.game.model import PolicyDefinition,PolicyRuleDefinition,PolicyCondition
from src.game.multi_pull import evaluate_repeated_pulls
from src.v2.source_joint_discovery import _gear_envelope
from tools.wf255_ingest_command import ingest,CAPTURE

COMMAND={'benediction':5,'conviction':5,'seal_of_command':1}

def source():return build_game_ir_slice(class_key='paladin',level=20)

def test_ingest_idempotent_and_provenance():
    a=ingest();b=ingest()
    assert a==b and a['new_talent_grants']==1
    with sqlite3.connect(DEFAULT_DB) as db:
        rows=db.execute("SELECT spell_id,exclusive_group FROM sourced_timed_aura_actions WHERE class_key='paladin'").fetchall()
        assert len(rows)==17 and all(x[1]=='paladin_seal' for x in rows)
        g=db.execute("SELECT action_json FROM verified_talent_granted_action_facts WHERE class_key='paladin' AND spell_id=20375").fetchone()
        assert g and json.loads(g[0])['proc_authority'].startswith('CLASSIC_')


def test_command_is_talent_gated_and_row_legal():
    x=source()
    assert not any(a.family_key=='seal_of_command' for a in x.actions)
    assert not any(t.required_aura_id=='seal:command' for t in x.triggers)
    with pytest.raises(ValueError,match='tier gate'):
        validate_talent_selection(x,{'seal_of_command':1},level=20)
    with pytest.raises(ValueError,match='point'):
        validate_talent_selection(x,COMMAND,level=19)
    y,app=apply_talent_selection(x,COMMAND,level=20)
    assert any(a.family_key=='seal_of_command' for a in y.actions)
    assert {t.required_aura_id for t in y.triggers if 'seal_of_command' in t.id}=={'seal:command'}
    assert len([t for t in y.triggers if 'seal_of_command' in t.id])==2


def test_equipped_weapon_speed_and_proc_use_same_sourced_item():
    x=source();g=_gear_envelope('paladin',20,max_gear_candidates=256,
        required_level_policy='observed',include_melee_gear=True,ir_slice=x)[0]
    weapon=g['selection'].slots['weapon']
    assert weapon['weapon_speed']>0 and weapon['weapon_dps']>0
    geared,_=apply_gear_selection(x,aggregate_stats=g['selection'].aggregate_stats,
        selected_items=tuple(g['selection'].slots.values()))
    auto=geared.auto_attacks[0]
    assert auto.swing_time_s==pytest.approx(weapon['weapon_speed'])
    y,_=apply_talent_selection(geared,COMMAND,level=20)
    proc=next(t.effects[0] for t in y.triggers if t.id.startswith('seal_of_command:swing'))
    assert proc.weapon_damage_time_s==pytest.approx(weapon['weapon_speed'])
    assert proc.damage_source.flat_dps==pytest.approx(weapon['weapon_dps'])
    actor=ActorState.from_ir(y.actor,y.resources,y.modes)
    expected=expected_weapon_damage(proc,actor=actor)['expected_damage']
    assert expected>0
    assert expected/weapon['weapon_speed']>0


def test_exclusive_seal_and_judgement_actual_events():
    x=source();y,_=apply_talent_selection(x,COMMAND,level=20)
    actor=ActorState.from_ir(y.actor,y.resources,y.modes)
    runtime=CombatRuntime(actor=actor,target=TargetState.with_health('enemy',2000),
        auto_attacks=y.auto_attacks,triggers=y.triggers)
    right=next(a for a in y.actions if a.family_key=='seal_of_righteousness')
    command=next(a for a in y.actions if a.family_key=='seal_of_command')
    judge=next(a for a in y.actions if a.family_key=='judgement')
    assert not action_eligibility(action=judge,actor=actor,target=runtime.target).eligible
    runtime.schedule_action(right);runtime.advance_to(1.5)
    assert 'seal:righteousness' in actor.active_auras
    runtime.schedule_action(command);runtime.advance_to(3.0)
    assert 'seal:command' in actor.active_auras
    assert 'seal:righteousness' not in actor.active_auras
    assert any(e.kind=='AuraRemovedExclusive' for e in runtime.trace)
    assert action_eligibility(action=judge,actor=actor,target=runtime.target).eligible
    runtime.schedule_action(judge);runtime.advance_to(3.0)
    assert any(e.kind=='TriggerFired' and e.action_id.startswith('seal_of_command:judgement') for e in runtime.trace)
    assert not any(e.kind=='TriggerFired' and e.action_id.startswith('seal_of_righteousness:judgement') for e in runtime.trace)


def test_invalid_source_grant_rejected(tmp_path):
    original=json.loads(CAPTURE.read_text())
    original['talent']['source_url']='http://unsafe'
    bad=tmp_path/'bad.json';bad.write_text(json.dumps(original))
    with pytest.raises(ValueError,match='invalid sourced'):
        ingest(capture_path=bad)
    grant=json.loads(sqlite3.connect(DEFAULT_DB).execute("SELECT action_json FROM verified_talent_granted_action_facts WHERE spell_id=20375 AND class_key='paladin'").fetchone()[0])
    grant.pop('proc_reference_speed_s')
    with pytest.raises(ValueError,match='incomplete'):
        compile_granted_timed_aura(grant,ir_slice=source())


def test_three_pull_real_command_and_cross_class():
    x=source();y,_=apply_talent_selection(x,COMMAND,level=20)
    seal=next(a for a in y.actions if a.family_key=='seal_of_command')
    judge=next(a for a in y.actions if a.family_key=='judgement')
    strike=next(a for a in y.actions if a.family_key=='holy_strike')
    policy=PolicyDefinition(id='wf255_command',label='Command independent test',rules=(
        PolicyRuleDefinition('strike',strike.id),
        PolicyRuleDefinition('judge',judge.id,conditions=(PolicyCondition('aura_any_present',scope='actor',value=['seal:command']),)),
        PolicyRuleDefinition('seal',seal.id,conditions=(PolicyCondition('aura_missing',scope='actor',aura_id='seal:command'),)),
    ))
    result=evaluate_repeated_pulls(ir_slice=y,policy=policy,level=20,target_health=450,
        count=3,apply_target_defense=True)
    assert 0<result.seconds_per_mob<100
    assert any('seal_of_command' in a['action_id'] for pull in result.pulls for a in pull['selected_actions'])
    for key in ('hunter','mage','druid'):
        other=build_game_ir_slice(class_key=key,level=20)
        assert other and not any(a.family_key=='seal_of_command' for a in other.actions)


def test_trigger_damage_talent_modifies_granted_weapon_proc_generic():
    # Mechanical unit probe only: the native Paladin provider is currently
    # bounded to L20; do not claim a sourced L28 encounter scenario.
    x=source()
    a,_=apply_talent_selection(x,COMMAND,level=20)
    combo={**COMMAND,'divine_strength':5,'improved_seals':3}
    b,_=apply_talent_selection(x,combo,level=28)
    proc_a=next(t.effects[0] for t in a.triggers if t.id.startswith('seal_of_command:swing'))
    proc_b=next(t.effects[0] for t in b.triggers if t.id.startswith('seal_of_command:swing'))
    assert proc_b.weapon_damage_multiplier==pytest.approx(proc_a.weapon_damage_multiplier*1.15)


def test_exclusive_group_survives_new_combat_runtime_without_old_action_registration():
    x=source();y,_=apply_talent_selection(x,COMMAND,level=20)
    actor=ActorState.from_ir(y.actor,y.resources,y.modes)
    right=next(a for a in y.actions if a.family_key=='seal_of_righteousness')
    command=next(a for a in y.actions if a.family_key=='seal_of_command')
    first=CombatRuntime(actor=actor,target=TargetState.with_health('one',2000),auto_attacks=y.auto_attacks,triggers=y.triggers)
    first.schedule_action(right);first.advance_to(1.5)
    assert 'seal:righteousness' in actor.active_auras
    second=CombatRuntime(actor=actor,target=TargetState.with_health('two',2000),auto_attacks=y.auto_attacks,triggers=y.triggers)
    second.schedule_action(command);second.advance_to(3.0)
    assert 'seal:command' in actor.active_auras
    assert 'seal:righteousness' not in actor.active_auras
    assert any(e.kind=='AuraRemovedExclusive' for e in second.trace)


def test_cross_class_source_speed_semantics_preserve_druid_forms_and_hunter_ranged():
    for cls in ('hunter','druid'):
        x=build_game_ir_slice(class_key=cls,level=20)
        gear=_gear_envelope(cls,20,max_gear_candidates=256,required_level_policy='observed',
                            include_melee_gear=True,ir_slice=x)[0]['selection']
        equipped,_=apply_gear_selection(x,aggregate_stats=gear.aggregate_stats,
            selected_items=tuple(gear.slots.values()))
        if cls=='hunter':
            assert equipped.auto_attacks[0].swing_time_s==pytest.approx(gear.slots['ranged']['weapon_speed'])
            assert equipped.auto_attacks[1].swing_time_s==x.auto_attacks[1].swing_time_s
        else:
            assert [a.swing_time_s for a in equipped.auto_attacks]==[a.swing_time_s for a in x.auto_attacks]


def test_named_equipped_weapon_missing_speed_fails_closed():
    x=source();g=_gear_envelope('paladin',20,max_gear_candidates=256,
        required_level_policy='observed',include_melee_gear=True,ir_slice=x)[0]['selection']
    items=[dict(row) for row in g.slots.values()]
    for item in items:
        if item['slot']=='weapon':item['weapon_speed']=0
    with pytest.raises(ValueError,match='sourced positive speed'):
        apply_gear_selection(x,aggregate_stats=g.aggregate_stats,selected_items=items)
