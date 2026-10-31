"""WF318: generic SHA-verified movement-slow slot is not a silent no-op."""
from __future__ import annotations
import hashlib,shutil,sqlite3,zlib
from pathlib import Path
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_partial_l1 import (
    complete_verified_detail_l1_action,probe_verified_detail_composite_l1,
    bounded_actor_l1_probe_ir)
from src.game.data.forever.source_verified_detail_effects import ingest,read_current_effects
from tools.wf292_ingest_verified_detail_headers_sqlite import ingest as ingest_headers
from src.game.runtime.state import ActorState,TargetState
from src.game.runtime.simulator import CombatRuntime,execute_action

DB=Path('data/forever/catalogue/forever_abilities.sqlite')

@pytest.fixture
def db(tmp_path):
    path=tmp_path/'source.sqlite';shutil.copy2(DB,path);ingest(path)
    return path


def mutate_html(db,spell_id,old,new):
    with sqlite3.connect(db) as con:
        bid=con.execute('SELECT batch_id FROM spell_index WHERE class_key=? AND spell_id=?',
                        ('mage',spell_id)).fetchone()[0]
        raw=zlib.decompress(con.execute('SELECT html_zlib FROM spell_detail_snapshots WHERE batch_id=? AND spell_id=?',
                                    (bid,spell_id)).fetchone()[0])
        assert raw.count(old)==1
        modified=raw.replace(old,new)
        digest=hashlib.sha256(modified).hexdigest()
        con.execute('UPDATE spell_detail_snapshots SET html_zlib=?,html_bytes=?,html_sha256=? WHERE batch_id=? AND spell_id=?',
                    (zlib.compress(modified),len(modified),digest,bid,spell_id))
        con.execute('UPDATE spell_details SET html_sha256=? WHERE batch_id=? AND spell_id=?',
                    (digest,bid,spell_id))


def test_slow_and_damage_are_one_verified_cast_and_expire(db):
    ir=build_game_ir_slice(class_key='mage',level=20,ability_db_path=db)
    a,proof=complete_verified_detail_l1_action(ir,class_key='mage',spell_id=116,db_path=db)
    assert len(a.effects)==2
    assert a.effects[0].effect_type=='target_stat_debuff'
    assert a.effects[0].delta==-.39
    assert a.effects[0].duration_s==5
    assert a.effects[1].effect_type=='damage'
    actor=ActorState.from_ir(ir.actor,ir.resources,())
    target=TargetState.with_health('L1',1e6,movement_speed=1.,spell_hit=1.)
    runtime=CombatRuntime(actor=actor,target=target,allow_source_partial_l1=True)
    runtime.schedule_action(a)
    # The actual target stat changes while the sourced aura is active,
    # and returns to baseline on its source-declared expiry.
    runtime.advance_to(2.0)
    assert target.effective_stat('movement_speed')==pytest.approx(.61)
    runtime.run_until_idle()
    result=runtime.result()
    assert result.total_damage==20
    applied=[e for e in result.events if e.kind=='TargetStatDebuffApplied']
    expired=[e for e in result.events if e.kind=='TargetStatDebuffExpired']
    assert len(applied)==len(expired)==1
    assert applied[0].payload['effective_delta']==-.39
    assert expired[0].payload['expired'] is True
    assert target.effective_stat('movement_speed')==1.0
    assert sum(e.kind=='ActionStarted' for e in result.events)==1
    assert [e.payload['resource_spend'][0]['amount'] for e in result.events if e.kind=='ActionStarted']==[25]
    with pytest.raises(ValueError,match='SOURCE_PARTIAL_L1_ACTION_FORBIDDEN'):
        execute_action(action=a,actor=ActorState.from_ir(ir.actor,ir.resources,()),
            target=TargetState.with_health('L2',1e6,movement_speed=1.,spell_hit=1.))


def test_verified_slow_source_only_mutation_changes_runtime_and_stale_blocks(db):
    ir=build_game_ir_slice(class_key='mage',level=20,ability_db_path=db)
    before=probe_verified_detail_composite_l1(ir,class_key='mage',spell_id=116,db_path=db)
    assert before['movement_slow_L1_delta_at_application']==-.39
    mutate_html(db,116,b'Value: -39%',b'Value: -29%')
    with pytest.raises(ValueError,match='STALE_VERIFIED_'):
        complete_verified_detail_l1_action(ir,class_key='mage',spell_id=116,db_path=db)
    ingest_headers(db);ingest(db)
    after=probe_verified_detail_composite_l1(ir,class_key='mage',spell_id=116,db_path=db)
    assert after['movement_slow_L1_delta_at_application']==-.29
    assert after['total_damage']==before['total_damage']==20
    mutate_html(db,116,b'Value: -29%',b'Value: 29%')
    ingest_headers(db);ingest(db)
    with pytest.raises(ValueError,match='UNSUPPORTED_VERIFIED_COMPOSITE_SLOTS'):
        complete_verified_detail_l1_action(ir,class_key='mage',spell_id=116,db_path=db)


def test_higher_rank_legality_and_l30_proxy_label(db):
    l20=build_game_ir_slice(class_key='mage',level=20,ability_db_path=db)
    with pytest.raises(ValueError,match='VERIFIED_RANK_EXCEEDS_ACTOR_LEVEL'):
        complete_verified_detail_l1_action(l20,class_key='mage',spell_id=120,db_path=db)
    ir,template,proxy=bounded_actor_l1_probe_ir(class_key='mage',level=30,db_path=db)
    assert proxy is True
    r=probe_verified_detail_composite_l1(ir,class_key='mage',spell_id=120,db_path=db)
    assert r['total_damage']==98
    assert r['movement_slow_L1_delta_at_application']==-.39
    assert r['valid_for_l2_score'] is False
