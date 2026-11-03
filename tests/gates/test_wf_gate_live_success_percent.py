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
                                    p7_final_stochastic_mean_passes,
                                    p7_required_dps,
                                    P7_FINAL_STOCHASTIC_ITERATIONS,
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
    assert "Best-observed fractional gate coverage" in result.stdout
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
    assert pareto_effort_fraction(1.0) == pytest.approx(1.0)


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
    assert m["dps_objective_required"] == 792.0
    assert m["dps_objective_proximity_percent"] == 90.91
    assert m["dps_objective_pareto_effort_estimate_percent"] == 63.64
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


def test_owner_approved_all_five_p7_gates_use_same_one_percent_floor():
    for gate in ("P7.1", "P7.2", "P7.3", "P7.4"):
        assert p7_required_dps(gate, 1000.) == pytest.approx(990.)
        assert p7_final_stochastic_mean_passes(
            gate, 990., 1000., iterations=1000, stochastic=True)
        assert not p7_final_stochastic_mean_passes(
            gate, 989.9, 1000., iterations=1000, stochastic=True)


def test_final_requires_1000_original_stochastic_iterations_not_balanced_search():
    assert P7_FINAL_STOCHASTIC_ITERATIONS == 1000
    for count, stochastic in ((999, True), (10000, True), (1000, False)):
        assert not p7_final_stochastic_mean_passes(
            "P7.1", 1000., 1000., iterations=count,
            stochastic=stochastic)
    assert p7_final_stochastic_mean_passes(
        "P7.1", 990., 1000., iterations=1000, stochastic=True)


def test_p7_5_one_percent_applies_to_both_external_and_best_accepted_prior():
    assert p7_required_dps("P7.5", 1000.,
        strongest_accepted_compatible_prior=850.) == pytest.approx(990.)
    assert p7_required_dps("P7.5", 800.,
        strongest_accepted_compatible_prior=1000.) == pytest.approx(990.)
    for external, prior in ((1000., 850.), (800., 1000.)):
        assert p7_final_stochastic_mean_passes(
            "P7.5", 990., external, iterations=1000,
            stochastic=True, strongest_accepted_compatible_prior=prior)
        assert not p7_final_stochastic_mean_passes(
            "P7.5", 989., external, iterations=1000,
            stochastic=True, strongest_accepted_compatible_prior=prior)
    with pytest.raises(ValueError, match="PRIOR_REQUIRED"):
        p7_required_dps("P7.5", 800.)


def test_p7_5_actual_joint_dps_visible_without_forged_prior_fraction(monkeypatch, capsys):
    import json
    from tools import wf_gate as runner
    monkeypatch.setattr(runner, "_run_live_gate", lambda *args: {
        "status": "FAIL",
        "reasons": ["P7_5_ACCEPTED_COMPATIBLE_PRIOR_REQUIRED_FOR_FINAL_DPS_FLOOR"],
        "production_engine": "pinned_mythicsim_rust_gsim_2d",
        "joint_cold_world_dps": 512.5,
        "external_reference_only_floor": 720.9117,
        "final_required_dps": None,
        "source_legal_joint_candidates_paid": 2,
    })
    assert runner.main(["--class", "druid", "--level", "60",
                        "--spec", "balance", "--gate", "P7.5"]) == 1
    row = json.loads(capsys.readouterr().out)["results"][0]
    assert row["joint_cold_world_dps"] == 512.5
    assert row["source_legal_joint_candidates_paid"] == 2
    assert "dps_objective_proximity_percent" not in row
    assert "verified" not in row and "applicable" not in row


def test_p7_5_cli_receipt_exposes_real_stochastic_final_without_prior_pass(monkeypatch, capsys):
    """RED in actual WF613 run: provider final DPS was hidden by CLI output.

    A frozen final score is a diagnostic fact; it cannot create a P7.5 PASS
    when the accepted-compatible prior is missing.
    """
    import json
    from tools import wf_gate as runner

    monkeypatch.setattr(runner, "_run_live_gate", lambda *args: {
        "status": "FAIL",
        "reasons": ["P7_5_ACCEPTED_COMPATIBLE_PRIOR_REQUIRED_FOR_FINAL_DPS_FLOOR",
                    "P7_5_FROZEN_STOCHASTIC_DPS_BELOW_EXTERNAL_ONLY_FLOOR"],
        "production_engine": "pinned_mythicsim_rust_gsim_2d",
        "source_request_raw_sha256": "pinned-report",
        "native_source_revision": "pinned-rust",
        "joint_cold_world_dps": 607.9683,
        "external_reference_only_floor": 720.9117,
        "source_legal_joint_candidates_paid": 1584,
        "search_wall_s": 300.12,
        "independent_300s_search_completed": True,
        "search_strategy": "wf613",
        "frozen_request_raw_sha256": "frozen-request",
        "frozen_stochastic_iterations": 1000,
        "frozen_stochastic_native_dps": 610.0,
        "frozen_stochastic_world_dps": 600.0,
        "frozen_stochastic_world_damage_events": 17,
        "frozen_stochastic_world_boundaries": 50,
        "frozen_stochastic_external_only_floor_met": False,
    })
    assert runner.main(["--class", "druid", "--level", "60",
                        "--spec", "balance", "--gate", "P7.5"]) == 1
    row = json.loads(capsys.readouterr().out)["results"][0]
    assert row["frozen_stochastic_iterations"] == 1000
    assert row["frozen_stochastic_world_dps"] == 600.0
    assert row["frozen_stochastic_native_dps"] == 610.0
    assert row["search_wall_s"] == 300.12
    assert row["search_strategy"] == "wf613"
    assert row["frozen_stochastic_external_only_floor_met"] is False
    assert row["status"] == "FAIL"
    assert "dps_objective_proximity_percent" not in row
    assert "verified" not in row and "applicable" not in row


def _native_p2_diagnostic_report():
    probe = {
        "rank_key": "moonkin_form:1",
        "target_talent_id": "moonkin_form",
        "target_rank": 1,
        "status": "PROBE_PASS",
        "executor": "selected_mythicsim_rust",
        "accepted_for_p2": False,
        "rng_mode": "balanced",
        "iterations": 100,
        "engine_identity": "a" * 40,
        "scenario": "balance",
        "source_layout_sha256": "b" * 64,
        "delta_dps": 2.0,
        "before": {
            "prepared": {"status": "PREPARED", "prepared_sha256": "before"},
            "simulation": {"status": "EXECUTED", "dps": 100.0},
        },
        "after": {
            "prepared": {"status": "PREPARED", "prepared_sha256": "after"},
            "simulation": {"status": "EXECUTED", "dps": 102.0},
        },
    }
    return {
        "production_engine": "live_game_ir_compiler_and_runtime",
        "structurally_reachable_ranks": 1,
        "ranks_with_executed_behavior_tests": 0,
        "ranks_with_executor_paths": 0,
        "missing_executor_ranks": 1,
        "failed_behavior_ranks": 1,
        "talent_paths_legal": False,
        "ranks_represented_in_search": 0,
        "unlocked_actions_available_to_generated_search": False,
        "native_rank_probe_scope": "DIAGNOSTIC_ONLY_NOT_COUNTED_IN_P2_ACCEPTANCE",
        "native_rank_probe_results": [probe],
        "native_rank_probe_summary": {
            "scope": "druid:60:balance; moonkin_form:1",
            "attempted": 1,
            "pass_count": 1,
            "fail_count": 0,
            "blocked_count": 0,
            "rng_mode": "balanced",
            "counted_in_p2_acceptance": False,
        },
    }


def test_p2_validator_keeps_native_rank_probes_diagnostic_only():
    from tools.wf_gate import _validate_p2

    errors = _validate_p2(_native_p2_diagnostic_report(), {})
    # A positive native probe is visible and schema-checked, but it cannot
    # replace the complete per-rank P2 ledger or approve the GameIR provider.
    assert "UNAPPROVED_P2_PRODUCTION_ENGINE:live_game_ir_compiler_and_runtime" in errors
    assert "INCOMPLETE:ranks_with_executed_behavior_tests=0/1" in errors
    assert not any(error.startswith("INVALID_NATIVE_P2") for error in errors)
    assert not any(error.startswith("INCOMPLETE_NATIVE_P2") for error in errors)


def test_p2_validator_rejects_native_probe_receipts_that_claim_acceptance():
    from tools.wf_gate import _validate_p2

    report = _native_p2_diagnostic_report()
    report["native_rank_probe_results"][0]["accepted_for_p2"] = True
    report["native_rank_probe_summary"]["counted_in_p2_acceptance"] = True
    errors = _validate_p2(report, {})
    assert "NATIVE_P2_DIAGNOSTIC_ACCEPTANCE_CLAIMED:moonkin_form:1" in errors
    assert "NATIVE_P2_DIAGNOSTIC_SUMMARY_NOT_FAIL_CLOSED" in errors

