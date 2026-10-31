from src.rulesets.forever.classes.hunter import mechanics as hm
from src.rulesets.forever.classes.hunter.talents import Talents


def test_pet_active_skills_start_post20_without_changing_l20_baseline():
    l20 = hm._ranged_profile(20, Talents(), no_pet=False, pet_family='cat')
    l24 = hm._ranged_profile(24, Talents(), no_pet=False, pet_family='cat')
    assert l20['pet_active_skill_dps'] == 0.0
    assert l24['pet_active_skill_dps'] > 0.0
    assert l24['pet_bite_casts_per_s'] > 0.0


def test_bestial_discipline_increases_focus_budget_and_pet_damage():
    base = hm._ranged_profile(32, Talents(), no_pet=False, pet_family='cat')
    bd2 = hm._ranged_profile(32, Talents(bestial_discipline=2), no_pet=False, pet_family='cat')
    assert bd2['pet_focus_regen_per_s'] > base['pet_focus_regen_per_s']
    assert bd2['pet_damage_focus_per_s'] > base['pet_damage_focus_per_s']
    assert bd2['pet_active_skill_dps'] > base['pet_active_skill_dps']
    assert bd2['pet_raw_dps'] > base['pet_raw_dps']


def test_bestial_discipline_also_preserves_hunter_spirit_regen():
    base = hm._ranged_profile(32, Talents(), no_pet=False, pet_family='cat')
    bd1 = hm._ranged_profile(32, Talents(bestial_discipline=1), no_pet=False, pet_family='cat')
    bd2 = hm._ranged_profile(32, Talents(bestial_discipline=2), no_pet=False, pet_family='cat')
    assert bd1['bestial_discipline_combat_regen_fraction'] == 0.25
    assert bd2['bestial_discipline_combat_regen_fraction'] == 0.50
    assert bd2['combat_mana_regen_per_s'] >= bd1['combat_mana_regen_per_s'] > base['combat_mana_regen_per_s']


def test_focus_policy_reserves_growl_and_obeys_pet_gcd():
    row = hm._ranged_profile(40, Talents(bestial_discipline=2), no_pet=False, pet_family='cat')
    assert row['pet_focus_regen_per_s'] == 6.0
    assert row['pet_damage_focus_per_s'] == 3.0
    assert row['pet_bite_casts_per_s'] + row['pet_claw_casts_per_s'] <= (1.0 / 1.5) + 1e-12
    spent = row['pet_bite_casts_per_s'] * 35.0 + row['pet_claw_casts_per_s'] * 25.0
    assert spent <= row['pet_damage_focus_per_s'] + 1e-12


def test_bestial_discipline_no_longer_reported_inactive():
    row = hm._ranged_profile(35, Talents(bestial_discipline=2), no_pet=False, pet_family='cat')
    assert not any('bestial_discipline:' in x for x in row['inactive_talent_effects'])
