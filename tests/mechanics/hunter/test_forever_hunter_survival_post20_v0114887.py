from src.rulesets.forever.classes.hunter import mechanics as hm
from src.rulesets.forever.classes.hunter.talents import Talents, TALENT_RULES, legal_add


def test_survival_l21_l40_roster_and_prereqs_are_source_backed():
    expected = {
        'survival_tactics': ('survival',2,15,None),
        'predators_edge': ('survival',5,15,None),
        'counterattack': ('survival',1,15,('deterrence',1)),
        'resourcefulness': ('survival',2,20,None),
        'expose_prey': ('survival',2,20,None),
        'survivalists_discipline': ('survival',2,20,None),
        'strider_kick': ('survival',1,20,None),
        'lightning_reflexes': ('survival',5,25,None),
        'lacerating_strikes': ('survival',1,30,('expose_prey',2)),
    }
    for name, rule in expected.items(): assert TALENT_RULES[name] == rule
    base = Talents(deflection=5, survivalist=5, surefooted=3, deterrence=1, survival_tactics=2)
    assert legal_add(base, 'counterattack')
    assert not legal_add(base, 'lacerating_strikes')


def test_lightning_reflexes_changes_real_ranged_stats():
    base = hm._ranged_profile(35, Talents(), no_pet=False)
    lr = hm._ranged_profile(35, Talents(lightning_reflexes=5), no_pet=False)
    assert lr['effective_agility'] > base['effective_agility']
    assert lr['hunter_dps'] > base['hunter_dps']


def test_resourcefulness_and_discipline_have_bounded_effects():
    base = hm._ranged_profile(35, Talents(deterrence=1), no_pet=False)
    r = hm._ranged_profile(35, Talents(deterrence=1, resourcefulness=2, survivalists_discipline=2), no_pet=False)
    assert r['resourcefulness_uptime_ev'] > 0
    assert r['combat_mana_regen_per_s'] >= base['combat_mana_regen_per_s']
    assert r['incoming_damage'] <= base['incoming_damage']


def test_melee_survival_effects_are_explicitly_deferred_not_faked():
    t=Talents(survival_tactics=2,predators_edge=5,counterattack=1,expose_prey=2,strider_kick=1,lacerating_strikes=1)
    row=hm._ranged_profile(40,t,no_pet=False)
    inactive=' | '.join(row['inactive_talent_effects'])
    for key in ('survival_tactics','predators_edge','counterattack','expose_prey','strider_kick','lacerating_strikes'):
        assert key in inactive


def test_post20_marker_says_talents_are_backed_but_melee_and_pet_focus_remain_partial():
    row=hm.experimental_level_score(40,Talents(lightning_reflexes=5),'survival')
    assert row['post20_fallback']=='hunter_l21_l40_planning_range_source_backed_bounded'
