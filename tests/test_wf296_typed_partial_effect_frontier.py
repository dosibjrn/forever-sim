"""WF296: batch source-derived L1 typed effects, never L2 promotion."""
import json
import shutil
import sqlite3

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_effect_atoms import ingest
from src.game.data.forever.source_partial_l1 import (
    PartialSourceEvidenceError,partial_source_action,probe_l1_source_fragment,
    bounded_actor_l1_probe_ir,probe_l1_indexed_rank_with_bounded_actor)
from src.game.runtime.state import ActorState,TargetState
from src.game.runtime.simulator import execute_action
from tools.wf296_l1_typed_fragments_nine_class import measure


def test_generic_healing_fragment_executes_in_existing_runtime_and_never_l2():
    ir=build_game_ir_slice(class_key='druid',level=20)
    a,e=partial_source_action(ir,class_key='druid',spell_id=5185,fragment_kind='direct_heal')
    assert a.metadata['never_l2_legal'] and e['partial_not_l2']
    assert a.effects[0].base_min==40 and a.effects[0].base_max==54
    assert a.effects[0].unsupported_semantics
    actor=ActorState.from_ir(ir.actor,ir.resources,())
    with pytest.raises(ValueError,match='SOURCE_PARTIAL_L1_ACTION_FORBIDDEN'):
        execute_action(action=a,actor=actor,target=TargetState.with_health('target',10000))
    r=probe_l1_source_fragment(ir,class_key='druid',spell_id=5185,fragment_kind='direct_heal')
    assert r['base_healing_requested']==47
    assert r['base_healing_restored']==0  # actor starts at full health
    assert r['base_damage_observed']==0
    assert r['valid_for_l2_score'] is False
    with pytest.raises(PartialSourceEvidenceError,match='FORBIDDEN_AT_L2'):
        partial_source_action(ir,class_key='druid',spell_id=5185,
                              fragment_kind='direct_heal',execution_tier='L2')


def test_zero_cost_is_only_allowed_with_verified_detail_not_empty_index():
    ir=build_game_ir_slice(class_key='warrior',level=20)
    a,_=partial_source_action(ir,class_key='warrior',spell_id=100,
                              fragment_kind='resource_gain')
    assert not a.costs
    assert a.metadata['never_l2_legal']
    r=probe_l1_source_fragment(ir,class_key='warrior',spell_id=100,
                               fragment_kind='resource_gain')
    assert r['base_resource_gain_requested']==9
    assert r['base_resource_gain_actual']==9
    with pytest.raises(PartialSourceEvidenceError,match='UNSUPPORTED_OR_MISSING_SOURCE_COST_CAST'):
        partial_source_action(ir,class_key='warrior',spell_id=6178,
                              fragment_kind='resource_gain')
    with pytest.raises(PartialSourceEvidenceError,match='UNSUPPORTED_OR_MISSING_SOURCE_COST_CAST'):
        partial_source_action(build_game_ir_slice(class_key='rogue',level=20),
                              class_key='rogue',spell_id=432293,fragment_kind='resource_gain')


def test_healing_value_changes_from_data_only_and_stale_proof_fails(tmp_path):
    db=tmp_path/'stage.sqlite';shutil.copy2(DEFAULT_DB,db)
    ir=build_game_ir_slice(class_key='druid',level=20)
    before=probe_l1_source_fragment(ir,class_key='druid',spell_id=5185,
                                    fragment_kind='direct_heal',db_path=db)
    assert before['base_healing_requested']==47
    with sqlite3.connect(db) as conn:
        raw=conn.execute('''SELECT raw_listview_json FROM spell_index
            WHERE class_key='druid' AND spell_id=5185''').fetchone()[0]
        data=json.loads(raw)
        data['envChange']['after']['text']=data['envChange']['after']['text'].replace(
            '40 to 54','80 to 108')
        conn.execute('''UPDATE spell_index SET raw_listview_json=?
            WHERE class_key='druid' AND spell_id=5185''',(json.dumps(data),))
    with pytest.raises(ValueError,match='STALE_ATOM_INDEX'):
        probe_l1_source_fragment(ir,class_key='druid',spell_id=5185,
                                 fragment_kind='direct_heal',db_path=db)
    summary=ingest(db)
    assert summary['ranks_with_atoms']>500
    after=probe_l1_source_fragment(ir,class_key='druid',spell_id=5185,
                                   fragment_kind='direct_heal',db_path=db)
    assert after['base_healing_requested']==94
    assert after['valid_for_l2_score'] is False


def test_cross_class_typed_batch_breadth_and_zero_promotions():
    out=measure(20)
    assert len(out['classes'])==9
    assert out['partial_l1_executed']>=80
    assert out['partial_l1_by_kind']['direct_heal']>=19
    assert out['partial_l1_by_kind']['resource_gain']>=1
    assert out['classes']['warrior']['partial_l1_executed']>=1
    assert out['partial_l1_executor_events']>=275
    assert out['accepted_class_level_checkpoints']==0
    assert out['world_continuous_routes']==0
    assert out['l2_source_complete_promotions']==0


def test_l60_cross_class_source_rank_probe_never_promotes_proxy_actor():
    ir,template,proxy=bounded_actor_l1_probe_ir(class_key='mage',level=60)
    assert proxy is True and template==20
    assert ir.actor.metadata['level']==60
    assert ir.actor.metadata['L1_NOT_SOURCE_VALIDATED_ACTOR_AT_LEVEL'] is True
    actor=ActorState.from_ir(ir.actor,ir.resources,())
    action=ir.actions[0]
    with pytest.raises(ValueError,match='SOURCE_L1_BOUNDED_ACTOR_FORBIDDEN'):
        execute_action(action=action,actor=actor,
                       target=TargetState.with_health('enemy',10000))
    r=probe_l1_indexed_rank_with_bounded_actor(
        class_key='mage',level=60,spell_id=133,fragment_kind='direct_damage')
    assert r['bounded_actor_level_proxy'] is True
    assert r['bounded_actor_template_level']==20
    assert r['valid_for_l2_score'] is False
    assert r['accepted_checkpoints']==0
    report=measure(60,bounded_actor_l1=True)
    assert report['partial_l1_executed']>=350
    assert report['proxy_actor_rank_probes']>=300
    assert report['partial_l1_by_kind']['direct_heal']>=65
    assert report['accepted_class_level_checkpoints']==0


def test_rogue_source_weapon_multiplier_uses_existing_runtime_and_source_data(tmp_path):
    ir=build_game_ir_slice(class_key='rogue',level=20)
    a,e=partial_source_action(ir,class_key='rogue',spell_id=53,
                              fragment_kind='weapon_multiplier')
    assert a.effects[0].weapon_damage_multiplier==1.5
    assert a.metadata['weapon_base_is_proxy'] is True
    assert e['partial_not_l2']
    with pytest.raises(ValueError,match='SOURCE_PARTIAL_L1_ACTION_FORBIDDEN'):
        execute_action(action=a,actor=ActorState.from_ir(ir.actor,ir.resources,()),
                       target=TargetState.with_health('enemy',10000))
    base=probe_l1_source_fragment(ir,class_key='rogue',spell_id=2589,
                                  fragment_kind='weapon_multiplier')
    db=tmp_path/'stage.sqlite';shutil.copy2(DEFAULT_DB,db)
    with sqlite3.connect(db) as conn:
        raw=conn.execute('''SELECT raw_listview_json FROM spell_index
            WHERE class_key='rogue' AND spell_id=2589''').fetchone()[0]
        data=json.loads(raw)
        assert '150% weapon damage' in data['envChange']['after']['text']
        data['envChange']['after']['text']=data['envChange']['after']['text'].replace(
            '150% weapon damage','200% weapon damage')
        conn.execute('''UPDATE spell_index SET raw_listview_json=?
            WHERE class_key='rogue' AND spell_id=2589''',(json.dumps(data),))
    with pytest.raises(ValueError,match='STALE_ATOM_INDEX'):
        probe_l1_source_fragment(ir,class_key='rogue',spell_id=2589,
                                 fragment_kind='weapon_multiplier',db_path=db)
    ingest(db)
    changed=probe_l1_source_fragment(ir,class_key='rogue',spell_id=2589,
                                     fragment_kind='weapon_multiplier',db_path=db)
    assert changed['base_damage_observed']==pytest.approx(base['base_damage_observed']*4/3)
    assert changed['valid_for_l2_score'] is False


def test_nine_class_level60_fragment_canary_remains_ineligible():
    out=measure(60,bounded_actor_l1=True)
    assert all(v['partial_l1_executed']>0 for v in out['classes'].values())
    assert out['partial_l1_executed']>=370
    assert out['partial_l1_by_kind']['weapon_multiplier']>=10
    assert out['proxy_actor_rank_probes']>=310
    assert out['accepted_class_level_checkpoints']==0
    assert out['world_continuous_routes']==0
