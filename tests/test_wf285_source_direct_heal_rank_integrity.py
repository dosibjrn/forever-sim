"""WF285: Forever public-page crosschecked direct heals and exact-rank integrity."""
from pathlib import Path
import json
import sqlite3

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.model.ir import HealEffect
from src.game.runtime import ActorState, TargetState, execute_action
from src.game.recovery import recover_actor_to_full
from tools.ingest_source_ability_semantics_sqlite import ingest

CAPTURE = Path(__file__).resolve().parents[1] / 'data/forever/source_captures/WF285_FOREVER_HEALING_TOUCH_20261012.json'


def _source_ranks(ir):
    return {a.provenance[0]['source_spell_id']: a for a in ir.actions
            if a.family_key == 'healing_touch' and a.metadata.get('source_semantic_type') == 'direct_heal'}


def test_rank2_and_rank3_are_distinct_exact_source_executable_actions():
    ir=build_game_ir_slice(class_key='druid',level=20)
    ranks=_source_ranks(ir)
    assert set(ranks)=={5186,5187}
    assert len({a.id for a in ir.actions})==len(ir.actions)
    assert ranks[5186].id=='source_spell:5186'
    assert ranks[5187].id=='source_spell:5187'
    assert (ranks[5186].cast_time_s,ranks[5186].costs[0].amount)==(2.0,55.0)
    assert (ranks[5187].cast_time_s,ranks[5187].costs[0].amount)==(2.5,110.0)
    assert (ranks[5186].effects[0].base_min,ranks[5186].effects[0].base_max,
            ranks[5186].effects[0].spell_power_coefficient)==(95,119,0.571)
    assert (ranks[5187].effects[0].base_min,ranks[5187].effects[0].base_max,
            ranks[5187].effects[0].spell_power_coefficient)==(188,233,0.714)
    assert ir.provenance['indexed_ability_coverage']['exact_source_rank_in_ir_count']==15
    assert ir.provenance['indexed_ability_coverage']['unrepresented_rank_count']==109
    assert ir.provenance['indexed_ability_coverage']['not_proof_of_legal_action_coverage']
    assert all(a.id in next(m for m in ir.modes if m.id=='caster').enabled_action_ids for a in ranks.values())


def test_real_executor_direct_heal_and_recovery_candidates():
    ir=build_game_ir_slice(class_key='druid',level=20)
    ranks=_source_ranks(ir)
    for sid,expected in ((5186,107.0),(5187,210.5)):
        actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
        actor.resources['health']=100
        result=execute_action(action=ranks[sid],actor=actor,target=TargetState.with_health('recovery',1))
        heals=[e for e in result.events if e.kind=='Heal']
        assert len(heals)==1
        assert heals[0].payload['amount']==pytest.approx(expected)
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    actor.resources.update(health=200.0,mana=550.0)
    recovered=recover_actor_to_full(actor=actor,level=20,actions=ir.actions,
        start_time_s=actor.current_time_s)
    assert recovered.total_s>=0
    assert actor.resources['health']==actor.resource_capacity['health']
    assert recovered.provenance['healing_execution']=='src.game.runtime.CombatRuntime'


def test_exact_rank_not_rewritten_by_legacy_promotion_even_with_higher_index_rank():
    ir=build_game_ir_slice(class_key='druid',level=60)
    ranks=_source_ranks(ir)
    assert set(ranks)=={5186,5187}
    assert all(a.id==f'source_spell:{sid}' for sid,a in ranks.items())
    assert len({a.id for a in ir.actions})==len(ir.actions)


def test_data_only_heal_change_and_missing_source_row_fail_closed(tmp_path):
    db=tmp_path/'stage.sqlite'
    with sqlite3.connect(DEFAULT_DB) as src,sqlite3.connect(db) as dest:src.backup(dest)
    with sqlite3.connect(db) as conn:
        raw=conn.execute('SELECT raw_listview_json FROM spell_index WHERE class_key="druid" AND spell_id=5186').fetchone()[0]
        obj=json.loads(raw)
        obj['envChange']['after']['text']='Heals a friendly target for 105 to 129.'
        conn.execute('UPDATE spell_index SET raw_listview_json=? WHERE class_key="druid" AND spell_id=5186',(json.dumps(obj),))
    ir=build_game_ir_slice(class_key='druid',level=20,ability_db_path=db)
    assert _source_ranks(ir)[5186].effects[0].base_min==105
    with sqlite3.connect(db) as conn:
        conn.execute('DELETE FROM ability_semantic_source_facts WHERE class_key="druid" AND spell_id=5186')
    blocked=build_game_ir_slice(class_key='druid',level=20,ability_db_path=db)
    assert 5186 not in _source_ranks(blocked)
    assert blocked.provenance['indexed_ability_coverage']['unrepresented_rank_count']==110


def test_ingest_rejects_current_public_page_index_drift_and_rolls_back(tmp_path):
    db=tmp_path/'stage.sqlite'
    with sqlite3.connect(DEFAULT_DB) as src,sqlite3.connect(db) as dest:src.backup(dest)
    with sqlite3.connect(db) as conn:
        conn.execute('DELETE FROM ability_semantic_source_facts WHERE class_key="druid" AND spell_id IN (5186,5187)')
    data=json.loads(CAPTURE.read_text())
    data['entries'][1]['public_page_observation']['cost']='185 Mana'  # stale vs current mismatch
    capture=tmp_path/'bad.json';capture.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='public page/index drift'):
        ingest(db,capture)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT count(*) FROM ability_semantic_source_facts WHERE spell_id IN (5186,5187)').fetchone()[0]==0
    data['entries']=data['entries'][:1]
    data['entries'][0]['public_page_observation']['spell_power_coefficient']=0.999
    capture.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='coefficient mismatch'):
        ingest(db,capture)
