from __future__ import annotations

"""Canonical dual-spec decision derived from one DecisionResult.

I17 deliberately does *not* re-solve a presentation frontier.  The shared
``solve_routes()`` call has already produced legal route paths from the retained
``LevelFrontier`` set.  Dual spec only pairs those canonical paths and chooses
which already-legal spec is active at each level after the configured unlock.

The model used by this project permits switching only at level boundaries once
dual spec is unlocked.  One spec remains active for the whole level; there is no
additional switching-time penalty unless a later ruleset explicitly supplies one.
"""

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from src.class_registry import class_names
from .decision_artifacts import DECISION_ROOT, update_scoped
from .decision_result import DecisionResult, RouteResult

UNLOCK_LEVEL = 40


def _step_rows(route: RouteResult) -> dict[int, dict[str, Any]]:
    if route.path is None:
        return {}
    out: dict[int, dict[str, Any]] = {}
    previous_cumulative = 0.0
    for step in route.path.steps:
        level = int(step.node.level)
        cumulative = float(step.cumulative_s)
        local_objective = max(0.0, cumulative - previous_cumulative)
        previous_cumulative = cumulative
        details = dict(step.node.details or {})
        candidate = details.get("candidate_result")
        publication = dict(getattr(candidate, "metadata", {}).get("publication_row", {}) or {}) if candidate is not None else {}
        out[level] = {
            "level": level,
            "local_objective_s": local_objective,
            "cumulative_objective_s": cumulative,
            "allocation": publication.get("allocation") or details.get("allocation"),
            "talent_family": publication.get("talent_family") or details.get("talent_family"),
            "combat_profile": publication.get("combat_profile") or details.get("combat_profile"),
            "gear": publication.get("gear") or details.get("gear"),
            "pull_size": publication.get("pull_size") or details.get("pull_size"),
            "rotation": publication.get("rotation") or publication.get("policy") or details.get("rotation") or details.get("policy"),
            "score_s_per_100": float(step.node.score_s_per_100),
            "build_key": repr(getattr(candidate, "build", step.node.talents)),
        }
    return out


def _route_identity(name: str, route: RouteResult) -> dict[str, Any]:
    rows = _step_rows(route)
    final = rows[max(rows)] if rows else {}
    return {
        "route": name,
        "definition": dict(route.definition),
        "target_level": int(route.target_level),
        "allocation": final.get("allocation"),
        "talent_family": final.get("talent_family"),
        "combat_profile": final.get("combat_profile"),
        "gear": final.get("gear"),
        "pull_size": final.get("pull_size"),
        "objective_seconds": float(route.path.cumulative_s) if route.path is not None else None,
    }


def _phases(choices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in choices:
        if out and out[-1]["slot"] == row["slot"] and int(out[-1]["end_level"]) + 1 == int(row["level"]):
            out[-1]["end_level"] = int(row["level"])
            continue
        out.append({
            "start_level": int(row["level"]),
            "end_level": int(row["level"]),
            "slot": row["slot"],
            "route": row.get("route"),
            "talent_family": row.get("talent_family"),
            "combat_profile": row.get("combat_profile"),
            "allocation": row.get("allocation"),
        })
    return out


def solve_decision_result(
    result: DecisionResult,
    *,
    unlock_level: int = UNLOCK_LEVEL,
    target_level: int | None = None,
    verified_level_cap: int = 0,
) -> dict[str, Any]:
    """Choose the best pair of canonical route paths from one DecisionResult."""
    unlock = max(1, int(unlock_level))
    target = int(target_level if target_level is not None else result.end_level)
    cap = int(verified_level_cap or 0)
    above_cap = bool(cap and target > cap)
    base = {
        "schema_version": 2,
        "ruleset": "forever",
        "class": str(result.class_name),
        "unlock_level": unlock,
        "target_level": target,
        "verified_level_cap": cap,
        "verification_status": "provisional_above_verified_cap" if above_cap else "verified_range",
        "uses_unverified_levels": above_cap,
        "unverified_from_level": (cap + 1) if above_cap else None,
        "method": "canonical_decision_result_route_pair_v1",
        "authority": result.authority,
        "switch_model": "level_boundaries_only",
        "switch_cost_seconds": 0.0,
    }
    if target < unlock:
        return {**base, "status": "unlock_after_target", "reason": f"unlock level {unlock} is after target {target}", "pair": None}

    routes = result.targets.get(target)
    if not routes:
        return {**base, "status": "target_not_in_decision_result", "pair": None}

    # Pair canonical named routes only. Generic user constraints are challengers,
    # not spec identities, and unconstrained is the baseline rather than a second spec.
    available: list[tuple[str, RouteResult, dict[int, dict[str, Any]]]] = []
    for name, route in sorted(routes.items()):
        if name == "unconstrained" or route.status != "available" or route.path is None:
            continue
        kind = str(route.definition.get("kind") or "")
        if kind == "generic_constraint":
            continue
        rows = _step_rows(route)
        if target in rows:
            available.append((name, route, rows))
    if len(available) < 2:
        return {**base, "status": "insufficient_canonical_routes", "canonical_routes": len(available), "pair": None}

    best_single_name, best_single_route, _ = min(
        available,
        key=lambda row: (float(row[1].path.cumulative_s), row[0]),
    )
    best_single = float(best_single_route.path.cumulative_s)
    best: tuple[tuple[float, str, str], Any] | None = None

    for i, (name_a, route_a, rows_a) in enumerate(available):
        for name_b, route_b, rows_b in available[i + 1:]:
            common = sorted(set(rows_a) & set(rows_b))
            if not common or target not in common:
                continue
            # Before unlock only one spec can be active. Pick the cheaper legal
            # prefix of the two canonical paths. At/after unlock, choose one
            # already-legal route for each whole level; changes therefore occur
            # only on Lx -> Lx+1 boundaries, never between pulls within a level.
            pre_levels = [level for level in common if level < unlock]
            pre_a = sum(float(rows_a[level]["local_objective_s"]) for level in pre_levels)
            pre_b = sum(float(rows_b[level]["local_objective_s"]) for level in pre_levels)
            primary = ("A" if (pre_a, name_a) <= (pre_b, name_b) else "B") if pre_levels else None
            total = min(pre_a, pre_b)
            choices: list[dict[str, Any]] = []
            for level in common:
                if level < unlock or level > target:
                    continue
                a = rows_a[level]; b = rows_b[level]
                if (float(a["local_objective_s"]), name_a) <= (float(b["local_objective_s"]), name_b):
                    slot, route_name, chosen = "A", name_a, a
                else:
                    slot, route_name, chosen = "B", name_b, b
                total += float(chosen["local_objective_s"])
                choices.append({
                    "level": level,
                    "slot": slot,
                    "route": route_name,
                    "local_objective_s": float(chosen["local_objective_s"]),
                    "score_s_per_100": float(chosen["score_s_per_100"]),
                    "allocation": chosen.get("allocation"),
                    "talent_family": chosen.get("talent_family"),
                    "combat_profile": chosen.get("combat_profile"),
                    "gear": chosen.get("gear"),
                    "pull_size": chosen.get("pull_size"),
                    "rotation": chosen.get("rotation"),
                })
            if primary is None and choices:
                primary = str(choices[0]["slot"])
            key = (total, name_a, name_b)
            if best is None or key < best[0]:
                best = (key, name_a, route_a, name_b, route_b, primary or "A", choices)

    if best is None:
        return {**base, "status": "no_distinct_canonical_pair", "pair": None}

    key, name_a, route_a, name_b, route_b, primary, choices = best
    total = float(key[0])
    gain = max(0.0, best_single - total)
    phases = _phases(choices)
    switches = []
    previous_slot = primary
    for phase in phases:
        if phase["slot"] != previous_slot:
            switches.append({
                "level": int(phase["start_level"]),
                "from_slot": previous_slot,
                "to_slot": phase["slot"],
                "to_route": phase.get("route"),
            })
        previous_slot = phase["slot"]
    recommendation = (
        "No post-unlock switch needed; keep the primary spec active."
        if not switches else
        "; ".join(f"L{s['level']}: switch to {s['to_route']} ({s['to_slot']})" for s in switches)
    )
    return {
        **base,
        "status": "available",
        "pair": {"A": _route_identity(name_a, route_a), "B": _route_identity(name_b, route_b)},
        "primary_before_unlock": primary,
        "choices": choices,
        "phases": phases,
        "switches": switches,
        "switch_recommendation": recommendation,
        "objective_seconds": total,
        "best_single_route": best_single_name,
        "best_single_objective_seconds": best_single,
        "gain_seconds": gain,
        "gain_percent": 100.0 * gain / best_single if best_single > 0 else 0.0,
        "canonical_routes_considered": len(available),
        "confidence_note": (
            f"Levels {cap + 1}-{target} use provisional/fallback Forever data; verified snapshot ends at level {cap}."
            if above_cap else
            f"All modeled levels through target {target} are within the verified level cap {cap}."
        ),
    }


def build_status(class_name: str, verified_level_cap: int, result: DecisionResult | None = None,
                 *, unlock_level: int = UNLOCK_LEVEL, target_level: int | None = None) -> dict[str, Any]:
    if result is not None:
        return solve_decision_result(result, unlock_level=unlock_level, target_level=target_level,
                                     verified_level_cap=verified_level_cap)
    target = int(target_level) if target_level is not None else None
    cap = int(verified_level_cap)
    above_cap = bool(target is not None and cap and target > cap)
    return {
        "schema_version": 2, "ruleset": "forever", "class": class_name,
        "unlock_level": int(unlock_level), "target_level": target,
        "verified_level_cap": cap,
        "verification_status": "provisional_above_verified_cap" if above_cap else "verified_range",
        "uses_unverified_levels": above_cap,
        "unverified_from_level": (cap + 1) if above_cap else None,
        "status": "decision_result_unavailable",
        "method": "canonical_decision_result_route_pair_v1",
        "pair": None,
    }


def publish_for_class(class_name: str, verified_level_cap: int, result: DecisionResult | None = None,
                      *, unlock_level: int = UNLOCK_LEVEL, target_level: int | None = None) -> tuple[Path, dict]:
    payload = build_status(class_name, verified_level_cap, result,
                           unlock_level=unlock_level, target_level=target_level)
    path = update_scoped(DECISION_ROOT / "dual_spec.json", class_name, payload)
    return path, payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dual-spec status is published by the canonical decision pipeline")
    ap.add_argument("--class", dest="class_name", choices=class_names("forever"), required=True)
    ap.add_argument("--verified-level-cap", type=int, required=True)
    ap.add_argument("--unlock-level", type=int, default=UNLOCK_LEVEL)
    ap.add_argument("--target", type=int)
    args = ap.parse_args(argv)
    payload = build_status(args.class_name, args.verified_level_cap, None,
                           unlock_level=args.unlock_level, target_level=args.target)
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
