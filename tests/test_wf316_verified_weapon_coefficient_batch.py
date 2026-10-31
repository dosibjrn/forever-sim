"""WF316: source-verified weapon-slot reduction and real SP execution.

L1 only. Synthetic target and source-IR weapons are not acquisition proofs.
"""
from __future__ import annotations
import hashlib
import shutil
import sqlite3
import zlib
from pathlib import Path
import pytest
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_verified_detail_effects import ingest,read_current_effects
from src.game.data.forever.source_partial_l1 import (
    complete_verified_detail_l1_action,probe_verified_detail_composite_l1,
    PartialSourceEvidenceError)
from src.game.runtime.simulator import execute_action,CombatRuntime
from src.game.runtime.state import ActorState,TargetState
from src.game.model.ir import IncomingAttackDefinition
from tools.wf292_ingest_verified_detail_headers_sqlite import ingest as ingest_headers

@pytest.fixture
def db(tmp_path):
    path=tmp_path/'canonical_copy.sqlite';shutil.copy2(DEFAULT_DB,path);ingest(path)
    return path

def action(db,cl,sid):
    ir=build_game_ir_slice(class_key=cl,level=20,ability_db_path=db)
    a,_=complete_verified_detail_l1_action(ir,class_key=cl,spell_id=sid,db_path=db)
    return ir,a

def source_replace(db,cl,sid,old,new):
    with sqlite3.connect(db) as con:
        batch=con.execute('SELECT batch_id FROM spell_index WHERE class_key=? AND spell_id=?',(cl,sid)).fetchone()[0]
        raw=zlib.decompress(con.execute('SELECT html_zlib FROM spell_detail_snapshots WHERE batch_id=? AND spell_id=?',(batch,sid)).fetchone()[0])
        assert raw.count(old)==1
        updated=raw.replace(old,new);digest=hashlib.sha256(updated).hexdigest()
        con.execute('UPDATE spell_detail_snapshots SET html_zlib=?,html_bytes=?,html_sha256=? WHERE batch_id=? AND spell_id=?',
                    (zlib.compress(updated),len(updated),digest,batch,sid))
        con.execute('UPDATE spell_details SET html_sha256=? WHERE batch_id=? AND spell_id=?',(digest,batch,sid))

def test_three_weapon_opcode_families_from_verified_html_and_one_rogue_hit(db):
    with sqlite3.connect(db) as con:
        assert [e['kind'] for e in read_current_effects(con,class_key='rogue',spell_id=53)['effects']]==[
            'normalized_weapon_bonus','weapon_multiplier','resource_gain']
        assert read_current_effects(con,class_key='hunter',spell_id=75)['effects'][0]['kind']=='weapon_base'
        assert read_current_effects(con,class_key='warrior',spell_id=78)['effects'][0]['kind']=='weapon_bonus'
    ir,a=action(db,'rogue',53)
    assert len(a.effects)==2 and a.effects[0].effect_type=='weapon_damage'
    assert a.effects[0].weapon_damage_multiplier==1.51 and a.effects[0].flat_damage==11
    assert a.effects[0].metadata['verified_weapon_slots_folded_into_one_hit']==2
    result=execute_action(action=a,actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes),
        target=TargetState.with_health('synthetic',1e6),allow_source_partial_l1=True)
    assert sum(e.kind=='ActionStarted' for e in result.events)==1
    assert sum(e.kind=='Damage' for e in result.events)==1
    assert sum(e.kind=='ResourceChanged' for e in result.events)==1
    assert [e.payload['amount'] for e in result.events if e.kind=='ResourceChanged']==[2]
    assert result.events[0].payload['resource_spend'][0]['amount']==60
    with pytest.raises(ValueError,match='SOURCE_PARTIAL_L1_ACTION_FORBIDDEN'):
        execute_action(action=a,actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes),
            target=TargetState.with_health('synthetic',1e6))
    hi,ha=action(db,'hunter',75)
    assert ha.gcd_s==0 and ha.costs==()
    assert probe_verified_detail_composite_l1(hi,class_key='hunter',spell_id=75,db_path=db)['total_damage']>0
    wi,wa=action(db,'warrior',78)
    assert wa.gcd_s==0 and wa.effects[0].flat_damage==12
    with pytest.raises(PartialSourceEvidenceError,match='INSUFFICIENT_SOURCE_IR_RESOURCE'):
        probe_verified_detail_composite_l1(wi,class_key='warrior',spell_id=78,db_path=db)

def test_source_sp_coefficients_reach_direct_periodic_heal_and_shield_runtime(db):
    mage,fire=action(db,'mage',133)
    assert fire.effects[0].spell_power_coefficient==.429
    zero=probe_verified_detail_composite_l1(mage,class_key='mage',spell_id=133,db_path=db,spell_power=0)
    powered=probe_verified_detail_composite_l1(mage,class_key='mage',spell_id=133,db_path=db,spell_power=100)
    assert zero['total_damage']==23
    assert powered['total_damage']==pytest.approx(65.9)
    priest,renew=action(db,'priest',139)
    assert renew.effects[0].spell_power_coefficient_per_tick==.2
    result=execute_action(action=renew,actor=ActorState.from_ir(priest.actor,priest.resources,priest.modes),
        target=TargetState.with_health('synthetic',1e6),spell_power=100,allow_source_partial_l1=True)
    heals=[e.payload['amount'] for e in result.events if e.kind=='Heal']
    assert heals==[30]*5
    pi,shield=action(db,'priest',17)
    assert shield.effects[0].actor_absorb_spell_power_coefficient==.1
    actor=ActorState.from_ir(pi.actor,pi.resources,pi.modes)
    rt=CombatRuntime(actor=actor,target=TargetState.with_health('synthetic',1e6),
        spell_power=100,allow_source_partial_l1=True)
    rt.schedule_action(shield)
    key=shield.effects[0].aura_id
    assert actor.absorb_shields[key]==55
    attack=IncomingAttackDefinition(id='synthetic',name='test',source_actor_id='enemy',
        target_actor_id=actor.id,school='physical',raw_damage=50,hit_chance=1,
        health_resource_id='health')
    hit=rt.resolve_incoming_attack(attack,at_time_s=1)
    assert hit['absorbed_damage']==50 and actor.absorb_shields[key]==5
    with pytest.raises(PartialSourceEvidenceError,match='INVALID_L1_PROBE_SPELL_POWER'):
        probe_verified_detail_composite_l1(mage,class_key='mage',spell_id=133,db_path=db,spell_power=-10)

def test_data_only_weapon_percent_change_changes_one_hit_and_stale_fails_closed(db):
    ir,a=action(db,'rogue',53)
    before=probe_verified_detail_composite_l1(ir,class_key='rogue',spell_id=53,db_path=db)['total_damage']
    source_replace(db,'rogue',53,b'Value: 151',b'Value: 171')
    with pytest.raises(ValueError,match='STALE_VERIFIED_(EFFECT_HTML|DETAIL_HEADER)'):
        action(db,'rogue',53)
    ingest_headers(db);ingest(db)
    new,_=complete_verified_detail_l1_action(ir,class_key='rogue',spell_id=53,db_path=db)
    assert new.effects[0].weapon_damage_multiplier==1.71
    after=probe_verified_detail_composite_l1(ir,class_key='rogue',spell_id=53,db_path=db)['total_damage']
    assert after>before
    assert after-before==pytest.approx((before-11)*(.2/1.51))

def test_data_only_sp_coefficient_change_modifies_damage_and_stale_blocks(db):
    ir,a=action(db,'mage',133)
    before=probe_verified_detail_composite_l1(ir,class_key='mage',spell_id=133,db_path=db,spell_power=100)['total_damage']
    source_replace(db,'mage',133,b'0.429)',b'0.529)')
    with pytest.raises(ValueError,match='STALE_VERIFIED_(EFFECT_HTML|DETAIL_HEADER)'):
        action(db,'mage',133)
    ingest_headers(db);ingest(db)
    after=probe_verified_detail_composite_l1(ir,class_key='mage',spell_id=133,db_path=db,spell_power=100)['total_damage']
    assert after-before==pytest.approx(10)

def test_unsupported_slots_and_invalid_weapon_composition_stay_blocked(db):
    mage=build_game_ir_slice(class_key='mage',level=20,ability_db_path=db)
    slow,_=complete_verified_detail_l1_action(mage,class_key='mage',spell_id=116,db_path=db)
    assert [e.effect_type for e in slow.effects]==['target_stat_debuff','damage']
    with pytest.raises(PartialSourceEvidenceError,match='UNSUPPORTED_VERIFIED_COMPOSITE_SLOTS'):
        complete_verified_detail_l1_action(mage,class_key='mage',spell_id=118,db_path=db)
    with pytest.raises(PartialSourceEvidenceError,match='VERIFIED_RANK_EXCEEDS_ACTOR_LEVEL'):
        complete_verified_detail_l1_action(mage,class_key='mage',spell_id=120,db_path=db)
    source_replace(db,'rogue',53,b'Normalized Weapon Damage',b'Weapon Damage - %')
    ingest_headers(db);ingest(db)
    rogue=build_game_ir_slice(class_key='rogue',level=20,ability_db_path=DEFAULT_DB)
    with pytest.raises(PartialSourceEvidenceError,match='AMBIGUOUS_VERIFIED_WEAPON_SLOT_COMPOSITION'):
        complete_verified_detail_l1_action(rogue,class_key='rogue',spell_id=53,db_path=db)
