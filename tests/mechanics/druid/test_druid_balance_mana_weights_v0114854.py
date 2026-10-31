from src.rulesets.forever.classes.druid import mechanics as dm
from src.rulesets.forever.classes.druid.talents import Talents


def _l20_balance():
    return Talents(
        improved_wrath=5,
        moonglow=2,
        improved_moonfire=2,
        natures_majesty=2,
    )


def test_balance_recovery_credits_item_spirit_and_mp5():
    t = _l20_balance()
    row = dm.experimental_level_score(20, t, "balance")
    assert row["recovery_s"] > 0
    assert row["gear_stats"]["spirit"] > 0
    assert row["gear_stats"]["mp5"] > 0
    assert row["spirit_recovery_mps"] > 0
    assert row["mp5_recovery_mps"] > 0
    assert row["base_spirit"] == 37.0
    assert row["total_spirit"] == row["base_spirit"] + row["item_spirit"]
    assert row["base_mana_regen_per_s"] == 7.5
    assert row["passive_mana_regen_per_s"] == row["base_mana_regen_per_s"] + row["spirit_recovery_mps"] + row["mp5_recovery_mps"]


def test_balance_mana_stats_have_real_marginal_weights_and_feed_fixed_point():
    t = _l20_balance()
    row = dm.experimental_level_score(20, t, "balance")
    weights = dm.marginal_stat_weights(20, t, "balance", row)
    assert weights["stats"]["spirit"]["seconds_saved_per_100_per_point"] > 0
    assert weights["stats"]["mp5"]["seconds_saved_per_100_per_point"] > 0
    assert "mp5" in weights["stats"]
    fp = row["gear_fixed_point"]
    assert fp["role"] == "druid_balance"
    assert fp["trace"]
