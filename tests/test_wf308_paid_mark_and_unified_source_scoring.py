"""WF308: genuinely sourced Mark, persistent aura capacity, L2/L3 parity."""
from dataclasses import replace
import json,sqlite3
from pathlib import Path

import pytest

from src.game.data.forever.source_maintenance_ranks import latest_stat_maintenance_rank
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.registry import build_game_ir_slice
from src.game.runtime import ActorState
from src.game.runtime.source_maintenance import _execute_source_maintenance_upkeep
from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate
from src.v2.generic_backend import _policy_combat_evaluation

ROOT=Path(__file__).resolve().parents[1]


def candidate():
    stage=json.loads((ROOT/'WF303_COLD_TWO_PROFILE.json').read_text())['persistent_winner']['stage']
    return prepare_candidate(class_key='druid',level=20,stage=stage)


def test_mark_rank_is_exact_source_index_fact_not_hardcoded_level20():
    levels=[(1,1126,20,34,0,3600),(10,5232,50,88,3,3600),
            (20,6756,100,142,5,3600),(30,5234,160,203,8,3600)]
    for level,sid,mana,armor,attrs,duration in levels:
        r=latest_stat_maintenance_rank('druid','Mark of the Wild',level)
        assert (r['spell_id'],r['mana_cost'],r['armor'],r['attributes'],r['duration_s']) == (sid,mana,armor,attrs,duration)
    assert latest_stat_maintenance_rank('druid','Mark of the Wild',30)['resistances']==7
    assert latest_stat_maintenance_rank('druid','Mark of the Wild',20)['resistances']==0


def test_l20_mark_aura_has_source_derived_stats_and_resource_capacity():
    ir=build_game_ir_slice(class_key='druid',level=20)
    a=next(x for x in ir.actions if x.id=='source_spell:6756')
    eff=a.effects[0]
    assert a.costs[0].amount==100 and eff.duration_s==3600
    assert eff.actor_stat_deltas['armor']==142
    assert eff.actor_stat_deltas['strength']==5
    # WF309: derived stats are resolved from canonical conversion rules
    # against the actual geared actor at CAST time, not naked IR-build stats.
    assert eff.apply_primary_stat_conversions
    assert 'attack_power' not in eff.actor_stat_deltas
    assert 'health' not in eff.actor_resource_capacity_deltas
    assert any(f.get('maintenance_action_id')=='source_spell:6756'
               for p in ir.policies for f in p.maintenance)


def test_two_auras_actual_casts_mana_and_expiration_no_stat_drift():
    ir=build_game_ir_slice(class_key='druid',level=20)
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    initial=dict(actor.stats);hp=actor.resource_capacity['health'];mana=actor.resources['mana']
    cost,casts,events=_execute_source_maintenance_upkeep(ir,actor)
    assert (cost,casts)==(3.,2) and events>0
    # Mark grants +5 Intellect => +75 max mana (source conversion);
    # percentage-preserving capacity semantics also change current mana.
    assert actor.resource_capacity['mana']==mana+75
    assert actor.resources['mana'] < actor.resource_capacity['mana']
    assert actor.stats['attack_power']==initial['attack_power']+10
    assert abs(actor.stats['melee_crit_chance']-initial['melee_crit_chance']-.0025)<1e-10
    assert actor.stats['armor']==initial['armor']+142
    assert actor.resource_capacity['health']==hp+50
    assert actor.resource_capacity['mana']==mana+75
    assert set(actor.active_auras)=={'source_maintenance:mark_of_the_wild:6756','source_maintenance:thorns:782'}
    assert not _execute_source_maintenance_upkeep(ir,actor)[1]
    actor.current_time_s=605
    expired=actor.expire_elapsed_auras(actor.current_time_s)
    assert expired==('source_maintenance:thorns:782',)
    assert actor.stats['armor']==initial['armor']+142
    assert _execute_source_maintenance_upkeep(ir,actor)[1]==1
    actor.current_time_s=3605
    expired=actor.expire_elapsed_auras(actor.current_time_s)
    assert set(expired)=={'source_maintenance:mark_of_the_wild:6756','source_maintenance:thorns:782'}
    assert actor.stats==initial
    assert actor.resource_capacity['health']==hp
    assert actor.resource_capacity['mana']==mana


def test_l2_one_mob_exact_same_as_persistent_100mob_first_mob():
    c=candidate()
    actual=evaluate_persistent_candidate(c,level=20,mobs=1)
    score,exec_result,details=_policy_combat_evaluation(
        c.ir,level=20,policy_override=c.policy,opening_action_ids=c.opening,
        schedule_incoming_attacks=True)
    assert actual['status']=='COMPLETE' and exec_result.timeline.target_defeated
    assert abs(score.seconds_per_mob-actual['mean_s_per_mob'])<1e-9
    assert (details['source_maintenance_casts'],details['source_maintenance_events'])==(
        actual['maintenance_casts'],actual['maintenance_runtime_events'])
    assert details['event_transitions_new']==actual['events']
    long=evaluate_persistent_candidate(c,level=20,mobs=100)
    assert long['status']=='COMPLETE' and long['maintenance_casts']==4
    assert long['mean_s_per_mob']<actual['mean_s_per_mob']


def test_source_tamper_without_proof_fails_closed(tmp_path):
    db=tmp_path/'tampered.sqlite'
    with sqlite3.connect(f'file:{DEFAULT_DB}?mode=ro',uri=True) as src,sqlite3.connect(db) as dest:
        src.backup(dest)
    with sqlite3.connect(db) as con:
        raw=json.loads(con.execute("SELECT raw_listview_json FROM spell_index WHERE class_key='druid' AND spell_id=6756").fetchone()[0])
        raw['envChange']['after']['text']='Unknown effect with unverified values'
        con.execute("UPDATE spell_index SET raw_listview_json=? WHERE class_key='druid' AND spell_id=6756",(json.dumps(raw),))
    with pytest.raises(ValueError,match='UNPARSED_STAT_AURA_SEMANTICS'):
        latest_stat_maintenance_rank('druid','Mark of the Wild',20,db_path=db)
