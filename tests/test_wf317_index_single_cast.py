"""Real source-index batch => existing CombatRuntime L1, not L2 checkpoint."""
from __future__ import annotations
import json
import shutil
import sqlite3
from pathlib import Path
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_index_l1 import source_index_single_l1_action,probe_index_single_l1
from src.game.data.forever.source_effect_atoms import ingest
from src.game.runtime.state import ActorState,TargetState
from src.game.runtime.simulator import execute_action
from tools.wf317_source_index_single_batch import measure

DB=Path('data/forever/catalogue/forever_abilities.sqlite')


def test_source_l20_druid_lower_rank_and_heal_execute_and_pay_resource():
    ir=build_game_ir_slice(class_key='druid',level=20)
    dmg=probe_index_single_l1(ir,class_key='druid',spell_id=5178)
    heal=probe_index_single_l1(ir,class_key='druid',spell_id=5188)
    assert dmg['damage']==34.5 and dmg['actual_cost']==40
    assert heal['healing_requested']==375.5 and heal['actual_cost']==190
    assert dmg['event_count']>=3 and heal['event_count']>=3
    assert dmg['L2_eligible'] is False and heal['checkpoint_accepted'] is False


def test_listview_batch_is_broad_and_blockers_are_explicit():
    data=measure(DB,level=20)
    assert data['classes']==9
    assert data['index_single_L1_casts']>=30
    assert data['index_single_L1_events']>=100
    assert data['by_class']['druid']['L1_index_simple_executed']>=8
    assert data['validated_checkpoints']==0
    assert data['blocker_reasons']['NO_SOURCE_INDEX_EFFECT_TOOLTIP']>300


def test_negative_composite_removed_l2_and_level():
    ir=build_game_ir_slice(class_key='druid',level=20)
    for sid,why in [(8924,'COMPOSITE_OR_UNRECOGNIZED_INDEX_TOOLTIP'),
                    (467,'COMPOSITE_OR_UNRECOGNIZED_INDEX_TOOLTIP'),
                    (6808,'NO_SOURCE_INDEX_EFFECT_TOOLTIP'),
                    (5179,'RANK_EXCEEDS_SOURCE_ACTOR_LEVEL')]:
        with pytest.raises(ValueError,match=why):
            source_index_single_l1_action(ir,class_key='druid',spell_id=sid)
    with pytest.raises(ValueError,match='INDEX_ONLY_ACTION_L2_L3_FORBIDDEN'):
        source_index_single_l1_action(ir,class_key='druid',spell_id=5178,execution_tier='L2')
    action,_=source_index_single_l1_action(ir,class_key='druid',spell_id=5178)
    actor=ActorState.from_ir(ir.actor,ir.resources,())
    with pytest.raises(ValueError,match='source-partial|partial|L1|NOT_LEGAL|not legal'):
        execute_action(action=action,actor=actor,target=TargetState.with_health('no_L2',1000))


def test_data_only_index_patch_changes_actual_runtime_and_stale_ledger_fails(tmp_path):
    stage=tmp_path/'stage.sqlite'
    shutil.copy2(DB,stage)
    ir=build_game_ir_slice(class_key='druid',level=20)
    before=probe_index_single_l1(ir,class_key='druid',spell_id=5178,db_path=stage)
    with sqlite3.connect(stage) as db:
        old=db.execute("SELECT raw_listview_json FROM spell_index WHERE class_key='druid' AND spell_id=5178").fetchone()[0]
        raw=json.loads(old)
        raw['envChange']['after']['text']='Causes 42 to 47 Nature damage to the target.'
        db.execute("UPDATE spell_index SET raw_listview_json=? WHERE class_key='druid' AND spell_id=5178",
                   (json.dumps(raw,sort_keys=True),))
    with pytest.raises(ValueError,match='STALE_ATOM_INDEX_REINGEST_REQUIRED'):
        source_index_single_l1_action(ir,class_key='druid',spell_id=5178,db_path=stage)
    ingest(stage)
    after=probe_index_single_l1(ir,class_key='druid',spell_id=5178,db_path=stage)
    assert before['damage']==34.5 and after['damage']==44.5
    with sqlite3.connect(stage) as db:
        raw=json.loads(db.execute("SELECT raw_listview_json FROM spell_index WHERE class_key='druid' AND spell_id=5178").fetchone()[0])
        raw['envChange']['after']['text']+=' Also stuns the target for 6 sec.'
        db.execute("UPDATE spell_index SET raw_listview_json=? WHERE class_key='druid' AND spell_id=5178",
                   (json.dumps(raw,sort_keys=True),))
    ingest(stage)
    with pytest.raises(ValueError,match='COMPOSITE_OR_UNRECOGNIZED_INDEX_TOOLTIP'):
        source_index_single_l1_action(ir,class_key='druid',spell_id=5178,db_path=stage)
