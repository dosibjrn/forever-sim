"""P6 first live production contact: cold source searches plus paid 100-mob replays.

The bounded calls share the actual P4/P5 search, full source build rebuild and
persistent CombatRuntime. They are only a provisional diagnostic of P6's two
independent replay legs: the accepted 30s/300s optimizer winners and selected
hybrid native/world backend must still be tested before a whole-gate PASS.
No saved search reports, independent simulator, synthetic mobs or fake PASS.
"""
from __future__ import annotations

from pathlib import Path
from math import isfinite


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
    if (not isinstance(rows, (list, tuple)) or len(rows) != 1
            or not isinstance(rows[0], dict)):
        # A single shortlisted build must produce exactly one replay receipt.
        # Taking rows[0] silently masks a malformed/duplicated paid evaluation.
        return {"status": "AMBIGUOUS_SOURCE_PAID_REPLAY",
                "mob_completed": 0, "reason": "EXPECTED_ONE_PAID_RESULT_ROW"}
    row = rows[0]
    if row.get("status") == "COMPLETE":
        seconds = row.get("full_s_per_mob")
        if (type(row.get("count")) is not int or row["count"] != 100
                or _mob_kills(row) != 100
                or type(seconds) not in (int, float)
                or not isfinite(seconds) or seconds <= 0):
            # Real complete 100-mob paid scores must be positive and finite;
            # an invalid receipt never contributes saturation or verified mobs.
            return {"status": "INVALID_COMPLETE_PAID_REPLAY",
                    "mob_completed": 0, "count": row.get("count"),
                    "mean_s_per_mob": None,
                    "reason": "EXPECTED_100_KILLS_AND_FINITE_POSITIVE_TIME"}
    return {
        "status": row.get("status", "UNKNOWN"),
        "mob_completed": _mob_kills(row),
        "count": row.get("count"),
        "mean_s_per_mob": row.get("full_s_per_mob"),
        "events": row.get("events", 0),
        "reason": row.get("reason"),
    }


def _complete_finite_paid_replay(row: dict) -> bool:
    """Only one valid completed, timed 100-mob run can enter P6's ratio."""
    seconds = row.get("mean_s_per_mob") if isinstance(row, dict) else None
    return bool(isinstance(row, dict)
        and row.get("status") == "COMPLETE"
        and type(row.get("count")) is int and row["count"] == 100
        and _mob_kills(row) == 100
        and type(seconds) in (int, float)
        and isfinite(seconds) and seconds > 0)


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

    # The full 30/300s source runner already applies this approved product
    # profile. Reuse its source-bound rule in the cheap production diagnostic
    # too; never silently search unrestricted talents under a named spec.
    spec_params = {}
    if spec != "unrestricted":
        from hashlib import sha256
        from src.game.data.forever.sqlite_talents import DEFAULT_DB
        from tools.wf_source_profile import _load_product_spec_profile

        db = Path(DEFAULT_DB)
        if not db.is_file():
            return {"status": "BLOCKED",
                    "reasons": ["P6_SOURCE_ABILITY_DB_MISSING"]}
        profile = _load_product_spec_profile(
            root, class_key, level, spec,
            source_sha256=sha256(db.read_bytes()).hexdigest())
        if profile is None:
            return {"status": "BLOCKED",
                    "reasons": ["P6_SOURCE_SPEC_PRODUCT_PROFILE_NOT_CONFIGURED"]}
        spec_params = {"spec_tree": profile["tree_key"],
                       "min_spec_points": profile["minimum_points"]}
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
            refinement_rounds=0, **spec_params)
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
    both = all(_complete_finite_paid_replay(row) for row in results)
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
        "source_replay_300s_nonregression": bool(ratio is not None
                                              and results[1]["mean_s_per_mob"]
                                              <= 1.01 * results[0]["mean_s_per_mob"]),
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
