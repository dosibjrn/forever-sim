from src import game_context
from src.engine_registry import reset_engine_cache, get_engine
from src.rulesets.forever.classes.hunter import mechanics as hm


def _hunter():
    game_context.configure('forever', 'hunter')
    reset_engine_cache()
    return get_engine()


def _s(row):
    return float(row['total_s'])


def test_pet_family_damage_modifiers_change_real_score():
    e = _hunter(); t = e.Talents()
    cat = hm._ranged_profile(20, t, no_pet=False, pet_family='cat')
    bear = hm._ranged_profile(20, t, no_pet=False, pet_family='bear')
    assert cat['pet_family_damage_mult'] == 1.10
    assert bear['pet_family_damage_mult'] == 0.91
    assert cat['pet_raw_dps'] > bear['pet_raw_dps']
    assert _s(cat) < _s(bear)


def test_pet_uptime_is_not_display_only_and_bm_synergy_changes_it():
    e = _hunter()
    base = hm._ranged_profile(20, e.Talents(), no_pet=False, pet_family='cat')
    durable = hm._ranged_profile(20, e.Talents(endurance_training=5, improved_revive_pet=2, bestial_swiftness=1), no_pet=False, pet_family='cat')
    assert 0.0 < base['pet_uptime'] < 1.0
    assert durable['pet_uptime'] > base['pet_uptime']
    assert durable['pet_expected_revive_s'] < base['pet_expected_revive_s']
    assert _s(durable) < _s(base)


def test_bm_damage_talents_reach_pet_and_owner_scorer():
    e = _hunter()
    base = hm._ranged_profile(20, e.Talents(), no_pet=False, pet_family='cat')
    ff = hm._ranged_profile(20, e.Talents(focused_fire=2), no_pet=False, pet_family='cat')
    uf = hm._ranged_profile(20, e.Talents(unleashed_fury=1), no_pet=False, pet_family='cat')
    da = hm._ranged_profile(20, e.Talents(deadly_aspects=5), no_pet=False, pet_family='cat')
    assert ff['hunter_dps'] > base['hunter_dps'] and ff['pet_raw_dps'] > base['pet_raw_dps']
    assert uf['pet_raw_dps'] > base['pet_raw_dps']
    assert da['quick_shots_uptime_ev'] > 0 and da['hunter_dps'] > base['hunter_dps']


def test_lone_wolf_vs_pet_is_a_real_alternative():
    e = _hunter(); t = e.Talents(lethal_attacks=5, careful_aim=5, lone_wolf=1)
    pet = hm._ranged_profile(20, t, no_pet=False, pet_family='cat')
    wolf = hm._ranged_profile(20, t, no_pet=True)
    assert pet['pet_dps'] > 0 and pet['pet_uptime'] > 0
    assert wolf['pet_dps'] == 0 and wolf['profile'] == 'lone_wolf_ranged'
    assert wolf['hunter_dps'] > pet['hunter_dps']
    assert _s(wolf) != _s(pet)


def test_auto_shot_and_ranged_weapon_dps_are_live_inputs():
    e = _hunter(); t = e.Talents()
    base = e.experimental_level_score(20, t, 'all')
    token = hm._GEAR_PROBE.set({'weapon_dps': 5.0})
    try:
        stronger = e.experimental_level_score(20, t, 'all')
    finally:
        hm._GEAR_PROBE.reset(token)
    assert stronger['hunter_dps'] > base['hunter_dps']
    assert _s(stronger) < _s(base)


def test_mana_recovery_and_resource_stat_weights_are_live():
    e = _hunter(); t = e.Talents(lethal_attacks=5, careful_aim=5, lone_wolf=1)
    base = e.experimental_level_score(20, t, 'all')
    sw = e.marginal_stat_weights(20, t, 'all', base)['stats']
    assert base['mana_deficit_per_mob'] > 0 and base['drink_s_per_mob'] > 0
    for stat in ('intellect', 'spirit', 'mp5', 'agility', 'weapon_dps'):
        assert float(sw[stat]['seconds_saved_per_100_per_point']) > 0
    # Stamina is survival capacity, not guaranteed throughput. Under concurrent
    # food+water recovery it is legitimately zero when mana is the bottleneck.
    assert float(sw['stamina']['seconds_saved_per_100_per_point']) >= 0


def test_mm_active_talents_change_score_in_expected_direction():
    e = _hunter(); base = hm._ranged_profile(20, e.Talents(), no_pet=False, pet_family='cat')
    variants = [
        e.Talents(lethal_attacks=1), e.Talents(improved_stings=1), e.Talents(efficiency=1),
        e.Talents(careful_aim=1), e.Talents(rapid_killing=1), e.Talents(improved_arcane_shot=1),
    ]
    for t in variants:
        assert _s(hm._ranged_profile(20, t, no_pet=False, pet_family='cat')) != _s(base)


def test_survival_active_talents_change_score_and_policy_inactive_are_explicit():
    e = _hunter(); base = hm._ranged_profile(20, e.Talents(), no_pet=False, pet_family='cat')
    # Damage/hit talents improve total cycle time directly.
    for t in (e.Talents(improved_tracking=1), e.Talents(surefooted=1)):
        assert _s(hm._ranged_profile(20, t, no_pet=False, pet_family='cat')) < _s(base)
    # Avoidance remains a live HP-recovery input even when concurrent water is
    # the cycle bottleneck, so it may reduce food time without changing total.
    for t in (e.Talents(deflection=1), e.Talents(deterrence=1)):
        row=hm._ranged_profile(20, t, no_pet=False, pet_family='cat')
        assert row['food_s_per_mob'] < base['food_s_per_mob']
        assert _s(row) <= _s(base)
    # Survivalist increases capacity/survival margin; max HP alone does not erase
    # damage already taken and therefore need not create fake throughput.
    surv=hm._ranged_profile(20, e.Talents(survivalist=1), no_pet=False, pet_family='cat')
    assert surv['player_hp'] > base['player_hp']
    assert _s(surv) == _s(base)
    inert = hm._ranged_profile(20, e.Talents(entrapment=1, savage_strikes=1, improved_wing_clip=1), no_pet=False, pet_family='cat')
    joined = ' | '.join(inert['inactive_talent_effects'])
    assert 'entrapment' in joined and 'savage_strikes' in joined and 'improved_wing_clip' in joined
