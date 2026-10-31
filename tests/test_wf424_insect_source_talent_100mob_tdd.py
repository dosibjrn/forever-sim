"""L30 26-point Insect Swarm: SQL source -> grant -> paid executable witnesses."""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection
from src.game.model import (ActorDefinition,ResourceDefinition,IncomingAttackDefinition)
from src.game.runtime import ActorState,CombatRuntime,TargetState
from src.v2.source_bounded_joint_frontier import (bounded_full_point_talent_frontier,
    source_talent_unlock_witnesses,_prepare_joint_policy_candidate)
from src.v2.source_persistent_joint_finalists import evaluate_persistent_candidate

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite'


def _source():
    return compile_talent_runtime(build_game_ir_slice(class_key='druid',level=30,
        ability_db_path=DB))[0]


def _allocation(ir):
    full,_=bounded_full_point_talent_frontier(ir,level=30,max_frontier=16,
        bonus_talent_points=5)
    return next(a for a in full if a.get('insect_swarm') == 1)


def _candidate():
    source=_source();allocation=_allocation(source)
    chosen,_=apply_talent_selection(source,allocation,level=30,bonus_talent_points=5)
    stage=json.loads((ROOT/'evidence/wf360/WF360_L30_P4_30S.json').read_text())['winner_stage']
    witness=next(w for w in source_talent_unlock_witnesses(source,chosen,stage)
                 if w['action_id']=='insect_swarm:24974')
    candidate=_prepare_joint_policy_candidate(class_key='druid',level=30,
        stage=stage,allocation=allocation,source_ir=source,
        allow_partial_gear_stats=True,policy_label='talent_unlock:insect_swarm:24974',
        policy=witness['policy'],bonus_talent_points=5)
    return candidate,witness


def test_source_rank2_after_tooltip_not_legacy_before_and_no_free_cast():
    with sqlite3.connect(DB) as db:
        source=json.loads(db.execute('select action_json from verified_talent_granted_action_facts where spell_id=24974').fetchone()[0])
        assert source['periodic_total_base_damage']==90
        assert source['mana_cost']==85
        assert source['target_hit_chance_delta']==-0.02
        assert source['required_level']==30
        assert source['grant_parent_spell_id']==5570
    root=_source()
    assert 'insect_swarm:24974' not in {a.id for a in root.actions}
    naked,_=apply_talent_selection(root,{},level=30,bonus_talent_points=5)
    assert 'insect_swarm:24974' not in {a.id for a in naked.actions}
    chosen,_=apply_talent_selection(root,_allocation(root),level=30,bonus_talent_points=5)
    granted=next(a for a in chosen.actions if a.id=='insect_swarm:24974')
    assert [e.effect_type for e in granted.effects]==['periodic_damage','target_stat_debuff']
    assert [e.total_base_damage for e in granted.effects if e.effect_type=='periodic_damage']==pytest.approx([94.5])  # 90 sourced base + Genesis 5%
    assert 'insect_swarm:24974' in next(m for m in chosen.modes if m.id=='caster').enabled_action_ids
    assert all('insect_swarm:24974' not in (m.enabled_action_ids or ())
               for m in chosen.modes if m.id!='caster')


def test_source_witness_fills_direct_damage_and_actually_casts_both_paid():
    candidate,witness=_candidate()
    ids=[rule.action_id for rule in witness['policy'].rules]
    assert ids[:2]==['insect_swarm:24974','wrath:5180']
    result=evaluate_persistent_candidate(candidate,level=30,mobs=4,max_total_events=200000)
    assert result['status']=='COMPLETE',result
    assert result['source_action_counts']['insect_swarm:24974'] > 0
    assert result['source_action_counts']['wrath:5180'] > 0


def test_100mob_paid_persistent_source_witness():
    candidate,_=_candidate()
    result=evaluate_persistent_candidate(candidate,level=30,mobs=100,max_total_events=200000)
    assert result['status']=='COMPLETE' and result['count']==100,result
    assert result['source_action_counts']['insect_swarm:24974']>=100
    assert result['source_action_counts']['wrath:5180']>0
    assert result['mean_s_per_mob']>0


def test_target_hit_debuff_affects_own_enemy_not_other_then_expires():
    # A sourced -2pp attack-hit debuff cannot affect a different mob.
    actor=ActorState.from_ir(ActorDefinition('hero','player',base_stats={}),
        (ResourceDefinition('health','HP','hero',initial_amount=1000,capacity=1000),),())
    enemy1=TargetState.with_health('m1',500,spell_hit=1.,melee_hit=1.)
    enemy2=TargetState.with_health('m2',500,spell_hit=1.,melee_hit=1.)
    rt=CombatRuntime(actor=actor,target=enemy1,other_targets=(enemy2,),
        spatial_positions_yards={'m1':(0.,0.),'m2':(4.,0.)})
    source=_source()
    unlocked,_=apply_talent_selection(source,_allocation(source),level=30,bonus_talent_points=5)
    source_effect=next(a for a in unlocked.actions if a.id=='insect_swarm:24974').effects[1]
    # Directly scheduled typed source debuff action avoids gear and mana.
    from src.game.model import ActionDefinition
    debuff=ActionDefinition('debuff','debuff','Source debuff','hero',(),(),0,0,0,
        (source_effect,),({'test':'wf424'},))
    rt.schedule_action(debuff)
    attacks=[IncomingAttackDefinition(f'atk{i}',f'Attack{i}',f'm{i}','hero',
        'physical',100.,1.,'health',provenance=({'source':'wf424'},)) for i in (1,2)]
    first=rt.resolve_incoming_attack(attacks[0]);other=rt.resolve_incoming_attack(attacks[1])
    assert first['hit_chance']==pytest.approx(.98)
    assert other['hit_chance']==pytest.approx(1.)
    rt.advance_to(13.)
    after=rt.resolve_incoming_attack(attacks[0]);assert after['hit_chance']==pytest.approx(1.)
