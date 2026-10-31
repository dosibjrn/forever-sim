"""Source-observed periodic totals through existing executor, NEVER full DoT mechanics."""
import json
import sqlite3
from pathlib import Path
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_partial_l1 import (
    partial_source_action, probe_l1_source_fragment, PartialSourceEvidenceError)
from src.game.data.forever.source_effect_atoms import ingest
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from tools.wf296_l1_typed_fragments_nine_class import measure


def test_source_observed_integral_through_generic_periodic_executor():
    ir=build_game_ir_slice(class_key='druid',level=20)
    a,e=partial_source_action(ir,class_key='druid',spell_id=8921,fragment_kind='periodic_total')
    assert a.metadata['never_l2_legal'] is True
    assert a.metadata['periodic_timing_is_proxy'] is True
    assert a.effects[0].duration_s == 9
    assert a.effects[0].tick_interval_s == 9  # explicitly NOT game tick timing
    assert a.effects[0].total_base_damage == 12
    assert any('UNKNOWN_ONE_TERMINAL_TICK' in str(x) for x in a.effects[0].unsupported_semantics)
    r=probe_l1_source_fragment(ir,class_key='druid',spell_id=8921,fragment_kind='periodic_total')
    assert r['base_damage_observed'] == 12
    assert r['periodic_tick_count_not_source_verified'] is True
    assert r['valid_for_l2_score'] is False
    with pytest.raises(PartialSourceEvidenceError,match='FORBIDDEN_AT_L2'):
        partial_source_action(ir,class_key='druid',spell_id=8921,
                              fragment_kind='periodic_total',execution_tier='L2')


def test_source_integral_changes_only_when_verified_ledger_reingested(tmp_path):
    stage=tmp_path/'source.sqlite'
    with sqlite3.connect(f'file:{Path(DEFAULT_DB).resolve()}?mode=ro',uri=True) as source,sqlite3.connect(stage) as dest:
        source.backup(dest)
    ir=build_game_ir_slice(class_key='druid',level=20)
    old=probe_l1_source_fragment(ir,class_key='druid',spell_id=8921,
                                 fragment_kind='periodic_total',db_path=stage)
    with sqlite3.connect(stage) as db:
        row=db.execute("SELECT raw_listview_json FROM spell_index WHERE class_key='druid' AND spell_id=8921").fetchone()
        data=json.loads(row[0]);txt=data['envChange']['after']['text']
        assert '12 Arcane damage over 9 sec' in txt
        data['envChange']['after']['text']=txt.replace('12 Arcane damage over 9 sec','17 Arcane damage over 9 sec')
        db.execute("UPDATE spell_index SET raw_listview_json=? WHERE class_key='druid' AND spell_id=8921",(json.dumps(data),))
    with pytest.raises(ValueError,match='STALE_ATOM_INDEX_REINGEST_REQUIRED'):
        probe_l1_source_fragment(ir,class_key='druid',spell_id=8921,
                                 fragment_kind='periodic_total',db_path=stage)
    assert ingest(stage)['indexed_ranks']==2255
    new=probe_l1_source_fragment(ir,class_key='druid',spell_id=8921,
                                 fragment_kind='periodic_total',db_path=stage)
    assert old['base_damage_observed']==12 and new['base_damage_observed']==17


def test_periodic_integral_batch_broad_but_never_checkpoint():
    r=measure(20)
    assert len(r['classes'])==9
    assert r['partial_l1_by_kind']['periodic_total']>=30
    assert r['accepted_class_level_checkpoints']==0
    assert r['l2_source_complete_promotions']==0
    assert r['world_continuous_routes']==0


def test_unverified_school_and_multi_combo_point_scaling_fail_closed():
    ir=build_game_ir_slice(class_key='druid',level=30)
    a,_=partial_source_action(ir,class_key='druid',spell_id=1822,fragment_kind='periodic_total')
    assert a.effects[0].school == 'unverified'
    assert any('UNKNOWN_PHYSICAL_L1_PROXY' in str(x) for x in a.effects[0].unsupported_semantics)
    with pytest.raises(PartialSourceEvidenceError,match='REQUIRES_EXACTLY_ONE_SELECTED_SOURCE_FRAGMENT'):
        partial_source_action(ir,class_key='druid',spell_id=1079,fragment_kind='periodic_total')
