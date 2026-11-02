"""One canonical calculation of LIVE gate coverage and per-gate 80/20.

Only executed, comparable production behavior is counted.  A source inventory,
a provider module, a prepared APL, or a BLOCKED gate is not a measurement.
This is a diagnostic calculation, not a PASS oracle or a state ledger.
"""
from __future__ import annotations

from math import isfinite


def pareto_effort_fraction(coverage: float) -> float:
    """Illustrative effort curve for a *single* checkpoint-gate's coverage."""
    coverage = float(coverage)
    if not isfinite(coverage) or not 0 <= coverage <= 1:
        raise ValueError("COVERAGE_OUT_OF_RANGE")
    return 0.25 * coverage if coverage <= 0.8 else 0.20 + 4 * (coverage - 0.8)


def measured_live_coverage(report: dict) -> dict | None:
    """Compute a defensible within-gate percentage from fresh runtime evidence.

    May return 100% for one *bounded subcomponent* while the enclosing gate
    still FAILs. The component/scope flags MUST travel with its percentages;
    neither 100% component coverage nor this 80/20 estimate is gate PASS.
    """
    if not isinstance(report, dict) or report.get("status") not in ("FAIL", "PASS"):
        return None
    # A completed paid *screen*, a visited gear slot, and a stochastic
    # sample size are NOT successes of a gate's real behavioral predicates.
    # The provider must count individually asserted, functioning behaviors.
    # This marker alone is never enough: the executed-probe check below,
    # source-backed positive/negative regression tests and Merge review
    # must all hold. No arbitrary metadata-only progress is allowed.
    if report.get("coverage_basis") != "executed_behavior_assertions":
        return None
    n, d = report.get("pass_count"), report.get("reachability_count")
    if not (type(n) is int and type(d) is int and 0 <= n <= d and d > 0):
        return None
    probes = report.get("behavior_probes_executed")
    proof = report.get("runtime_proof") or {}
    if not ((type(probes) is int and probes > 0)
            or (isinstance(proof, dict) and proof.get("executed") is True)):
        return None
    coverage = n / d
    scope = (report.get("partial_scope") or report.get("coverage_component")
             or "COMPARABLE_EXECUTED_BEHAVIOR_SUBTESTS")
    provisional = bool(
        report.get("scope_provisional") is True
        or report.get("unresolved_count")
        or report.get("source_spec_profile_verified") is False
        or report.get("coverage_scope_complete") is not True
    )
    return {
        "verified": n,
        "applicable": d,
        "partial_coverage_percent": round(100 * coverage, 2),
        "pareto_effort_estimate_percent": round(
            100 * pareto_effort_fraction(coverage), 2),
        "coverage_component": str(scope),
        "scope_provisional": provisional,
    }
