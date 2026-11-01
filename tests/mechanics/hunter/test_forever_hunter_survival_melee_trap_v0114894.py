from src.rulesets.forever.classes.hunter import mechanics as hm
from src.rulesets.forever.classes.hunter.talents import Talents


def survival_core(**kw):
    base=dict(improved_tracking=5,savage_strikes=2,clever_traps=2,surefooted=3,predators_edge=5,resourcefulness=2,expose_prey=2,survivalists_discipline=2)
    base.update(kw)
    return Talents(**base)


def test_survival_profile_competes_ranged_and_melee_without_permutation_search():
    row=hm._score(40,survival_core(lightning_reflexes=5,lacerating_strikes=1),'survival')
    assert row['profile'] in {'pet_ranged','survival_melee_trap'}
    if row['profile']=='survival_melee_trap':
        assert row['policy']=='survival_melee_trap_bounded'
        assert row['combat_profile']=='melee'
        assert 'Raptor Strike' in row['rotation']


def test_clever_traps_and_survivalists_discipline_only_improve_melee_trap_candidate():
    plain=hm._survival_melee_profile(36,survival_core(clever_traps=0,survivalists_discipline=0),pet_family='cat')
    tuned=hm._survival_melee_profile(36,survival_core(clever_traps=2,survivalists_discipline=2),pet_family='cat')
    assert tuned['survival_trap_damage_per_cast'] > plain['survival_trap_damage_per_cast']
    assert tuned['survival_trap_cooldown_s'] < plain['survival_trap_cooldown_s']
    ranged_plain=hm._ranged_profile(36,survival_core(clever_traps=0,survivalists_discipline=0),no_pet=False,pet_family='cat')
    ranged_tuned=hm._ranged_profile(36,survival_core(clever_traps=2,survivalists_discipline=2),no_pet=False,pet_family='cat')
    assert ranged_tuned['hunter_dps'] == ranged_plain['hunter_dps']


def test_expose_prey_enables_bounded_mongoose_and_lacerating_adds_only_bleed():
    no_expose=hm._survival_melee_profile(40,survival_core(expose_prey=0,lacerating_strikes=0),pet_family='cat')
    expose=hm._survival_melee_profile(40,survival_core(expose_prey=2,lacerating_strikes=0),pet_family='cat')
    bleed=hm._survival_melee_profile(40,survival_core(expose_prey=2,lacerating_strikes=1),pet_family='cat')
    assert no_expose['survival_mongoose_dps'] == 0
    assert expose['survival_mongoose_dps'] > 0
    assert expose['survival_lacerating_dps'] == 0
    assert bleed['survival_lacerating_dps'] > 0


def test_resourcefulness_reduces_melee_trap_mana_cost():
    zero=hm._survival_melee_profile(36,survival_core(resourcefulness=0),pet_family='cat')
    two=hm._survival_melee_profile(36,survival_core(resourcefulness=2),pet_family='cat')
    assert two['mana_spent_per_mob'] < zero['mana_spent_per_mob']


def test_unpinned_counterattack_and_strider_kick_fail_closed():
    row=hm._survival_melee_profile(40,survival_core(counterattack=1,strider_kick=1),pet_family='cat')
    inactive=' | '.join(row['inactive_talent_effects'])
    assert 'counterattack:' in inactive
    assert 'strider_kick:' in inactive
