"""Regression tests for real gear stat deltas and non-monotone scorer samples.

These exercise the shared production stat-sensitivity selector with canonical
Druid gear application. The deliberately controlled score curves isolate the
selection rule; they are NOT a P3 acceptance run or a gate PASS.
"""
from __future__ import annotations

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.stat_sensitivity import measure_stat_sensitivities


def _real_gear_probe(curve):
    ir = build_game_ir_slice(class_key="druid", level=60)
    assert ir is not None

    def score(probed_ir):
        applied = probed_ir.actor.metadata.get("gear_executable_stats", {})
        delta = float(applied.get("armor", 0.0))
        assert delta in curve, f"unexpected gear delta {delta}"
        return curve[delta]

    return measure_stat_sensitivities(
        ir, stats=("armor",), score=score, probe_deltas=(5.0, 20.0)
    ).rows[0]


def test_real_gear_delta_can_recover_from_small_discrete_regression():
    # The +5 armor sample loses time, but +20 genuinely saves time.
    row = _real_gear_probe({0.0: 10.0, 5.0: 11.0, 20.0: 8.0})
    assert row.first_effective_delta == 20.0
    assert row.value == pytest.approx(0.1)
    assert [p["seconds_per_mob"] for p in row.probes] == [11.0, 8.0]


def test_real_regression_is_not_clipped_when_no_step_helps():
    row = _real_gear_probe({0.0: 10.0, 5.0: 11.0, 20.0: 12.0})
    assert row.first_effective_delta == 5.0
    assert row.value == pytest.approx(-0.2)
    assert len(row.probes) == 2


def test_first_beneficial_step_preserves_early_exit_and_budget():
    row = _real_gear_probe({0.0: 10.0, 5.0: 9.0})
    assert row.first_effective_delta == 5.0
    assert row.value == pytest.approx(0.2)
    assert len(row.probes) == 1


def test_flat_small_step_does_not_hide_larger_real_improvement():
    row = _real_gear_probe({0.0: 10.0, 5.0: 10.0, 20.0: 8.0})
    assert row.first_effective_delta == 20.0
    assert row.value == pytest.approx(0.1)


def test_nonfinite_and_nonpositive_paid_probes_cannot_create_fake_positive_weight():
    # Real source gear application; invalid paid-score outputs are not valid
    # CombatRuntime seconds/mob and cannot count as stat improvement.
    for invalid in (float("nan"), float("inf"), float("-inf"), 0.0, -1.0):
        row = _real_gear_probe({0.0: 10.0, 5.0: invalid, 20.0: 8.0})
        assert row.first_effective_delta == 20.0
        assert row.value == pytest.approx(0.1)
        assert row.probes[0]["seconds_per_mob"] is None
        assert row.probes[1]["seconds_per_mob"] == 8.0


def test_all_invalid_paid_probes_never_produce_a_weight():
    row = _real_gear_probe({0.0: 10.0, 5.0: -1.0, 20.0: float("nan")})
    assert row.first_effective_delta is None
    assert row.value == 0.0
    assert all(probe["seconds_per_mob"] is None for probe in row.probes)


def test_invalid_paid_baseline_fails_closed_before_any_stat_claim():
    for invalid in (float("nan"), float("inf"), 0.0, -1.0):
        with pytest.raises(ValueError, match="nonpositive or nonfinite"):
            _real_gear_probe({0.0: invalid})
