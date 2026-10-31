"""WF284: independently sourced healing downranks use real executor and recovery."""
from dataclasses import replace
from itertools import chain
import json
import sqlite3

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.model.ir import HealEffect, PeriodicHealEffect
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.game.recovery import recover_actor_to_full
from src.game.recovery_hot import _plans
from src.v2.generic_backend import _policy_combat_evaluation


def _ranks(ir):
    return {a.id:a for a in ir.actions if a.family_key == 'regrowth'}


def test_l20_verified_downrank_is_executable_and_exact_source_id_covered():
    ir=build_game_ir_slice(class_key='druid',level=20)
    actions=_ranks(ir)
    assert set(actions)=={'source_spell:8938','source_spell:8936'}
    assert actions['source_spell:8938'].costs[0].amount == 125
    assert actions['source_spell:8936'].costs[0].amount == 70
    for sid,a in ((8938,actions['source_spell:8938']),(8936,actions['source_spell:8936'])):
        assert a.provenance[0]['source_spell_id']==sid
        assert a.provenance[0]['url'].endswith(f'spell={sid}')
        assert isinstance(a.effects[0],HealEffect)
        assert isinstance(a.effects[1],PeriodicHealEffect)
        assert a.effects[1].aura_id=='source_periodic_heal:regrowth'
    coverage=ir.provenance['indexed_ability_coverage']
    assert coverage['exact_source_rank_in_ir_count']==15
    assert coverage['unrepresented_rank_count']==109
    assert coverage['not_proof_of_legal_action_coverage']


def test_lower_rank_real_executor_heals_and_same_family_replaces():
    ir=build_game_ir_slice(class_key='druid',level=20)
    low=_ranks(ir)['source_spell:8936'];high=_ranks(ir)['source_spell:8938']
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    actor.resources['health']=0
    target=TargetState.with_health('mob',1000)
    runtime=CombatRuntime(actor=actor,target=target,spell_power=0)
    runtime.schedule_action(high)
    runtime.advance_to(2.1)
    assert actor.resources['health']>0
    runtime.schedule_action(low)
    runtime.advance_to(5)
    assert any(e.kind=='AuraReplaced' and e.payload.get('aura_id')=='source_periodic_heal:regrowth'
               for e in runtime.trace)
    assert len([a for a in actor.active_auras if a=='source_periodic_heal:regrowth'])<=1
    assert not any(e.kind=='Heal' and e.payload.get('periodic') and e.action_id==high.id
                   for e in runtime.trace)


def test_recovery_frontier_does_not_stack_two_ranks_of_one_hot():
    ir=build_game_ir_slice(class_key='druid',level=20)
    regrowth=_ranks(ir)
    plans=list(_plans(tuple(regrowth.values()),hp_missing=300,healing_power=0))
    assert any(p and p[0].id=='source_spell:8936' for p in plans)
    assert any(p and p[0].id=='source_spell:8938' for p in plans)
    assert all(len({e.aura_id for a in p for e in a.effects if isinstance(e,PeriodicHealEffect)})
               ==sum(isinstance(e,PeriodicHealEffect) for a in p for e in a.effects)
               for p in plans)


def test_real_recovery_evaluates_lower_rank_with_same_runtime():
    ir=build_game_ir_slice(class_key='druid',level=20)
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    actor.resources['health']=200
    actor.resources['mana']=550
    result=recover_actor_to_full(actor=actor,level=20,actions=ir.actions,
        start_time_s=actor.current_time_s,healing_power=0)
    assert result.total_s>=0
    assert actor.resources['health']==actor.resource_capacity['health']
    assert actor.resources['mana']==actor.resource_capacity['mana']
    assert result.provenance['healing_execution']=='src.game.runtime.CombatRuntime'


def test_canonical_l20_full_cycle_real_scorer_remains_reproducible():
    ir=build_game_ir_slice(class_key='druid',level=20)
    policy=ir.policies[0]
    a,_,da=_policy_combat_evaluation(ir,level=20,policy_override=policy,schedule_incoming_attacks=True)
    b,_,db=_policy_combat_evaluation(ir,level=20,policy_override=policy,schedule_incoming_attacks=True)
    assert a is not None and b is not None
    assert a.seconds_per_mob==pytest.approx(b.seconds_per_mob,abs=1e-10)
    assert da['recovery']['total_s']==pytest.approx(db['recovery']['total_s'],abs=1e-10)
    assert da['event_transitions_new']==db['event_transitions_new']


def test_data_only_lower_rank_change_and_semantic_removal_fail_closed(tmp_path):
    db=tmp_path/'staged.sqlite'
    with sqlite3.connect(DEFAULT_DB) as source,sqlite3.connect(db) as dest:source.backup(dest)
    original=build_game_ir_slice(class_key='druid',level=20)
    base=_ranks(original)['source_spell:8936']
    with sqlite3.connect(db) as conn:
        raw=conn.execute('SELECT raw_listview_json FROM spell_index WHERE class_key="druid" AND spell_id=8936').fetchone()[0]
        obj=json.loads(raw)
        obj['envChange']['after']['text']='Heals a friendly target for 120 to 130 and another 91 over 21 sec.'
        conn.execute('UPDATE spell_index SET raw_listview_json=? WHERE class_key="druid" AND spell_id=8936',(json.dumps(obj),))
    updated=build_game_ir_slice(class_key='druid',level=20,ability_db_path=db)
    assert _ranks(updated)['source_spell:8936'].effects[0].base_min==120
    assert _ranks(updated)['source_spell:8936'].effects[0].base_min!=base.effects[0].base_min
    with sqlite3.connect(db) as conn:
        conn.execute('DELETE FROM ability_semantic_source_facts WHERE class_key="druid" AND spell_id=8936')
    blocked=build_game_ir_slice(class_key='druid',level=20,ability_db_path=db)
    assert 'source_spell:8936' not in _ranks(blocked)
    assert blocked.provenance['indexed_ability_coverage']['unrepresented_rank_count']==110


def test_l60_source_downranks_remain_distinct_actions_but_one_hot_family():
    ir=build_game_ir_slice(class_key='druid',level=60)
    ranks=_ranks(ir)
    assert len(ranks)==9
    assert len({a.provenance[0]['source_spell_id'] for a in ranks.values()})==9
    assert {a.effects[1].aura_id for a in ranks.values()}=={'source_periodic_heal:regrowth'}
    assert all(a.id in next(m for m in ir.modes if m.id=='caster').enabled_action_ids
               for a in ranks.values())
