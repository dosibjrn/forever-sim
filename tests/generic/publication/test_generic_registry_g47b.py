"""G47b: source/route/race capabilities have one registry authority."""
from pathlib import Path

from src.game.data.forever import registry
from src.v2.decision_dashboard import _generic_ui_metadata
from src.v2.generic_backend import build_partial_generic_records
from src.v2.generic_frontier import GENERIC_DRUID_ROUTE_LEVELS
from src.v2.generic_melee_routes import MELEE_CORRIDORS
from src.version import SOFTWARE_VERSION


def test_g47b_route_corridors_have_registry_authority():
    assert GENERIC_DRUID_ROUTE_LEVELS == registry.generic_planning_levels("druid")
    assert all(v == registry.generic_planning_levels(k) for k, v in MELEE_CORRIDORS.items())
    assert registry.generic_planning_levels("priest") == ()
    assert registry.generic_source_level_bounds("priest") == (10, 20)
    assert registry.generic_source_level_bounds("druid") == (1, 60)


def test_g47b_metadata_distinguishes_source_proof_route_and_race():
    data = _generic_ui_metadata(selected_level=21)
    druid, priest, rogue = data["druid"], data["priest"], data["rogue"]
    assert druid["selected_level_source_ir_available"] is True
    assert priest["selected_level_source_ir_available"] is False
    assert priest["planning_status"] == "no_verified_route"
    assert priest["planning_level_cap"] is None
    assert rogue["planning_level_cap"] == 14
    assert druid["planning_level_cap"] == 14
    assert druid["race_availability"]["representative_scenario_race"] == "tauren"
    assert druid["race_availability"]["playable_races"] == []
    assert all(m["capabilities"]["full_leveling"] is False for m in data.values())
    assert all(m["capabilities"]["race_selection"] is False for m in data.values())


def test_g47b_new_provider_remains_discoverable_but_not_falsely_supported(monkeypatch):
    monkeypatch.setitem(registry._PROVIDERS, "test_beast", lambda level: None)
    row = _generic_ui_metadata(selected_level=10)["test_beast"]
    assert row["source_ir_level_bounds"] is None
    assert row["planning_level_cap"] is None
    assert row["selected_level_source_ir_available"] is False
    assert row["race_availability"]["status"] == "not_verified_for_generic"
    records = build_partial_generic_records(class_names=("test_beast",), selected_level=10)
    assert len(records) == 1
    assert records[0].identity["class_name"] == "test_beast"
    assert records[0].capability["game_ir"] is False


def test_g47b_listener_renders_registry_capabilities():
    source = Path("src/listener.py").read_text()
    assert "function genericAvailabilitySummary(cls)" in source
    assert "${genericAvailabilitySummary(state.cls)}" in source
    assert "Playable race selection: not verified" in source
    assert tuple(map(int, SOFTWARE_VERSION.split("."))) >= (0, 11, 48, 172)


def test_g47b_multi_actor_providers_publish_without_solo_probe_crash():
    # A Shaman totem autoattack cannot be run as the player; a Warlock
    # summon cannot be re-cast while its companion is active.
    records = build_partial_generic_records(
        class_names=("shaman", "warlock"), selected_level=10
    )
    assert {r.identity["class_name"] for r in records} == {"shaman", "warlock"}
    assert all(r.capability["game_ir"] for r in records)
    assert all(r.capability["decision_publication"] for r in records)
