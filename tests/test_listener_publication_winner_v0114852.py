import json

from src.v2 import decision_dashboard
from src.v2.experimental_classes import _per_level_best_path


def _rich_row(level=20):
    return {
        "level": level,
        "allocation": "balance-rich",
        "score_s_per_100": 1451.5,
        "mobs_per_hour": 248.0,
        "gear": "canonical_sqlite_druid_balance",
        "gear_stats": {
            "name": "canonical_sqlite_druid_balance",
            "gear_selection_method": "canonical_sqlite_runtime_selection_v1",
            "slots": {
                "head": {"item_id": 252448, "name": "Rich Head"},
                "weapon": {"item_id": 5187, "name": "Rich Weapon"},
            },
        },
        "gear_fixed_point": {"iterations": 2, "converged": True},
        "stat_weights": {"stats": {"spell_power": {"seconds_saved_per_100_per_point": 4.98}}},
        "rotation": "Wrath",
    }


def test_experimental_per_level_path_prefers_enriched_best_over_raw_event_row(monkeypatch):
    monkeypatch.setattr("src.objective.level_weight_per_100", lambda level: 1.0)
    rich = _rich_row()
    raw_event = {
        "level": 20,
        "allocation": "balance-rich",
        "score_s_per_100": 1451.5,
        "mobs_per_hour": 248.0,
        "gear": "legacy_floor",
        # Deliberately missing gear_stats/stat_weights/fixed-point diagnostics.
    }
    path = _per_level_best_path([{"level": 20, "best": rich, "event_validated_best": raw_event}])
    step = path["steps"][0]
    assert step["gear"] == "canonical_sqlite_druid_balance"
    assert step["gear_stats"]["gear_selection_method"] == "canonical_sqlite_runtime_selection_v1"
    assert step["gear_fixed_point"]["converged"] is True
    assert "stat_weights" in step


def test_decision_listener_prefers_current_experimental_summary_over_stale_explicit_path(tmp_path, monkeypatch):
    monkeypatch.setattr(decision_dashboard, "CLASSES", ("druid",))
    viewer = tmp_path / "state/games/forever-druid/v2/viewer.json"
    viewer.parent.mkdir(parents=True)
    rich = _rich_row()
    stale = {
        "level": 20,
        "allocation": "balance-rich",
        "score_s_per_100": 1719.0,
        "mobs_per_hour": 209.4,
        "gear": "leatherworking_totemic_skycaller_craft_floor",
        "gear_stats": {"name": "Leatherworking Totemic Skycaller Craft Floor", "slots": {}},
    }
    viewer.write_text(json.dumps({
        "views": {"experimental": {
            "level_summaries": [{"level": 20, "best": rich}],
            "paths": {"per_level_best": {"steps": [stale]}},
        }}
    }), encoding="utf-8")

    payload = decision_dashboard.build_decision_payload(tmp_path, selected_level=20)
    row = payload["per_level_rows"]["druid"][0]
    assert row["mobs_per_hour"] == 248.0
    assert row["gear"] == "canonical_sqlite_druid_balance"
    assert row["gear_stats"]["slots"]["weapon"]["item_id"] == 5187
    assert row["gear_fixed_point"]["iterations"] == 2


def test_real_druid_l20_score_carries_canonical_fixed_point_gear():
    # Fast single-candidate regression: the exact talent row that previously
    # appeared in the listener as 209.4 mobs/h must now carry the fixed-point
    # SQLite selection all the way out of the scorer.
    from src import game_context
    from src.engine_registry import get_engine, reset_engine_cache

    game_context.configure("forever", "druid")
    reset_engine_cache()
    engine = get_engine()
    talents = engine.Talents(
        improved_wrath=5, genesis=2, improved_moonfire=2, natures_majesty=2
    )
    row = engine.experimental_level_score(20, talents, "all")
    gear = row["gear_stats"]
    assert row["gear"] == "canonical_sqlite_druid_balance"
    assert gear["gear_selection_method"] == "canonical_sqlite_runtime_selection_v1"
    assert len(gear["slots"]) >= 10
    assert row["gear_fixed_point"]["iterations"] >= 1
    assert 360000.0 / row["total_s"] > 209.4
