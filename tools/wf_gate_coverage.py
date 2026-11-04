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


P7_FINAL_STOCHASTIC_ITERATIONS = 1_000
P7_FINAL_DPS_FLOOR_FRACTION = 0.99  # P7.1-P7.4
P7_5_FINAL_DPS_FLOOR_FRACTION = 0.93

P7_SEARCH_BUDGET_SECONDS = 300.0
P7_SEARCH_OBSERVATION_TOLERANCE_SECONDS = 1.0


def p7_search_window_completed(*, full_search: bool, elapsed_seconds: float) -> bool:
    """Accept the executed 300s cold search by elapsed wall-clock time alone.

    The 1s allowance is for clock observation/scheduling. There is no
    per-candidate final-step timestamp or strict last-step deadline proof.
    Historical production runs with a genuine 300-301s measured search window
    remain comparable when all other gate criteria are met.
    """
    return bool(
        full_search is True
        and type(elapsed_seconds) in (int, float)
        and isfinite(elapsed_seconds)
        and P7_SEARCH_BUDGET_SECONDS <= elapsed_seconds
        <= P7_SEARCH_BUDGET_SECONDS + P7_SEARCH_OBSERVATION_TOLERANCE_SECONDS
    )


def p7_required_dps(gate: str, saved_reference: float, *,
                    strongest_accepted_compatible_prior: float | None = None) -> float:
    """Owner-approved final floors: 99% P7.1-P7.4, 93% P7.5.

    The strongest prior must be from independently ACCEPTED compatible P7
    evidence, never a tentative search candidate. A common floor avoids a
    stale P7.1 full-reference or P7.5 full-external special case.
    """
    if gate not in ("P7.1", "P7.2", "P7.3", "P7.4", "P7.5"):
        raise ValueError("UNKNOWN_P7_GATE")
    if (type(saved_reference) not in (int, float)
            or not isfinite(saved_reference) or saved_reference <= 0):
        raise ValueError("P7_SAVED_REFERENCE_DPS_INVALID")
    comparator = float(saved_reference)
    if gate == "P7.5":
        prior = strongest_accepted_compatible_prior
        if type(prior) not in (int, float) or not isfinite(prior) or prior <= 0:
            raise ValueError("P7_5_ACCEPTED_COMPATIBLE_PRIOR_REQUIRED")
        comparator = max(comparator, float(prior))
    return (P7_5_FINAL_DPS_FLOOR_FRACTION if gate == "P7.5"
            else P7_FINAL_DPS_FLOOR_FRACTION) * comparator


def p7_final_stochastic_mean_passes(gate: str, observed_mean: float,
                                   saved_reference: float, *,
                                   iterations: int, stochastic: bool,
                                   strongest_accepted_compatible_prior: float | None = None
                                   ) -> bool:
    """Final DPS numerical predicate, not source/legal/live integration PASS.

    Search uses low-repeat deterministic balanced RNG. A final numerical PASS
    must use exactly 1000 genuine stochastic iterations from a FROZEN result;
    legal configs, selected-engine causality and holdout independence must be
    verified by the actual producer before it can award the whole gate.
    """
    floor = p7_required_dps(
        gate, saved_reference,
        strongest_accepted_compatible_prior=strongest_accepted_compatible_prior)
    return bool(type(iterations) is int and iterations == P7_FINAL_STOCHASTIC_ITERATIONS
                and stochastic is True
                and type(observed_mean) in (int, float)
                and isfinite(observed_mean) and observed_mean >= floor)


def measured_p7_dps_proximity(gate: str, report: dict) -> dict | None:
    """P7 DPS-objective closeness; NEVER the full gate's functional success%.

    A selected native↔world execution must have actually produced the measured
    score on the pinned report. Earlier UI/legality/holdout requirements can
    still BLOCK the gate. The final full gate uses 1000 stochastic iterations; search diagnostics may be shorter.
    """
    if gate not in ("P7.1", "P7.2", "P7.3", "P7.4", "P7.5"):
        return None
    if not isinstance(report, dict) or report.get("status") not in ("FAIL", "BLOCKED", "PASS"):
        return None
    if gate == "P7.5" and report.get("production_engine") == "pinned_mythicsim_rust_native":
        # The unrestricted P7.5 stationary reference runs directly in the
        # selected Rust scorer. No world ACKs or duplicate 2D score can be
        # required to report its genuine stochastic DPS objective.
        reference = report.get("saved_reference_dps")
        actual = report.get("frozen_stochastic_native_dps")
        prior = report.get("strongest_accepted_compatible_prior_dps")
        if (not report.get("source_request_raw_sha256")
                or not report.get("native_source_revision")
                or not report.get("frozen_request_raw_sha256")
                or type(report.get("frozen_stochastic_iterations")) is not int
                or report["frozen_stochastic_iterations"] != P7_FINAL_STOCHASTIC_ITERATIONS
                or type(reference) not in (int, float)
                or not isfinite(reference) or reference <= 0
                or type(actual) not in (int, float)
                or not isfinite(actual) or actual < 0
                or (prior is not None and (
                    type(prior) not in (int, float)
                    or not isfinite(prior) or prior <= 0))):
            return None
        required = p7_required_dps(
            gate, float(reference),
            strongest_accepted_compatible_prior=(
                float(prior) if prior is not None else float(reference)))
        c = min(1., float(actual) / required)
        return {
            "dps_objective_actual": round(float(actual), 4),
            "dps_objective_required": round(required, 4),
            "dps_objective_proximity_percent": round(100 * c, 2),
            "dps_objective_pareto_effort_estimate_percent": round(
                100 * pareto_effort_fraction(c), 2),
            "dps_objective_scope": "PINNED_NATIVE_STOCHASTIC_DPS_ONLY",
            "dps_objective_provisional": True,
            "dps_objective_gate_pass": False,
        }
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

    # The discovery gates' "winner_live_dps" is the *three-fight balanced
    # search score*. It is not the frozen 1,000-stochastic-fight final mean and
    # must never be published as proximity to the P7 acceptance DPS floor.
    # A completed final uses the existing live provider's actual field names.
    if gate == "P7.1":
        # Three-fight live probes are valuable diagnostics, but do not imply
        # 96%+ of an accepted 1,000-fight DPS result. Only a genuine completed
        # final has comparable arithmetic-mean DPS for M1 proximity.
        if (type(report.get("iterations")) is not int
                or report["iterations"] != P7_FINAL_STOCHASTIC_ITERATIONS
                or report.get("selected_validation")
                != "1000_native_and_live_stochastic_fights"
                or report.get("stochastic_rng") is not True):
            return None
        actual = report.get("world_dps")
        required = p7_required_dps(gate, float(reference))
    else:
        if (type(report.get("frozen_stochastic_iterations")) is not int
                or report["frozen_stochastic_iterations"] != P7_FINAL_STOCHASTIC_ITERATIONS
                or not report.get("frozen_request_raw_sha256")
                or type(report.get("frozen_stochastic_world_damage_events")) is not int
                or report["frozen_stochastic_world_damage_events"] <= 0
                or type(report.get("frozen_stochastic_world_boundaries")) is not int
                or report["frozen_stochastic_world_boundaries"] <= 0):
            return None
        actual = report.get("frozen_stochastic_world_dps")
        if gate == "P7.5":
            # An accepted-compatible prior is mandatory for the P7.5 floor.
            # Search scores and unaccepted historical native-only wins do not
            # establish that provenance.
            prior = report.get("strongest_accepted_compatible_prior_dps")
            if (type(prior) not in (int, float) or not isfinite(prior)
                    or prior <= 0):
                return None
            required = p7_required_dps(
                gate, float(reference),
                strongest_accepted_compatible_prior=float(prior))
        else:
            required = p7_required_dps(gate, float(reference))
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
