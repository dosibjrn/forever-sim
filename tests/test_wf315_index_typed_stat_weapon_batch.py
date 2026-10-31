"""WF315: canonical nine-class index -> generic runtime, partial L1 ONLY.

This suite never treats index-change text as complete spell detail, a learned
rank, a legal equipped weapon or a source-complete checkpoint.
"""
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_effect_atoms import ingest
from src.game.data.forever.source_partial_l1 import (
    partial_source_action,probe_l1_source_fragment,PartialSourceEvidenceError,
    bounded_actor_l1_probe_ir)
from src.game.runtime.state import ActorState,TargetState
from src.game.runtime.simulator import CombatRuntime,expected_weapon_damage,execute_action

@pytest.fixture
def db(tmp_path):
    p=tmp_path/'catalogue.sqlite'
    shutil.copy2(DEFAULT_DB,p)
    ingest(p)
    return p

def ir_for(db,cl,level=20):
    return build_game_ir_slice(class_key=cl,level=level,ability_db_path=db)

def mutate_index(db,cl,sid,old,new):
    with sqlite3.connect(db) as c:
        row=c.execute("SELECT raw_listview_json FROM spell_index WHERE class_key=? AND spell_id=? AND kind='abilities'",(cl,sid)).fetchone()
        d=json.loads(row[0]);after=d['envChange']['after'];assert after['text'].count(old)==1
        after['text']=after['text'].replace(old,new)
        c.execute("UPDATE spell_index SET raw_listview_json=? WHERE class_key=? AND spell_id=? AND kind='abilities'",(json.dumps(d),cl,sid))

def test_batch_2255_ranks_cross_class_and_composite_weapon_are_typed_but_not_l2(db):
    with sqlite3.connect(db) as c:
        rows=c.execute("SELECT kind,count(*) FROM ability_effect_atom_observations GROUP BY kind").fetchall()
        d=dict(rows)
        assert d['actor_attack_power_increase']==26
        assert d['target_armor_reduction']==10
        assert d['weapon_damage_plus']==21
        assert d['weapon_multiplier_plus']==17
        assert c.execute("SELECT COUNT(DISTINCT class_key) FROM spell_index WHERE kind='abilities'").fetchone()[0]==9
        assert c.execute("SELECT COUNT(*) FROM spell_index WHERE kind='abilities'").fetchone()[0]==2255
        assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    ir=ir_for(db,'rogue')
    a,e=partial_source_action(ir,class_key='rogue',spell_id=53,db_path=db,fragment_kind='weapon_flat_bonus')
    assert a.effects[0].weapon_damage_multiplier==1.5
    assert a.effects[0].flat_damage==10
    assert e['partial_not_l2'] and a.metadata['never_l2_legal']
    with pytest.raises(PartialSourceEvidenceError,match='FORBIDDEN_AT_L2'):
        partial_source_action(ir,class_key='rogue',spell_id=53,db_path=db,
                              fragment_kind='weapon_flat_bonus',execution_tier='L2')

def test_ap_aura_changes_real_actor_weapon_dps_then_expires(db):
    ir=ir_for(db,'paladin')
    a,_=partial_source_action(ir,class_key='paladin',spell_id=19740,db_path=db,
                              fragment_kind='actor_attack_power_aura')
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    weapon=next(x for x in ir.auto_attacks if x.school=='physical')
    from src.game.model.ir import WeaponDamageEffect
    effect=WeaponDamageEffect('weapon_damage','physical','enemy',weapon.damage_source,weapon.swing_time_s)
    before=expected_weapon_damage(effect,actor=actor)['expected_damage']
    rt=CombatRuntime(actor=actor,target=TargetState.with_health('enemy',1e6),allow_source_partial_l1=True)
    rt.schedule_action(a)
    assert actor.stats['attack_power']>=14
    buffed=expected_weapon_damage(effect,actor=actor)['expected_damage']
    assert buffed>before
    rt.advance_to(3601)
    assert expected_weapon_damage(effect,actor=actor)['expected_damage']==pytest.approx(before)
    with pytest.raises(ValueError,match='SOURCE_PARTIAL_L1_ACTION_FORBIDDEN'):
        execute_action(action=a,actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes),
                       target=TargetState.with_health('enemy',1e6))

def test_target_armor_effect_and_source_level_legality(db):
    ir=ir_for(db,'warlock')
    a,_=partial_source_action(ir,class_key='warlock',spell_id=704,db_path=db,
                              fragment_kind='target_armor_debuff')
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    target=TargetState.with_health('enemy',1e6,armor=1000,spell_hit=1.)
    rt=CombatRuntime(actor=actor,target=target,allow_source_partial_l1=True)
    rt.schedule_action(a)
    assert target.effective_stat('armor')==825
    rt.advance_to(121)
    assert target.effective_stat('armor')==1000
    low=ir_for(db,'warlock',10)
    with pytest.raises(PartialSourceEvidenceError,match='SOURCE_RANK_EXCEEDS_ACTOR_LEVEL'):
        partial_source_action(low,class_key='warlock',spell_id=7658,db_path=db,
                              fragment_kind='target_armor_debuff')

def test_data_only_index_change_changes_actual_weapon_damage_after_reingest(db):
    ir=ir_for(db,'hunter')
    before=probe_l1_source_fragment(ir,class_key='hunter',spell_id=2973,
                                    fragment_kind='weapon_flat_bonus',db_path=db)
    assert before['l1_weapon_flat_bonus']==5
    mutate_index(db,'hunter',2973,'weapon damage plus 5','weapon damage plus 25')
    with pytest.raises(ValueError,match='STALE|REINGEST'):
        probe_l1_source_fragment(ir,class_key='hunter',spell_id=2973,
                                 fragment_kind='weapon_flat_bonus',db_path=db)
    ingest(db)
    after=probe_l1_source_fragment(ir,class_key='hunter',spell_id=2973,
                                   fragment_kind='weapon_flat_bonus',db_path=db)
    assert after['l1_weapon_flat_bonus']==25
    assert after['base_damage_observed']==pytest.approx(before['base_damage_observed']+20)
    assert not after['valid_for_l2_score']

def test_negative_missing_duration_and_ambiguous_weapon_fail_closed(db):
    ir,template,proxy=bounded_actor_l1_probe_ir(class_key='hunter',level=30,db_path=db)
    assert proxy is True
    with pytest.raises(PartialSourceEvidenceError,match='DURATION_MISSING_OR_AMBIGUOUS'):
        partial_source_action(ir,class_key='hunter',spell_id=13161,
                              fragment_kind='actor_attack_power_aura',db_path=db)
    ir=ir_for(db,'druid')
    with pytest.raises(PartialSourceEvidenceError,match='AMBIGUOUS_SOURCE_IR_WEAPON'):
        partial_source_action(ir,class_key='druid',spell_id=1082,
                              fragment_kind='weapon_flat_bonus',db_path=db)
