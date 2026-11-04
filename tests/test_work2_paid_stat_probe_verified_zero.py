"""P3 paid stat weights: a failed perturbation must never masquerade as zero."""

from src.optimization.stat_sensitivity import measure_stat_sensitivities
from src.v2.source_budgeted_gear import _paid_measured_stat_weights


def _measure_with_mixed_paid_outcomes():
    def change(_state, stat, delta):
        return {"stat": stat, "delta": delta}

    def score(state):
        stat = state["stat"]
        if stat is None:
            return 50.0
        if stat == "blocked":
            return None
        if stat == "neutral":
            return 50.0
        if stat == "late_neutral":
            return None if state["delta"] == 5.0 else 50.0
        if stat == "regression":
            return 52.0
        if stat == "improvement":
            return 45.0
        raise AssertionError(stat)

    return measure_stat_sensitivities(
        {"stat": None, "delta": 0.0},
        stats=("blocked", "neutral", "late_neutral", "regression", "improvement"),
        apply_delta=change,
        score=score,
        probe_deltas=(5.0, 20.0),
    ).as_dict()


def test_failed_paid_stat_probe_is_missing_not_measured_zero():
    report = _measure_with_mixed_paid_outcomes()
    # The generic scorer historically writes 0.0 even when every paid
    # perturbation is blocked. The P3 source consumer must not accept it.
    assert report["values"]["blocked"] == 0.0
    weights, unmeasured = _paid_measured_stat_weights(report)
    assert "blocked" not in weights
    assert unmeasured == ["blocked"]


def test_real_paid_zero_and_negative_derivative_are_preserved():
    weights, unmeasured = _paid_measured_stat_weights(
        _measure_with_mixed_paid_outcomes()
    )
    assert unmeasured == ["blocked"]
    assert weights["neutral"] == 0.0
    # One failed attempt followed by a genuine completed unchanged objective
    # is still a measured zero, not an absent weight.
    assert weights["late_neutral"] == 0.0
    assert weights["regression"] < 0.0
    assert weights["improvement"] > 0.0
