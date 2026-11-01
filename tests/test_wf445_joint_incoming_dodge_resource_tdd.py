"""RED: sourced incoming dodge must resolve damage and resource on ONE event.

The fixture is synthetic. It tests generic engine semantics, not source-build
certification or a 100-mob checkpoint.
"""
from dataclasses import replace
import pytest
from src.game.model.ir import (ActorDefinition, GameIRSlice, IncomingAttackDefinition,
    ResourceDefinition, ModeDefinition, ModeResourceRule, TalentDefinition,
    TalentRankDefinition, TalentModifier)
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.game.talents import apply_talent_selection

SOURCE = 'https://theforeverera.com/en/talents/druid/natural-reaction/'


def _ir(*, talent=True, proc=.4):
    actor=ActorDefinition(id='player',actor_type='player',base_stats={'dodge_chance':.25})
    resources=(ResourceDefinition(id='health',name='Health',owner_actor_id='player',
            initial_amount=5000.,capacity=5000.),
        ResourceDefinition(id='rage',name='Rage',owner_actor_id='player',
            initial_amount=0.,capacity=1000.))
    modes=(ModeDefinition(id='bear',label='Bear',initial=True,
            resource_rules=(ModeResourceRule(resource_id='rage',active=True),)),)
    modifier=TalentModifier(kind='incoming_dodge_resource_gain',target_type='resource',
        target_id='rage',value=proc,provenance={'source_url':SOURCE,
            'source_build':'1.60.1.70338','required_mode_id':'bear',
            'bonus_resource_amount':5.,'source_build_bridge_verified':False})
    rank=TalentRankDefinition(rank=1,modifiers=(modifier,))
    talents=(TalentDefinition(id='sourced_avoidance',name='Avoidance',tree_key='test',
        max_rank=1,ranks=(rank,),metadata={'row':0}),)
    base=GameIRSlice(id='incoming-joint',ruleset='test',actor=actor,
        actions=(),resources=resources,modes=modes,talents=talents)
    return apply_talent_selection(base,{'sourced_avoidance':1},level=30)[0] if talent else base


def _run(*, talent=True, seed=9, school='physical', proc=.4, included=False):
    ir=_ir(talent=talent,proc=proc)
    attack=IncomingAttackDefinition(id='attack',name='Attack',source_actor_id='mob',
        target_actor_id='player',school=school,raw_damage=10.,hit_chance=.8,
        health_resource_id='health',metadata={'hit_chance_includes_actor_dodge':included})
    rt=CombatRuntime(actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes),
        target=TargetState.with_health('mob',1e6),sampling_seed=seed)
    results=[rt.resolve_incoming_attack(attack,at_time_s=i*.1) for i in range(100)]
    gains=[e for e in rt.trace if e.kind=='ResourceEventGain'
           and e.payload.get('rule_id')=='source_dodge_gain:sourced_avoidance:rage']
    return rt,results,gains


def test_source_rank_compiles_discrete_dodge_event_without_lying_about_build_bridge():
    ir=_ir()
    rule=next(r for r in ir.resources if r.id=='rage').event_gain_rules[0]
    assert rule.event_kind=='incoming_physical_dodge'
    assert rule.event_value_field=='sampled_dodge_count'
    assert rule.multiplier==5.
    assert rule.metadata['resolution']=='sampled_joint_dodge'
    assert rule.metadata['proc_probability']==pytest.approx(.4)
    assert rule.provenance[0]['source_build_bridge_verified'] is False


def test_100_incoming_events_joint_hit_dodge_and_discrete_rage():
    rt,results,gains=_run()
    outcomes=[r['sampled_incoming_outcome'] for r in results]
    assert {'hit','miss','dodge'}<=set(outcomes)
    assert all(r['health_damage_applied']==pytest.approx(
        10. if r['sampled_incoming_outcome']=='hit' else 0.) for r in results)
    assert all(r['sampled_dodge_count']==int(r['sampled_incoming_outcome']=='dodge')
               for r in results)
    assert all(g.payload['requested_gain']==5. for g in gains)
    assert 0<len(gains)<outcomes.count('dodge')
    assert rt.actor.resources['rage']==5.*len(gains)
    assert rt.actor.resources['health']==pytest.approx(
        5000.-10.*outcomes.count('hit'))


def test_dodge_outcomes_and_resource_procs_replay_from_seed():
    _,a,ag=_run(seed=10)
    _,b,bg=_run(seed=10)
    _,c,cg=_run(seed=11)
    assert [(r['sampled_incoming_outcome'],r['health_damage_applied']) for r in a]==[
        (r['sampled_incoming_outcome'],r['health_damage_applied']) for r in b]
    assert [r['sampled_incoming_outcome'] for r in a]!=[
        r['sampled_incoming_outcome'] for r in c]
    assert [g.time_s for g in ag]==[g.time_s for g in bg]


def test_magic_never_dodges_or_grants_dodge_rage():
    rt,results,gains=_run(school='arcane')
    assert not gains
    assert all(r['expected_dodge_count']==0. for r in results)
    assert all('sampled_incoming_outcome' not in r for r in results)
    assert rt.actor.resources['rage']==0.


def test_legacy_expected_value_and_pre_accounted_avoidance_do_not_gain_rage():
    rt,results,gains=_run(talent=False)
    assert not gains
    assert all('sampled_incoming_outcome' not in r for r in results)
    assert all(r['health_damage_applied']==pytest.approx(6.) for r in results)
    assert rt.actor.resources['health']==pytest.approx(4400.)
    rt2,pre,gains2=_run(included=True)
    assert not gains2
    assert all(r['sampled_dodge_count']==0 for r in pre)
    assert all(r['health_damage_applied'] in (0.,10.) for r in pre)
