"""WF430: source-staged compound talent, paid deterministic proc and incoming suppression."""
from pathlib import Path
from dataclasses import replace
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection
from src.game.model import (ActorDefinition, ResourceDefinition, ActionDefinition,
                            DamageEffect, ControlEffect, IncomingAttackDefinition)
from src.game.runtime import ActorState, TargetState, CombatRuntime

DB=Path(__file__).resolve().parents[1]/'data/forever/staged_druid_l30_talents_70338.sqlite'


def _compiled():
    return compile_talent_runtime(build_game_ir_slice(class_key='druid',level=30,ability_db_path=DB))


def test_source_compound_five_ranks_and_duration_are_all_executable():
    ir,coverage=_compiled()
    t=next(t for t in ir.talents if t.id=='improved_starfire')
    assert coverage['rank_missing_executor']==sum(
        not r.modifiers for talent in ir.talents for r in talent.ranks)
    assert coverage['rank_missing_executor']>0  # P2 still RED
    for rank,row in enumerate(t.ranks,1):
        assert len(row.modifiers)==2
        cast,proc=row.modifiers
        assert cast.kind=='cast_time_delta_s'
        assert cast.target_type=='action_family' and cast.target_id=='starfire'
        assert cast.value==pytest.approx(-.1*rank)
        assert proc.kind=='action_control_proc'
        assert proc.target_type=='action_family' and proc.target_id=='starfire'
        assert proc.value==pytest.approx(.03*rank)
        assert proc.provenance['duration_s']==pytest.approx(3.)
        assert proc.provenance['control_id']=='stun'
        assert proc.provenance['source_build']=='1.60.1.70338'


def test_legal_26_point_selection_applies_only_starfire_not_wrath():
    ir,_=_compiled()
    base={'genesis':5,'improved_wrath':5,'improved_moonfire':2,
          'natures_majesty':2,'moonglow':3,'natures_reach':2,
          'natures_splendor':1,'insect_swarm':1,'ferocity':5}
    selected=dict(base); selected.pop('ferocity');selected['improved_starfire']=5
    assert sum(base.values())==sum(selected.values())==26
    before,_=apply_talent_selection(ir,base,level=30,bonus_talent_points=5)
    after,_=apply_talent_selection(ir,selected,level=30,bonus_talent_points=5)
    for family in ('wrath','starfire'):
        original=next(a for a in before.actions if a.family_key==family)
        modified=next(a for a in after.actions if a.family_key==family)
        if family=='starfire':
            assert modified.cast_time_s==pytest.approx(original.cast_time_s-.5)
            stuns=[e for e in modified.effects if isinstance(e,ControlEffect) and e.control_id=='stun']
            assert len(stuns)==1 and stuns[0].duration_s==pytest.approx(3.)
            assert stuns[0].proc_chance==pytest.approx(.15)
        else:
            assert modified==original


def _runtime(chance):
    actor=ActorState.from_ir(ActorDefinition('hero','player',base_stats={}),
        (ResourceDefinition('health','Health','hero',initial_amount=500,capacity=500),),())
    rt=CombatRuntime(actor=actor,target=TargetState.with_health('mob',1000))
    action=ActionDefinition('source_proc','source_proc','source_proc','hero',
        requirements=(),costs=(),cast_time_s=0,gcd_s=0,cooldown_s=0,
        effects=(ControlEffect('control','stun','enemy',3.,prevents_enemy_actions=True,
            proc_chance=chance),),provenance=())
    rt.enqueue_action(action)
    rt.advance_to(0)
    attack=IncomingAttackDefinition('swing','swing','mob','hero',
        school='physical',raw_damage=40,hit_chance=1.,health_resource_id='health')
    return rt,attack


def test_generic_control_proc_zero_and_one_and_paid_swing():
    for chance in (0.,1.):
        rt,attack=_runtime(chance)
        applied=[e for e in rt.trace if e.kind=='ControlApplied']
        assert len(applied)==1
        assert applied[0].payload['proc_chance']==pytest.approx(chance)
        assert applied[0].payload['proc_triggered'] is (chance==1.)
        before=rt.actor.resource_amount('health')
        resolved=rt.resolve_incoming_attack(attack,at_time_s=1.)
        assert (resolved.get('suppressed_by_control')=='stun') is (chance==1.)
        assert (rt.actor.resource_amount('health')==before) is (chance==1.)


def test_compound_fail_closed_if_duration_missing_or_conflicting(tmp_path):
    import sqlite3,shutil
    path=tmp_path/'without_control_duration.sqlite'
    shutil.copy2(DB,path)
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM sourced_talent_proc_control_facts WHERE talent_id='improved_starfire'")
    ir,cov=compile_talent_runtime(build_game_ir_slice(class_key='druid',level=30,ability_db_path=path))
    t=next(t for t in ir.talents if t.id=='improved_starfire')
    assert all(not r.modifiers for r in t.ranks)
    baseline=_compiled()[1]['rank_missing_executor']
    assert cov['rank_missing_executor']>=baseline+5


def test_paid_100mob_starfire_proc_counts_and_independent_replay():
    from src.v2.source_bounded_joint_frontier import (source_cold_start_stage,
        _source_stat_package_proposals,_recovery_variants)
    from src.game.data.forever.source_checkpoint_p3_swaps import substituted_multi_stage
    from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate
    from src.game.model import PolicyDefinition,PolicyRuleDefinition
    ir,_=_compiled()
    stage=source_cold_start_stage(class_key='druid',level=30,source_ir=ir,gear_role='druid_feral')
    packs=dict(_source_stat_package_proposals(class_key='druid',level=30,
        base=stage['gear_policy_result']['winner']['gear'],max_packages=4)[0])
    stage=substituted_multi_stage(stage=stage,class_key='druid',level=30,swaps=packs['spell_power'])
    rec=dict(_recovery_variants(ir,stage,2))['always']
    base={'genesis':5,'improved_wrath':5,'improved_moonfire':2,
          'natures_majesty':2,'moonglow':3,'natures_reach':2,
          'natures_splendor':1,'insect_swarm':1,'ferocity':5}
    source={**{k:v for k,v in base.items() if k!='ferocity'},'improved_starfire':5}
    results={}
    for label,allocation in [('baseline',base),('source_proc',source)]:
        candidate=prepare_candidate(class_key='druid',level=30,stage=stage,
            allocation_override=allocation,source_ir=ir,allow_partial_gear_stats=True,
            bonus_talent_points=5)
        starfire=next(a for a in candidate.ir.actions if a.family_key=='starfire')
        policy=PolicyDefinition('starfire_only','Starfire only',
            rules=(PolicyRuleDefinition('cast_starfire',starfire.id),),
            provenance={'authority':'source_ir_mechanics_witness'})
        candidate=replace(candidate,policy=policy,opening=())
        first=evaluate_persistent_candidate(candidate,level=30,mobs=100,
            max_total_events=250000,max_wall_s=30,max_cpu_s=30,recovery_policy=rec)
        second=evaluate_persistent_candidate(candidate,level=30,mobs=100,
            max_total_events=250000,max_wall_s=30,max_cpu_s=30,recovery_policy=rec)
        assert first['status']==second['status']=='COMPLETE'
        assert first['count']==second['count']==100
        assert first['mean_s_per_mob']==pytest.approx(second['mean_s_per_mob'],abs=1e-10)
        assert first['source_control_proc_attempts']==second['source_control_proc_attempts']
        assert first['source_control_proc_triggered']==second['source_control_proc_triggered']
        results[label]=first
    assert results['baseline']['source_control_proc_attempts']==0
    assert results['source_proc']['source_control_proc_attempts']>100
    assert 0<results['source_proc']['source_control_proc_triggered']<results['source_proc']['source_control_proc_attempts']
    assert results['source_proc']['mean_s_per_mob']<results['baseline']['mean_s_per_mob']


def test_cold_full_point_frontier_reserves_sourced_max_rank_control_witness():
    from src.v2.source_bounded_joint_frontier import bounded_full_point_talent_frontier
    from src.game.talents import validate_talent_selection
    ir,_=_compiled()
    allocations,ledger=bounded_full_point_talent_frontier(ir,level=30,
        max_frontier=64,bonus_talent_points=5)
    assert len(allocations)<=64
    assert any(a.get('improved_starfire')==5 for a in allocations)
    assert any(a.get('insect_swarm')==1 for a in allocations)
    for allocation in allocations:
        assert sum(allocation.values())==26
        validate_talent_selection(ir,allocation,level=30,bonus_talent_points=5)
    assert 'improved_starfire' in ledger['source_max_rank_witnesses_found']
    assert ledger['source_max_rank_witnesses_admitted']>0


@pytest.mark.parametrize('chance,should_freeze',[(0.,False),(1.,True)])
def test_source_stun_proc_freezes_real_2d_approach_and_resumes(chance,should_freeze):
    actor=ActorState.from_ir(ActorDefinition('hero','player',base_stats={}),
        (ResourceDefinition('health','Health','hero',initial_amount=500,capacity=500),),())
    targets=[TargetState.with_health('m0',500),TargetState.with_health('m1',500)]
    rt=CombatRuntime(actor=actor,target=targets[0],other_targets=(targets[1],),
        spatial_positions_yards={'m0':(0.,0.),'m1':(20.,0.)},
        enemy_move_speed_yards_s=5.,melee_radius_yards=5.)
    rt.engage_target('m1');rt.select_target('m1');rt.advance_to(1.)
    assert rt._enemy_distance('m1')==pytest.approx(15.)
    action=ActionDefinition('proc','proc','proc','hero',requirements=(),costs=(),
        cast_time_s=0.,gcd_s=0.,cooldown_s=0.,
        effects=(ControlEffect('control','stun','enemy',3.,
            prevents_enemy_actions=True,proc_chance=chance),),provenance=(),
        metadata={'range_yards':30.})
    rt.schedule_action(action)
    rt.advance_to(3.5)
    if should_freeze:
        assert rt._enemy_distance('m1')==pytest.approx(15.)
        assert 'm1' not in rt._melee_targets
        rt.advance_to(5.9)
        assert 'm1' not in rt._melee_targets
        rt.advance_to(6.)
        assert 'm1' in rt._melee_targets
    else:
        assert 'm1' in rt._melee_targets
