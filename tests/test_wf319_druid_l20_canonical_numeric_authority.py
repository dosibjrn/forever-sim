"""WF319: Druid L20's actual L2 source provider must use indexed values.

Independently verified spell-detail/source-version coverage is a separate hard
blocker. These tests do not certify 1/148.
"""
from __future__ import annotations
import json,shutil,sqlite3
from pathlib import Path
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_index_rank_parity import (
    indexed_rank_fact,IndexedRankParityError)
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_effect_atoms import ingest as reingest_index_atoms
from src.game.runtime.state import ActorState,TargetState
from src.game.runtime.simulator import execute_action


def _action(ir, family):
    rows=[a for a in ir.actions if a.family_key==family and not a.id.startswith('source_spell:')]
    assert len(rows)==1,(family,[a.id for a in rows])
    return rows[0]


def _captured_build(monkeypatch):
    monkeypatch.setenv('WOW_FOREVER_BUILD_AS_OF','2026-10-08')
    monkeypatch.setenv('WOW_FOREVER_BUILD_SOURCE','wf319_test')


def test_real_l20_druid_core_spell_amounts_match_canonical_sqlite(monkeypatch):
    _captured_build(monkeypatch)
    ir=build_game_ir_slice(class_key='druid',level=20)
    wrath=_action(ir,'wrath')
    assert (wrath.effects[0].base_min,wrath.effects[0].base_max)==(32,37)
    assert ir.overlays==()  # Index after-tooltip already postdates beta tuning.
    assert wrath.costs[0].amount==40
    moon=_action(ir,'moonfire')
    assert (moon.effects[0].base_min,moon.effects[0].base_max,
        moon.effects[1].total_base_damage,moon.costs[0].amount)==(25,29,36,75)
    assert moon.effects[0].field_provenance['source'][0]['indexed_rank_fact']['spell_id']==8925
    rejuv=_action(ir,'rejuvenation')
    assert (rejuv.effects[0].total_base_heal,rejuv.costs[0].amount)==(92,75)
    ht=_action(ir,'healing_touch')
    assert (ht.effects[0].base_min,ht.effects[0].base_max,ht.costs[0].amount)==(339,412,190)
    star=[a for a in ir.actions if a.family_key=='starfire']
    assert len(star)==1 and star[0].effects[0].base_min==79
    assert all(a.family_key not in {'other_class'} for a in ir.actions)


def test_historical_build_never_reads_future_snapshot(monkeypatch):
    monkeypatch.setenv('WOW_FOREVER_BUILD_AS_OF','2026-10-02')
    ir=build_game_ir_slice(class_key='druid',level=20)
    assert ir.actions[0].effects[0].base_min==48  # Old 1.5x approximation
    assert _action(ir,'moonfire').effects[0].base_min==30
    assert _action(ir,'rejuvenation').effects[0].total_base_heal==116
    assert _action(ir,'healing_touch').costs[0].amount==185


def test_data_only_canonical_source_change_changes_real_l2_combat_runtime(tmp_path,monkeypatch):
    _captured_build(monkeypatch)
    stage=tmp_path/'source.sqlite';shutil.copy2(DEFAULT_DB,stage)
    before=build_game_ir_slice(class_key='druid',level=20,ability_db_path=stage)
    a0=_action(before,'moonfire')
    r0=execute_action(action=a0,actor=ActorState.from_ir(before.actor,before.resources,before.modes),
        target=TargetState.with_health('monster',100000))
    with sqlite3.connect(stage) as con:
        raw=json.loads(con.execute('SELECT raw_listview_json FROM spell_index WHERE class_key=? AND spell_id=?',
            ('druid',8925)).fetchone()[0])
        text=raw['envChange']['after']['text']
        assert '25 to 29 Arcane damage' in text
        raw['envChange']['after']['text']=text.replace('25 to 29 Arcane damage','45 to 49 Arcane damage')
        con.execute('UPDATE spell_index SET raw_listview_json=? WHERE class_key=? AND spell_id=?',
            (json.dumps(raw,sort_keys=True),'druid',8925))
    with pytest.raises(ValueError,match='STALE_ATOM_INDEX_REINGEST_REQUIRED'):
        build_game_ir_slice(class_key='druid',level=20,ability_db_path=stage)
    reingest_index_atoms(stage)
    after=build_game_ir_slice(class_key='druid',level=20,ability_db_path=stage)
    a1=_action(after,'moonfire')
    r1=execute_action(action=a1,actor=ActorState.from_ir(after.actor,after.resources,after.modes),
        target=TargetState.with_health('monster',100000))
    assert a1.effects[0].base_min-a0.effects[0].base_min==20
    assert r1.total_damage-r0.total_damage==pytest.approx(20)
    assert (a1.effects[0].field_provenance['source'][0]['indexed_rank_fact']['raw_index_sha256']
         !=a0.effects[0].field_provenance['source'][0]['indexed_rank_fact']['raw_index_sha256'])


def test_malformed_and_missing_index_evidence_fail_closed(tmp_path,monkeypatch):
    _captured_build(monkeypatch)
    stage=tmp_path/'source.sqlite';shutil.copy2(DEFAULT_DB,stage)
    with sqlite3.connect(stage) as con:
        raw=json.loads(con.execute('SELECT raw_listview_json FROM spell_index WHERE class_key=? AND spell_id=?',
            ('druid',8925)).fetchone()[0])
        raw['envChange']['after']['text']+=' and also silently casts a bear form'
        con.execute('UPDATE spell_index SET raw_listview_json=? WHERE class_key=? AND spell_id=?',
            (json.dumps(raw,sort_keys=True),'druid',8925))
    with pytest.raises(IndexedRankParityError,match='INDEX_EFFECT_DESCRIPTION_UNSUPPORTED'):
        build_game_ir_slice(class_key='druid',level=20,ability_db_path=stage)
    with sqlite3.connect(stage) as con:
        raw=json.loads(con.execute('SELECT raw_listview_json FROM spell_index WHERE class_key=? AND spell_id=?',
            ('druid',8925)).fetchone()[0]);raw['envChange']['status']='removed'
        con.execute('UPDATE spell_index SET raw_listview_json=? WHERE class_key=? AND spell_id=?',
            (json.dumps(raw,sort_keys=True),'druid',8925))
    with pytest.raises(IndexedRankParityError,match='SOURCE_RANK_REMOVED'):
        build_game_ir_slice(class_key='druid',level=20,ability_db_path=stage)
