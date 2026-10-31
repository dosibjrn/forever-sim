from src import game_context
from src.engine_registry import reset_engine_cache, get_engine
from src.rulesets.forever.classes.hunter import mechanics as hm
from src.rulesets.forever.classes.hunter.talents import Talents, legal_add


def _hunter():
    game_context.configure('forever','hunter')
    reset_engine_cache()
    return get_engine()


def test_bm_l21_l40_roster_and_prerequisites_are_source_backed():
    # 15-point row opens at 15 spent.
    t15 = Talents(endurance_training=5, focused_fire=2, bestial_swiftness=1, unleashed_fury=5, deadly_aspects=2)
    assert t15.points() == 15
    assert legal_add(t15, 'ferocity')
    assert legal_add(t15, 'summon_hawk')

    # Intimidation requires both 20 points and Bestial Swiftness.
    no_swift = Talents(endurance_training=5, focused_fire=2, unleashed_fury=5, ferocity=5, improved_mend_pet=2, deadly_aspects=1)
    assert no_swift.points() == 20
    assert not legal_add(no_swift, 'intimidation')
    with_swift = Talents(endurance_training=5, focused_fire=2, bestial_swiftness=1, unleashed_fury=5, ferocity=5, improved_mend_pet=2)
    assert with_swift.points() == 20
    assert legal_add(with_swift, 'intimidation')

    # Frenzy requires max Ferocity; Bestial Wrath requires Intimidation.
    no_ferocity = Talents(endurance_training=5, focused_fire=2, bestial_swiftness=1, unleashed_fury=5, improved_mend_pet=2, spirit_bond=2, bestial_discipline=2, summon_hawk=1, deadly_aspects=5)
    assert no_ferocity.points() == 25
    assert not legal_add(no_ferocity, 'frenzy')
    bw_ready = Talents(endurance_training=5, focused_fire=2, bestial_swiftness=1, unleashed_fury=5, ferocity=5, improved_mend_pet=2, spirit_bond=2, intimidation=1, bestial_discipline=2, frenzy=5)
    assert bw_ready.points() == 30
    assert legal_add(bw_ready, 'bestial_wrath')


def test_ferocity_increases_effective_pet_crit_and_pet_damage():
    e = _hunter()
    base = hm._ranged_profile(30, e.Talents(), no_pet=False, pet_family='cat')
    feral = hm._ranged_profile(30, e.Talents(ferocity=5), no_pet=False, pet_family='cat')
    assert abs(feral['pet_effective_crit_chance'] - (base['pet_effective_crit_chance'] + 0.10)) < 1e-12
    assert feral['pet_raw_dps'] > base['pet_raw_dps']


def test_spirit_bond_reduces_player_recovery_pressure_with_pet():
    e = _hunter()
    base = hm._ranged_profile(35, e.Talents(), no_pet=False, pet_family='cat')
    bonded = hm._ranged_profile(35, e.Talents(spirit_bond=2), no_pet=False, pet_family='cat')
    assert bonded['spirit_bond_hps'] > 0
    assert bonded['resource_recovery_s_per_mob'] <= base['resource_recovery_s_per_mob']


def test_frenzy_and_bestial_wrath_credit_bounded_pet_expected_value():
    e = _hunter()
    base = hm._ranged_profile(40, e.Talents(), no_pet=False, pet_family='cat')
    frenzy = hm._ranged_profile(40, e.Talents(ferocity=5, frenzy=5), no_pet=False, pet_family='cat')
    wrath = hm._ranged_profile(40, e.Talents(bestial_wrath=1), no_pet=False, pet_family='cat')
    assert 0 < frenzy['frenzy_uptime_ev'] <= 1
    assert frenzy['pet_raw_dps'] > base['pet_raw_dps']
    assert abs(wrath['bestial_wrath_uptime_ev'] - 0.15) < 1e-12
    assert wrath['pet_raw_dps'] > base['pet_raw_dps']


def test_unmodeled_bm_effects_are_explicit_not_silently_credited():
    e = _hunter()
    row = hm._ranged_profile(35, e.Talents(improved_mend_pet=2, summon_hawk=1, intimidation=1, bestial_discipline=2), no_pet=False, pet_family='cat')
    inactive = ' | '.join(row['inactive_talent_effects'])
    assert 'improved_mend_pet' in inactive
    assert 'summon_hawk' in inactive
    assert 'intimidation' in inactive
    assert 'bestial_discipline' not in inactive
    assert row['bestial_discipline_combat_regen_fraction'] == 0.50
    assert row['pet_focus_regen_per_s'] > 5.0


def test_global_cap_stays_l20_until_mm_and_survival_are_brought_forward():
    e = _hunter()
    assert e.VERIFIED_LEVEL_CAP == 20
    row = e.experimental_level_score(40, e.Talents(ferocity=5, frenzy=5), 'beast_mastery')
    assert row['post20_fallback'] == 'hunter_l21_l40_planning_range_source_backed_bounded'
