from __future__ import annotations

from pathlib import Path

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talents import apply_talent_selection, explicit_seed_selection, validate_talent_selection
from src.v2.generic_backend import build_partial_generic_records


def _druid(level: int = 20):
    ir = build_game_ir_slice(class_key="Druid", level=level)
    assert ir is not None
    return ir


def test_g13_canonical_talent_record_normalizes_rank_modifiers_and_legality():
    ir = _druid(20)
    assert ir.schema_version == 16
    talent = next(t for t in ir.talents if t.id == "improved_wrath")
    assert talent.name == "Improved Wrath"
    assert talent.tree_key == "balance"
    assert talent.max_rank == 5
    assert talent.prerequisite is None
    rank5 = next(row for row in talent.ranks if row.rank == 5)
    assert [(m.kind, m.target_type, m.target_id, m.value) for m in rank5.modifiers] == [
        ("cast_time_delta_s", "action_family", "wrath", -0.5),
        ("resource_cost_pct", "action_family", "wrath", -0.5),
    ]
    assert rank5.provenance["source"]["provider"] == "wowhead"
    assert rank5.provenance["source"]["entity_id"] == 16814


def test_g13_seed_selection_obeys_level_point_budget_and_canonical_max_rank():
    assert explicit_seed_selection(_druid(10), level=10) == {"improved_wrath": 1}
    seed = explicit_seed_selection(_druid(20), level=20)
    assert len(seed) == 1 and next(iter(seed.values())) == 5
    validate_talent_selection(_druid(20), seed, level=20)
    with pytest.raises(ValueError, match="illegal rank"):
        validate_talent_selection(_druid(20), {"improved_wrath": 6}, level=20)
    with pytest.raises(ValueError, match="level budget"):
        validate_talent_selection(_druid(10), {"improved_wrath": 2}, level=10)


def test_g13_generic_modifier_application_changes_action_without_mutating_source_ir():
    source = _druid(20)
    source_wrath = next(a for a in source.actions if a.family_key == "wrath")
    assert source_wrath.cast_time_s == pytest.approx(2.0)
    assert source_wrath.costs[0].amount == pytest.approx(40.0)

    modified, application = apply_talent_selection(source, {"improved_wrath": 5}, level=20)
    wrath = next(a for a in modified.actions if a.family_key == "wrath")
    assert wrath.cast_time_s == pytest.approx(1.5)
    assert wrath.costs[0].amount == pytest.approx(20.0)
    assert source_wrath.cast_time_s == pytest.approx(2.0)
    assert source_wrath.costs[0].amount == pytest.approx(40.0)
    assert [x["kind"] for x in application.applied_modifiers] == ["cast_time_delta_s", "resource_cost_pct"]
    assert all(p["stage"] == "talent_modifier" for p in wrath.provenance[-2:])


def test_g13_active_generic_evaluation_is_changed_by_real_talent_choice():
    record = build_partial_generic_records(class_names=["Druid"], selected_level=20)[0]
    talents = record.talents
    comparison = talents["evaluation_comparison"]
    assert talents["status"] == "joint_talent_policy_search"
    assert talents["ranks"] == {"improved_wrath": 5}
    assert talents["spent_points"] == 5
    assert talents["available_points"] == 11
    assert comparison["baseline_seconds_per_mob"] == pytest.approx(26.347826086956523)
    assert comparison["selected_seconds_per_mob"] == pytest.approx(21.73913043478261)
    assert comparison["delta_seconds_per_mob"] == pytest.approx(-4.608695652173914)
    # G13 fixed-seed comparison remains isolated above. Later optimizer
    # dimensions publish their own authorities instead of redefining this proof.
    naked = record.provenance["naked_evaluation"]
    assert naked["kill_seconds_per_mob"] == pytest.approx(13.5)
    assert naked["recovery_seconds_per_mob"] == pytest.approx(5.108695652173914)
    assert naked["seconds_per_mob"] == pytest.approx(18.608695652173914)
    assert comparison["active_searched_seconds_per_mob"] == pytest.approx(11.5)
    assert record.capability["talent_modifier_evaluation"] is True
    assert record.capability["talent_search"] is True
    assert "talent_modifier_evaluation" not in record.unsupported_mechanics
    assert "talent_search" not in record.unsupported_mechanics
    assert record.provenance["legacy_fallback"] is False


def test_g13_generic_talent_engine_and_listener_have_no_druid_talent_branch():
    engine = Path("src/game/talents.py").read_text(encoding="utf-8").lower()
    assert "druid" not in engine
    assert "improved_wrath" not in engine
    assert '== "wrath"' not in engine

    from src import listener
    html = listener.DECISIONS_HTML
    assert "Generic Talent IR" in html
    start = html.index("function genericTalentSummary(r)")
    end = html.index("function genericFrontierSummary(r)", start)
    renderer = html[start:end].lower()
    assert "druid" not in renderer
    assert "improved wrath" not in renderer
    assert "wrath" not in renderer
