from src.rulesets.forever.classes.druid import mechanics
from src.rulesets.forever.classes.druid.talents import TALENT_RULES, Talents


def test_current_tree_uses_blood_frenzy_name_and_keeps_old_fixture_alias_out_of_search():
    assert "blood_frenzy" in TALENT_RULES
    assert "primal_fury" not in TALENT_RULES
    assert Talents(blood_frenzy=2).effective_blood_frenzy == 2
    assert Talents(primal_fury=2).effective_blood_frenzy == 2
    assert Talents(primal_fury=2).points() == 0


def test_blood_frenzy_bear_rage_matches_recorded_rank_proc_chances():
    # 20% crit, 0.4 white swings/s + 0.6 crit-capable abilities/s =>
    # 0.2 crit events/s. Rank 1 procs 50% * 5 Rage; rank 2 procs 100% * 5.
    r1 = mechanics._blood_frenzy_bear_rage_per_second(
        Talents(blood_frenzy=1), crit=0.20, white_swing_rate=0.4, ability_crit_rate=0.6
    )
    r2 = mechanics._blood_frenzy_bear_rage_per_second(
        Talents(blood_frenzy=2), crit=0.20, white_swing_rate=0.4, ability_crit_rate=0.6
    )
    assert abs(r1 - 0.5) < 1e-12
    assert abs(r2 - 1.0) < 1e-12


def test_blood_frenzy_is_live_in_cat_cp_and_bear_rage_paths():
    cat0 = mechanics._cat_single(40, Talents())
    cat2 = mechanics._cat_single(40, Talents(blood_frenzy=2))
    assert cat2["combo_points_per_builder_ev"] > cat0["combo_points_per_builder_ev"]

    bear0 = mechanics._bear_pack(40, Talents(), 1)
    bear2 = mechanics._bear_pack(40, Talents(blood_frenzy=2), 1)
    assert bear0["blood_frenzy_rage_rate"] == 0.0
    assert bear2["blood_frenzy_rage_rate"] > 0.0
    assert bear2["rage_rate_proxy"] > bear0["rage_rate_proxy"]
