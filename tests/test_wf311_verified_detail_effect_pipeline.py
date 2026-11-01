"""Nine-class generic source detail slot -> typed stage -> existing L1 executor.

Every partial action remains forbidden in L2/L3, including an apparently
complete-looking one-slot periodic heal. No hardcoded runtime spell behavior.
"""
from __future__ import annotations
import hashlib
from pathlib import Path
import shutil
import sqlite3
import zlib
import pytest
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_verified_detail_effects import (
    ingest,read_current_effects,parse_detail_effects)
from src.game.data.forever.source_partial_l1 import (
    partial_verified_detail_action,probe_verified_detail_l1,PartialSourceEvidenceError)
from tools.wf292_batch_verified_source_recovery import typed_ingest_stage


def staged(tmp_path):
    path=tmp_path/'source.sqlite';shutil.copy2(DEFAULT_DB,path)
    return path


def test_nine_class_verified_slot_batch_and_no_legal_promotions(tmp_path):
    source=staged(tmp_path)
    result=ingest(source)
    assert result['verified_pages']==20
    assert result['effect_slots']==36
    assert result['by_kind']['periodic_damage']==1
    assert result['by_kind']['periodic_heal']==2
    assert result['by_kind']['direct_damage']==5
    assert result['executable_promotions']==result['accepted_checkpoints']==0
    with sqlite3.connect(source) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('SELECT COUNT(*) FROM verified_spell_detail_effect_slots').fetchone()[0]==36
        # Eight classes have independently verified detail HTML, ninth has
        # indexed but no detail evidence; do not synthesize a Paladin slot.
        assert db.execute("SELECT COUNT(*) FROM verified_spell_detail_effect_headers WHERE class_key='paladin'").fetchone()[0]==0
        fb=read_current_effects(db,class_key='mage',spell_id=133)
        assert len(fb['effects'])==2
        assert [x['kind'] for x in fb['effects']]==['direct_damage','periodic_damage']
        assert fb['effects'][1]['values']['tick_interval_s']==2
        assert fb['effects'][1]['values']['tick_count']==2
        assert fb['effects'][1]['values']['total_base']==4
        assert read_current_effects(db,class_key='priest',spell_id=139)['effects'][0]['values']['tick_count']==5
        assert read_current_effects(db,class_key='mage',spell_id=10)['effects'][0]['kind']=='unsupported'


def test_source_detail_ticks_are_real_generic_runtime_events_not_terminal_proxy(tmp_path):
    source=staged(tmp_path);ingest(source)
    mage=build_game_ir_slice(class_key='mage',level=20,ability_db_path=source)
    priest=build_game_ir_slice(class_key='priest',level=20,ability_db_path=source)
    fire=probe_verified_detail_l1(mage,class_key='mage',spell_id=133,slot=2,db_path=source)
    assert fire['total_damage']==4
    assert fire['damage_event_times']==[3.5,5.5]
    assert fire['verified_tick_interval_s']==2
    assert not fire['valid_for_l2_score']
    from src.game.runtime.simulator import execute_action
    from src.game.runtime.state import ActorState,TargetState
    action,_=partial_verified_detail_action(mage,class_key='mage',spell_id=133,slot=2,db_path=source)
    with pytest.raises(ValueError,match='SOURCE_PARTIAL_L1_ACTION_FORBIDDEN'):
        execute_action(action=action,actor=ActorState.from_ir(mage.actor,mage.resources,()),
                       target=TargetState.with_health('enemy',100000))
    renew=probe_verified_detail_l1(priest,class_key='priest',spell_id=139,slot=1,db_path=source)
    assert renew['heal_event_times']==[3,6,9,12,15]
    assert renew['verified_tick_count']==5
    frost=probe_verified_detail_l1(mage,class_key='mage',spell_id=116,slot=2,db_path=source)
    assert frost['total_damage']==20
    assert frost['damage_event_times']==[1.5]
    with pytest.raises(PartialSourceEvidenceError,match='L2_L3_FORBIDDEN'):
        partial_verified_detail_action(mage,class_key='mage',spell_id=133,slot=2,
                                      db_path=source,execution_tier='L2')
    with pytest.raises(PartialSourceEvidenceError,match='UNSUPPORTED_VERIFIED_EFFECT_SLOT'):
        partial_verified_detail_action(mage,class_key='mage',spell_id=10,slot=1,db_path=source)
    with pytest.raises(PartialSourceEvidenceError,match='NO_VERIFIED_DETAIL_EFFECT_SLOTS'):
        partial_verified_detail_action(build_game_ir_slice(class_key='paladin',level=20,ability_db_path=source),
                                      class_key='paladin',spell_id=999,slot=1,db_path=source)


def test_data_only_verified_effect_patch_changes_executor_after_reingest(tmp_path):
    source=staged(tmp_path);ingest(source)
    ir=build_game_ir_slice(class_key='mage',level=20,ability_db_path=source)
    assert probe_verified_detail_l1(ir,class_key='mage',spell_id=133,slot=2,db_path=source)['total_damage']==4
    with sqlite3.connect(source) as db:
        bid=db.execute("SELECT batch_id FROM spell_index WHERE class_key='mage' AND spell_id=133").fetchone()[0]
        original=zlib.decompress(db.execute('SELECT html_zlib FROM spell_detail_snapshots WHERE batch_id=? AND spell_id=133',(bid,)).fetchone()[0])
        old=b'Value: 2 every 2 seconds'
        assert original.count(old)==1
        updated=original.replace(old,b'Value: 3 every 2 seconds')
        digest=hashlib.sha256(updated).hexdigest()
        db.execute('UPDATE spell_detail_snapshots SET html_zlib=?,html_bytes=?,html_sha256=? WHERE batch_id=? AND spell_id=133',
                   (zlib.compress(updated),len(updated),digest,bid))
        db.execute('UPDATE spell_details SET html_sha256=? WHERE batch_id=? AND spell_id=133',(digest,bid))
        with pytest.raises(ValueError,match='STALE_VERIFIED_EFFECT_HTML'):
            read_current_effects(db,class_key='mage',spell_id=133)
    from tools.wf292_ingest_verified_detail_headers_sqlite import ingest as ingest_headers
    ingest_headers(source)
    ingest(source)
    assert probe_verified_detail_l1(ir,class_key='mage',spell_id=133,slot=2,db_path=source)['total_damage']==6
    with sqlite3.connect(source) as db:
        db.execute("UPDATE verified_spell_detail_effect_slots SET values_json='{}' WHERE class_key='mage' AND spell_id=133 AND slot=2")
        with pytest.raises(ValueError,match='TAMPERED_VERIFIED_EFFECT_SLOTS'):
            read_current_effects(db,class_key='mage',spell_id=133)


def test_source_pipeline_is_staged_and_immutable(tmp_path):
    source=staged(tmp_path);target=tmp_path/'typed.sqlite'
    old=hashlib.sha256(source.read_bytes()).hexdigest()
    r=typed_ingest_stage(source_stage=source,typed_stage=target)
    assert r['ingested']['verified_detail_effect_slots']['effect_slots']==36
    assert r['accepted_checkpoints']==r['executable_promotions']==0
    assert hashlib.sha256(source.read_bytes()).hexdigest()==old
    with sqlite3.connect(target) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert read_current_effects(db,class_key='mage',spell_id=133)['effects'][1]['kind']=='periodic_damage'


def test_malformed_or_unsourced_slots_are_not_silently_ignored():
    good='''<table id="spelldetails"><tbody><tr><th>Cost</th><td>10 Mana</td></tr>
      <tr><th>Cast time</th><td>Instant</td></tr>
      <tr><th>Effect #1</th><td>Apply Aura: Periodic Damage<small>Value: 5 every 2 seconds</small></td></tr>
      <tr><th>Effect #2</th><td>Dummy<small>Value: 1</small></td></tr></tbody></table>'''
    parsed=parse_detail_effects(good)
    assert [x['kind'] for x in parsed['effects']]==['unsupported_periodic_schedule','unsupported']
    with pytest.raises(ValueError,match='NONCONTIGUOUS'):
        parse_detail_effects(good.replace('Effect #2','Effect #3'))
    with pytest.raises(ValueError,match='INCOMPLETE'):
        parse_detail_effects(good.replace('<th>Cost</th>','<th>Unknown</th>'))
