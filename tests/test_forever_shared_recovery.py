from src.rulesets.forever.shared.recovery import HealOption, food_tier, water_tier, recover_to_full


def test_best_baseline_tiers_are_level_scoped():
    assert food_tier(20).amount == 552.0
    assert water_tier(20).amount == 835.2
    assert food_tier(60).amount == 2452.0
    assert water_tier(60).amount == 2934.0


def test_food_and_water_are_concurrent_and_full_targeted():
    r = recover_to_full(20, hp_missing=552.0, mana_missing=835.2)
    assert abs(r.total_s - 24.0) < 1e-9
    assert abs(r.food_s - 24.0) < 1e-9
    assert abs(r.water_s - 24.0) < 1e-9


def test_heal_is_used_only_when_it_reduces_time_to_full():
    heal = HealOption("test heal", heal=300.0, mana=100.0, cast_s=2.0)
    # HP is the bottleneck: healing should help.
    helped = recover_to_full(20, hp_missing=600.0, mana_missing=100.0, heal_options=(heal,))
    baseline = recover_to_full(20, hp_missing=600.0, mana_missing=100.0)
    assert helped.total_s < baseline.total_s
    assert helped.heal_casts > 0
    # Mana is already the bottleneck: extra heal mana cannot help.
    no_help = recover_to_full(20, hp_missing=50.0, mana_missing=800.0, heal_options=(heal,))
    assert no_help.heal_casts == 0


def test_flat_mp5_regen_reduces_water_recovery_time():
    base = recover_to_full(20, hp_missing=0.0, mana_missing=400.0)
    boosted = recover_to_full(20, hp_missing=0.0, mana_missing=400.0, passive_mana_regen_per_s=1.0)
    assert boosted.total_s < base.total_s
    assert boosted.water_s < base.water_s
