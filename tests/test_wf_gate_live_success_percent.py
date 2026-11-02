"""Live FAIL success% and 80/20 are asserted behavior, never exploration.

Real P2 test executes the production GameIR/CombatRuntime rank probes.
Unit cases guard against metadata, sampling and candidate-count fraud.
"""
import subprocess
import sys

from tools.wf_gate import ROOT
from tools.wf_gate_coverage import measured_live_coverage, pareto_effort_fraction
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
    assert pareto_effort_fraction(0.9) == 0.6
    assert pareto_effort_fraction(1.0) == 1.0
