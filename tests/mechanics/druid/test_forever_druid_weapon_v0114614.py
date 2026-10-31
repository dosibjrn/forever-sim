import pytest

from src.rulesets.forever.classes import druid
from src.rulesets.forever.classes.druid import mechanics as dm
from src.rulesets.forever.classes.druid.weapon import (
    BEAR_FORM_SWING_S,
    CAT_FORM_SWING_S,
    form_white_dps,
    normal_form_hit,
    weapon_for_level,
)


def test_named_weapon_anchor_reaches_runtime_gear():
    w = weapon_for_level(20)
    assert w is not None and w.name == "Hammerbone"
    assert w.weapon_dps == pytest.approx(20.44)
    _, _, _, cat = dm._feral_attack_power(20, druid.Talents())
    _, _, _, bear = dm._feral_attack_power(20, druid.Talents(), bear=True)
    for gear in (cat, bear):
        assert gear["weapon_dps"] == pytest.approx(20.44)
        assert gear["slots"]["weapon"]["name"] == "Hammerbone"


def test_form_weapon_math_uses_weapon_dps_not_equipped_speed():
    # Equipped weapon speed is deliberately absent from the form transform:
    # Forever guide evidence says DPS carries over and equipped speed is irrelevant.
    dps = form_white_dps(weapon_dps=20.44, attack_power=140.0)
    assert dps == pytest.approx(30.44)
    assert normal_form_hit(weapon_dps=20.44, attack_power=140.0, bear=False) == pytest.approx(dps * CAT_FORM_SWING_S)
    assert normal_form_hit(weapon_dps=20.44, attack_power=140.0, bear=True) == pytest.approx(dps * BEAR_FORM_SWING_S)


def test_cat_score_reports_named_weapon_and_weapon_dps_has_value():
    t = druid.Talents()
    row = druid.experimental_level_score(20, t, "feral")
    assert row["weapon_dps"] == pytest.approx(20.44)
    assert row["gear_stats"]["slots"]["weapon"]["name"] == "Hammerbone"
    weights = dm.marginal_stat_weights(20, t, "feral", row)
    assert weights["stats"]["weapon_dps"]["status"] == "measured"
    assert weights["stats"]["weapon_dps"]["seconds_saved_per_100_per_point"] > 0


def test_bear_normal_hit_and_primal_bite_consume_same_weapon_transform():
    t = druid.Talents(ferocity=5, mangle=1)
    row = dm._bear_pack(30, t, 1)
    assert row["weapon_dps"] == pytest.approx(29.0)
    assert row["gear_stats"]["slots"]["weapon"]["name"] == "Manual Crowd Pummeler"
    assert row["bear_normal_weapon_hit"] > row["weapon_dps"]
    assert row["maul_rank_level"] == 26
    assert row["maul_flat_damage"] == pytest.approx(37.0)
    assert row["weapon_scaling_provenance"]["scaling"] == "equipped_weapon_dps_carried_into_cat_and_bear"


def test_maul_is_capped_by_bear_swing_rate():
    t = druid.Talents(ferocity=5)
    row = dm._bear_pack(60, t, 3)
    assert row["weapon_dps"] == pytest.approx(41.29)
    assert row["maul_rate_per_s"] <= 1.0 / BEAR_FORM_SWING_S + 1e-12
    assert row["dps"] > 0
