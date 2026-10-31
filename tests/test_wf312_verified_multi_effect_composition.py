"""Source-verified multi-effect actions, strict L1 gate and one paid cast."""
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
    probe_verified_detail_l1,PartialSourceEvidenceError)
from src.game.runtime.simulator import execute_action
from src.game.runtime.state import ActorState,TargetState
from tools.wf292_ingest_verified_detail_headers_sqlite import ingest as ingest_headers

@pytest.fixture
def db(tmp_path):
    path=tmp_path/'canonical_copy.sqlite'
    shutil.copy2(DEFAULT_DB,path)
    ingest(path)
    return path

def test_all_slots_one_paid_cast_real_ordered_direct_then_dot(db):
    ir=build_game_ir_slice(class_key='mage',level=20,ability_db_path=db)
    action,proof=complete_verified_detail_l1_action(ir,class_key='mage',spell_id=133,db_path=db)
    assert len(action.effects)==2
    assert len(action.costs)==1 and action.costs[0].amount==30
    assert action.cast_time_s==1.5
    assert proof['verified_slots']==(1,2)
    assert action.metadata['never_l2_legal']
    with pytest.raises(ValueError,match='SOURCE_PARTIAL_L1_ACTION_FORBIDDEN'):
        execute_action(action=action,actor=ActorState.from_ir(ir.actor,ir.resources,()),
            target=TargetState.with_health('enemy',100000))
    result=execute_action(action=action,actor=ActorState.from_ir(ir.actor,ir.resources,()),
        target=TargetState.with_health('enemy',100000),allow_source_partial_l1=True)
    starts=[e for e in result.events if e.kind=='ActionStarted']
    assert len(starts)==1
    assert starts[0].payload['resource_spend']==[{'resource_id':'mana','amount':30.0,
        'before':570.0,'after':540.0}]
    assert [(e.time_s,e.payload['amount']) for e in result.events if e.kind=='Damage']==[
        (1.5,19.0),(3.5,2.0),(5.5,2.0)]
    assert result.total_damage==23
    assert probe_verified_detail_composite_l1(ir,class_key='mage',spell_id=133,db_path=db)['total_damage']==23


def test_source_data_only_change_alters_full_composite_and_stale_data_fails_closed(db):
    ir=build_game_ir_slice(class_key='mage',level=20,ability_db_path=db)
    with sqlite3.connect(db) as con:
        batch=con.execute("SELECT batch_id FROM spell_index WHERE class_key='mage' AND spell_id=133").fetchone()[0]
        original=zlib.decompress(con.execute('SELECT html_zlib FROM spell_detail_snapshots WHERE batch_id=? AND spell_id=133',(batch,)).fetchone()[0])
        assert original.count(b'Value: 2 every 2 seconds')==1
        updated=original.replace(b'Value: 2 every 2 seconds',b'Value: 3 every 2 seconds')
        digest=hashlib.sha256(updated).hexdigest()
        con.execute('UPDATE spell_detail_snapshots SET html_zlib=?,html_bytes=?,html_sha256=? WHERE batch_id=? AND spell_id=133',
                    (zlib.compress(updated),len(updated),digest,batch))
        con.execute('UPDATE spell_details SET html_sha256=? WHERE batch_id=? AND spell_id=133',(digest,batch))
    with pytest.raises(ValueError,match='STALE_VERIFIED_EFFECT_HTML'):
        complete_verified_detail_l1_action(ir,class_key='mage',spell_id=133,db_path=db)
    ingest_headers(db);ingest(db)
    assert probe_verified_detail_composite_l1(ir,class_key='mage',spell_id=133,db_path=db)['total_damage']==25


def test_unsupported_slots_never_silently_compose_and_l2_forbidden(db):
    mage=build_game_ir_slice(class_key='mage',level=20,ability_db_path=db)
    slow,_=complete_verified_detail_l1_action(mage,class_key='mage',spell_id=116,db_path=db)
    assert [e.effect_type for e in slow.effects]==['target_stat_debuff','damage']
    with pytest.raises(PartialSourceEvidenceError,match='UNSUPPORTED_VERIFIED_COMPOSITE_SLOTS'):
        complete_verified_detail_l1_action(mage,class_key='mage',spell_id=118,db_path=db)
    with pytest.raises(PartialSourceEvidenceError,match='VERIFIED_RANK_EXCEEDS_ACTOR_LEVEL'):
        complete_verified_detail_l1_action(mage,class_key='mage',spell_id=120,db_path=db)
    with pytest.raises(PartialSourceEvidenceError,match='VERIFIED_COMPOSITE_L2_L3_FORBIDDEN'):
        complete_verified_detail_l1_action(mage,class_key='mage',spell_id=133,db_path=db,execution_tier='L2')
    low=build_game_ir_slice(class_key='mage',level=1,ability_db_path=db)
    with pytest.raises((PartialSourceEvidenceError,ValueError)):
        complete_verified_detail_l1_action(low,class_key='mage',spell_id=133,db_path=db)


def test_resource_gain_from_verified_source_is_typed_but_not_a_complete_spell(db):
    with sqlite3.connect(db) as con:
        rogue=read_current_effects(con,class_key='rogue',spell_id=53)
        assert rogue['effects'][2]['kind']=='resource_gain'
        assert rogue['effects'][2]['values']=={'resource':'combo_points','amount':2.0}
    ir=build_game_ir_slice(class_key='rogue',level=20,ability_db_path=db)
    result=probe_verified_detail_l1(ir,class_key='rogue',spell_id=53,slot=3,db_path=db)
    assert result['events']>0 and not result['valid_for_l2_score']
    action,_=complete_verified_detail_l1_action(ir,class_key='rogue',spell_id=53,db_path=db)
    assert [x.effect_type for x in action.effects]==['weapon_damage','resource_change']
    assert action.effects[0].weapon_damage_multiplier==1.51
    assert action.effects[0].flat_damage==11
    assert action.metadata['never_l2_legal']


def test_verified_resource_gain_data_only_changes_actual_executor(db):
    ir=build_game_ir_slice(class_key='rogue',level=20,ability_db_path=db)
    def gain():
        from src.game.data.forever.source_partial_l1 import partial_verified_detail_action
        action,_=partial_verified_detail_action(ir,class_key='rogue',spell_id=53,slot=3,db_path=db)
        result=execute_action(action=action,actor=ActorState.from_ir(ir.actor,ir.resources,()),
            target=TargetState.with_health('enemy',100000),allow_source_partial_l1=True)
        return [(e.payload['amount'],e.payload['after']) for e in result.events if e.kind=='ResourceChanged']
    assert gain()==[(2.0,2.0)]
    with sqlite3.connect(db) as con:
        batch=con.execute("SELECT batch_id FROM spell_index WHERE class_key='rogue' AND spell_id=53").fetchone()[0]
        original=zlib.decompress(con.execute('SELECT html_zlib FROM spell_detail_snapshots WHERE batch_id=? AND spell_id=53',(batch,)).fetchone()[0])
        assert original.count(b'Value: 2')==1
        updated=original.replace(b'Value: 2',b'Value: 3')
        digest=hashlib.sha256(updated).hexdigest()
        con.execute('UPDATE spell_detail_snapshots SET html_zlib=?,html_bytes=?,html_sha256=? WHERE batch_id=? AND spell_id=53',
                    (zlib.compress(updated),len(updated),digest,batch))
        con.execute('UPDATE spell_details SET html_sha256=? WHERE batch_id=? AND spell_id=53',(digest,batch))
    with pytest.raises(ValueError,match='STALE_VERIFIED_EFFECT_HTML'):
        gain()
    ingest_headers(db);ingest(db)
    assert gain()==[(3.0,3.0)]
