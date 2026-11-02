"""P6 first live production contact: cold source searches plus paid 100-mob replays.

The bounded calls share the actual P4/P5 search, full source build rebuild and
persistent CombatRuntime. They are only a provisional diagnostic of P6's two
independent replay legs: the accepted 30s/300s optimizer winners and selected
hybrid native/world backend must still be tested before a whole-gate PASS.
No saved search reports, independent simulator, synthetic mobs or fake PASS.
"""
from __future__ import annotations

from pathlib import Path


def _mob_kills(row: dict) -> int:
    """Only real kills reported by the paid persistent 100-mob executor count."""
    if not isinstance(row, dict):
        return 0
    amount = row.get("mob_completed", row.get("count", 0))
    if type(amount) is not int or not 0 <= amount <= 100:
        return 0
    if row.get("status") == "COMPLETE" and amount != 100:
        return 0
    return amount


def _replay_first_paid_winner(search, *, source_ir, seed_stage, class_key, level):
    from src.v2.source_bounded_joint_frontier import replay_joint_shortlist_100mob

    shortlist = search.get("validation_shortlist") or []
    if not shortlist:
        return {"status": "NO_SOURCE_PAID_FINALIST", "mob_completed": 0}
    # Exactly one fully specified cold-generated winner is freshly rebuilt.
    # No replay of a screen score, no saved stage, no repeated ranking oracle.
    selected = {**search, "validation_shortlist": shortlist[:1]}
    replay = replay_joint_shortlist_100mob(
        selected, source_ir=source_ir, seed_stage=seed_stage,
        class_key=class_key, level=level,
        bonus_talent_points=search["bonus_talent_points"],
        pack_size=search["pack_size"], max_per_candidate_wall_s=25.)
    rows = replay.get("rows") or []
    if not rows:
        return {"status": "NO_COMPLETED_REPLAY", "mob_completed": 0}
    row = rows[0]
    return {
        "status": row.get("status", "UNKNOWN"),
        "mob_completed": _mob_kills(row),
        "count": row.get("count"),
        "mean_s_per_mob": row.get("full_s_per_mob"),
        "events": row.get("events", 0),
        "reason": row.get("reason"),
    }


def run_live(root: Path, class_key: str, level: int, *,
             spec: str = "unrestricted") -> dict:
    # Full 30/300s paid searches are deliberately explicit, never hourly.
    # This is the SAME source-paid production runner, not a gate-only scorer.
    import os
    if os.environ.get("FOREVER_P6_FULL_SOURCE_COMPARE") == "1":
        from tools.wf_gate_p6_full_source import run_full_source_comparison
        return run_full_source_comparison(root, class_key, level, spec=spec)

    from src.game.data.forever.registry import build_game_ir_slice
    from src.game.data.forever.gear import available_gear_roles
    from src.v2.source_bounded_joint_frontier import (
        source_cold_start_stage, search_bounded_joint_frontier)

    if spec != "unrestricted":
        return {"status": "BLOCKED",
                "reasons": ["P6_SOURCE_SPEC_TREE_SEARCH_CONSTRAINT_NOT_YET_CONNECTED"]}
    ir = build_game_ir_slice(class_key=class_key, level=level)
    roles = available_gear_roles(class_key)
    if ir is None or not roles:
        return {"status": "BLOCKED",
                "reasons": ["P6_SOURCE_COLD_SEARCH_IR_OR_GEAR_ROLE_UNAVAILABLE"]}
    seed = source_cold_start_stage(
        class_key=class_key, level=level, source_ir=ir, gear_role=roles[0])
    results = []
    for budget in (4., 6.):
        # Independent cold starts; these are NOT the full approved 30/300s.
        # Reuse the existing paid 2D controller, never a gate-specific scorer.
        search = search_bounded_joint_frontier(
            class_key=class_key, level=level, source_ir=ir, seed_stage=seed,
            bonus_talent_points=None, max_talents=8, max_gear_moves=12,
            max_policies=4, max_recovery_policies=2, max_paid_builds=32,
            max_cpu_s=budget, per_candidate_wall_s=.75,
            screen_mobs=2, finalist_mobs=100, pack_size=2,
            search_only=True, screen_evaluator_backend="direct",
            refinement_rounds=0)
        paid = int(search.get("screen_complete_candidates") or 0)
        if paid:
            try:
                row = _replay_first_paid_winner(
                    search, source_ir=ir, seed_stage=seed,
                    class_key=class_key, level=level)
            except (ValueError, RuntimeError, KeyError, TypeError) as exc:
                row = {"status": "SOURCE_REPLAY_REJECTED",
                       "mob_completed": 0, "reason": type(exc).__name__ + ":" + str(exc)[:160]}
        else:
            row = {"status": "NO_COMPLETE_PAID_SCREEN", "mob_completed": 0}
        results.append({"cold_search_budget_s": budget,
                        "paid_screens": paid, **row})
    verified = sum(_mob_kills(row) for row in results)
    both = all(row["status"] == "COMPLETE" and row["mob_completed"] == 100
               and isinstance(row.get("mean_s_per_mob"), (int, float))
               and row["mean_s_per_mob"] > 0 for row in results)
    ratio = (results[0]["mean_s_per_mob"] / results[1]["mean_s_per_mob"]
             if both else None)
    reasons = ["P6_FULL_INDEPENDENT_30S_300S_WINNERS_NOT_EXECUTED",
               "P6_SELECTED_NATIVE_2D_BACKEND_NOT_VERIFIED"]
    if not both:
        reasons.append("P6_INCOMPLETE_SOURCE_PAID_100MOB_REPLAY")
    return {
        "status": "FAIL", "reasons": reasons,
        "production_engine": "gsim_CombatRuntime",
        "production_component": "src.v2.source_bounded_joint_frontier.replay_joint_shortlist_100mob",
        "source_replay_results": results,
        "source_replay_Tfirst_Tsecond": ratio,
        "source_replay_numeric_saturation": bool(ratio is not None and ratio <= 1.01),
        "full_p6_selected_backend_acceptance": False,
        "coverage_scope_complete": False,
        # Genuine sequential mob kills on TWO independently built candidates,
        # not candidate/sample inventory. Strictly provisional: those two
        # candidates are not yet approved 30s/300s winners.
        **({"pass_count": verified,
            "reachability_count": 200,
            "behavior_probes_executed": sum(int(row.get("paid_screens", 0)) for row in results),
            "coverage_basis": "executed_behavior_assertions",
            "partial_scope": "TWO_COLD_SOURCE_CANDIDATE_PAID_100MOB_REPLAY_KILLS",
            } if verified > 0 else {}),
    }
