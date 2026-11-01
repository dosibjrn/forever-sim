"""WF294: existing CombatRuntime executes sourced *partial* fragments only at L1."""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
import shutil

import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_effect_atoms import ingest
from src.game.data.forever.source_partial_l1 import (
    PartialSourceEvidenceError,partial_source_action,probe_l1_source_fragment)
from src.game.runtime.state import ActorState,TargetState
from src.game.runtime.simulator import execute_action,CombatRuntime
from tools.wf294_l1_partial_nine_class import measure


def test_real_same_executor_source_fireball_l1_and_strict_default_l2_block():
    ir=build_game_ir_slice(class_key='mage',level=20)
    action,evidence=partial_source_action(ir,class_key='mage',spell_id=133)
    assert action.metadata['never_l2_legal'] and evidence['partial_not_l2']
    assert action.effects[0].unsupported_semantics
    assert {x['semantic'] for x in action.effects[0].unsupported_semantics} >= {
        'spell_power_coefficient','gcd_mode_and_acquisition','remaining_tooltip'}
    target=TargetState.with_health('target',10_000)
    actor=ActorState.from_ir(ir.actor,ir.resources,())
    start=dict(actor.resources)
    with pytest.raises(ValueError,match='SOURCE_PARTIAL_L1_ACTION_FORBIDDEN_IN_PRODUCTION_RUNTIME'):
        execute_action(action=action,actor=actor,target=target)
    assert dict(actor.resources)==start and actor.current_time_s==0 and target.health==10000
    with pytest.raises(ValueError,match='SOURCE_PARTIAL_L1_ACTION_FORBIDDEN_IN_PRODUCTION_RUNTIME'):
        CombatRuntime(actor=actor,target=target).schedule_action(action)
    l1=probe_l1_source_fragment(ir,class_key='mage',spell_id=133)
    assert l1['base_damage_observed']==19.0
    assert l1['events']>=3 and l1['valid_for_l2_score'] is False
    with pytest.raises(PartialSourceEvidenceError,match='FORBIDDEN_AT_L2'):
        partial_source_action(ir,class_key='mage',spell_id=133,execution_tier='L2')
    with pytest.raises(PartialSourceEvidenceError,match='FORBIDDEN_AT_L2'):
        probe_l1_source_fragment(ir,class_key='mage',spell_id=133,execution_tier='L3')


def test_derived_l1_runtime_changes_after_only_sqlite_data_patch(tmp_path):
    stage=tmp_path/'forever.sqlite'
    shutil.copy2(DEFAULT_DB,stage)
    ir=build_game_ir_slice(class_key='druid',level=20)
    before=probe_l1_source_fragment(ir,class_key='druid',spell_id=5176,db_path=stage)
    assert before['base_damage_observed']==16.5
    with sqlite3.connect(stage) as db:
        raw=db.execute("SELECT raw_listview_json FROM spell_index WHERE class_key='druid' AND spell_id=5176").fetchone()[0]
        d=json.loads(raw)
        d['envChange']['after']['text']=d['envChange']['after']['text'].replace('15 to 18 Nature damage','29 to 35 Nature damage')
        db.execute("UPDATE spell_index SET raw_listview_json=? WHERE class_key='druid' and spell_id=5176",(json.dumps(d),))
    with pytest.raises(ValueError,match='STALE_ATOM_INDEX'):
        probe_l1_source_fragment(ir,class_key='druid',spell_id=5176,db_path=stage)
    changed=ingest(stage)
    assert changed['ranks_with_atoms']>500
    after=probe_l1_source_fragment(ir,class_key='druid',spell_id=5176,db_path=stage)
    assert after['base_damage_observed']==32.0 and after['base_damage_observed']>before['base_damage_observed']
    assert after['valid_for_l2_score'] is False


def test_source_legality_blocks_unknown_and_no_cost_and_underlevel():
    ir=build_game_ir_slice(class_key='mage',level=10)
    with pytest.raises(PartialSourceEvidenceError,match='UNKNOWN_SOURCE_ABILITY_ID'):
        partial_source_action(ir,class_key='mage',spell_id=999999999)
    with pytest.raises(PartialSourceEvidenceError):
        partial_source_action(ir,class_key='warrior',spell_id=100)
    low=build_game_ir_slice(class_key='mage',level=20)
    with pytest.raises(Exception,match='minimum level'):
        probe_l1_source_fragment(low,class_key='mage',spell_id=120)


def test_cross_class_no_whitelist_source_probes():
    report=measure(20)
    assert len(report['classes'])==9
    assert report['partial_l1_completed']>=60
    assert report['partial_l1_executor_events']>=200
    assert report['classes']['mage']['l1_partial_executed']>=14
    assert report['classes']['hunter']['l1_partial_executed']>=3
    assert report['classes']['rogue']['l1_partial_executed']==0
    assert report['classes']['warrior']['l1_partial_executed']==0
    assert report['l2_source_complete_promotions']==0
    assert report['accepted_class_level_checkpoints']==0
