from __future__ import annotations

from pathlib import Path

import pytest

from src.game.data.forever import build_game_ir_slice
from src.game.model import ResourceChangeEffect, ResourceScaledPeriodicEffect
from src.game.policy import execute_priority_policy
from src.game.runtime import ActorState, CombatRuntime, TargetState, action_eligibility
from src.listener import DECISIONS_HTML
from src.shared.leveling.objective import representative_hp
from src.v2.generic_backend import build_partial_generic_records


def _cat_runtime(level: int, target_id: str = "g26-target", hp: float = 10000.0):
    ir = build_game_ir_slice(class_key="Druid", level=level)
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    target = TargetState.with_health(target_id, hp)
    runtime = CombatRuntime(actor=actor, target=target, auto_attacks=ir.auto_attacks)
    cat = next(a for a in ir.actions if a.family_key == "cat_form")
    runtime.schedule_action(cat)
    runtime.advance_to(actor.gcd_ready_s)
    return ir, actor, target, runtime


def test_g26_combo_points_and_rip_are_target_bound_generic_ir():
    ir = build_game_ir_slice(class_key="Druid", level=23)
    assert ir.schema_version == 16
    cp = next(r for r in ir.resources if r.id == "combo_points")
    assert cp.scope == "target"
    assert cp.initial_amount == pytest.approx(0.0)
    assert cp.capacity == pytest.approx(5.0)

    claw = next(a for a in ir.actions if a.family_key == "claw")
    cp_gain = next(e for e in claw.effects if isinstance(e, ResourceChangeEffect))
    assert cp_gain.resource_id == "combo_points"
    assert cp_gain.target == "enemy"
    assert cp_gain.operation == "add"
    assert cp_gain.amount == pytest.approx(1.0)

    rip = next(a for a in ir.actions if a.family_key == "rip")
    scaled = next(e for e in rip.effects if isinstance(e, ResourceScaledPeriodicEffect))
    assert scaled.resource_id == "combo_points"
    assert scaled.resource_scope == "target"
    assert dict(scaled.total_base_damage_by_resource_amount) == {1: 44.0, 2: 71.0, 3: 97.0, 4: 124.0, 5: 150.0}
    assert scaled.tick_interval_s == pytest.approx(2.0)
    cp_reset = next(e for e in rip.effects if isinstance(e, ResourceChangeEffect))
    assert cp_reset.operation == "set" and cp_reset.amount == pytest.approx(0.0)

    policy = next(p for p in ir.policies if p.provenance.get("g26_scope") == "builder_finisher_threshold_seed")
    finisher = next(r for r in policy.rules if r.id == "cat_finisher")
    cp_condition = next(c for c in finisher.conditions if c.resource_id == "combo_points")
    assert cp_condition.search_values == (1.0, 2.0, 3.0, 4.0, 5.0)


def test_g26_target_bound_combo_points_reset_with_new_target_and_rip_consumes_snapshot():
    ir, actor, target1, runtime1 = _cat_runtime(23, "mob-1")
    claw = next(a for a in ir.actions if a.family_key == "claw")
    rip = next(a for a in ir.actions if a.family_key == "rip")

    runtime1.schedule_action(claw)
    runtime1.advance_to(actor.gcd_ready_s)
    runtime1.schedule_action(claw)
    assert target1.resource_amount("combo_points") == pytest.approx(2.0)

    # A fresh target receives a fresh target-scoped resource state while the actor persists.
    target2 = TargetState.with_health("mob-2", 10000.0)
    runtime2 = CombatRuntime(actor=actor, target=target2, auto_attacks=ir.auto_attacks)
    assert target1.resource_amount("combo_points") == pytest.approx(2.0)
    assert target2.resource_amount("combo_points") == pytest.approx(0.0)

    # Build two points on target2, then Rip snapshots 2 CP, consumes them, and deals 71 total periodic damage.
    runtime2.advance_to(max(actor.current_time_s, actor.gcd_ready_s))
    ready = action_eligibility(action=claw, actor=actor, target=target2)
    if not ready.eligible:
        runtime2.advance_to(ready.next_ready_s)
    runtime2.schedule_action(claw)
    runtime2.advance_to(actor.gcd_ready_s)
    ready = action_eligibility(action=claw, actor=actor, target=target2)
    if not ready.eligible:
        runtime2.advance_to(ready.next_ready_s)
    runtime2.schedule_action(claw)
    assert target2.resource_amount("combo_points") == pytest.approx(2.0)
    runtime2.advance_to(actor.gcd_ready_s)
    rip_ready = action_eligibility(action=rip, actor=actor, target=target2)
    if not rip_ready.eligible:
        runtime2.advance_to(rip_ready.next_ready_s)
        rip_ready = action_eligibility(action=rip, actor=actor, target=target2)
    assert rip_ready.eligible is True
    runtime2.schedule_action(rip)
    assert target2.resource_amount("combo_points") == pytest.approx(0.0)
    runtime2.advance_to(actor.current_time_s + 12.0)
    result = runtime2.result()
    ticks = [e for e in result.events if e.kind == "Damage" and e.action_id == rip.id and e.payload.get("periodic")]
    assert len(ticks) == 6
    assert sum(float(e.payload["amount"]) for e in ticks) == pytest.approx(71.0)


def test_g26_generic_policy_search_selects_real_builder_finisher_threshold_and_l23_can_still_prefer_claw_spam():
    # L25 is the architectural proof: the generic search selects a real Rip threshold.
    r25 = build_partial_generic_records(class_names=("Druid",), selected_level=25)[0]
    probe25 = r25.provenance["combo_point_policy_probe"]
    assert r25.capability["target_bound_resource_runtime"] is True
    assert r25.capability["builder_finisher_policy_search"] is True
    assert probe25["selected_combo_point_threshold"] == pytest.approx(3.0)
    assert probe25["selected_seconds_per_mob"] == pytest.approx(17.0)
    assert "claw:20" in probe25["selected_action_ids"]
    assert "rip:20" in probe25["selected_action_ids"]
    threshold_scores = {
        int(row["combo_point_threshold"]): float(row["seconds_per_mob"])
        for row in probe25["threshold_results"]
        if row["action_ids"] == ["claw:20", "rip:20"]
    }
    assert len(set(threshold_scores.values())) > 1

    # User-observed L23 Claw spam is allowed to win naturally; the search is not forced to use a finisher.
    r23 = build_partial_generic_records(class_names=("Druid",), selected_level=23)[0]
    probe23 = r23.provenance["combo_point_policy_probe"]
    assert probe23["selected_combo_point_threshold"] is None
    assert probe23["selected_action_ids"] == ["claw:20"] * 5
    assert probe23["selected_seconds_per_mob"] == pytest.approx(15.0)


def test_g26_resource_wait_is_generic_and_policy_runtime_has_no_class_dispatch():
    ir = build_game_ir_slice(class_key="Druid", level=25)
    policy = next(p for p in ir.policies if p.provenance.get("g26_scope") == "builder_finisher_threshold_seed")
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    target = TargetState.with_health("g26-policy", representative_hp(25))
    runtime = CombatRuntime(actor=actor, target=target, auto_attacks=ir.auto_attacks)
    entry = next(a for a in ir.actions if a.id == policy.provenance["entry_action_id"])
    runtime.schedule_action(entry)
    runtime.advance_to(actor.gcd_ready_s)
    execution = execute_priority_policy(policy=policy, actions=ir.actions, runtime=runtime, max_actions=256)
    assert execution.timeline.target_defeated is True
    assert any(e.kind == "ResourceRegenerated" and e.payload.get("resource_id") == "energy" for e in execution.timeline.events)

    runtime_source = Path("src/game/runtime/simulator.py").read_text(encoding="utf-8").lower()
    policy_source = Path("src/game/policy.py").read_text(encoding="utf-8").lower()
    assert "druid" not in runtime_source
    assert "claw" not in runtime_source
    assert "rip" not in runtime_source
    assert "druid" not in policy_source
    assert "claw" not in policy_source
    assert "rip" not in policy_source


def test_g26_listener_publishes_target_bound_combo_point_search():
    r = build_partial_generic_records(class_names=("Druid",), selected_level=25)[0]
    assert "target_bound_resource_runtime" not in r.unsupported_mechanics
    assert "builder_finisher_policy_search" not in r.unsupported_mechanics
    probe = r.provenance["combo_point_policy_probe"]
    assert probe["legacy_fallback"] is False
    assert probe["target_bound_resource_ids"] == ["combo_points"]
    assert "Generic target-bound combo points + finisher search" in DECISIONS_HTML
    assert "function genericComboPointSummary(r)" in DECISIONS_HTML
