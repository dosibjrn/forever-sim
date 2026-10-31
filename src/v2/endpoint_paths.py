from __future__ import annotations

"""Named endpoint-route paths and regret over the preserved frontier."""

import argparse
import json
from pathlib import Path
from typing import Callable

from src.class_registry import class_names, get_definition

from .decision_artifacts import (
    DECISION_ROOT, MILESTONE_LEVELS, bounded_candidate, frontier_path,
    read_json, update_scoped,
)


ROUTE_DEFINITIONS_VERSION = 1


def _transitions(candidate: dict) -> list[dict]:
    """Compress a full path into the points where the player changes something."""
    fields = ("talent_family", "combat_profile", "gear", "pull_size", "rotation", "policy", "aura", "mana_plan")
    out: list[dict] = []
    previous: dict = {}
    for step in candidate.get("steps", ()):
        current = {key: step.get(key) for key in fields if step.get(key) is not None}
        changed = {key: value for key, value in current.items() if previous.get(key) != value}
        if step.get("talent_added") is not None:
            changed["talent_added"] = step["talent_added"]
        if not out or changed:
            out.append({"level": int(step["level"]), "allocation": step.get("allocation"), "changes": changed})
        previous = current
    return out


def route_definitions(class_name: str) -> dict[str, dict]:
    """Return registry-declared endpoint routes for one Forever class."""
    return {str(k): dict(v) for k, v in get_definition("forever", class_name).route_definitions.items()}


def candidate_matches(candidate: dict, definition: dict) -> bool:
    minimum = int(definition.get("minimum", 1))
    if definition.get("kind") == "talent":
        return int((candidate.get("talent_ranks") or {}).get(definition.get("talent"), 0)) >= minimum
    if definition.get("kind") == "tree_points":
        return int((candidate.get("tree_points") or {}).get(definition.get("tree"), 0)) >= minimum
    return False


def _best(candidates: list[dict]) -> dict | None:
    eligible = [c for c in candidates if c.get("cumulative_objective_s") is not None]
    return min(eligible, key=lambda c: (float(c["cumulative_objective_s"]), float(c.get("score_s_per_100", 1e99)))) if eligible else None


def _verification(target: int, verified_level_cap: int) -> dict:
    cap = int(verified_level_cap or 0)
    target = int(target)
    above = bool(cap and target > cap)
    return {
        "verified_level_cap": cap,
        "verification_status": "provisional_above_verified_cap" if above else "verified_range",
        "uses_unverified_levels": above,
        "unverified_from_level": (cap + 1) if above else None,
    }


def analyze_frontier(frontier: dict, *, targets=MILESTONE_LEVELS) -> tuple[dict, dict]:
    class_name = str(frontier.get("class") or "unknown")
    verified_level_cap = int(frontier.get("verified_level_cap", 0) or 0)
    by_level = {int(row.get("level", -1)): row for row in frontier.get("levels", ())}
    definitions = route_definitions(class_name)
    route_report = {
        "schema_version": 1,
        "ruleset": "forever",
        "class": class_name,
        "route_definitions_version": ROUTE_DEFINITIONS_VERSION,
        "definitions": definitions,
        "targets": {},
        "level_curve": [],
        "authority": "best_preserved_frontier_path",
        "verified_level_cap": verified_level_cap,
    }
    regret_report = {
        "schema_version": 1,
        "ruleset": "forever",
        "class": class_name,
        "basis": "preserved cumulative leveling objective",
        "targets": {},
        "level_curve": [],
        "verified_level_cap": verified_level_cap,
    }
    # A compact point for every computed level powers a true regret curve without
    # duplicating the large path-step payload at every x coordinate.
    for level, level_row in sorted(by_level.items()):
        candidates = list(level_row.get("candidates") or ())
        unconstrained = _best(candidates)
        if unconstrained is None:
            continue
        base_s = float(unconstrained["cumulative_objective_s"])
        base_mph = float(unconstrained.get("mobs_per_hour") or 0.0)
        point = {"level": level, **_verification(level, verified_level_cap), "routes": {"unconstrained": {
            "status": "available", "regret_seconds": 0.0, "regret_percent": 0.0,
            "target_level_mobs_per_hour_delta": 0.0,
        }}}
        for name, definition in definitions.items():
            chosen = _best([c for c in candidates if candidate_matches(c, definition)])
            if chosen is None:
                point["routes"][name] = {"status": "not_preserved"}
                continue
            objective_s = float(chosen["cumulative_objective_s"])
            delta = objective_s - base_s
            point["routes"][name] = {
                "status": "available", "regret_seconds": delta,
                "regret_percent": (100.0 * delta / base_s) if base_s > 0 else 0.0,
                "target_level_mobs_per_hour_delta": float(chosen.get("mobs_per_hour") or 0.0) - base_mph,
                "allocation": chosen.get("allocation"),
            }
        route_report["level_curve"].append(point)
        regret_report["level_curve"].append(point)
    for target in targets:
        level_row = by_level.get(int(target))
        if not level_row:
            missing = {"status": "not_available_in_frontier", "target_level": int(target), **_verification(target, verified_level_cap)}
            route_report["targets"][str(target)] = missing
            regret_report["targets"][str(target)] = missing
            continue
        candidates = list(level_row.get("candidates") or ())
        unconstrained = _best(candidates)
        if unconstrained is None:
            missing = {"status": "no_preserved_candidates", "target_level": int(target), **_verification(target, verified_level_cap)}
            route_report["targets"][str(target)] = missing
            regret_report["targets"][str(target)] = missing
            continue
        base_s = float(unconstrained["cumulative_objective_s"])
        base_mph = float(unconstrained.get("mobs_per_hour") or 0.0)
        routes = {
            "unconstrained": {
                "status": "available", "definition": {"kind": "unconstrained"},
                "path": bounded_candidate(unconstrained, include_steps=True),
                "transitions": _transitions(unconstrained),
            }
        }
        regrets = {
            "unconstrained": {
                "status": "available", "objective_seconds": base_s,
                "regret_seconds": 0.0, "regret_percent": 0.0,
                "target_level_mobs_per_hour_delta": 0.0,
            }
        }
        for name, definition in definitions.items():
            chosen = _best([c for c in candidates if candidate_matches(c, definition)])
            if chosen is None:
                routes[name] = {"status": "not_preserved", "definition": definition}
                regrets[name] = {"status": "not_preserved"}
                continue
            objective_s = float(chosen["cumulative_objective_s"])
            delta = objective_s - base_s
            routes[name] = {
                "status": "available", "definition": definition,
                "path": bounded_candidate(chosen, include_steps=True),
                "transitions": _transitions(chosen),
            }
            regrets[name] = {
                "status": "available", "objective_seconds": objective_s,
                "regret_seconds": delta,
                "regret_percent": (100.0 * delta / base_s) if base_s > 0 else 0.0,
                "target_level_mobs_per_hour_delta": float(chosen.get("mobs_per_hour") or 0.0) - base_mph,
            }
        route_report["targets"][str(target)] = {
            "status": "available", "target_level": int(target), **_verification(target, verified_level_cap), "routes": routes,
        }
        regret_report["targets"][str(target)] = {
            "status": "available", "target_level": int(target), **_verification(target, verified_level_cap), "routes": regrets,
        }
    return route_report, regret_report


def publish_for_class(class_name: str, frontier: dict | None = None) -> tuple[Path, Path, dict, dict]:
    frontier = frontier or read_json(frontier_path(class_name), {}) or {}
    routes, regrets = analyze_frontier(frontier)
    rp = update_scoped(DECISION_ROOT / "endpoint_paths.json", class_name, routes)
    gp = update_scoped(DECISION_ROOT / "spec_regret.json", class_name, regrets)
    return rp, gp, routes, regrets


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Analyze named endpoint routes from a bounded decision frontier")
    ap.add_argument("--class", dest="class_name", choices=class_names("forever"), required=True)
    args = ap.parse_args(argv)
    rp, gp, routes, _ = publish_for_class(args.class_name)
    print(json.dumps({"routes": str(rp), "regret": str(gp), "targets": routes.get("targets", {})}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
