from __future__ import annotations

from src.game.data.forever import build_game_ir_slice
from src.game.data.forever.tuning_overlays import direct_damage_overlays
from src.game.model.overlay import FieldOverlay, apply_numeric_field_overlays
from src.v2.generic_backend import build_partial_generic_records


def test_generic_numeric_overlay_engine_is_path_based_and_fail_closed():
    overlays = (
        FieldOverlay(id="x", target_path="effects.0.base_min", operation="multiply", value=1.5),
    )
    values, trace = apply_numeric_field_overlays({"effects.0.base_min": 10.0}, overlays)
    assert values["effects.0.base_min"] == 15.0
    assert trace["effects.0.base_min"][0] == {"stage": "raw_source", "value": 10.0}
    assert trace["effects.0.base_min"][1]["overlay_id"] == "x"

    bad = (FieldOverlay(id="bad", target_path="druid.wrath.damage", operation="multiply", value=2),)
    try:
        apply_numeric_field_overlays({"effects.0.base_min": 10.0}, bad)
    except KeyError:
        pass
    else:
        raise AssertionError("unknown/class-shaped overlay target must fail closed")


def test_forever_wrath_overlay_is_dated_and_source_backed():
    assert direct_damage_overlays(class_key="druid", family_key="wrath", as_of="2026-09-23") == ()
    overlays = direct_damage_overlays(class_key="druid", family_key="wrath", as_of="2026-09-24")
    assert len(overlays) == 2
    assert {x.target_path for x in overlays} == {"effects.0.base_min", "effects.0.base_max"}
    assert {x.value for x in overlays} == {1.5}
    assert all(x.effective_from == "2026-09-24" for x in overlays)
    assert all(x.provenance[0]["provider"] == "blizzard_forums" for x in overlays)
    assert all(x.unsupported_semantics[0]["code"] == "approximate_tuning_magnitude" for x in overlays)


def test_wrath_raw_fact_remains_unchanged_while_executable_ir_uses_overlay(monkeypatch):
    monkeypatch.setenv("WOW_FOREVER_BUILD_AS_OF", "2026-10-02")
    monkeypatch.setenv("WOW_FOREVER_BUILD_SOURCE", "g06_test")
    ir = build_game_ir_slice(class_key="druid", level=20)
    assert ir is not None
    assert ir.source_facts[0]["damage_min"] == 32.0
    assert ir.source_facts[0]["damage_max"] == 37.0
    assert len(ir.overlays) == 2

    effect = ir.actions[0].effects[0]
    assert effect.base_min == 48.0
    assert effect.base_max == 55.5
    assert effect.spell_power_coefficient == 0.571

    min_trace = effect.field_provenance["base_min"]
    assert min_trace[0]["stage"] == "raw_source"
    assert min_trace[0]["value"] == 32.0
    assert min_trace[0]["provenance"][0]["provider"] == "wowhead"
    assert min_trace[1]["stage"] == "overlay"
    assert min_trace[1]["operation"] == "multiply"
    assert min_trace[1]["operand"] == 1.5
    assert min_trace[1]["value"] == 48.0
    assert min_trace[1]["provenance"][0]["provider"] == "blizzard_forums"
    assert effect.unsupported_semantics[0]["status"] == "explicit_approximation"


def test_pre_tuning_build_keeps_raw_executable_damage(monkeypatch):
    monkeypatch.setenv("WOW_FOREVER_BUILD_AS_OF", "2026-09-23")
    monkeypatch.setenv("WOW_FOREVER_BUILD_SOURCE", "g06_test_pre_tuning")
    ir = build_game_ir_slice(class_key="druid", level=20)
    assert ir is not None
    assert ir.overlays == ()
    assert ir.actions[0].effects[0].base_min == 32.0
    assert ir.actions[0].effects[0].base_max == 37.0
    assert ir.unsupported_semantics == ()


def test_generic_backend_publishes_overlay_provenance_and_explicit_caveat(monkeypatch):
    monkeypatch.setenv("WOW_FOREVER_BUILD_AS_OF", "2026-10-02")
    monkeypatch.setenv("WOW_FOREVER_BUILD_SOURCE", "g06_test")
    druid, mage = build_partial_generic_records(class_names=("druid", "mage"), selected_level=20)
    assert druid.capability["tuning_overlays"] is True
    assert druid.capability["field_provenance"] is True
    assert druid.capability["unsupported_semantic_count"] == 2
    assert len(druid.provenance["semantic_overlays"]) == 2
    assert len(druid.provenance["unsupported_semantics"]) == 2
    assert "exact_tuning_for_approximate_overlays" in druid.unsupported_mechanics
    assert druid.actions[0]["effects"][0]["base_min"] == 48.0
    assert druid.provenance["legacy_fallback"] is False

    assert mage.capability["tuning_overlays"] is False
    assert mage.provenance["semantic_overlays"] == []
    assert "exact_tuning_for_approximate_overlays" not in mage.unsupported_mechanics


def test_listener_renders_generic_overlay_provenance_without_class_branch():
    from src import listener

    html = listener.DECISIONS_HTML
    assert "IR provenance &amp; overlays" in html
    assert "dated tuning" in html
    assert "≈ source magnitude" in html
    start = html.index("function genericActionSummary(a)")
    end = html.index("function genericActorStateSummary", start)
    renderer = html[start:end]
    assert "druid" not in renderer.lower()
    assert "wrath" not in renderer.lower()
