from __future__ import annotations

import pytest

from src.game.data.forever import build_game_ir_slice
from src.game.runtime import ActorState, TargetState, execute_action
from src.v2.generic_backend import build_partial_generic_records


def _wrath_ir(monkeypatch):
    monkeypatch.setenv("WOW_FOREVER_BUILD_AS_OF", "2026-10-02")
    monkeypatch.setenv("WOW_FOREVER_BUILD_SOURCE", "g07_test")
    ir = build_game_ir_slice(class_key="druid", level=20)
    assert ir is not None
    return ir


def test_generic_event_queue_executes_source_backed_tuned_wrath(monkeypatch):
    ir = _wrath_ir(monkeypatch)
    actor = ActorState.from_ir(ir.actor, ir.resources)
    target = TargetState.with_health("target", 50.0)

    result = execute_action(action=ir.actions[0], actor=actor, target=target)

    assert result.elapsed_s == pytest.approx(2.0)
    assert result.total_damage == pytest.approx((48.0 + 55.5) / 2.0)
    assert result.target_defeated is True
    assert result.target_end_health == 0.0
    assert result.target_death_s == pytest.approx(2.0)
    assert [x.kind for x in result.events] == [
        "ActionStarted", "ActionCompleted", "Damage", "TargetDied"
    ]
    assert result.events[0].payload["declared_costs"] == [
        {"resource_id": "mana", "amount": 40.0}
    ]
    assert result.events[0].payload["costs_applied"] is True
    assert result.events[0].payload["resource_spend"][0] == {
        "resource_id": "mana", "amount": 40.0, "before": 614.0, "after": 574.0
    }
    assert actor.resources["mana"] == pytest.approx(574.0)


def test_generic_event_runtime_can_damage_without_killing(monkeypatch):
    ir = _wrath_ir(monkeypatch)
    actor = ActorState.from_ir(ir.actor, ir.resources)
    target = TargetState.with_health("target", 100.0)

    result = execute_action(action=ir.actions[0], actor=actor, target=target)

    assert result.target_defeated is False
    assert result.target_end_health == pytest.approx(48.25)
    assert result.target_death_s is None
    assert [x.kind for x in result.events] == [
        "ActionStarted", "ActionCompleted", "Damage"
    ]


def test_generic_backend_publishes_native_runtime_probe(monkeypatch):
    monkeypatch.setenv("WOW_FOREVER_BUILD_AS_OF", "2026-10-02")
    monkeypatch.setenv("WOW_FOREVER_BUILD_SOURCE", "g07_test")
    druid, mage = build_partial_generic_records(class_names=("druid", "mage"), selected_level=20)

    assert druid.capability["event_runtime"] is True
    assert druid.capability["single_action_runtime"] is True
    assert druid.capability["action_effect_execution"] is True
    assert "combat_event_runtime" not in druid.unsupported_mechanics
    assert "action_effect_execution" not in druid.unsupported_mechanics
    assert "resource_state_evaluation" not in druid.unsupported_mechanics
    assert "gcd_cooldown_readiness" not in druid.unsupported_mechanics
    assert "source_backed_target_state" not in druid.unsupported_mechanics
    assert druid.provenance["evaluation_seed"]["target_source_status"] == "source_backed_canonical_leveling_reference"
    assert "combat_attack_table_resolution" in druid.unsupported_mechanics
    assert "direct_damage_variance_roll" in druid.unsupported_mechanics

    runtime = druid.provenance["runtime_execution"]
    assert runtime["total_damage"] == pytest.approx(51.75)
    assert runtime["target_start_health"] == 50.0
    assert runtime["target_end_health"] == 0.0
    assert runtime["target_defeated"] is True
    assert runtime["target_death_s"] == 1.5
    assert [x["kind"] for x in runtime["events"]] == [
        "ActionStarted", "ActionCompleted", "Damage", "TargetDied"
    ]
    assert druid.objective["status"] == "combat_recovery_evaluation"
    assert druid.capability["recovery_evaluation"] is True
    assert druid.objective["optimization_ready"] is False
    assert druid.objective["mobs_per_hour"] is None
    assert druid.timing["action_elapsed_s"] == 1.5
    assert druid.provenance["legacy_fallback"] is False

    assert mage.capability["event_runtime"] is False
    assert mage.provenance["runtime_execution"] is None
    assert "combat_event_runtime" in mage.unsupported_mechanics


def test_runtime_layer_has_no_druid_or_wrath_dispatch():
    from pathlib import Path

    # G36 added a source-aware timed-summon *probe* in this folder; the
    # executable engine remains data-driven and may not dispatch on class.
    runtime_source = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (Path("src/game/runtime/simulator.py"), Path("src/game/runtime/state.py"))
    ).lower()
    assert "druid" not in runtime_source
    assert "wrath" not in runtime_source


def test_listener_renders_runtime_probe_without_class_specific_branch():
    from src import listener

    html = listener.DECISIONS_HTML
    assert "function genericRuntimeSummary(r)" in html
    assert "Generic event runtime" in html
    start = html.index("function genericRuntimeSummary(r)")
    end = html.index("function genericPeriodicRuntimeSummary(r)", start)
    renderer = html[start:end].lower()
    assert "druid" not in renderer
    assert "wrath" not in renderer
