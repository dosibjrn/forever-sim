"""Source-pinned Eclipse: real Wrath -> Starfire paid charge state and 100mob APL."""
from dataclasses import replace
from pathlib import Path
import sqlite3
import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection
from src.game.runtime import ActorState, TargetState, CombatRuntime
from src.game.policy import condition_matches
from src.game.model import PolicyCondition, PolicyDefinition, PolicyRuleDefinition

DB=Path(__file__).resolve().parents[1]/'data/forever/staged_druid_l30_talents_70338.sqlite'
FILLER={'genesis':5,'improved_wrath':5,'improved_moonfire':2,
        'natures_majesty':2,'moonglow':3,'natures_reach':2,
        'improved_entangling_roots':1}
ECLIPSE={**FILLER,'eclipse':3,'ferocity':3}


def _ir():
    return compile_talent_runtime(build_game_ir_slice(class_key='druid',level=30,ability_db_path=DB))[0]


def _selected():
    return apply_talent_selection(_ir(),ECLIPSE,level=30,bonus_talent_points=5)[0]


def _actions(ir):
    return (next(a for a in ir.actions if a.family_key=='wrath'),
            next(a for a in ir.actions if a.family_key=='starfire'))


def test_pinned_70338_charge_facts_compile_all_three_ranks_atomically():
    with sqlite3.connect(DB) as db:
        rows=db.execute("SELECT source_build,producer_family,consumer_family,grant_per_cast,capacity,duration_s,source_url FROM sourced_talent_charge_facts WHERE class_key='druid' AND talent_id='eclipse'").fetchall()
    assert rows==[('1.60.1.70338','wrath','starfire',2,4,15.,'https://theforeverera.com/en/talents/druid/eclipse/')]
    ir=_ir()
    ranks=next(t.ranks for t in ir.talents if t.id=='eclipse')
    assert len(ranks)==3
    for rank in ranks:
        assert len(rank.modifiers)==1
        mod=rank.modifiers[0]
        assert mod.kind=='cast_charge_exchange'
        assert mod.target_type=='action_family' and mod.target_id=='starfire'
        assert mod.value==pytest.approx((.17,.33,.5)[rank.rank-1])
        assert mod.provenance['grant_per_cast']==2
        assert mod.provenance['capacity']==4
        assert mod.provenance['duration_s']==15.
        assert mod.provenance['source_build']=='1.60.1.70338'


def test_legal_26pt_allocation_wires_source_action_families_without_static_cast_shortcut():
    assert sum(ECLIPSE.values())==26
    ir=_selected()
    wrath,starfire=_actions(ir)
    assert wrath.metadata['source_cast_charge_producer']['grant_per_cast']==2
    assert starfire.metadata['source_cast_charge_consumer']['reduction_s']==pytest.approx(.5)
    assert starfire.cast_time_s==pytest.approx(3.5)  # charge must be paid dynamically
    assert wrath.metadata['source_cast_charge_producer']['bank_id']==starfire.metadata['source_cast_charge_consumer']['bank_id']


def _runtime():
    ir=_selected()
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    actor.resource_capacity['mana']=100000.
    actor.resources['mana']=100000.
    rt=CombatRuntime(actor=actor,target=TargetState.with_health('large',1e7),spell_power=0.)
    return rt,*_actions(ir)


def _cast(rt,action):
    rt.advance_to(max(rt.actor.current_time_s,rt.actor.gcd_ready_s,
                      rt.actor.cooldown_ready_s.get(action.id,0.)))
    end=rt.schedule_action(action)
    rt.advance_to(end)
    return [e for e in rt.trace if e.kind=='ActionStarted' and e.action_id==action.id][-1]


def test_real_combat_casts_grant_cap_consume_and_expire_paid_charges():
    rt,wrath,starfire=_runtime()
    bank=starfire.metadata['source_cast_charge_consumer']['bank_id']
    _cast(rt,wrath)
    assert rt.actor.source_cast_charge_banks[bank]['charges']==2
    _cast(rt,wrath)
    assert rt.actor.source_cast_charge_banks[bank]['charges']==4
    _cast(rt,wrath)
    assert rt.actor.source_cast_charge_banks[bank]['charges']==4
    for remaining in (3,2,1,0):
        event=_cast(rt,starfire)
        assert event.payload['cast_time_s']==pytest.approx(3.0)
        assert rt.actor.source_cast_charge_banks[bank]['charges']==remaining
    assert _cast(rt,starfire).payload['cast_time_s']==pytest.approx(3.5)
    _cast(rt,wrath)
    rt.advance_to(rt.actor.current_time_s+16.)
    assert _cast(rt,starfire).payload['cast_time_s']==pytest.approx(3.5)
    assert any(e.kind=='CastChargeGranted' for e in rt.trace)
    assert any(e.kind=='CastChargeConsumed' for e in rt.trace)


def test_policy_reads_source_charge_state_not_a_fake_static_talent_score():
    rt,wrath,starfire=_runtime()
    bank=starfire.metadata['source_cast_charge_consumer']['bank_id']
    condition=PolicyCondition(kind='stored_cast_charges',field=bank,operator='gte',value=1)
    assert condition_matches(condition,action=starfire,runtime=rt) is False
    _cast(rt,wrath)
    assert condition_matches(condition,action=starfire,runtime=rt) is True
    with pytest.raises(ValueError,match='UNKNOWN_SOURCE_CHARGE_BANK'):
        condition_matches(replace(condition,field='not_a_sourced_bank'),action=starfire,runtime=rt)


def test_source_26pt_charge_apl_completes_real_paid_100mob():
    from src.v2.source_bounded_joint_frontier import source_cold_start_stage,_source_stat_package_proposals,_recovery_variants
    from src.game.data.forever.source_checkpoint_p3_swaps import substituted_multi_stage
    from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate
    ir=_ir()
    stage=source_cold_start_stage(class_key='druid',level=30,source_ir=ir,gear_role='druid_feral')
    packs=dict(_source_stat_package_proposals(class_key='druid',level=30,
        base=stage['gear_policy_result']['winner']['gear'],max_packages=4)[0])
    stage=substituted_multi_stage(stage=stage,class_key='druid',level=30,swaps=packs['spell_power'])
    candidate=prepare_candidate(class_key='druid',level=30,stage=stage,
        allocation_override=ECLIPSE,source_ir=ir,allow_partial_gear_stats=True,bonus_talent_points=5)
    wrath,starfire=_actions(candidate.ir)
    bank=starfire.metadata['source_cast_charge_consumer']['bank_id']
    policy=PolicyDefinition('source_charge_apl','source-derived charge consumer then producer',
        rules=(PolicyRuleDefinition('consume',starfire.id,
                    conditions=(PolicyCondition(kind='stored_cast_charges',field=bank,operator='gte',value=1),)),
               PolicyRuleDefinition('generate',wrath.id)),
        provenance={'authority':'source_gameir_charge_witness'})
    candidate=replace(candidate,policy=policy,opening=())
    rec=dict(_recovery_variants(ir,stage,2))['always']
    r=evaluate_persistent_candidate(candidate,level=30,mobs=100,
        max_total_events=250000,max_wall_s=30,max_cpu_s=30,recovery_policy=rec)
    assert r['status']=='COMPLETE',r
    assert r['count']==100
    assert r['source_action_counts'][wrath.id]>=100
    assert r['source_action_counts'][starfire.id]>=100
    assert r['mean_s_per_mob']>0


def test_cold_search_independently_generates_source_charge_apl_witness():
    from src.v2.source_bounded_joint_frontier import _source_modified_action_policy_witnesses,source_cold_start_stage
    root=_ir()
    selected=_selected()
    stage=source_cold_start_stage(class_key='druid',level=30,source_ir=root,gear_role='druid_feral')
    witnesses=_source_modified_action_policy_witnesses(root,selected,ECLIPSE,stage)
    assert witnesses
    assert any('charge' in label for label,_ in witnesses)
    wrath,starfire=_actions(selected)
    assert any(any(r.action_id==starfire.id and any(c.kind=='stored_cast_charges' for c in r.conditions)
                   for r in policy.rules) and any(r.action_id==wrath.id for r in policy.rules)
               for _,policy in witnesses)


def test_cold_64_full_point_frontier_reserves_source_charge_mechanism():
    from src.v2.source_bounded_joint_frontier import bounded_full_point_talent_frontier
    from src.game.talents import validate_talent_selection
    ir=_ir()
    charges={t.id for t in ir.talents if any(
        m.kind=='cast_charge_exchange' for r in t.ranks for m in r.modifiers)}
    assert charges
    allocations,ledger=bounded_full_point_talent_frontier(ir,level=30,
        max_frontier=64,bonus_talent_points=5)
    for talent_id in charges:
        talent=next(t for t in ir.talents if t.id==talent_id)
        assert any(a.get(talent_id)==talent.max_rank for a in allocations),talent_id
    for allocation in allocations:
        assert sum(allocation.values())==26
        validate_talent_selection(ir,allocation,level=30,bonus_talent_points=5)


@pytest.mark.parametrize('corruption',('missing_row','wrong_producer','wrong_source_build'))
def test_source_charge_fact_must_match_pinned_build_and_both_action_families(tmp_path,corruption):
    import shutil
    copied=tmp_path/'source.sqlite'
    shutil.copy2(DB,copied)
    with sqlite3.connect(copied) as db:
        if corruption=='missing_row':
            db.execute("DELETE FROM sourced_talent_charge_facts WHERE talent_id='eclipse'")
        elif corruption=='wrong_producer':
            db.execute("UPDATE sourced_talent_charge_facts SET producer_family='unknown_family' WHERE talent_id='eclipse'")
        else:
            db.execute("UPDATE sourced_talent_charge_facts SET source_build='WRONG_BUILD' WHERE talent_id='eclipse'")
    ir,coverage=compile_talent_runtime(build_game_ir_slice(
        class_key='druid',level=30,ability_db_path=copied))
    eclipse=next(t for t in ir.talents if t.id=='eclipse')
    assert all(not rank.modifiers for rank in eclipse.ranks)
    baseline=compile_talent_runtime(build_game_ir_slice(
        class_key='druid',level=30,ability_db_path=DB))[1]['rank_missing_executor']
    assert coverage['rank_missing_executor']>=baseline+3
