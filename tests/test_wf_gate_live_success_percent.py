"""Live FAIL success% and 80/20 are asserted behavior, never exploration.

Real P2 test executes the production GameIR/CombatRuntime rank probes.
Unit cases guard against metadata, sampling and candidate-count fraud.
"""
import subprocess
import sys
import pytest

from tools.wf_gate import ROOT
from tools.wf_gate_coverage import (measured_live_coverage,
                                    measured_p7_dps_proximity,
                                    pareto_effort_fraction)
from tools.wf_gate_probe import probe_gate


def test_real_druid_p2_live_fail_shows_success_and_8020():
    row = probe_gate("druid", 60, "balance", "P2", timeout_s=45.0)
    assert row["status"] == "FAIL", row
    assert row["verified"] > 0
    assert row["applicable"] >= row["verified"]
    c = row["verified"] / row["applicable"]
    assert row["partial_coverage_percent"] == round(100 * c, 2)
    assert row["pareto_effort_estimate_percent"] == round(
        100 * pareto_effort_fraction(c), 2)
    assert row["engine_id"] == "live_game_ir_compiler_and_runtime"
    assert len(row["source_id"]) == 64


def test_direct_scoreboard_script_still_runs_without_pythonpath():
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "m1_progress.py")],
        cwd=ROOT, text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert "Observed fractional gate coverage" in result.stdout
    assert "Pareto-modeled work" in result.stdout


def test_actual_paid_stat_assertions_get_provisional_percentages():
    report = dict(status="FAIL", pass_count=88, reachability_count=230,
                  behavior_probes_executed=33,
                  coverage_basis="executed_behavior_assertions",
                  partial_scope="CURRENT_SOURCE_TOP5_ITEM_STAT_WEIGHT_ASSERTIONS",
                  coverage_scope_complete=False)
    m = measured_live_coverage(report)
    assert (m["verified"], m["applicable"]) == (88, 230)
    assert m["partial_coverage_percent"] == 38.26
    assert m["pareto_effort_estimate_percent"] == 9.57
    assert m["scope_provisional"]
    assert m["coverage_component"] == report["partial_scope"]


def test_gear_slot_visits_and_sample_breadth_are_not_success():
    explored_gear = dict(status="FAIL", pass_count=5, reachability_count=16,
                         behavior_probes_executed=29,
                         partial_scope="COMPLETED_PAID_SOURCE_GEAR_SLOT_CANDIDATES")
    sampled_fights = dict(status="FAIL", pass_count=100, reachability_count=10000,
                          behavior_probes_executed=100,
                          coverage_component="STOCHASTIC_FIGHT_SAMPLE")
    assert measured_live_coverage(explored_gear) is None
    assert measured_live_coverage(sampled_fights) is None


def test_source_inventory_and_unexecuted_effects_are_not_success():
    assert measured_live_coverage(dict(status="FAIL", pass_count=8,
        reachability_count=10, behavior_probes_executed=0,
        coverage_basis="executed_behavior_assertions")) is None
    assert measured_live_coverage(dict(status="BLOCKED", pass_count=8,
        reachability_count=10, behavior_probes_executed=99,
        coverage_basis="executed_behavior_assertions")) is None


def test_functionality_and_modeled_effort_are_different():
    assert pareto_effort_fraction(0.8) == 0.2
    assert pareto_effort_fraction(0.9) == pytest.approx(0.6)
    assert pareto_effort_fraction(1.0) == 1.0


def _real_coupled_p7_dps_report(*, gate: str, score: float, reference: float,
                               prior: float | None = None) -> dict:
    # Contract regression with numeric examples, not evidence of a production
    # P7 run. No M1 PASS/PARTIAL can be derived from these synthetic values.
    report = dict(status="FAIL", production_engine="pinned_mythicsim_rust_gsim_2d",
                  native_source_revision="pinned", source_request_raw_sha256="source",
                  world_damage_events=20, world_boundaries=400,
                  saved_reference_dps=reference)
    if gate == "P7.1":
        report["world_dps"] = score
    elif gate == "P7.5":
        report["holdout_mean_dps"] = score
        if prior is not None:
            report["strongest_accepted_compatible_prior_dps"] = prior
    else:
        report["winner_live_dps"] = score
    return report


def test_p7_1_objective_closeness_not_stochastic_sample_fraction():
    r = _real_coupled_p7_dps_report(gate="P7.1", score=720., reference=800.)
    m = measured_p7_dps_proximity("P7.1", r)
    assert m["dps_objective_proximity_percent"] == 90.0
    assert m["dps_objective_pareto_effort_estimate_percent"] == 60.0
    assert m["dps_objective_gate_pass"] is False
    assert measured_live_coverage(r) is None


def test_p7_2_3_4_correct_99_percent_floor_not_fixed_10000_samples():
    for gate in ("P7.2", "P7.3", "P7.4"):
        r = _real_coupled_p7_dps_report(gate=gate, score=792., reference=1000.)
        m = measured_p7_dps_proximity(gate, r)
        assert m["dps_objective_required"] == 990.
        assert m["dps_objective_proximity_percent"] == 80.
        assert m["dps_objective_pareto_effort_estimate_percent"] == 20.


def test_p7_5_uses_higher_accepted_compatible_holdout_floor():
    r = _real_coupled_p7_dps_report(
        gate="P7.5", score=900., reference=800., prior=1000.)
    m = measured_p7_dps_proximity("P7.5", r)
    assert m["dps_objective_required"] == 990.
    assert m["dps_objective_proximity_percent"] == 90.91
    assert m["dps_objective_pareto_effort_estimate_percent"] == 63.64
    del r["strongest_accepted_compatible_prior_dps"]
    assert measured_p7_dps_proximity("P7.5", r) is None


def test_unverified_native_only_or_incomplete_p7_cannot_show_score():
    r = _real_coupled_p7_dps_report(gate="P7.1", score=900., reference=800.)
    r["production_engine"] = "native_rust_only"
    assert measured_p7_dps_proximity("P7.1", r) is None
    r["production_engine"] = "pinned_mythicsim_rust_gsim_2d"
    r["world_damage_events"] = 0
    assert measured_p7_dps_proximity("P7.1", r) is None
