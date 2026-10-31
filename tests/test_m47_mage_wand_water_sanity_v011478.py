import pytest


def test_best_water_uses_strict_best_normally_usable_tier():
    from src.rulesets.forever.classes.mage.resources import best_mage_water
    expected={
        13:(5,'Ice Cold Milk tier'),
        20:(15,'Melon Juice tier'),
        40:(35,'Moonberry Juice tier'),
        55:(55,'Crystal Water tier'),
        60:(55,'Crystal Water tier'),
    }
    for level,(req,name) in expected.items():
        tier=best_mage_water(level,best_available=True)
        assert tier.required_level == req
        assert tier.name == name


def test_self_conjured_water_is_only_the_sensitivity_table():
    from src.rulesets.forever.classes.mage.resources import best_mage_water
    # At L55 the optimized baseline can buy/use Crystal Water, while a
    # self-conjured-only sensitivity run is still on the L50 tier.
    best=best_mage_water(55,best_available=True)
    self_only=best_mage_water(55,best_available=False)
    assert best.name == 'Crystal Water tier'
    assert self_only.name == 'Conjured Sparkling Water tier'
    assert best.rate_per_s > self_only.rate_per_s


def test_default_mage_config_prefers_best_available_water():
    from src.rulesets.forever.classes.mage.engine import SimConfig
    assert SimConfig().use_best_water is True
