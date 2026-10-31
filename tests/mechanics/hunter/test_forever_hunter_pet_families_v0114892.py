from src.rulesets.forever.classes.hunter import mechanics as hm
from src.rulesets.forever.classes.hunter.pets import (
    PET_FAMILIES, capability_payload, latest_damage_rank, modeled_damage_skills,
)
from src.rulesets.forever.classes.hunter.talents import Talents


def test_family_capability_table_matches_forever_family_damage_skills():
    expected = {
        'cat': {'bite', 'claw'},
        'raptor': {'bite', 'claw'},
        'wind_serpent': {'bite', 'lightning_breath'},
        'spider': {'bite'},
        'wolf': {'bite'},
        'bear': {'bite', 'claw'},
        'boar': {'bite'},
        'turtle': {'bite'},
    }
    assert set(PET_FAMILIES) == set(expected)
    for family, skills in expected.items():
        modeled = {x['skill'] for x in modeled_damage_skills(family, 40)}
        assert modeled == skills


def test_source_backed_l24_l40_pet_damage_rank_legality():
    assert latest_damage_rank('bite', 23) is None
    assert latest_damage_rank('bite', 24)['damage'] == 34.0
    assert latest_damage_rank('bite', 32)['damage'] == 44.0
    assert latest_damage_rank('bite', 40)['damage'] == 54.0
    assert latest_damage_rank('claw', 24)['damage'] == 19.0
    assert latest_damage_rank('claw', 40)['damage'] == 31.0
    assert latest_damage_rank('lightning_breath', 23) is None
    assert latest_damage_rank('lightning_breath', 24)['damage'] == 38.5
    assert latest_damage_rank('lightning_breath', 36)['damage'] == 56.5


def test_family_capability_payload_keeps_unpriced_specials_explicit():
    boar = capability_payload('boar', 24)
    turtle = capability_payload('turtle', 24)
    cat = capability_payload('cat', 30)
    assert any(x['skill'] == 'charge' and not x['modeled'] for x in boar['available_utility_skills'])
    assert any(x['skill'] == 'shell_shield' and not x['modeled'] for x in turtle['available_utility_skills'])
    assert any(x['skill'] == 'prowl' and not x['modeled'] for x in cat['available_utility_skills'])


def test_real_scorer_exposes_only_family_legal_damage_skills():
    t = Talents()
    cat = hm._ranged_profile(40, t, no_pet=False, pet_family='cat')
    wind = hm._ranged_profile(40, t, no_pet=False, pet_family='wind_serpent')
    spider = hm._ranged_profile(40, t, no_pet=False, pet_family='spider')
    assert set(cat['pet_modeled_damage_skills']) == {'bite', 'claw'}
    assert set(wind['pet_modeled_damage_skills']) == {'bite', 'lightning_breath'}
    assert set(spider['pet_modeled_damage_skills']) == {'bite'}
    assert 'claw' not in wind['pet_skill_casts_per_s']
    assert 'claw' not in spider['pet_skill_casts_per_s']


def test_family_skill_availability_changes_real_scorer_when_focus_can_use_filler(monkeypatch):
    # Controlled scorer fixture: increase regen so Bite reaches its cooldown cap
    # and a legal filler can consume the remainder.  This proves the actual
    # scorer consults family capability rather than a display-only table.
    monkeypatch.setattr(hm, 'PET_BASE_FOCUS_REGEN_PER_S', 10.0)
    t = Talents()
    cat = hm._ranged_profile(32, t, no_pet=False, pet_family='cat')
    spider = hm._ranged_profile(32, t, no_pet=False, pet_family='spider')
    assert cat['pet_claw_casts_per_s'] > 0.0
    assert spider['pet_claw_casts_per_s'] == 0.0
    assert cat['pet_active_skill_dps'] > spider['pet_active_skill_dps']


def test_focus_budget_never_overspends_with_family_scheduler():
    for family in PET_FAMILIES:
        row = hm._ranged_profile(40, Talents(bestial_discipline=2), no_pet=False, pet_family=family)
        spent = 0.0
        ranks = {x['skill']: x for x in modeled_damage_skills(family, 40)}
        for skill, rate in row['pet_skill_casts_per_s'].items():
            spent += float(rate) * float(ranks[skill]['focus'])
        assert spent <= row['pet_damage_focus_per_s'] + 1e-12
        assert sum(row['pet_skill_casts_per_s'].values()) <= (1.0 / 1.5) + 1e-12


def test_l20_behavioral_contract_still_has_no_active_skill_damage():
    for family in PET_FAMILIES:
        row = hm._ranged_profile(20, Talents(), no_pet=False, pet_family=family)
        assert row['pet_active_skill_dps'] == 0.0
        assert row['pet_skill_casts_per_s'] == {}
        assert row['pet_modeled_damage_skills'] == []
