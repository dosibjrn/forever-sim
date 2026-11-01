"""RED: typed talent dodge+resource proc uses the real incoming event pipeline."""
from dataclasses import replace
import pytest
from src.game.model.ir import (ActorDefinition, GameIRSlice, IncomingAttackDefinition,
    ResourceDefinition, TalentDefinition, TalentRankDefinition, TalentModifier)
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.game.talents import apply_talent_selection

SOURCE='https://theforeverera.com/en/talents/druid/natural-reaction/'


def _slice():
    modifiers=(
        TalentModifier(kind='actor_stat_flat',target_type='actor_stat',
            target_id='dodge_chance',value=.01,provenance={'url':SOURCE}),
        TalentModifier(kind='avoidance_resource_proc',target_type='resource',
            target_id='rage',value=.20,provenance={'url':SOURCE,
                'gain_amount':5.,'source_build':'1.60.1.70374',
                'source_build_verified':False,'proc_distribution_verified':False}),
    )
    talent=TalentDefinition(id='test_avoidance',name='Source avoidance',tree_key='test',
        max_rank=1,ranks=(TalentRankDefinition(rank=1,modifiers=modifiers),),
        metadata={'row':0})
    return GameIRSlice(id='avoidance-test',ruleset='test',
        actor=ActorDefinition(id='player',actor_type='player',
            base_stats={'dodge_chance':.10}),
        resources=(ResourceDefinition(id='health',name='Health',owner_actor_id='player',
                initial_amount=100.,capacity=100.),
            ResourceDefinition(id='rage',name='Rage',owner_actor_id='player',
                initial_amount=0.,capacity=100.)),
        actions=(),talents=(talent,))


def _attack(school='physical'):
    return IncomingAttackDefinition(id='attack',name='attack',source_actor_id='mob',
        target_actor_id='player',school=school,raw_damage=10.,hit_chance=1.,
        health_resource_id='health')


def _runtime(ir):
    return CombatRuntime(actor=ActorState.from_ir(ir.actor,ir.resources),
        target=TargetState.with_health('mob',1000.))


def test_avoidance_rank_compiles_two_real_effects_and_preserves_base():
    original=_slice()
    changed,application=apply_talent_selection(original,{'test_avoidance':1},level=30)
    assert original.actor.base_stats['dodge_chance']==pytest.approx(.10)
    assert changed.actor.base_stats['dodge_chance']==pytest.approx(.11)
    rage=next(r for r in changed.resources if r.id=='rage')
    assert len(rage.event_gain_rules)==1
    rule=rage.event_gain_rules[0]
    assert rule.event_kind=='incoming_dodge'
    assert rule.event_value_field=='dodge_probability'
    assert rule.multiplier==pytest.approx(1.) # 20% proc * 5 rage
    assert len(application.applied_modifiers)==2


def test_expected_dodge_proc_is_paid_through_real_incoming_resource_events():
    changed,_=apply_talent_selection(_slice(),{'test_avoidance':1},level=30)
    rt=_runtime(changed)
    payload=rt.resolve_incoming_attack(_attack())
    assert payload['dodge_probability']==pytest.approx(.11)
    assert payload['health_damage_applied']==pytest.approx(8.9)
    assert rt.actor.resources['rage']==pytest.approx(.11)
    assert any(e.kind=='ResourceEventGain' for e in rt.trace)
    # Dodge is physical-only. The same talent never generates rage from magic.
    rt2=_runtime(changed)
    payload2=rt2.resolve_incoming_attack(_attack('nature'))
    assert payload2['dodge_probability']==0.
    assert rt2.actor.resources['rage']==0.


def test_missing_source_proc_facts_fail_atomically():
    ir=_slice()
    bad=replace(ir.talents[0].ranks[0].modifiers[1],provenance={'url':SOURCE})
    rank=replace(ir.talents[0].ranks[0],modifiers=(ir.talents[0].ranks[0].modifiers[0],bad))
    talent=replace(ir.talents[0],ranks=(rank,))
    with pytest.raises(ValueError,match='AVOIDANCE_PROC_SOURCE_FACTS_REQUIRED'):
        apply_talent_selection(replace(ir,talents=(talent,)),{'test_avoidance':1},level=30)


def test_two_source_observations_compile_to_generic_avoidance_modifiers():
    from src.game.data.forever.source_rank_promotion import _compile_clause
    common={'source':SOURCE,'condition':'passive'}
    dodge=_compile_clause({**common,'domain':'dodge_bonus_pct',
        'target':'dodge_chance','sourced_value':1.},
        actions=set(),schools=set(),actor_stats={'dodge_chance'},build='1.60.1.70374')
    proc=_compile_clause({**common,'domain':'avoidance_resource_proc_chance_pct',
        'condition':'on_dodge','target':'rage','sourced_value':20.,
        'gain_amount':5.,'source_build_verified':False,
        'proc_distribution_verified':False},
        actions=set(),schools=set(),actor_stats={'dodge_chance'},build='1.60.1.70374')
    assert (dodge.kind,dodge.target_type,dodge.target_id,dodge.value)==(
        'actor_stat_flat','actor_stat','dodge_chance',pytest.approx(.01))
    assert (proc.kind,proc.target_type,proc.target_id,proc.value)==(
        'avoidance_resource_proc','resource','rage',pytest.approx(.20))
    assert proc.provenance['gain_amount']==5.
    assert proc.provenance['source_build_verified'] is False
    assert _compile_clause({**common,'domain':'avoidance_resource_proc_chance_pct',
        'condition':'on_dodge','target':'rage','sourced_value':20.},
        actions=set(),schools=set(),actor_stats={'dodge_chance'},
        build='1.60.1.70374') is None
