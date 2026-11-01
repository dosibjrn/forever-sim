"""Pure numerical P7 reference floors; never declares a gate PASS.

For actual certification, use a source-legal, independently executed gate runner,
matching saved encounter and engine and required causal evidence. This module
computes only the threshold; acceptance provenance and execution are external.
"""
from __future__ import annotations

from math import isfinite

TOLERANCE = 0.99
GATES = ("P7.1", "P7.2", "P7.3", "P7.4", "P7.5")


def _dps(value: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{label} must be a finite positive DPS")
    result = float(value)
    if not isfinite(result) or result <= 0:
        raise ValueError(f"{label} must be a finite positive DPS")
    return result


def minimum_dps(gate: str, external_reference_dps: float, *,
                strongest_prior_stochastic_dps: float | None = None) -> float:
    """Required point-estimate DPS floor; other gate criteria remain separate.

    P7.1 reproduces >=100% saved external reference.
    P7.2–P7.4 each require >=99% saved external reference.
    P7.5 requires both >=100% saved external reference and >=99% strongest
    **accepted, same-scenario, same-engine, source-legal** compatible
    P7.1–P7.4 winner. P7.5 compares the >=1000-fight *frozen stochastic
    holdout MEAN* to this floor, without a 95% lower-bound PASS test.
    Caller must independently verify approval and full comparison provenance.
    """
    if gate not in GATES:
        raise ValueError("Unsupported P7 gate: " + str(gate))
    ref = _dps(external_reference_dps, "external_reference_dps")
    if gate in ("P7.2", "P7.3", "P7.4"):
        if strongest_prior_stochastic_dps is not None:
            raise ValueError("prior-winner floor applies only to P7.5")
        return TOLERANCE * ref
    if gate == "P7.1":
        if strongest_prior_stochastic_dps is not None:
            raise ValueError("prior-winner floor applies only to P7.5")
        return ref
    if strongest_prior_stochastic_dps is None:
        raise ValueError("P7.5 requires a compatible strongest prior stochastic DPS")
    return max(ref, TOLERANCE * _dps(strongest_prior_stochastic_dps,
                                   "strongest_prior_stochastic_dps"))


def p75_holdout_mean_meets_floor(holdout_mean_dps: float,
                                 external_reference_dps: float, *,
                                 strongest_accepted_compatible_prior_mean_dps: float) -> bool:
    """Evaluate ONLY the v2.10 mean-based numeric P7.5 criterion.

    No CI/p95 lower bound is required or evaluated. This numeric check does
    NOT certify an executed gate: the caller must independently verify >=1000
    frozen stochastic fights, cold <=300s legal search, true live 2D causality,
    prior gate acceptance and all source/engine/encounter comparability.
    Unaccepted, incompatible or unknown prior scores must NEVER be supplied.
    """
    mean = _dps(holdout_mean_dps, "holdout_mean_dps")
    floor = minimum_dps(
        "P7.5", external_reference_dps,
        strongest_prior_stochastic_dps=strongest_accepted_compatible_prior_mean_dps,
    )
    return mean >= floor
