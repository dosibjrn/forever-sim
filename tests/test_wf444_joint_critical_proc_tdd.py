"""RED: source-typed critical resource proc must share a sampled hit/crit event.

Synthetic GameIR isolates the generic mechanism; no class, talent or item facts
are invented or treated as Forever source coverage.
"""
from dataclasses import replace
import pytest
from src.game.model.ir import (ActorDefinition, AutoAttackDamageSource,
    AutoAttackDefinition, GameIRSlice, ModeDefinition, ModeResourceRule,
    ResourceDefinition, ResourceEventGainRule, TalentDefinition,
    TalentRankDefinition, TalentModifier)
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.game.talents import apply_talent_selection

SOURCE='https://theforeverera.com/en/talents/druid/blood-frenzy/'


def _setup(*, sampled=True, seed=7, hit=.8, crit=.3, proc=1.):
    actor=ActorDefinition(id='player',actor_type='player')
    rule=ResourceEventGainRule(id='sourced_crit_resource',
        event_kind='nonperiodic_melee_critical',
        event_value_field=('sampled_critical_count' if sampled else 'expected_critical_count'),
        multiplier=(5. if sampled else 5.*proc),required_mode_id='form',
        metadata=({'resolution':'sampled_joint_critical','proc_probability':proc}
                  if sampled else {'expected_value_semantics':'legacy'}),
        provenance=({'url':SOURCE,'source_build':'1.60.1.70338'},))
    resource=ResourceDefinition(id='rage',name='Rage',owner_actor_id='player',
        initial_amount=0.,capacity=10000.,event_gain_rules=(rule,))
    modes=(ModeDefinition(id='form',label='Form',initial=True,
        resource_rules=(ModeResourceRule(resource_id='rage',active=True),)),)
    attack=AutoAttackDefinition(id='auto',name='Auto',owner_actor_id='player',
        attack_type='melee',swing_time_s=2.,school='physical',
        damage_source=AutoAttackDamageSource(kind='flat',flat_dps=10.),
        hit_chance=hit,crit_chance_on_landed_hit=crit,crit_multiplier=2.,
        required_mode_id='form')
    runtime=CombatRuntime(actor=ActorState.from_ir(actor,(resource,),modes),
        target=TargetState.with_health('mob',1e7),auto_attacks=(attack,),
        sampling_seed=seed)
    runtime.advance_to(80.)
    damages=[e for e in runtime.trace if e.kind=='Damage' and e.payload.get('auto_attack')]
    gains=[e for e in runtime.trace if e.kind=='ResourceEventGain' and
           e.payload.get('rule_id')=='sourced_crit_resource']
    return runtime,damages,gains


def test_joint_critical_proc_real_combat_no_fractional_resource_or_damage():
    rt,damages,gains=_setup()
    assert len(damages)==40
    outcomes=[e.payload['sampled_outcome'] for e in damages]
    assert {'miss','hit','crit'}<=set(outcomes)
    assert all(e.payload['amount']==pytest.approx(
        {'miss':0.,'hit':20.,'crit':40.}[e.payload['sampled_outcome']])
        for e in damages)
    assert len(gains)==outcomes.count('crit')
    assert all(e.payload['requested_gain']==5. for e in gains)
    assert rt.actor.resources['rage']==5.*outcomes.count('crit')
    assert rt.total_damage==pytest.approx(sum(e.payload['amount'] for e in damages))


def test_joint_proc_seed_reproducibility_and_non_guaranteed_proc():
    first,damage1,gain1=_setup(seed=11,proc=.4)
    second,damage2,gain2=_setup(seed=11,proc=.4)
    third,damage3,gain3=_setup(seed=12,proc=.4)
    assert [e.payload['sampled_outcome'] for e in damage1]==[
        e.payload['sampled_outcome'] for e in damage2]
    assert [e.payload['sampled_outcome'] for e in damage1]!=[
        e.payload['sampled_outcome'] for e in damage3]
    assert len(gain1)==len(gain2)
    assert 0<len(gain1)<sum(e.payload['sampled_outcome']=='crit' for e in damage1)
    assert all(e.payload['requested_gain']==5. for e in gain1)
    assert all(e.payload['sampled_outcome']!='miss' or
        not e.payload['sampled_critical_count'] for e in damage1)


def test_expected_value_existing_rule_remains_exactly_unchanged():
    rt,damages,gains=_setup(sampled=False)
    assert len(damages)==40
    assert all(e.payload['amount']==pytest.approx(20.*(.8*.7+.8*.3*2.))
               for e in damages)
    assert len(gains)==40
    assert all(e.payload['requested_gain']==pytest.approx(.8*.3*5.) for e in gains)
    assert all('sampled_outcome' not in e.payload for e in damages)


def test_source_critical_modifier_compiles_discrete_rule_not_fractional():
    actor=ActorDefinition(id='player',actor_type='player')
    talent=TalentDefinition(id='sourced',name='Sourced',tree_key='test',max_rank=1,
        ranks=(TalentRankDefinition(rank=1,modifiers=(TalentModifier(
            kind='critical_resource_gain',target_type='resource',target_id='rage',
            value=.4,provenance={'source_url':SOURCE,'source_build':'1.60.1.70338',
                'resource_amount_source_build':'1.60.1.70374',
                'required_mode_id':'form','bonus_resource_amount':5.,
                'requires_resource_generator':False}),)),),metadata={'row':0})
    ir=GameIRSlice(id='test',ruleset='test',actor=actor,actions=(),
        resources=(ResourceDefinition(id='rage',name='Rage',owner_actor_id='player',
                                     initial_amount=0.,capacity=100.),),
        modes=(ModeDefinition(id='form',label='Form',initial=True),),talents=(talent,))
    changed,_=apply_talent_selection(ir,{'sourced':1},level=30)
    rule=changed.resources[0].event_gain_rules[0]
    assert rule.metadata['resolution']=='sampled_joint_critical'
    assert rule.metadata['proc_probability']==pytest.approx(.4)
    assert rule.event_value_field=='sampled_critical_count'
    assert rule.multiplier==pytest.approx(5.)


def test_joint_cat_generator_direct_physical_damage_and_extra_combo():
    from src.game.model.ir import ActionDefinition, DamageEffect, ResourceChangeEffect
    actor=ActorDefinition(id='player',actor_type='player')
    rule=ResourceEventGainRule(id='source_combo_crit',
        event_kind='nonperiodic_melee_critical',
        event_value_field='sampled_critical_count',multiplier=1.,
        required_mode_id='form',filters={'required_generated_resource':'combo'},
        metadata={'resolution':'sampled_joint_critical','proc_probability':1.},
        provenance=({'url':SOURCE,'source_build':'1.60.1.70338'},))
    resource=ResourceDefinition(id='combo',name='Combo',owner_actor_id='player',
        initial_amount=0.,capacity=1000.,event_gain_rules=(rule,))
    modes=(ModeDefinition(id='form',label='Form',initial=True,
        resource_rules=(ModeResourceRule(resource_id='combo',active=True),)),)
    attack=ActionDefinition(id='strike',family_key='strike',name='Strike',
        owner_actor_id='player',requirements=(),costs=(),cast_time_s=0.,
        gcd_s=0.,cooldown_s=0.,provenance=(),effects=(
            DamageEffect(effect_type='damage',school='physical',target='enemy',
                         base_min=20.,base_max=20.,crit_chance_bonus=.5,crit_multiplier=2.),
            ResourceChangeEffect(effect_type='resource_change',resource_id='combo',
                                 target='self',operation='add',amount=1.),
        ))
    rt=CombatRuntime(actor=ActorState.from_ir(actor,(resource,),modes),
        target=TargetState.with_health('mob',1e7),sampling_seed=7)
    for i in range(40):
        rt.advance_to(i+1.)
        rt.schedule_action(attack)
        rt.advance_to(i+1.+.001)
    damage=[e for e in rt.trace if e.kind=='Damage' and e.action_id=='strike']
    proc=[e for e in rt.trace if e.kind=='ResourceEventGain' and
          e.payload.get('rule_id')=='source_combo_crit']
    assert len(damage)==40
    assert {'hit','crit'}<=set(e.payload['sampled_outcome'] for e in damage)
    assert all(e.payload['amount']==pytest.approx(
        {'hit':20.,'crit':40.}[e.payload['sampled_outcome']]) for e in damage)
    assert len(proc)==sum(e.payload['sampled_outcome']=='crit' for e in damage)
    assert all(e.payload['requested_gain']==1. for e in proc)
    assert rt.actor.resources['combo']==40+len(proc)
