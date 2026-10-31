"""WF309: nine-class typed batch and generic sourced stat-aura conversions."""
from dataclasses import replace
from pathlib import Path
import json
import shutil
import sqlite3

import pytest

from src.game.data.forever.source_stat_aura_candidates import ingest,read_current_candidates
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.registry import build_game_ir_slice,registered_class_keys
from src.game.runtime import ActorState
from src.game.runtime.source_maintenance import _execute_source_maintenance_upkeep
from src.game.stat_math import converted_stat_amount
from src.game.model.ir import ActionDefinition,StatusAuraEffect
from src.game.runtime.simulator import execute_action
from src.game.runtime.state import TargetState


def _stage(tmp_path):
    p=tmp_path/'stage.sqlite'
    with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as src,sqlite3.connect(p) as dst:
        src.backup(dst)
    return p


def test_nine_class_batch_ingests_all_literal_buff_ranks_and_never_promotes(tmp_path):
    p=_stage(tmp_path)
    r=ingest(p)
    assert r['classes_scanned']==9 and r['indexed']==2255
    assert r['typed_candidates']==15 and r['executable_promotions']==0
    assert r['by_class']=={'mage':5,'priest':10}
    assert r['by_stat']=={'intellect':5,'stamina':6,'spirit':4}
    for cls in registered_class_keys():
        rows=read_current_candidates(p,class_key=cls)
        assert all(x['execution_status'].startswith('BLOCKED_') for x in rows)
    with sqlite3.connect(p) as db:
        assert db.execute('pragma integrity_check').fetchone()[0]=='ok'


def test_tamper_requires_reingest_not_a_free_buff(tmp_path):
    p=_stage(tmp_path)
    with sqlite3.connect(p) as db:
        raw=json.loads(db.execute('select raw_listview_json from spell_index where class_key=? and spell_id=?',('mage',1460)).fetchone()[0])
        raw['envChange']['after']['text']='Increases the target\'s Intellect by 999 for 1 hour.'
        db.execute('update spell_index set raw_listview_json=? where class_key=? and spell_id=?',(json.dumps(raw),'mage',1460))
    with pytest.raises(ValueError,match='STALE_SOURCE_STAT_AURA'):
        read_current_candidates(p,class_key='mage')
    assert ingest(p)['typed_candidates']==15
    assert any(x['stat_amount']==999 for x in read_current_candidates(p,class_key='mage'))


def test_generic_conversion_is_cast_time_geared_and_exactly_reversible():
    ir=build_game_ir_slice(class_key='druid',level=20)
    action=next(a for a in ir.actions if a.id=='source_spell:6756')
    assert action.effects[0].apply_primary_stat_conversions
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    before_stats=dict(actor.stats)
    before_caps=dict(actor.resource_capacity)
    # A legal gear/talent-derived primary stat crosses the conversion threshold.
    actor.stats['intellect']=19.
    actor.stats['stamina']=19.
    before_stats=dict(actor.stats)
    expected_mana=converted_stat_amount({'operation':'threshold_linear','coefficient':15.,
        'threshold':20.,'below_coefficient':1.},24)-converted_stat_amount({
        'operation':'threshold_linear','coefficient':15.,'threshold':20.,'below_coefficient':1.},19)
    expected_hp=1.+4.*10.
    cost,casts,events=_execute_source_maintenance_upkeep(ir,actor)
    assert casts==2 and events>0
    assert actor.resource_capacity['mana']==before_caps['mana']+expected_mana
    assert actor.resource_capacity['health']==before_caps['health']+expected_hp
    assert actor.stats['attack_power']==before_stats['attack_power']+10
    actor.current_time_s=4000
    assert actor.expire_elapsed_auras(actor.current_time_s)
    assert actor.stats==before_stats
    assert actor.resource_capacity==before_caps


def test_data_only_source_coefficient_changes_existing_runtime(tmp_path,monkeypatch):
    # Source fact coefficients are data, not class/spell dispatch in runtime.
    p=_stage(tmp_path)
    import src.game.data.forever.primary_stat_conversions as conv
    original=conv.DEFAULT_DB
    monkeypatch.setattr(conv,'DEFAULT_DB',p)
    ir1=build_game_ir_slice(class_key='druid',level=20)
    a1=ActorState.from_ir(ir1.actor,ir1.resources,ir1.modes)
    _execute_source_maintenance_upkeep(ir1,a1)
    with sqlite3.connect(p) as db:
        db.execute("update actor_stat_conversion_source_facts set coefficient=17 where class_key='*' and source_stat='intellect' and target_id='mana'")
    ir2=build_game_ir_slice(class_key='druid',level=20)
    a2=ActorState.from_ir(ir2.actor,ir2.resources,ir2.modes)
    _execute_source_maintenance_upkeep(ir2,a2)
    assert a2.resource_capacity['mana']-a1.resource_capacity['mana']==10


def test_nine_class_L20_canary_no_global_conversion_crash():
    for cls in registered_class_keys():
        ir=build_game_ir_slice(class_key=cls,level=20)
        assert ir is not None
        assert ir.provenance['indexed_ability_coverage']['source_stat_aura_candidates_not_executable']
    mage=build_game_ir_slice(class_key='mage',level=20)
    priest=build_game_ir_slice(class_key='priest',level=20)
    assert mage.provenance['indexed_ability_coverage']['source_stat_aura_typed_candidate_rank_count']==2
    assert priest.provenance['indexed_ability_coverage']['source_stat_aura_typed_candidate_rank_count']==2
    # No illegal auto-promotion of a buff on an unsourced baseline.
    assert not any(a.metadata.get('source_stat_aura_candidate') for a in mage.actions+priest.actions)
