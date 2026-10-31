from src import game_context
from src.engine_registry import reset_engine_cache, get_engine
from src.rulesets.forever.classes.hunter import mechanics as hm
from src.rulesets.forever.classes.hunter.talents import Talents, legal_add


def _hunter():
    game_context.configure("forever", "hunter")
    reset_engine_cache()
    return get_engine()


def test_summon_hawk_legality_stays_on_15_point_bm_row():
    below = Talents(endurance_training=5, focused_fire=2, bestial_swiftness=1, unleashed_fury=5, deadly_aspects=1)
    assert below.points() == 14
    assert not legal_add(below, "summon_hawk")
    ready = Talents(endurance_training=5, focused_fire=2, bestial_swiftness=1, unleashed_fury=5, deadly_aspects=2)
    assert ready.points() == 15
    assert legal_add(ready, "summon_hawk")


def test_summon_hawk_rank_cost_duration_cap_and_shared_cooldown_are_pinned():
    e = _hunter()
    l25 = hm._ranged_profile(25, e.Talents(summon_hawk=1), no_pet=False, pet_family="cat")
    assert l25["summon_hawk_available"] is True
    assert l25["summon_hawk_rank_min_level"] == 25
    assert l25["summon_hawk_base_initial_damage"] == 32.0
    assert l25["summon_hawk_duration_s"] == 18.0
    assert l25["summon_hawk_active_cap"] == 2
    assert l25["summon_hawk_shared_cooldown_s"] == 6.0
    assert abs(l25["summon_hawk_casts_per_s"] - (2.0 / 18.0)) < 1e-12
    assert abs(l25["summon_hawk_arcane_casts_per_s"] - (1.0 / 18.0)) < 1e-12
    assert abs(l25["summon_hawk_mana_per_s"] - (160.0 / 18.0)) < 1e-12

    l36 = hm._ranged_profile(36, e.Talents(summon_hawk=1), no_pet=False, pet_family="cat")
    assert l36["summon_hawk_rank_min_level"] == 36
    assert l36["summon_hawk_base_initial_damage"] == 47.0
    assert abs(l36["summon_hawk_mana_per_s"] - (210.0 / 18.0)) < 1e-12


def test_summon_hawk_does_not_exist_before_rank_one_level():
    e = _hunter()
    row = hm._ranged_profile(24, e.Talents(summon_hawk=1), no_pet=False, pet_family="cat")
    assert row["summon_hawk_available"] is False
    assert row["summon_hawk_initial_dps_floor"] == 0.0
    assert row["summon_hawk_mana_per_s"] == 0.0


def test_summon_hawk_initial_floor_uses_rap_unleashed_fury_and_ferocity_increment():
    e = _hunter()
    base = hm._ranged_profile(30, e.Talents(summon_hawk=1), no_pet=False, pet_family="cat")
    buffed = hm._ranged_profile(
        30,
        e.Talents(summon_hawk=1, unleashed_fury=5, ferocity=5),
        no_pet=False,
        pet_family="cat",
    )
    assert base["summon_hawk_rap_coefficient"] == 0.05
    assert buffed["summon_hawk_ferocity_crit_bonus"] == 0.10
    assert buffed["summon_hawk_credited_crit_chance"] == 0.10
    assert buffed["summon_hawk_initial_damage_ev"] > base["summon_hawk_initial_damage_ev"]
    assert buffed["summon_hawk_initial_dps_floor"] > base["summon_hawk_initial_dps_floor"]


def test_summon_hawk_shared_cd_changes_score_and_is_not_double_counted_with_arcane_spam():
    e = _hunter()
    plain = hm._ranged_profile(30, e.Talents(), no_pet=False, pet_family="cat")
    hawk = hm._ranged_profile(30, e.Talents(summon_hawk=1), no_pet=False, pet_family="cat")
    assert hawk["summon_hawk_initial_dps_floor"] > 0.0
    assert hawk["mobs_per_hour"] != plain["mobs_per_hour"]
    assert "Summon Hawk; Summon Hawk; Arcane Shot shared-CD cycle" in hawk["rotation"]
    # Source-backed known floor only: do not fabricate the 18s summoned-unit attacks.
    assert hawk["summon_hawk_sustained_assault_modeled"] is False
    assert hawk["summon_hawk_scoring_mode"] == "source_backed_initial_strike_lower_bound"


def test_summon_hawk_is_partially_modeled_not_wholly_inactive():
    e = _hunter()
    row = hm._ranged_profile(35, e.Talents(summon_hawk=1), no_pet=False, pet_family="cat")
    inactive = " | ".join(row["inactive_talent_effects"])
    assert "summon_hawk: hawk sustained attack table not yet source-pinned" not in inactive
    assert "summon_hawk_sustained_assault" in inactive
    assert row["summon_hawk_initial_damage_ev"] > 0.0
