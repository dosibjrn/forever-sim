from src.shared.leveling.objective import representative_hp, mob_hp
from src.rulesets.forever.shared.mobs import fixture_snapshot
from src.rulesets.forever.classes.mage import engine as mage
from src.rulesets.forever.classes.mage.resources import best_mage_water
from src.v2.expected_engine import simulate_fight_expected, score_policy
from src.v2.analytic_scorer import AnalyticOptions


def _fb_policy():
    return mage.Policy(name="fb", primary="frostbolt")


def test_same_level_is_the_forever_default_target_everywhere():
    assert representative_hp(40) == mob_hp(40)
    snap = fixture_snapshot(40)
    assert snap["target_level_offsets"] == [[0, 1.0]]
    assert {row["mob_level"] for row in snap["rows"]} == {40}
    out = simulate_fight_expected(40, mage.Talents(), _fb_policy(), mage.SimConfig())
    assert out.mob_level == 40


def test_mage_best_available_water_uses_crystal_tier_at_55_plus():
    assert best_mage_water(54).amount == 2934.0
    assert best_mage_water(55).amount == 4200.0


def test_mage_chain_carries_mana_and_does_not_full_reset_each_mob():
    out = mage.simulate_chain(28, mage.Talents(), _fb_policy(), mage.SimConfig(), n=20, seed=7)
    assert out["full_recoveries"] < 12
    assert out["mana_gem_uses"] > 0


def test_mage_chain_evocation_is_an_explicit_between_pull_action():
    out = mage.simulate_chain(20, mage.Talents(), _fb_policy(), mage.SimConfig(), n=20, seed=7)
    assert out["evocation_uses"] > 0


def test_forever_incremental_chain_matches_fresh_chain_with_resource_carry():
    talents = mage.Talents()
    policy = _fb_policy()
    cfg = mage.SimConfig()
    _, state6 = mage.simulate_chain_incremental(28, talents, policy, cfg, target_n=6, seed=19)
    extended, state12 = mage.simulate_chain_incremental(28, talents, policy, cfg, target_n=12, seed=19, continuation=state6)
    fresh, fresh_state = mage.simulate_chain_incremental(28, talents, policy, cfg, target_n=12, seed=19)
    # Display output closes at a full-resource boundary; continuation state is
    # pre-tail and must therefore remain exactly extendable.
    for key in ("total_s","kill_s","recovery_s","mana","wand_s","damage_done","mana_gem_uses","evocation_uses","full_recoveries"):
        assert abs(float(extended[key]) - float(fresh[key])) < 1e-9
    for key in ("n","cooldowns","current_mana","hp_missing_pool","mana_gem_cd_s","evocation_cd_s","mana_gem_needs_restock","mana_gem_uses","evocation_uses","full_recoveries"):
        assert state12[key] == fresh_state[key]


def test_expected_chain_also_carries_resources_and_same_level_target():
    out = score_policy(28, mage.Talents(), _fb_policy(), mage.SimConfig(), cycle_pulls=12)
    assert out["target_level_offset"] == 0
    assert out["full_recoveries"] < 12
    assert out["mana_gem_uses"] > 0


def test_forever_analytic_default_uses_the_sustained_resource_chain():
    from src.v2.analytic_scorer import score_policy_analytic
    out = score_policy_analytic(28, mage.Talents(), _fb_policy(), mage.SimConfig(), options=AnalyticOptions())
    assert out["deterministic_resource_chain"] is True
    assert out["target_level_offset"] == 0
    assert out["full_recoveries"] < out["simulated_pulls"]
    assert "forever_default_same_level_resource_chain" in out["approximation_flags"]
