"""WF271: two former class-handwired actions compile from typed canonical SQL."""
from __future__ import annotations
from dataclasses import replace
import json
import sqlite3

import pytest

from src.game.data.forever.registry import build_game_ir_slice, registered_class_keys
from src.game.data.forever.source_ability_semantics import (
    latest_source_action_ref, source_ability_actions,
)
from src.game.data.forever.sqlite_talents import DEFAULT_DB


def _copy_db(tmp_path):
    dst=tmp_path/'source.sqlite'
    with sqlite3.connect(DEFAULT_DB) as src,sqlite3.connect(dst) as out:
        src.backup(out)
    return dst


def _recompile(base,db):
    # Remove the two typed actions to force the SAME generic compiler to
    # ingest from a modified canonical database without a Druid code change.
    excluded={a.id for a in base.actions if a.family_key in ('claw','rake')}
    stripped=replace(base,actions=tuple(a for a in base.actions if a.id not in excluded),
        modes=tuple(replace(m,enabled_action_ids=(None if m.enabled_action_ids is None else
            tuple(a for a in m.enabled_action_ids if a not in excluded))) for m in base.modes))
    return source_ability_actions(stripped,class_key='druid',level=27,db_path=db)


def test_all_melee_builder_ranks_from_sqlite_and_no_class_handwired_effects():
    for level,claw_id,rake_id in (
        (20,'claw:20',None),(24,'claw:20','rake:1822'),
        (28,'claw:28','rake:1822'),(34,'claw:28','rake:1823'),
        (38,'claw:38','rake:1823'),(44,'claw:38','rake:1824'),
        (54,'claw:48','rake:9904'),(58,'claw:58','rake:9904')):
        ir=build_game_ir_slice(class_key='druid',level=level)
        claw=next(a for a in ir.actions if a.family_key=='claw')
        assert claw.id==claw_id
        assert claw.metadata['source_semantic_type']=='weapon_combo'
        assert len(claw.effects)==2
        assert claw.effects[0].effect_type=='weapon_damage'
        assert claw.effects[1].resource_id=='combo_points'
        assert claw.id in next(m for m in ir.modes if m.id=='cat').enabled_action_ids
        rake=[a for a in ir.actions if a.family_key=='rake']
        assert (rake[0].id if rake else None) == rake_id
        assert all(a.id in next(m for m in ir.modes if m.id=='cat').enabled_action_ids for a in rake)
        if rake:
            assert rake[0].metadata['source_semantic_type']=='melee_direct_periodic_combo'
            assert [e.effect_type for e in rake[0].effects]==[
                'damage','periodic_damage','resource_change']
            assert rake[0].effects[1].crit_chance_stat_id=='melee_crit_chance'
    assert latest_source_action_ref('druid','claw',19) is None
    assert latest_source_action_ref('druid','rake',23) is None


def test_data_only_changes_claw_flat_rake_direct_and_crit_multiplier(tmp_path):
    db=_copy_db(tmp_path)
    ir=build_game_ir_slice(class_key='druid',level=27)
    before={a.family_key:a for a in ir.actions if a.family_key in ('claw','rake')}
    with sqlite3.connect(db) as con:
        for sid,old,new in ((1082,'plus 27.','plus 227.'),
                            (1822,'for 23 damage','for 123 damage')):
            raw=json.loads(con.execute('SELECT raw_listview_json FROM spell_index WHERE spell_id=?',(sid,)).fetchone()[0])
            txt=raw['envChange']['after']['text']
            assert old in txt
            raw['envChange']['after']['text']=txt.replace(old,new)
            con.execute('UPDATE spell_index SET raw_listview_json=? WHERE spell_id=?',(json.dumps(raw),sid))
        con.execute('UPDATE sourced_direct_periodic_melee_semantics SET crit_multiplier=2.5 WHERE spell_id=1822')
    after=_recompile(ir,db)
    actions={a.family_key:a for a in after.actions if a.family_key in ('claw','rake')}
    assert actions['claw'].effects[0].flat_damage==before['claw'].effects[0].flat_damage+200
    assert actions['rake'].effects[0].base_min==before['rake'].effects[0].base_min+100
    assert actions['rake'].effects[0].crit_multiplier==2.5
    assert actions['rake'].effects[1].crit_multiplier==2.5
    assert actions['claw'].id==before['claw'].id
    assert actions['rake'].id==before['rake'].id


@pytest.mark.parametrize('mutation',('delete_claw','delete_rake','rake_bad_source','rake_bad_crit'))
def test_missing_or_invalid_melee_semantics_fail_closed(tmp_path,mutation):
    db=_copy_db(tmp_path)
    with sqlite3.connect(db) as con:
        if mutation=='delete_claw':
            con.execute('DELETE FROM ability_semantic_source_facts WHERE spell_id=1082')
        elif mutation=='delete_rake':
            con.execute('DELETE FROM ability_semantic_source_facts WHERE spell_id=1822')
        elif mutation=='rake_bad_source':
            con.execute("UPDATE sourced_direct_periodic_melee_semantics SET source_url='https://invalid.example/spell=1822' WHERE spell_id=1822")
        else:
            con.execute('UPDATE sourced_direct_periodic_melee_semantics SET crit_multiplier=-1 WHERE spell_id=1822')
    base=build_game_ir_slice(class_key='druid',level=27)
    with pytest.raises(ValueError,match='required source action not executable|invalid sourced melee'):
        _recompile(base,db)


def test_non_druid_registry_uses_same_compiler_no_source_action_regression():
    assert len(registered_class_keys())==9
    for key in registered_class_keys():
        ir=build_game_ir_slice(class_key=key,level=20)
        assert ir is not None
        assert ir.provenance.get('source_ability_ingest') is not None
