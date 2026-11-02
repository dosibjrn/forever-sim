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


def measured_p7_dps_proximity(gate: str, report: dict) -> dict | None:
    """P7 DPS-objective closeness; NEVER the full gate's functional success%.

    A selected native↔world execution must have actually produced the measured
    score on the pinned report. Earlier UI/legality/holdout requirements can
    still BLOCK the gate. No 10000-iteration prerequisite is created here.
    """
    if gate not in ("P7.1", "P7.2", "P7.3", "P7.4", "P7.5"):
        return None
    if not isinstance(report, dict) or report.get("status") not in ("FAIL", "BLOCKED", "PASS"):
        return None
    if report.get("production_engine") != "pinned_mythicsim_rust_gsim_2d":
        return None
    if not (report.get("source_request_raw_sha256")
            and report.get("native_source_revision")
            and type(report.get("world_damage_events")) is int
            and report["world_damage_events"] > 0
            and type(report.get("world_boundaries")) is int
            and report["world_boundaries"] > 0):
        return None

    reference = report.get("saved_reference_dps")
    if type(reference) not in (int, float) or not isfinite(reference) or reference <= 0:
        return None

    if gate == "P7.5":
        actual = report.get("holdout_mean_dps")
        # Required comparator is the *strongest accepted compatible prior*,
        # not whichever unverified trial happens to have the largest DPS.
        prior = report.get("strongest_accepted_compatible_prior_dps")
        if (type(prior) not in (int, float) or not isfinite(prior)
                or prior <= 0):
            return None
        required = max(float(reference), .99 * prior)
    else:
        actual = report.get("world_dps") if gate == "P7.1" else report.get("winner_live_dps")
        required = float(reference) * (.99 if gate in ("P7.2", "P7.3", "P7.4") else 1.)
    if type(actual) not in (int, float) or not isfinite(actual) or actual < 0:
        return None

    c = min(1., float(actual) / required)
    return {
        "dps_objective_actual": round(float(actual), 4),
        "dps_objective_required": round(required, 4),
        "dps_objective_proximity_percent": round(100 * c, 2),
        "dps_objective_pareto_effort_estimate_percent": round(
            100 * pareto_effort_fraction(c), 2),
        "dps_objective_scope": "COUPLED_LIVE_REFERENCE_DPS_ONLY",
        "dps_objective_provisional": True,
        "dps_objective_gate_pass": False,
    }
