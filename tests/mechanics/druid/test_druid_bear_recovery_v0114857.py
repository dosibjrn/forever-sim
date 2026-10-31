from src.rulesets.forever.classes.druid import mechanics
from src.rulesets.forever.classes.druid.talents import Talents


def _l20_bear_talents(**kw):
    base=dict(ferocity=4, heart_of_the_wild=5, feral_swiftness=2)
    base.update(kw)
    return Talents(**base)


def test_heart_of_the_wild_is_cat_strength_but_bear_stamina():
    zero=Talents()
    hotw=Talents(heart_of_the_wild=5)
    cat_strength0, cat_ap0, _, _ = mechanics._feral_attack_power(20, zero, bear=False)
    cat_strength5, cat_ap5, _, _ = mechanics._feral_attack_power(20, hotw, bear=False)
    bear_strength0, bear_ap0, _, bear_gear = mechanics._feral_attack_power(20, zero, bear=True)
    bear_strength5, bear_ap5, _, _ = mechanics._feral_attack_power(20, hotw, bear=True)
    assert cat_strength5 > cat_strength0
    assert cat_ap5 > cat_ap0
    assert bear_strength5 == bear_strength0
    assert bear_ap5 == bear_ap0
    assert mechanics._player_hp(20,bear_gear,bear=True,talents=hotw) > mechanics._player_hp(20,bear_gear,bear=True,talents=zero)


def test_bear_humanoid_recovery_drinks_shift_mana_concurrently():
    row=mechanics._bear_pack(20,_l20_bear_talents(),3)
    assert row['feasible']
    assert row['recovery_method'] == 'caster_heal_food_water_reform'
    assert row['shift_cost'] > 0
    assert row['water_s'] > 0
    assert row['reform_mana_wait_s'] == 0.0
    # The recovery controller must expose the ordinary vendor tiers it chose.
    assert row['food_tier']
    assert row['water_tier']


def test_bear_recovery_is_not_artificial_hidden_shift_wait():
    t=_l20_bear_talents()
    row=mechanics._bear_pack(20,t,3)
    # Old code paid shift_cost / (8 + .45*level) after otherwise-complete
    # food/heal recovery. The new contract restores shift mana while drinking.
    old_hidden_wait=row['shift_cost']/(8.0+.45*20.0)
    assert row['reform_mana_wait_s'] == 0.0
    assert old_hidden_wait > 0.0
