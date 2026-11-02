"""P4/P5 short diagnostic on the existing cold, source-paid whole-build search.

Only counted partial unit: a sourced eligible equipment slot for which a
COMPLETE paid production CombatRuntime candidate actually exercised a source
action. This is a narrow, provisional gear-axis subset of P4/P5; it cannot
be mistaken for a full 30/300s+100mob gate acceptance.

No saved report is read; there is no second optimizer or gate-only engine.
"""
from __future__ import annotations

from pathlib import Path


def paid_gear_slot_coverage(search: dict) -> dict:
    """Derive a comparable real paid coverage fraction, not candidate count."""
    slots = search.get("source_slot_proposal_coverage") or {}
    eligible = set(slots.get("eligible_slots") or ())
    attempted = set(slots.get("paid_slots") or ())
    if not eligible:
        return {"verified": 0, "applicable": 0, "executed": 0,
                "reason": "NO_SOURCE_ELIGIBLE_EQUIPMENT_SLOTS"}
    # The paid_slots field is derived from real evaluated build identities
    # by source_bounded_joint_frontier. A paid candidate may still be rejected
    # or non-completing; count ONLY meaningful completed runtime screens.
    completed = [r for r in search.get("rows", ())
                 if r.get("screen_invoked")
                 and r.get("screen_status") == "COMPLETE"
                 and sum(int(n) for n in (r.get("source_action_counts") or {}).values()) > 0]
    verified = set()
    for row in completed:
        label = str(row.get("gear_move") or "")
        slot = label.split(":", 1)[0]
        if slot in eligible and slot in attempted:
            verified.add(slot)
    return {"verified": len(verified), "applicable": len(eligible),
            "executed": len(completed),
            "paid_slots": sorted(verified),
            "eligible_slots": sorted(eligible)}


def paid_source_action_coverage(search: dict, source_actions) -> dict:
    """Actual sourced actions cast in COMPLETE paid production screens.

    Use the production GameIR action universe as the denominator; neither
    candidate count nor explored gear slots contribute. This is a provisional
    source-policy functional slice of P4/P5, not independent search acceptance.
    A single completed source-action cast is useful, no 30/300s holdout required.
    """
    eligible = {str(a.id) for a in source_actions if getattr(a, "id", None)}
    complete = [row for row in search.get("rows", ())
                if row.get("screen_invoked")
                and row.get("screen_status") == "COMPLETE"]
    used = set()
    for row in complete:
        used.update(str(k) for k, n in
                    (row.get("source_action_counts") or {}).items()
                    if type(n) is int and n > 0)
    return {"verified": len(eligible & used), "applicable": len(eligible),
            "executed": len(complete)}


def run_paid_partial(root: Path, class_key: str, level: int, *,
                     spec: str, gate: str, budget_s: float = 6.) -> dict:
    if gate not in ("P4", "P5"):
        raise ValueError("UNSUPPORTED_LEVELING_SEARCH_GATE")
    if spec != "unrestricted":
        return {"status": "BLOCKED", "reasons": [
            "SOURCE_SPEC_TREE_SEARCH_CONSTRAINT_NOT_YET_CONNECTED"],
            "production_engine": "gsim_CombatRuntime"}
    from src.game.data.forever.registry import build_game_ir_slice
    from src.game.data.forever.gear import available_gear_roles
    from src.v2.source_bounded_joint_frontier import (
        source_cold_start_stage, search_bounded_joint_frontier)

    ir = build_game_ir_slice(class_key=class_key, level=level)
    roles = available_gear_roles(class_key)
    if ir is None or not roles:
        return {"status": "BLOCKED", "reasons": [
            "SOURCE_COLD_SEARCH_IR_OR_GEAR_ROLE_UNAVAILABLE"]}
    # The legal role only seeds equipment. It does not seed a talent, APL,
    # gear optimizer winner or previous run. Current native 2D integration
    # remains a separate gating dependency (gsim result is diagnostic).
    role = roles[0]
    seed = source_cold_start_stage(
        class_key=class_key, level=level, source_ir=ir, gear_role=role)
    search = search_bounded_joint_frontier(
        class_key=class_key, level=level, source_ir=ir, seed_stage=seed,
        bonus_talent_points=None,
        max_talents=8, max_gear_moves=12, max_policies=4,
        max_recovery_policies=2, max_paid_builds=32,
        max_cpu_s=float(budget_s), per_candidate_wall_s=.75,
        screen_mobs=2, finalist_mobs=100, pack_size=2,
        search_only=True, screen_evaluator_backend="direct",
        refinement_rounds=0)
    counts = paid_gear_slot_coverage(search)
    # Explored gear slots are search BREADTH, not correctly functioning
    # behavioral assertions. They must never be a gate success percentage.
    # P4/P5 do have an actual sourced functional requirement: talent-unlocked
    # actions must be cast in a completed paid CombatRuntime screen.
    unlocked = search.get("p4_talent_unlock_coverage") or {}
    verified_unlocks = sum(
        (row.get("status") == "EXECUTED_IN_COMPLETE_PAID_SCREEN"
         and int(row.get("executed_casts") or 0) > 0
         and int(row.get("complete_paid_screens") or 0) > 0)
        for row in unlocked.values()
    )
    actions = paid_source_action_coverage(search, ir.actions)
    reasons = [
        gate + "_FULL_SEARCH_AND_INDEPENDENT_100MOB_NOT_EXECUTED",
        gate + "_SELECTED_NATIVE_2D_COMPATIBILITY_NOT_VERIFIED"]
    if counts["executed"] == 0:
        reasons.append("NO_COMPLETE_SOURCE_PAID_RUNTIME_SCREENS")
    return {
        "status": "FAIL",
        "reasons": reasons,
        "production_component": "src.v2.source_bounded_joint_frontier.search_bounded_joint_frontier",
        "production_engine": "gsim_CombatRuntime",
        # This is the observed source-legal search BREADTH, never success%.
        "explored_paid_gear_slots": counts["verified"],
        "source_eligible_gear_slot_count": counts["applicable"],
        # Direct runtime contact with the source-legal action universe.
        # This grants the first positive PARTIAL on one genuine completed
        # paid source-action screen, without requiring a talent unlock.
        # It is still only a narrow, provisional part of P4/P5.
        **({
            "reachability_count": actions["applicable"],
            "pass_count": actions["verified"],
            "behavior_probes_executed": actions["executed"],
            "partial_scope": "SOURCE_ACTIONS_CAST_IN_COMPLETE_PAID_SCREEN",
            "coverage_basis": "executed_behavior_assertions",
        } if actions["applicable"] and actions["executed"] else {}),
        "real_talent_unlocked_actions_cast": verified_unlocks,
        "coverage_scope_complete": False,
        "paid_source_gear_slots": counts["paid_slots"],
        "source_eligible_gear_slots": counts["eligible_slots"],
        "real_paid_unique_full_builds": search["unique_full_builds"],
        "real_paid_screen_complete": search["screen_complete_candidates"],
        "real_source_unlock_coverage": search["p4_talent_unlock_coverage"],
        "diagnostic_wall_s": search["wall_s"],
        "required_full_search_s": (30 if gate == "P4" else 300),
        "source_role": role,
        "selected_backend_integration_pending": True,
    }
