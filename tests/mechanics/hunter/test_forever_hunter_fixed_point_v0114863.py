from src import game_context
from src.engine_registry import get_engine, reset_engine_cache
from src.rulesets.forever.classes.hunter import mechanics as hm


def _hunter():
    game_context.configure("forever", "hunter")
    reset_engine_cache()
    return get_engine()


def test_hunter_gear_is_selected_by_scorer_derived_stat_weights():
    e = _hunter()
    row = e.experimental_level_score(20, e.Talents(), "beast_mastery")
    gs = row["gear_stats"]
    assert gs["gear_selection_method"] == "hunter_stat_weight_fixed_point"
    assert gs["gear_selection_iterations"] >= 2
    assert gs["gear_selection_converged"] is True
    assert gs["selection_weights"]
    assert gs["selection_weights"]["weapon_dps"] > 0
    assert gs["selection_weights"]["agility"] > 0
    assert gs["selection_weights"] != {
        "agility": 1.00, "attack_power": .50, "intellect": .28,
        "spirit": .16, "mp5": .38, "stamina": .18,
        "armor": .001, "weapon_dps": 5.0,
    }


def test_fixed_point_improves_over_seed_preset_for_l20_baseline():
    e = _hunter(); t = e.Talents()
    fixed = e.experimental_level_score(20, t, "beast_mastery")
    trace = fixed["gear_stats"]["gear_selection_trace"]
    assert trace[0]["selection_weights"] == {}
    assert trace[-1]["objective_s_per_100"] <= trace[0]["objective_s_per_100"]
    assert trace[-1]["item_ids"] != trace[0]["item_ids"]


def test_published_marginals_match_final_selection_weights_at_convergence():
    e = _hunter(); t = e.Talents()
    row = e.experimental_level_score(20, t, "beast_mastery")
    model = e.marginal_stat_weights(20, t, "beast_mastery", baseline=row)
    expected = hm._selection_weights_from_stat_model(model)
    actual = row["gear_stats"]["selection_weights"]
    assert expected.keys() == actual.keys()
    for stat in expected:
        assert abs(expected[stat] - actual[stat]) < 1e-9


def test_direct_attack_power_is_now_probeable_and_positive():
    e = _hunter(); t = e.Talents()
    row = e.experimental_level_score(20, t, "beast_mastery")
    model = e.marginal_stat_weights(20, t, "beast_mastery", baseline=row)
    ap = model["stats"]["attack_power"]
    assert ap["status"] == "measured"
    assert ap["seconds_saved_per_100_per_point"] > 0
