"""Verified source-detail extraction and typed staging; no gameplay execution.

Effect slots remain source facts with explicit unsupported semantics. These
regressions cover SHA-verified parsing, quarantine and immutable staging used
by active indexed-action coverage; they do not validate GameIR combat.
"""
from __future__ import annotations
import hashlib
from pathlib import Path
import shutil
import sqlite3
import pytest
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_verified_detail_effects import (
    ingest,read_current_effects,parse_detail_effects)
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
