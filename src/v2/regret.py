from __future__ import annotations

"""Central regret metric contract for canonical leveling decisions.

Regret is always the objective cost of a constrained route relative to the
unrestricted optimum solved from the same canonical frontier/DP authority.
This module owns the arithmetic so publication, service queries and listener
views cannot drift into subtly different definitions.
"""

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class RegretMetrics:
    baseline_route: str
    constrained_route: str
    baseline_objective_s: float
    constrained_objective_s: float
    regret_seconds: float
    regret_percent: float
    constraint_label: str
    constraint_kind: str
    constraint_source: str
    authority: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "available",
            "baseline_route": self.baseline_route,
            "constrained_route": self.constrained_route,
            "baseline_objective_seconds": self.baseline_objective_s,
            "objective_seconds": self.constrained_objective_s,
            "regret_seconds": self.regret_seconds,
            "regret_percent": self.regret_percent,
            "constraint_label": self.constraint_label,
            "constraint_kind": self.constraint_kind,
            "constraint_source": self.constraint_source,
            "regret_authority": self.authority,
        }


def constraint_identity(name: str, definition: Mapping[str, Any] | None = None) -> tuple[str, str, str]:
    definition = dict(definition or {})
    if name == "unconstrained":
        return "Unconstrained optimum", "unconstrained", "canonical"
    label = str(definition.get("label") or name)
    kind = str(definition.get("kind") or ("generic_constraint" if definition else "named_route"))
    source = str(definition.get("source") or ("route_registry" if kind != "generic_constraint" else "user_constraint"))
    return label, kind, source


def compute_regret(*, baseline_objective_s: float, constrained_objective_s: float,
                   constrained_route: str, definition: Mapping[str, Any] | None = None,
                   authority: str = "canonical_level_frontier_dp",
                   baseline_route: str = "unconstrained") -> RegretMetrics:
    base = float(baseline_objective_s)
    chosen = float(constrained_objective_s)
    # Same-authority constrained search cannot legitimately beat unrestricted.
    # Tiny floating-point noise is clamped; a material negative value is a
    # correctness violation rather than a negative-regret feature.
    delta = chosen - base
    tolerance = max(1e-9, abs(base) * 1e-12)
    if delta < -tolerance:
        raise ValueError(
            f"constrained objective {chosen:.9f}s beats unrestricted {base:.9f}s; "
            "regret requires the same canonical scorer/frontier"
        )
    delta = max(0.0, delta)
    label, kind, source = constraint_identity(str(constrained_route), definition)
    return RegretMetrics(
        baseline_route=str(baseline_route), constrained_route=str(constrained_route),
        baseline_objective_s=base, constrained_objective_s=chosen,
        regret_seconds=delta, regret_percent=(100.0 * delta / base if base > 0 else 0.0),
        constraint_label=label, constraint_kind=kind, constraint_source=source,
        authority=str(authority),
    )
