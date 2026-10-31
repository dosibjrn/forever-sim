from src import game_context
from src.engine_registry import reset_engine_cache, get_engine
from src.rulesets.forever.classes.hunter import mechanics as hm
from src.rulesets.forever.classes.hunter.talents import Talents, legal_add


def _hunter():
    game_context.configure('forever','hunter')
    reset_engine_cache()
    return get_engine()


def test_mm_l21_l40_roster_and_prerequisites_are_source_backed():
    # 15-point row: Trueshot Aura is open; Mortal Shots additionally needs max Careful Aim.
    t15 = Talents(lethal_attacks=5, efficiency=5, careful_aim=5)
    assert t15.points() == 15
    assert legal_add(t15, 'trueshot_aura')
    assert legal_add(t15, 'mortal_shots')
    no_careful = Talents(lethal_attacks=5, efficiency=5, improved_stings=3, rapid_killing=2)
    assert no_careful.points() == 15
    assert not legal_add(no_careful, 'mortal_shots')

    # 20-point row: Rapid Recuperation needs max Rapid Killing; Barrage/Scatter only row gate.
    t20 = Talents(lethal_attacks=5, efficiency=5, careful_aim=5, mortal_shots=3, rapid_killing=2)
    assert t20.points() == 20
    assert legal_add(t20, 'rapid_recuperation')
    assert legal_add(t20, 'barrage')
    assert legal_add(t20, 'scatter_shot')

    # 25-point row and L40 capstone.
    t25 = Talents(lethal_attacks=5, efficiency=5, careful_aim=5, mortal_shots=5, rapid_killing=2, trueshot_aura=1, barrage=2)
    assert t25.points() == 25
    assert legal_add(t25, 'ranged_weapon_specialization')
    t30 = Talents(lethal_attacks=5, efficiency=5, careful_aim=5, mortal_shots=5, rapid_killing=2, trueshot_aura=1, barrage=3, ranged_weapon_specialization=4)
    assert t30.points() == 30
    assert legal_add(t30, 'sniper_shot')


def test_trueshot_and_mortal_shots_raise_ranged_output():
    e = _hunter()
    base = hm._ranged_profile(30, e.Talents(lone_wolf=1), no_pet=True)
    tsa = hm._ranged_profile(30, e.Talents(lone_wolf=1, trueshot_aura=1), no_pet=True)
    mortal = hm._ranged_profile(30, e.Talents(lone_wolf=1, mortal_shots=5), no_pet=True)
    assert tsa['trueshot_aura_rap'] == 30.0
    assert tsa['hunter_dps'] > base['hunter_dps']
    assert abs(mortal['mortal_shots_crit_bonus'] - 0.30) < 1e-12
    assert mortal['hunter_dps'] > base['hunter_dps']


def test_rapid_recuperation_restores_combat_spirit_regen_fraction():
    e = _hunter()
    base = hm._ranged_profile(35, e.Talents(rapid_killing=2), no_pet=True)
    rr1 = hm._ranged_profile(35, e.Talents(rapid_killing=2, rapid_recuperation=1), no_pet=True)
    rr2 = hm._ranged_profile(35, e.Talents(rapid_killing=2, rapid_recuperation=2), no_pet=True)
    assert abs(rr1['rapid_recuperation_combat_regen_fraction'] - 0.50) < 1e-12
    assert abs(rr2['rapid_recuperation_combat_regen_fraction'] - 1.00) < 1e-12
    assert rr1['combat_mana_regen_per_s'] > base['combat_mana_regen_per_s']
    assert rr2['combat_mana_regen_per_s'] > rr1['combat_mana_regen_per_s']


def test_barrage_ranged_specialization_and_sniper_are_real_scorer_inputs():
    e = _hunter()
    base30 = hm._ranged_profile(30, e.Talents(lone_wolf=1), no_pet=True)
    barrage30 = hm._ranged_profile(30, e.Talents(lone_wolf=1, barrage=3), no_pet=True)
    assert abs(barrage30['barrage_aimed_damage_mult'] - 1.10) < 1e-12
    assert barrage30['hunter_dps'] > base30['hunter_dps']

    base40 = hm._ranged_profile(40, e.Talents(lone_wolf=1), no_pet=True)
    rws40 = hm._ranged_profile(40, e.Talents(lone_wolf=1, ranged_weapon_specialization=5), no_pet=True)
    sniper40 = hm._ranged_profile(40, e.Talents(lone_wolf=1, trueshot_aura=1, sniper_shot=1), no_pet=True)
    assert abs(rws40['ranged_weapon_specialization_mult'] - 1.05) < 1e-12
    assert rws40['hunter_dps'] > base40['hunter_dps']
    assert sniper40['sniper_shot_damage'] > 0
    assert sniper40['sniper_shot_dps'] > 0
    assert sniper40['sniper_shot_mana_per_s'] > 0
    assert sniper40['hunter_dps'] > base40['hunter_dps']


def test_scatter_shot_is_explicit_utility_not_fake_dps():
    e = _hunter()
    base = hm._ranged_profile(35, e.Talents(lone_wolf=1), no_pet=True)
    scatter = hm._ranged_profile(35, e.Talents(lone_wolf=1, scatter_shot=1), no_pet=True)
    assert abs(scatter['hunter_dps'] - base['hunter_dps']) < 1e-12
    assert any('scatter_shot' in x for x in scatter['inactive_talent_effects'])


def test_global_cap_stays_l20_until_survival_and_pet_focus_are_brought_forward():
    e = _hunter()
    assert e.VERIFIED_LEVEL_CAP == 20
    row = e.experimental_level_score(40, e.Talents(lone_wolf=1, trueshot_aura=1, sniper_shot=1), 'marksmanship')
    assert row['post20_fallback'] == 'hunter_l21_l40_planning_range_source_backed_bounded'
