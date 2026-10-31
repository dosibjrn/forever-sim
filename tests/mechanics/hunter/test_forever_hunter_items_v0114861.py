from pathlib import Path

from src import game_context
from src.engine_registry import get_engine, reset_engine_cache
from src.rulesets.forever.items import runtime_selection as rs


def _hunter():
    game_context.configure("forever", "hunter")
    reset_engine_cache()
    return get_engine()


def test_packaged_catalogue_has_hunter_rows_and_ranged_weapon():
    rs.clear_runtime_item_cache()
    rows = rs.available_items("hunter", 20)
    assert len(rows) > 100
    gear = rs.select_gear("hunter", 20, "hunter")
    assert "ranged" in gear
    assert gear["ranged"].weapon_type in {"bow", "crossbow", "gun"}
    assert gear["ranged"].weapon_dps > 0


def test_hunter_scorer_publishes_named_sqlite_slots():
    e = _hunter()
    row = e.experimental_level_score(20, e.Talents(), "beast_mastery")
    gs = row["gear_stats"]
    assert gs["provenance"] == "sqlite_catalogue"
    assert gs["slots"]["ranged"]["name"]
    assert gs["weapon_dps"] == gs["slots"]["ranged"]["weapon_dps"]
    assert len(gs["slots"]) >= 5


def test_hunter_ranged_weapon_dps_mutation_changes_score(monkeypatch):
    e = _hunter()
    t = e.Talents()
    base = e.experimental_level_score(20, t, "beast_mastery")
    from src.rulesets.forever.classes.hunter import mechanics as hm
    original = hm._gear_from_catalogue
    def stronger(level, probe):
        g = original(level, probe)
        g = dict(g); g["slots"] = dict(g["slots"]); g["weapon_dps"] += 5.0
        return g
    monkeypatch.setattr(hm, "_gear_from_catalogue", stronger)
    boosted = e.experimental_level_score(20, t, "beast_mastery")
    assert boosted["mobs_per_hour"] > base["mobs_per_hour"]
