from __future__ import annotations

"""Canonical route/decision authority.

The search layer produces retained ``LevelFrontier`` objects.  This module is
the *only* place that turns those frontiers into unconstrained and named
endpoint routes.  Publication consumes the resulting ``DecisionResult``; it
must never re-solve from a smaller presentation frontier.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.class_registry import get_definition
from src.forever_build import metadata as forever_build_metadata
from .class_model import CandidateResult, ClassModel, LevelFrontier
from .decision_artifacts import DECISION_ROOT, bounded_candidate, update_scoped
from .path_dp import LevelNode, PathResult, solve_path_dp
from .route_constraint import RouteConstraint
from .regret import RegretMetrics, compute_regret


@dataclass(frozen=True)
class RouteResult:
    name: str
    target_level: int
    status: str
    definition: Mapping[str, Any] = field(default_factory=dict)
    path: PathResult | None = None
    reason: str | None = None


@dataclass(frozen=True)
class DecisionResult:
    class_name: str
    frontiers: tuple[LevelFrontier, ...]
    targets: Mapping[int, Mapping[str, RouteResult]]
    published_targets: tuple[int, ...] = ()
    authority: str = "canonical_level_frontier_dp"
    regret: Mapping[int, Mapping[str, RegretMetrics]] = field(default_factory=dict)

    @property
    def start_level(self) -> int:
        return min((f.level for f in self.frontiers), default=0)

    @property
    def end_level(self) -> int:
        return max((f.level for f in self.frontiers), default=0)


def _node(candidate: CandidateResult) -> LevelNode:
    return LevelNode(
        level=int(candidate.level), talents=candidate.build,
        score_s_per_100=float(candidate.evaluation.score_s_per_100),
        policy=candidate.policy,
        source=str(candidate.metadata.get("source") or "canonical_frontier"),
        details={"candidate_result": candidate, **dict(candidate.metadata)},
    )


def _candidate_from_step(step) -> CandidateResult | None:
    details = dict(step.node.details or {})
    cand = details.get("candidate_result")
    return cand if isinstance(cand, CandidateResult) else None


def _publication_row(candidate: CandidateResult | None, step) -> dict[str, Any]:
    if candidate is not None:
        row = dict(candidate.metadata.get("publication_row") or {})
        if not row:
            row = {
                "level": int(candidate.level),
                **candidate.evaluation.published_fields(),
            }
    else:
        row = {"level": int(step.node.level), "score_s_per_100": float(step.node.score_s_per_100)}
    row["level"] = int(step.node.level)
    row["kind"] = str(step.kind)
    row["talent_added"] = step.talent_added
    row["respecs_used"] = int(step.respecs_used)
    row["cumulative_objective_s"] = float(step.cumulative_s)
    return row


def _path_candidate(route: RouteResult) -> dict[str, Any]:
    path = route.path
    if path is None or not path.steps:
        return {}
    rows = [_publication_row(_candidate_from_step(step), step) for step in path.steps]
    final = dict(rows[-1])
    final.update({
        "level": int(route.target_level),
        "cumulative_objective_s": float(path.cumulative_s),
        "steps": rows,
        "source": "canonical_decision_result",
    })
    return final


def _transitions(candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    fields = ("talent_family", "combat_profile", "gear", "pull_size", "rotation", "policy", "aura", "mana_plan")
    out: list[dict[str, Any]] = []
    previous: dict[str, Any] = {}
    for step in candidate.get("steps", ()):
        current = {k: step.get(k) for k in fields if step.get(k) is not None}
        changed = {k: v for k, v in current.items() if previous.get(k) != v}
        if step.get("talent_added") is not None:
            changed["talent_added"] = step.get("talent_added")
        if not out or changed:
            out.append({"level": int(step["level"]), "allocation": step.get("allocation"), "changes": changed})
        previous = current
    return out


def solve_routes(
    frontiers: Sequence[LevelFrontier],
    *,
    model: ClassModel,
    class_name: str,
    targets: Sequence[int],
    unconstrained_max_respecs: int = 0,
    constrained_max_respecs: int = 0,
    weights: Mapping[int, float] | None = None,
    constraints: Mapping[str, RouteConstraint | Mapping[str, Any]] | None = None,
) -> DecisionResult:
    """Solve every published route from one canonical retained frontier set."""
    ordered = tuple(sorted(frontiers, key=lambda f: int(f.level)))
    by_level = {int(f.level): tuple(_node(c) for c in f.candidates) for f in ordered}
    definitions = {str(k): dict(v) for k, v in get_definition("forever", class_name).route_definitions.items()}
    generic_constraints: dict[str, RouteConstraint] = {}
    for constraint_name, raw in dict(constraints or {}).items():
        name = str(constraint_name)
        if name in definitions or name == "unconstrained":
            raise ValueError(f"constraint route name collides with canonical route: {name}")
        generic_constraints[name] = raw if isinstance(raw, RouteConstraint) else RouteConstraint.from_mapping(name, raw)
    solved: dict[int, dict[str, RouteResult]] = {}
    published_targets = tuple(sorted(set(int(t) for t in targets)))
    # Solve compact route state at every retained level so regret curves remain
    # available without reintroducing a second publication-side route selector.
    solve_levels = sorted(set(int(f.level) for f in ordered) | set(published_targets))

    for target0 in solve_levels:
        target = int(target0)
        levels = [l for l in sorted(by_level) if l <= target]
        if target not in by_level or not levels:
            missing = {"unconstrained": RouteResult("unconstrained", target, "unavailable", {"kind": "unconstrained"}, reason="target level absent from canonical frontier")}
            missing.update({name: RouteResult(name, target, "unavailable", definition, reason="target level absent from canonical frontier") for name, definition in definitions.items()})
            missing.update({name: RouteResult(name, target, "unavailable", constraint.definition(), reason="target level absent from canonical frontier") for name, constraint in generic_constraints.items()})
            solved[target] = missing
            continue
        pools = {l: by_level[l] for l in levels}
        start = levels[0]
        routes: dict[str, RouteResult] = {}
        try:
            path = solve_path_dp(
                pools, max_respecs=max(0, int(unconstrained_max_respecs)), weights=weights,
                start_level=start, end_level=target, model=model,
            )
            routes["unconstrained"] = RouteResult("unconstrained", target, "available", {"kind": "unconstrained"}, path=path)
        except Exception as exc:
            routes["unconstrained"] = RouteResult("unconstrained", target, "unavailable", {"kind": "unconstrained"}, reason=f"{type(exc).__name__}: {exc}")

        for name, definition in definitions.items():
            eligible = tuple(n for n in by_level[target] if model.route_matches(n.talents, definition))
            if not eligible:
                routes[name] = RouteResult(name, target, "unavailable", definition, reason="no canonical endpoint candidate satisfies route constraint")
                continue
            constrained = dict(pools); constrained[target] = eligible
            try:
                path = solve_path_dp(
                    constrained, max_respecs=max(0, int(constrained_max_respecs)), weights=weights,
                    start_level=start, end_level=target, model=model,
                )
                routes[name] = RouteResult(name, target, "available", definition, path=path)
            except Exception as exc:
                routes[name] = RouteResult(name, target, "unavailable", definition, reason=f"{type(exc).__name__}: {exc}")

        for name, constraint in generic_constraints.items():
            definition = constraint.definition()
            constrained: dict[int, tuple[LevelNode, ...]] = {}
            empty_level: int | None = None
            for level in levels:
                allowed = tuple(n for n in by_level[level] if constraint.allows(n, level=level, target_level=target, model=model))
                if not allowed:
                    empty_level = level
                    break
                constrained[level] = allowed
            if empty_level is not None:
                routes[name] = RouteResult(
                    name, target, "unavailable", definition,
                    reason=f"constraint eliminates canonical candidates at level {empty_level}",
                )
                continue
            try:
                path = solve_path_dp(
                    constrained, max_respecs=max(0, int(constrained_max_respecs)), weights=weights,
                    start_level=start, end_level=target, model=model,
                )
                routes[name] = RouteResult(name, target, "available", definition, path=path)
            except Exception as exc:
                routes[name] = RouteResult(name, target, "unavailable", definition, reason=f"{type(exc).__name__}: {exc}")
        solved[target] = routes

    regret: dict[int, dict[str, RegretMetrics]] = {}
    for target, routes in solved.items():
        base = routes.get("unconstrained")
        if base is None or base.status != "available" or base.path is None:
            continue
        base_s = float(base.path.cumulative_s)
        rows: dict[str, RegretMetrics] = {}
        for name, route in routes.items():
            if route.status != "available" or route.path is None:
                continue
            rows[name] = compute_regret(
                baseline_objective_s=base_s, constrained_objective_s=float(route.path.cumulative_s),
                constrained_route=name, definition=route.definition, authority="canonical_level_frontier_dp",
            )
        regret[int(target)] = rows

    return DecisionResult(
        class_name=str(class_name), frontiers=ordered, targets=solved,
        published_targets=published_targets, regret=regret,
    )


def reports(result: DecisionResult, *, verified_level_cap: int = 0) -> tuple[dict, dict]:
    definitions = {str(k): dict(v) for k, v in get_definition("forever", result.class_name).route_definitions.items()}
    # I15: generic constrained routes are first-class members of the same
    # DecisionResult, so publish their declarative definitions alongside the
    # registry routes rather than hiding them in a tooling-only side channel.
    for routes in result.targets.values():
        for name, route in routes.items():
            if name != "unconstrained" and route.definition:
                definitions.setdefault(str(name), dict(route.definition))
    build = forever_build_metadata()
    fidelity = dict(get_definition("forever", result.class_name).fidelity() or {})
    planning_level_cap = int(fidelity.get("planning_level_cap") or verified_level_cap or 0)
    route_report = {
        "schema_version": 2, "ruleset": "forever", "class": result.class_name, "forever_build": build,
        "route_definitions_version": 1, "definitions": definitions, "targets": {},
        "level_curve": [], "authority": result.authority, "verified_level_cap": int(verified_level_cap or 0),
        "planning_level_cap": planning_level_cap, "model_fidelity": fidelity,
    }
    regret_report = {
        "schema_version": 2, "ruleset": "forever", "class": result.class_name, "forever_build": build,
        "basis": "canonical LevelFrontier + generic route DP", "targets": {}, "level_curve": [],
        "metric_contract": "constrained_vs_unrestricted_v1",
        "authority": result.authority, "verified_level_cap": int(verified_level_cap or 0),
    }
    # Full compact per-level regret curve from the same DecisionResult.
    for level, routes in sorted(result.targets.items()):
        base = routes.get("unconstrained")
        if base is None or base.status != "available" or base.path is None:
            continue
        base_candidate = _path_candidate(base)
        base_s = float(base.path.cumulative_s)
        base_mph = float(base_candidate.get("mobs_per_hour") or 0.0)
        point = {"level": int(level), "routes": {}}
        for name, rr in routes.items():
            if rr.status != "available" or rr.path is None:
                point["routes"][name] = {"status": "unavailable", "reason": rr.reason}
                continue
            candidate = _path_candidate(rr)
            metric = (result.regret.get(int(level), {}) or {}).get(name) or compute_regret(
                baseline_objective_s=base_s, constrained_objective_s=float(rr.path.cumulative_s),
                constrained_route=name, definition=rr.definition, authority=result.authority,
            )
            point["routes"][name] = {
                **metric.as_dict(),
                "target_level_mobs_per_hour_delta": float(candidate.get("mobs_per_hour") or 0.0) - base_mph,
                "allocation": candidate.get("allocation"),
                "authority": result.authority,
            }
        route_report["level_curve"].append(point)
        regret_report["level_curve"].append(point)

    detailed_targets = result.published_targets or tuple(sorted(result.targets))
    for target in detailed_targets:
        routes = result.targets.get(int(target), {})
        base = routes.get("unconstrained")
        base_path = base.path if base and base.status == "available" else None
        base_s = float(base_path.cumulative_s) if base_path is not None else None
        base_candidate = _path_candidate(base) if base is not None and base.status == "available" else {}
        base_mph = float(base_candidate.get("mobs_per_hour") or 0.0)
        route_rows: dict[str, dict] = {}
        regret_rows: dict[str, dict] = {}
        for name, rr in routes.items():
            if rr.status != "available" or rr.path is None:
                route_rows[name] = {"status": "unavailable", "definition": dict(rr.definition), "reason": rr.reason}
                regret_rows[name] = {"status": "unavailable", "reason": rr.reason}
                continue
            candidate = _path_candidate(rr)
            objective = float(rr.path.cumulative_s)
            metric = None if base_s is None else ((result.regret.get(int(target), {}) or {}).get(name) or compute_regret(
                baseline_objective_s=base_s, constrained_objective_s=objective, constrained_route=name,
                definition=rr.definition, authority=result.authority,
            ))
            route_rows[name] = {
                "status": "available", "definition": dict(rr.definition),
                "path": bounded_candidate(candidate, include_steps=True),
                "transitions": _transitions(candidate),
                "authority": result.authority,
            }
            regret_rows[name] = {
                **(metric.as_dict() if metric is not None else {"status": "unavailable"}),
                "target_level_mobs_per_hour_delta": float(candidate.get("mobs_per_hour") or 0.0) - base_mph,
                "authority": result.authority,
            }
        verification = {
            "verified_level_cap": int(verified_level_cap or 0),
            "planning_level_cap": planning_level_cap,
            "verification_status": "provisional_above_verified_cap" if verified_level_cap and target > verified_level_cap else "verified_range",
            "planning_status": ("above_planning_cap" if planning_level_cap and target > planning_level_cap else ("provisional_planning_range" if verified_level_cap and target > verified_level_cap else "verified_range")),
            "uses_unverified_levels": bool(verified_level_cap and target > verified_level_cap),
            "uses_levels_above_planning_cap": bool(planning_level_cap and target > planning_level_cap),
            "unverified_from_level": (int(verified_level_cap) + 1) if verified_level_cap and target > verified_level_cap else None,
        }
        route_report["targets"][str(target)] = {"status": "available", "target_level": target, **verification, "routes": route_rows}
        regret_report["targets"][str(target)] = {"status": "available", "target_level": target, **verification, "routes": regret_rows}
    return route_report, regret_report


def publish(result: DecisionResult, *, verified_level_cap: int = 0) -> tuple[Path, Path, dict, dict]:
    route_report, regret_report = reports(result, verified_level_cap=verified_level_cap)
    rp = update_scoped(DECISION_ROOT / "endpoint_paths.json", result.class_name, route_report)
    gp = update_scoped(DECISION_ROOT / "spec_regret.json", result.class_name, regret_report)
    return rp, gp, route_report, regret_report
