"""Source-verified absorb/control category batch, all via existing CombatRuntime.

The source-derived actions remain L1 ONLY; none are independently learned or
eligible for policy/L2/checkpoint claims. Incoming damage values in these
mechanics tests are artificial test scenarios, not claimed Forever game facts.
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
from src.game.data.forever.source_verified_detail_effects import ingest, read_current_effects
from src.game.data.forever.source_partial_l1 import (
    complete_verified_detail_l1_action,partial_source_action,
    probe_l1_indexed_rank_with_bounded_actor,PartialSourceEvidenceError,
    bounded_actor_l1_probe_ir,
)
from src.game.model.ir import IncomingAttackDefinition
from src.game.runtime.state import ActorState,TargetState
from src.game.runtime.simulator import CombatRuntime,execute_action
from tools.wf292_ingest_verified_detail_headers_sqlite import ingest as ingest_headers

@pytest.fixture
def db(tmp_path):
    path=tmp_path/'source.sqlite'
    shutil.copy2(DEFAULT_DB,path)
    ingest(path)
    return path

def source_action(db,cl,sid,level=20):
    ir=build_game_ir_slice(class_key=cl,level=level,ability_db_path=db)
    action,_=complete_verified_detail_l1_action(ir,class_key=cl,spell_id=sid,db_path=db)
    return ir,action

def incoming(actor,damage):
    return IncomingAttackDefinition(id='test_attack',name='synthetic test',
        source_actor_id='test_enemy',target_actor_id=actor.id,school='physical',
        raw_damage=damage,hit_chance=1,health_resource_id='health')

def replace_source(db,cl,sid,old,new):
    with sqlite3.connect(db) as con:
        batch=con.execute('SELECT batch_id FROM spell_index WHERE class_key=? AND spell_id=?',(cl,sid)).fetchone()[0]
        raw=zlib.decompress(con.execute('SELECT html_zlib FROM spell_detail_snapshots WHERE batch_id=? AND spell_id=?',(batch,sid)).fetchone()[0])
        assert raw.count(old)==1
        modified=raw.replace(old,new)
        digest=hashlib.sha256(modified).hexdigest()
        con.execute('UPDATE spell_detail_snapshots SET html_zlib=?,html_bytes=?,html_sha256=? WHERE batch_id=? AND spell_id=?',
                    (zlib.compress(modified),len(modified),digest,batch,sid))
        con.execute('UPDATE spell_details SET html_sha256=? WHERE batch_id=? AND spell_id=?',(digest,batch,sid))
    return digest

def test_verified_shield_reduces_real_incoming_damage_refreshes_and_expires(db):
    ir,action=source_action(db,'priest',17)
    assert len(action.effects)==1
    assert action.effects[0].actor_absorb_amount==45
    assert action.effects[0].duration_s==30
    assert action.costs[0].amount==45
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    rt=CombatRuntime(actor=actor,target=TargetState.with_health('enemy',1_000_000),allow_source_partial_l1=True)
    rt.schedule_action(action)
    key=action.effects[0].aura_id
    assert actor.absorb_shields[key]==45
    hit1=rt.resolve_incoming_attack(incoming(actor,30),at_time_s=2)
    assert hit1['absorbed_damage']==30 and hit1['health_damage_applied']==0
    assert actor.absorb_shields[key]==15
    hit2=rt.resolve_incoming_attack(incoming(actor,20),at_time_s=3)
    assert hit2['absorbed_damage']==15 and hit2['health_damage_applied']==5
    assert key not in actor.absorb_shields
    rt.schedule_action(action,at_time_s=5)
    assert actor.absorb_shields[key]==45
    rt.advance_to(30)
    assert actor.absorb_shields[key]==45  # stale generation-1 expiry ignored
    rt.advance_to(36)
    assert key not in actor.absorb_shields
    hit3=rt.resolve_incoming_attack(incoming(actor,20),at_time_s=37)
    assert hit3['absorbed_damage']==0 and hit3['health_damage_applied']==20
    assert sum(x.kind=='AbsorbShieldGranted' for x in rt.trace)==2

def test_shield_survives_new_mob_and_uses_source_aura_expiry(db):
    ir,action=source_action(db,'priest',17)
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    rt=CombatRuntime(actor=actor,target=TargetState.with_health('mob1',1e6),allow_source_partial_l1=True)
    rt.schedule_action(action)
    rt.advance_to(5)
    transferred=rt.persist_actor_periodics()
    assert len(transferred)==1 and transferred[0].kind=='AuraExpired'
    rt2=CombatRuntime(actor=actor,target=TargetState.with_health('mob2',1e6),allow_source_partial_l1=True)
    hit=rt2.resolve_incoming_attack(incoming(actor,25),at_time_s=7)
    assert hit['absorbed_damage']==25 and hit['health_damage_applied']==0
    assert actor.absorb_shields[action.effects[0].aura_id]==20
    rt2.advance_to(31)
    assert not actor.absorb_shields

def test_verified_root_composes_with_damage_one_cast_and_expires(db):
    ir,action=source_action(db,'mage',122)
    assert len(action.effects)==2
    assert [x.effect_type for x in action.effects]==['damage','control']
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    rt=CombatRuntime(actor=actor,target=TargetState.with_health('enemy',1e6),allow_source_partial_l1=True)
    rt.schedule_action(action)
    assert rt.total_damage==21
    assert rt.target.active_controls['root']==8
    assert len([x for x in rt.trace if x.kind=='ActionStarted'])==1
    assert rt.trace[0].payload['resource_spend'][0]['amount']==55
    rt.advance_to(9)
    assert not rt.target.active_controls
    with pytest.raises(ValueError,match='SOURCE_PARTIAL_L1_ACTION_FORBIDDEN'):
        execute_action(action=action,actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes),
                       target=TargetState.with_health('enemy',1e6))

def test_data_only_verified_shield_change_modifies_survival_and_stale_is_blocked(db):
    ir,action=source_action(db,'priest',17)
    assert action.effects[0].actor_absorb_amount==45
    replace_source(db,'priest',17,b'Value: 45',b'Value: 65')
    with pytest.raises(ValueError,match='STALE_VERIFIED_(EFFECT_HTML|DETAIL_HEADER)'):
        source_action(db,'priest',17)
    ingest_headers(db);ingest(db)
    # Reuse pre-mutation actor IR for this isolated effect data-only test.
    # A production IR rebuild also requires re-ingesting all other typed ledgers.
    new,_=complete_verified_detail_l1_action(ir,class_key='priest',spell_id=17,db_path=db)
    assert new.effects[0].actor_absorb_amount==65
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    rt=CombatRuntime(actor=actor,target=TargetState.with_health('enemy',1e6),allow_source_partial_l1=True)
    rt.schedule_action(new)
    hit=rt.resolve_incoming_attack(incoming(actor,55),at_time_s=1)
    assert hit['absorbed_damage']==55 and hit['health_damage_applied']==0
    assert actor.absorb_shields[new.effects[0].aura_id]==10

def test_restricted_absorb_school_never_promoted_to_all_school(db):
    ir,_=source_action(db,'priest',17)
    replace_source(db,'priest',17,
        b'Absorb Damage (Arcane, Fire, Frost, Holy, Nature, Physical, Shadow)',
        b'Absorb Damage (Frost)')
    ingest_headers(db);ingest(db)
    with sqlite3.connect(db) as con:
        e=read_current_effects(con,class_key='priest',spell_id=17)
    assert e['effects'][0]['kind']=='unsupported_absorb_school_scope'
    with pytest.raises(PartialSourceEvidenceError,match='UNSUPPORTED_VERIFIED_COMPOSITE_SLOTS'):
        complete_verified_detail_l1_action(ir,class_key='priest',spell_id=17,db_path=db)

def test_index_shields_batch_12_ranks_l1_only_and_level_gate(db):
    with sqlite3.connect(db) as con:
        rows=con.execute("SELECT class_key,spell_id FROM ability_effect_atom_observations WHERE kind='damage_absorption'").fetchall()
    assert len(rows)==13
    executed=[];blocked=[]
    for cl,sid in rows:
        try:
            proof=probe_l1_indexed_rank_with_bounded_actor(class_key=cl,level=60,
                spell_id=sid,fragment_kind='damage_absorption',db_path=db)
            executed.append((cl,sid,proof))
        except PartialSourceEvidenceError as exc:
            blocked.append((cl,sid,str(exc)))
    assert len(executed)==13
    assert blocked==[]
    assert all(x['valid_for_l2_score'] is False and x['bounded_actor_level_proxy'] for _,_,x in executed)
    # The independently verified Priest detail has 45, while the source index
    # change-list tooltip says 48. Detail authority must win, not blend.
    priest_ir=build_game_ir_slice(class_key='priest',level=20,ability_db_path=db)
    verified_index_action,_=partial_source_action(priest_ir,class_key='priest',spell_id=17,
        db_path=db,fragment_kind='damage_absorption')
    assert verified_index_action.effects[0].actor_absorb_amount==45
    # Mage L46 shield cannot be legally cast by a level-20 actor, even in L1.
    ir=build_game_ir_slice(class_key='mage',level=20,ability_db_path=db)
    with pytest.raises(PartialSourceEvidenceError,match='SOURCE_RANK_EXCEEDS_ACTOR_LEVEL'):
        partial_source_action(ir,class_key='mage',spell_id=13031,
            db_path=db,fragment_kind='damage_absorption')
    with pytest.raises(PartialSourceEvidenceError,match='PARTIAL_SOURCE_ACTION_FORBIDDEN_AT_L2_OR_L3'):
        partial_source_action(ir,class_key='mage',spell_id=13031,
            db_path=db,fragment_kind='damage_absorption',execution_tier='L2')


def test_index_only_shield_data_change_requires_reingest_and_changes_executor(db):
    from src.game.data.forever.source_effect_atoms import ingest as ingest_atoms
    ir,template,proxy=bounded_actor_l1_probe_ir(class_key='mage',level=60,db_path=db)
    assert proxy is True
    before,_=partial_source_action(ir,class_key='mage',spell_id=13031,
        db_path=db,fragment_kind='damage_absorption')
    assert before.effects[0].actor_absorb_amount==561
    with sqlite3.connect(db) as con:
        raw=con.execute("SELECT raw_listview_json FROM spell_index WHERE class_key='mage' AND spell_id=13031").fetchone()[0]
        assert raw.count('absorbing 561 damage')==1
        con.execute("UPDATE spell_index SET raw_listview_json=? WHERE class_key='mage' AND spell_id=13031",
                    (raw.replace('absorbing 561 damage','absorbing 611 damage'),))
    with pytest.raises(ValueError,match='STALE_ATOM_INDEX'):
        partial_source_action(ir,class_key='mage',spell_id=13031,db_path=db,fragment_kind='damage_absorption')
    ingest_atoms(db)
    after,_=partial_source_action(ir,class_key='mage',spell_id=13031,
        db_path=db,fragment_kind='damage_absorption')
    assert after.effects[0].actor_absorb_amount==611
    assert after.metadata['never_l2_legal']
