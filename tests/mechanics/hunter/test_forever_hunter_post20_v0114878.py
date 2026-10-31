from src import game_context
from src.engine_registry import reset_engine_cache, get_engine
from src.rulesets.forever.classes.hunter import mechanics as hm


def _hunter():
    game_context.configure('forever','hunter')
    reset_engine_cache()
    return get_engine()


def test_forever_pet_inherits_player_stats_in_real_scorer():
    e=_hunter(); t=e.Talents()
    row=hm._ranged_profile(20,t,no_pet=False,pet_family='cat')
    assert row['pet_inherited_attack_power'] > 0
    assert row['pet_inherited_crit_chance'] == row['crit_chance']
    assert row['pet_inherited_health_from_stamina'] == 2.0 * row['gear_stats']['stamina']
    assert row['pet_inherited_armor'] == 0.30 * row['gear_stats']['armor']


def test_post20_fallback_advances_level_instead_of_freezing_l20():
    e=_hunter(); t=e.Talents(lethal_attacks=5,careful_aim=5,rapid_killing=1)
    r20=e.experimental_level_score(20,t,'marksmanship')
    r28=e.experimental_level_score(28,t,'marksmanship')
    assert r28['post20_fallback'] == 'hunter_l21_l40_planning_range_source_backed_bounded'
    assert r28['gear_stats']['slots'] != r20['gear_stats']['slots']
    assert r28['player_hp'] > r20['player_hp']
    assert r28['mana_pool'] > r20['mana_pool']


def test_post20_sourced_spell_ranks_are_consumed():
    assert hm._latest(hm.ARCANE_SHOT,28)[1:3] == (65.0,80.0)
    assert hm._latest(hm.ARCANE_SHOT,36)[1:3] == (94.0,105.0)
    assert hm._latest(hm.SERPENT_STING,26)[1:3] == (110.0,80.0)
    assert hm._latest(hm.SERPENT_STING,34)[1:3] == (170.0,115.0)
    assert hm._latest(hm.AIMED_SHOT,28)[1:3] == (34.0,115.0)
    assert hm._latest(hm.AIMED_SHOT,36)[1:3] == (55.0,160.0)
    assert hm._latest(hm.ASPECT_HAWK,28)[1] == 50.0
    assert hm._latest(hm.ASPECT_HAWK,38)[1] == 70.0


def test_verified_cap_stays_l20_until_post20_talents_are_sourced():
    e=_hunter()
    assert e.VERIFIED_LEVEL_CAP == 20
