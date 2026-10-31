"""A sourced spell-critical haste proc must use the same sampled damage outcome.

The synthetic action checks generic event semantics, not a Forever rank fact.
"""
import pytest
from src.game.model.ir import ActorDefinition, ActionDefinition, DamageEffect
from src.game.runtime import ActorState, CombatRuntime, TargetState

SOURCE='https://theforeverera.com/en/talents/druid/natures-grace/'


def _trial(*, seed=7, sourced=True, school='nature', crit=.4):
    rule={'event_kind':'nonperiodic_spell_crit','cast_speed_fraction':.2,
          'gcd_reduction_fraction':.2,'duration_s':3.,
          'source':{'source_url':SOURCE,'source_build':'1.60.1.70338'}}
    actor=ActorDefinition(id='player',actor_type='player',
        metadata={'source_timed_spell_crit_haste':rule} if sourced else {})
    action=ActionDefinition(id='spell',family_key='spell',name='Spell',
        owner_actor_id='player',requirements=(),costs=(),cast_time_s=0.,
        gcd_s=0.,cooldown_s=0.,provenance=(),effects=(DamageEffect(effect_type='damage',
            school=school,target='enemy',base_min=20.,base_max=20.,
            crit_chance_bonus=crit,crit_multiplier=2.),))
    rt=CombatRuntime(actor=ActorState.from_ir(actor,()),
        target=TargetState.with_health('mob',1e7),sampling_seed=seed)
    for i in range(40):
        rt.advance_to(float(i)+1.)
        rt.schedule_action(action)
        rt.advance_to(float(i)+1.001)
    damage=[e for e in rt.trace if e.kind=='Damage' and e.action_id=='spell']
    haste=[e for e in rt.trace if e.kind=='TimedSpellCritHasteGranted']
    return rt,damage,haste


def test_sourced_spell_crit_haste_is_joint_discrete_and_damage_correlated():
    rt,damage,haste=_trial()
    assert len(damage)==40
    assert all(e.payload.get('sampled_outcome') in ('hit','crit') for e in damage)
    assert all(e.payload['amount']==pytest.approx(
        40. if e.payload['sampled_outcome']=='crit' else 20.) for e in damage)
    assert 0<len(haste)<40
    assert len(haste)==sum(e.payload['sampled_outcome']=='crit' for e in damage)
    assert all(h.payload['sampled_critical_count']==1 for h in haste)
    assert rt.total_damage==pytest.approx(sum(e.payload['amount'] for e in damage))


def test_joint_spell_crit_is_seeded_and_repeatable():
    _,d1,h1=_trial(seed=17)
    _,d2,h2=_trial(seed=17)
    _,d3,h3=_trial(seed=18)
    a=lambda events:[e.payload.get('sampled_outcome') for e in events]
    assert a(d1)==a(d2)
    assert a(d1)!=a(d3)
    assert len(h1)==len(h2)


def test_without_source_haste_rule_magic_spell_stays_expected_value():
    _,damage,haste=_trial(sourced=False)
    assert len(damage)==40 and not haste
    assert all(e.payload['amount']==pytest.approx(28.) for e in damage)
    assert all('sampled_outcome' not in e.payload for e in damage)


def test_physical_spell_not_sampled_by_spell_crit_haste_rule():
    _,damage,haste=_trial(school='physical')
    assert len(damage)==40 and not haste
    assert all('sampled_outcome' not in e.payload for e in damage)


def test_magic_ranged_autoattack_is_not_a_spell_crit_haste_trigger():
    from src.game.model.ir import AutoAttackDefinition,AutoAttackDamageSource
    rule={'event_kind':'nonperiodic_spell_crit','cast_speed_fraction':.2,
          'gcd_reduction_fraction':.2,'duration_s':3.,
          'source':{'source_url':SOURCE,'source_build':'1.60.1.70338'}}
    actor=ActorDefinition(id='player',actor_type='player',
        metadata={'source_timed_spell_crit_haste':rule})
    auto=AutoAttackDefinition(id='wand',name='Wand',owner_actor_id='player',
        attack_type='ranged',swing_time_s=1.,school='arcane',
        damage_source=AutoAttackDamageSource(kind='flat',flat_dps=20.),
        hit_chance=1.,crit_chance_on_landed_hit=.5,crit_multiplier=2.)
    rt=CombatRuntime(actor=ActorState.from_ir(actor,()),
        target=TargetState.with_health('mob',1e7),auto_attacks=(auto,),sampling_seed=7)
    rt.advance_to(40.)
    damage=[e for e in rt.trace if e.kind=='Damage' and e.payload.get('auto_attack')]
    assert len(damage)==40
    assert all('sampled_outcome' not in e.payload for e in damage)
    assert not any(e.kind=='TimedSpellCritHasteGranted' for e in rt.trace)
