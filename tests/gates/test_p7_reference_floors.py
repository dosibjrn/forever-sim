"""Policy regression tests; these are NOT a combat/P7 simulation PASS."""
import math

import pytest
from src.game.p7_reference_floors import minimum_dps, p75_holdout_mean_meets_floor


def test_p71_accepts_one_percent_below_saved_reference():
    ref = 728.1936126415858
    assert minimum_dps("P7.1", ref) == pytest.approx(720.9116765151699)


@pytest.mark.parametrize("gate", ["P7.2", "P7.3", "P7.4"])
def test_single_dimension_gates_accept_one_percent_below_reference(gate):
    ref = 728.1936126415858
    assert minimum_dps(gate, ref) == pytest.approx(720.9116765151699)


def test_p75_uses_99_percent_of_external_when_prior_is_lower():
    assert minimum_dps("P7.5", 811.023726, strongest_prior_stochastic_dps=805) == pytest.approx(
        811.023726 * .99)


def test_p75_also_retains_ninety_nine_percent_of_stronger_prior():
    ref = 811.023726
    prior = 853.93055
    assert minimum_dps("P7.5", ref, strongest_prior_stochastic_dps=prior) == pytest.approx(845.3912445)


@pytest.mark.parametrize("gate", ["P7.2", "P7.3", "P7.4", "P7.1"])
def test_single_gate_rejects_prior_winner_threshold(gate):
    with pytest.raises(ValueError):
        minimum_dps(gate, 728, strongest_prior_stochastic_dps=800)


def test_p75_needs_compatible_prior_and_rejects_invalid_values():
    with pytest.raises(ValueError):
        minimum_dps("P7.5", 811)
    for value in (0, -1, float("nan"), float("inf"), "811", True):
        with pytest.raises(ValueError):
            minimum_dps("P7.2", value)
    with pytest.raises(ValueError):
        minimum_dps("P7.5", 811, strongest_prior_stochastic_dps=math.nan)
    with pytest.raises(ValueError):
        minimum_dps("P7.9", 811)


def test_p75_mean_passes_between_old_ci_limit_and_numeric_floor():
    # Historical WF613: 848.764 > 99% of 853.93055 and > 811.023726.
    # A one-sided confidence lower bound was previously examined; v2.10
    # deliberately uses only the frozen stochastic MEAN, never that CI limit.
    assert p75_holdout_mean_meets_floor(
        848.76436, 811.023726,
        strongest_accepted_compatible_prior_mean_dps=853.93055,
    )


def test_p75_mean_must_reach_99_percent_of_larger_external_or_prior():
    assert not p75_holdout_mean_meets_floor(
        802.0, 811.023726, strongest_accepted_compatible_prior_mean_dps=805,
    )
    assert p75_holdout_mean_meets_floor(
        809.9, 811.023726, strongest_accepted_compatible_prior_mean_dps=805,
    )
    assert not p75_holdout_mean_meets_floor(
        840.0, 811.023726, strongest_accepted_compatible_prior_mean_dps=853.93055,
    )
    assert p75_holdout_mean_meets_floor(
        853.93055 * 0.99, 811.023726,
        strongest_accepted_compatible_prior_mean_dps=853.93055,
    )


def test_p75_mean_requires_explicit_prior_and_rejects_invalid_scores():
    with pytest.raises(TypeError):
        p75_holdout_mean_meets_floor(850.0, 811.0)
    with pytest.raises(ValueError):
        p75_holdout_mean_meets_floor(
            float("nan"), 811.0,
            strongest_accepted_compatible_prior_mean_dps=853.0,
        )
    with pytest.raises(ValueError):
        p75_holdout_mean_meets_floor(
            850.0, 811.0,
            strongest_accepted_compatible_prior_mean_dps=float("inf"),
        )

def test_p75_external_threshold_equality_is_accepted_not_only_full_reference():
    external = 811.023726
    prior = 805.0
    assert p75_holdout_mean_meets_floor(
        .99 * external, external,
        strongest_accepted_compatible_prior_mean_dps=prior)
    assert not p75_holdout_mean_meets_floor(
        .99 * external - 0.001, external,
        strongest_accepted_compatible_prior_mean_dps=prior)
