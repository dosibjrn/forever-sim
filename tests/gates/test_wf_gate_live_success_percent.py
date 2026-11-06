"""Active-gate FAIL success% and 80/20 are asserted behavior, never exploration.

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
                  native_source_revision="a" * 40, source_request_raw_sha256="b" * 64,
                  world_damage_events=20, world_boundaries=400,
                  saved_reference_dps=reference)
    if gate == "P7.1":
        report.update(
            world_dps=score,
            iterations=1000,
            selected_validation="1000_native_and_live_stochastic_fights",
            stochastic_rng=True,
        )
    else:
        report.update(
            frozen_stochastic_iterations=1000,
            frozen_request_raw_sha256="c" * 64,
            frozen_stochastic_world_damage_events=20,
            frozen_stochastic_world_boundaries=400,
            frozen_stochastic_world_dps=score,
        )
        if gate == "P7.5" and prior is not None:
            report["strongest_accepted_compatible_prior_dps"] = prior
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
    assert m["dps_objective_required"] == 930.
    assert m["dps_objective_proximity_percent"] == 96.77
    assert m["dps_objective_pareto_effort_estimate_percent"] == 87.1
    del r["strongest_accepted_compatible_prior_dps"]
    reference_only = measured_p7_dps_proximity("P7.5", r)
    assert reference_only["dps_objective_required"] == 744.0
    assert reference_only["dps_objective_proximity_percent"] == 100.0
    assert reference_only["dps_objective_gate_pass"] is False


def test_unverified_native_only_or_incomplete_p7_cannot_show_score():
    r = _real_coupled_p7_dps_report(gate="P7.1", score=900., reference=800.)
    r["production_engine"] = "native_rust_only"
    assert measured_p7_dps_proximity("P7.1", r) is None
    r["production_engine"] = "pinned_mythicsim_rust_gsim_2d"
    r["world_damage_events"] = 0
    assert measured_p7_dps_proximity("P7.1", r) is None


def test_owner_approved_p7_1_to_p7_4_keep_one_percent_floor():
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


def test_p7_5_seven_percent_applies_to_both_external_and_best_accepted_prior():
    assert p7_required_dps("P7.5", 1000.,
        strongest_accepted_compatible_prior=850.) == pytest.approx(930.)
    assert p7_required_dps("P7.5", 800.,
        strongest_accepted_compatible_prior=1000.) == pytest.approx(930.)
    for external, prior in ((1000., 850.), (800., 1000.)):
        assert p7_final_stochastic_mean_passes(
            "P7.5", 930., external, iterations=1000,
            stochastic=True, strongest_accepted_compatible_prior=prior)
        assert not p7_final_stochastic_mean_passes(
            "P7.5", 929., external, iterations=1000,
            stochastic=True, strongest_accepted_compatible_prior=prior)
    assert p7_required_dps("P7.5", 800.) == pytest.approx(744.)
    assert p7_final_stochastic_mean_passes(
        "P7.5", 744., 800., iterations=1000, stochastic=True)
    assert not p7_final_stochastic_mean_passes(
        "P7.5", 743.9, 800., iterations=1000, stochastic=True)
    with pytest.raises(ValueError, match="PRIOR_INVALID"):
        p7_required_dps("P7.5", 800.,
                        strongest_accepted_compatible_prior=0.0)


def test_p7_5_actual_joint_dps_visible_without_forged_prior_fraction(monkeypatch, capsys):
    import json
    from tools import wf_gate as runner
    monkeypatch.setattr(runner, "_run_live_gate", lambda *args: {
        "status": "FAIL",
        "reasons": ["P7_5_1000_STOCHASTIC_HOLDOUT_NOT_VERIFIED"],
        "production_engine": "pinned_mythicsim_rust_gsim_2d",
        "joint_cold_world_dps": 512.5,
        "external_reference_only_floor": 677.2201,
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


def test_p7_5_cli_receipt_exposes_real_stochastic_final_below_reference_floor(monkeypatch, capsys):
    """A genuine frozen final remains visible even when below reference floor.

    A reported score is diagnostic; it cannot create a P7.5 PASS when the
    1,000-fight mean fails the approved 93%-of-reference threshold.
    """
    import json
    from tools import wf_gate as runner

    monkeypatch.setattr(runner, "_run_live_gate", lambda *args: {
        "status": "FAIL",
        "reasons": ["P7_5_FROZEN_STOCHASTIC_DPS_BELOW_EXTERNAL_ONLY_FLOOR"],
        "production_engine": "pinned_mythicsim_rust_gsim_2d",
        "source_request_raw_sha256": "pinned-report",
        "native_source_revision": "pinned-rust",
        "joint_cold_world_dps": 607.9683,
        "external_reference_only_floor": 677.2201,
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
