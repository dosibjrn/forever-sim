from __future__ import annotations

"""Shared DecisionResult publication pipeline for every Forever search strategy."""

from typing import Any, Mapping, Sequence

from .class_model import ClassModel, LevelFrontier
from .decision_artifacts import write_frontier
from .decision_result import publish as publish_decision_result, solve_routes
from .route_constraint import RouteConstraint
from .dual_spec import publish_for_class as publish_dual_spec


def publish_decisions(
    *,
    class_name: str,
    canonical_frontiers: Sequence[LevelFrontier],
    model: ClassModel,
    presentation_frontier: Mapping[str, Any],
    verified_level_cap: int,
    targets: Sequence[int],
    target_level: int,
    dual_spec_unlock_level: int = 40,
    unconstrained_max_respecs: int = 0,
    constrained_max_respecs: int = 0,
    constraints: Mapping[str, RouteConstraint | Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Publish diagnostics + canonical routes without a second route selector."""
    frontier_file = write_frontier(class_name, dict(presentation_frontier))
    decision_result = solve_routes(
        canonical_frontiers,
        model=model,
        class_name=str(class_name),
        targets=targets,
        unconstrained_max_respecs=max(0, int(unconstrained_max_respecs)),
        constrained_max_respecs=max(0, int(constrained_max_respecs)),
        constraints=constraints,
    )
    endpoint_file, regret_file, routes, regrets = publish_decision_result(
        decision_result, verified_level_cap=int(verified_level_cap),
    )
    dual_file, dual = publish_dual_spec(
        class_name, int(verified_level_cap), decision_result,
        unlock_level=int(dual_spec_unlock_level), target_level=int(target_level),
    )
    return {
        "decision_result": decision_result,
        "decision_frontier_json": str(frontier_file),
        "endpoint_paths_json": str(endpoint_file),
        "spec_regret_json": str(regret_file),
        "dual_spec_json": str(dual_file),
        "dual_spec": dual,
        "routes": routes,
        "regrets": regrets,
        "frontier": dict(presentation_frontier),
        "decision_authority": decision_result.authority,
    }
