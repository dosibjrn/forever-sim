"""WF305: level-20 source-ranked upkeep is paid and must expire/refresh."""
import json,sqlite3
from pathlib import Path
from dataclasses import replace
import pytest
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_maintenance_ranks import latest_reactive_maintenance_rank
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate

ROOT=Path(__file__).resolve().parents[1]
STAGE=json.loads((ROOT/'WF303_COLD_TWO_PROFILE.json').read_text())['persistent_winner']['stage']


def test_thorns_is_available_and_costs_mana_from_canonical_source_rank():
    a=latest_reactive_maintenance_rank('druid','Thorns',20)
    assert (a['spell_id'],a['level'],a['mana_cost'],a['reactive_damage'],a['duration_s'])==(782,14,60,9,600)
    newer=latest_reactive_maintenance_rank('druid','Thorns',24)
    assert (newer['spell_id'],newer['reactive_damage'])==(1075,11)
    assert latest_reactive_maintenance_rank('druid','Thorns',4) is None
    assert a['acquisition_status']=='INDEX_TRAINING_HINT_NOT_INDEPENDENTLY_VERIFIED'


def test_rank_compiles_exact_ir_cast_and_aura_gated_reactive_trigger():
    ir=build_game_ir_slice(class_key='druid',level=20)
    action=next(a for a in ir.actions if a.id=='source_spell:782')
    assert action.costs[0].amount==60
    assert action.effects[0].duration_s==600
    trigger=next(t for t in ir.triggers if t.id=='thorns:782:reactive')
    assert trigger.required_aura_id==action.effects[0].aura_id
    assert trigger.effects[0].base_min==9


def test_100_mob_recasts_timed_aura_and_charges_cost_and_mode_transitions():
    c=prepare_candidate(class_key='druid',level=20,stage=STAGE)
    r=evaluate_persistent_candidate(c,level=20,mobs=100)
    assert r['status']=='COMPLETE' and r['count']==100
    assert r['maintenance_casts']==4  # 3 paid Thorns + 1 paid Mark of the Wild
    assert r['maintenance_runtime_events']>0
    assert r['events']>=r['maintenance_runtime_events']
    assert r['maintenance_s']>=4.5
    assert r['skipped_satisfied_mode_prefixes']==97 # Cat was intentionally exited and reentered for upkeep
    # WF309 source-derived +Intellect mana capacity changes the long-horizon
    # recovery denominator; this is NOT comparable to pre-WF309 score.
    assert abs(r['mean_s_per_mob']-13.451479983031081)<1e-8
    assert abs(r['total_s']-(r['combat_s']+r['recovery_s']+r['maintenance_s']))<1e-7


def test_no_free_trigger_if_source_maintenance_spell_missing():
    c=prepare_candidate(class_key='druid',level=20,stage=STAGE)
    modified=replace(c,ir=replace(c.ir,actions=tuple(a for a in c.ir.actions if a.id!='source_spell:782')))
    r=evaluate_persistent_candidate(modified,level=20,mobs=2)
    assert r['status']=='BLOCKED_SOURCE_MAINTENANCE_UPKEEP'
    assert r['mob']==1


def test_malformed_source_rank_does_not_fallback_to_old_hardcoded_level24(tmp_path):
    stage=tmp_path/'source.sqlite'
    with sqlite3.connect(f'file:{DEFAULT_DB}?mode=ro',uri=True) as src,sqlite3.connect(stage) as dest:src.backup(dest)
    with sqlite3.connect(stage) as conn:
        raw=json.loads(conn.execute("SELECT raw_listview_json FROM spell_index WHERE class_key='druid' AND spell_id=782").fetchone()[0])
        raw['envChange']['after']['text']='Something unsupported'
        conn.execute("UPDATE spell_index SET raw_listview_json=? WHERE class_key='druid' AND spell_id=782",(json.dumps(raw),))
    with pytest.raises(ValueError,match='UNPARSED_REACTIVE_AURA_SEMANTICS'):
        latest_reactive_maintenance_rank('druid','Thorns',20,db_path=stage)
