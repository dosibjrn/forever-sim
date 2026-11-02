from __future__ import annotations

from dataclasses import replace

import pytest

from src.game.data.forever import build_game_ir_slice
from src.game.runtime import (
    ActionNotEligibleError,
    ActorState,
    TargetState,
    action_eligibility,
    execute_action,
    execute_repeated_actions,
)
from src.v2.generic_backend import build_partial_generic_records


def _wrath_ir(monkeypatch):
    monkeypatch.setenv("WOW_FOREVER_BUILD_AS_OF", "2026-10-02")
    monkeypatch.setenv("WOW_FOREVER_BUILD_SOURCE", "g08_test")
    ir = build_game_ir_slice(class_key="druid", level=20)
    assert ir is not None
    return ir


def test_wrath_spends_mana_and_advances_readiness_state(monkeypatch):
    ir = _wrath_ir(monkeypatch)
    actor = ActorState.from_ir(ir.actor, ir.resources)
    target = TargetState.with_health("target", 1000.0)

    result = execute_action(action=ir.actions[0], actor=actor, target=target)

    assert result.start_time_s == 0.0
    assert result.end_time_s == pytest.approx(2.0)
    assert result.resources_before["mana"] == 614.0
    assert result.resources_after["mana"] == 574.0
    assert actor.resources["mana"] == 574.0
    assert actor.current_time_s == pytest.approx(2.0)
    assert actor.gcd_ready_s == pytest.approx(1.5)
    assert actor.cooldown_ready_s[ir.actions[0].id] == 0.0
    assert result.events[0].payload["costs_applied"] is True


def test_repeated_wrath_uses_same_generic_execution_and_state(monkeypatch):
    ir = _wrath_ir(monkeypatch)
    actor = ActorState.from_ir(ir.actor, ir.resources)
    target = TargetState.with_health("durable", 100000.0)

    sequence = execute_repeated_actions(
        action=ir.actions[0], actor=actor, target=target, count=3
    )

    assert sequence.completed_casts == 3
    assert sequence.stopped_reason is None
    assert [x.start_time_s for x in sequence.executions] == [0.0, 2.0, 4.0]
    assert [x.end_time_s for x in sequence.executions] == [2.0, 4.0, 6.0]
    assert sequence.resources_before["mana"] == 614.0
    assert sequence.resources_after["mana"] == 494.0
    assert actor.current_time_s == 6.0


def test_insufficient_resource_fails_closed_after_legal_casts(monkeypatch):
    ir = _wrath_ir(monkeypatch)
    action = ir.actions[0]
    actor = ActorState.from_ir(ir.actor, ir.resources)
    target = TargetState.with_health("durable", 100000.0)

    sequence = execute_repeated_actions(action=action, actor=actor, target=target, count=15)
    assert sequence.completed_casts == 15
    assert actor.resources["mana"] == pytest.approx(14.0)

    eligibility = action_eligibility(action=action, actor=actor)
    assert eligibility.eligible is False
    assert eligibility.reason.startswith("insufficient mana")
    with pytest.raises(ActionNotEligibleError, match="insufficient mana"):
        execute_action(action=action, actor=actor, target=target)


def test_generic_gcd_and_cooldown_readiness_are_active(monkeypatch):
    ir = _wrath_ir(monkeypatch)
    # Synthetic mechanics probe only: same generic Action schema, deliberately
    # shorter cast and non-zero cooldown so readiness gates become observable.
    action = replace(ir.actions[0], cast_time_s=0.5, gcd_s=1.5, cooldown_s=3.0, costs=())
    actor = ActorState.from_ir(ir.actor, ir.resources)
    target = TargetState.with_health("durable", 100000.0)

    first = execute_action(action=action, actor=actor, target=target)
    assert first.end_time_s == 0.5
    blocked = action_eligibility(action=action, actor=actor)
    assert blocked.eligible is False
    assert blocked.reason == "action not ready: gcd/cooldown"
    assert blocked.next_ready_s == 3.0

    sequence = execute_repeated_actions(
        action=action, actor=actor, target=target, count=2, wait_for_readiness=True
    )
    assert sequence.completed_casts == 2
    assert [x.start_time_s for x in sequence.executions] == [3.0, 6.0]
    assert sequence.end_time_s == 6.5


def test_requirements_are_generic_and_fail_closed(monkeypatch):
    ir = _wrath_ir(monkeypatch)
    action = ir.actions[0]
    actor = ActorState.from_ir(ir.actor, ir.resources)
    actor.metadata["level"] = 10
    eligibility = action_eligibility(action=action, actor=actor)
    assert eligibility.eligible is False
    assert eligibility.reason == "minimum level 14 not met"

    actor.metadata["level"] = 20
    unknown = replace(action, requirements=({"kind": "druid_magic_requirement"},))
    eligibility = action_eligibility(action=unknown, actor=actor)
    assert eligibility.eligible is False
    assert eligibility.reason == "unsupported action requirement: druid_magic_requirement"


def test_generic_backend_publishes_stateful_runtime_without_legacy_fallback(monkeypatch):
    ir = _wrath_ir(monkeypatch)
    assert ir.actions[0].cooldown_s == 0.0
    druid, mage = build_partial_generic_records(class_names=("druid", "mage"), selected_level=20)

    assert druid.capability["status"] == "combat_recovery_evaluation"
    assert druid.capability["recovery_evaluation"] is True
    assert druid.capability["combat_evaluation"] is True
    assert druid.capability["optimization_ready"] is False
    assert druid.capability["resource_state_evaluation"] is True
    assert druid.capability["gcd_cooldown_readiness"] is True
    assert druid.capability["repeated_action_state_progression"] is True
    assert "resource_state_evaluation" not in druid.unsupported_mechanics
    assert "gcd_cooldown_readiness" not in druid.unsupported_mechanics
    assert druid.provenance["legacy_fallback"] is False

    execution = druid.provenance["runtime_execution"]
    assert execution["resources_before"]["mana"] == 614.0
    assert execution["resources_after"]["mana"] == 594.0
    assert execution["events"][0]["payload"]["costs_applied"] is True

    sequence = druid.provenance["runtime_sequence"]
    assert sequence["completed_casts"] == 3
    assert sequence["resources_before"]["mana"] == 614.0
    assert sequence["resources_after"]["mana"] == 554.0
    assert sequence["end_time_s"] == 4.5

    assert mage.capability["resource_state_evaluation"] is False
    assert mage.capability["gcd_cooldown_readiness"] is False
    assert mage.provenance["runtime_sequence"] is None


def test_runtime_and_listener_stay_class_neutral():
    from pathlib import Path
    from src import listener

    # Class-specific source-backed probes are not part of the shared runtime.
    runtime_source = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (Path("src/game/runtime/simulator.py"), Path("src/game/runtime/state.py"))
    ).lower()
    assert "druid" not in runtime_source
    assert "wrath" not in runtime_source

    html = listener.DECISIONS_HTML
    start = html.index("function genericRuntimeSummary(r)")
    end = html.index("function genericPeriodicRuntimeSummary", start)
    renderer = html[start:end].lower()
    assert "state progression" in renderer
    assert "gcd/cooldown ready" in renderer
    assert "druid" not in renderer
    assert "wrath" not in renderer
