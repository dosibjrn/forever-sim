"""Fast bookkeeping tests only; these are NOT active P3–P7.5 acceptance tests."""
from pathlib import Path

import pytest
from tools import m1_progress as m1
from tools import wf_gate


SHA = "a" * 40


def test_empty_m1_uses_148_times_nine(tmp_path):
    score = m1.scoreboard(tmp_path / "missing.tsv")
    assert (score["passed_gates"], score["total_gates"]) == (0, 1332)
    assert score["certified_checkpoints"] == 0


def test_real_pass_record_is_timestamped_and_deduplicated(monkeypatch, tmp_path):
    monkeypatch.setattr(m1.subprocess, "check_output", lambda *a, **k: SHA)
    path = tmp_path / "passes.tsv"
    for _ in range(2):
        m1.record_pass(class_key="druid", level=60, spec="balance",
                       gate="P3", report={"status": "PASS", "reasons": []},
                       root=tmp_path, path=path)
    rows = m1._rows(path)
    assert len(rows) == 1
    assert next(iter(rows.values()))["passed_at_utc"]
    assert m1.scoreboard(path)["passed_gates"] == 1
    assert m1.scoreboard(path)["gate_percent"] == pytest.approx(100 / 1332)


def test_cannot_stamp_fail_or_blocked(monkeypatch, tmp_path):
    monkeypatch.setattr(m1.subprocess, "check_output", lambda *a, **k: SHA)
    path = tmp_path / "passes.tsv"
    for status in ("FAIL", "BLOCKED"):
        with pytest.raises(ValueError):
            m1.record_pass(class_key="druid", level=60, spec="balance",
                           gate="P3", report={"status": status}, path=path)
    assert not path.exists()



def test_retired_p1_p2_cannot_be_recorded(monkeypatch, tmp_path):
    monkeypatch.setattr(m1.subprocess, "check_output", lambda *a, **k: SHA)
    path = tmp_path / "passes.tsv"
    for gate in ("P1", "P2"):
        with pytest.raises(ValueError):
            m1.record_pass(class_key="druid", level=60, spec="balance",
                           gate=gate, report={"status": "PASS", "reasons": []},
                           root=tmp_path, path=path)
        assert not m1.record_partial(
            class_key="druid", level=60, spec="balance", gate=gate,
            report={"status": "FAIL", "coverage_basis": "executed_behavior_assertions",
                    "pass_count": 1, "reachability_count": 2,
                    "behavior_probes_executed": 1}, path=path)
    assert not path.exists()


def test_nine_active_passes_certify_without_auxiliary_identity(monkeypatch, tmp_path):
    monkeypatch.setattr(m1.subprocess, "check_output", lambda *a, **k: SHA)
    path = tmp_path / "passes.tsv"
    for gate in m1.GATES:
        m1.record_pass(class_key="druid", level=60, spec="balance",
                       gate=gate, report={"status": "PASS", "reasons": []},
                       path=path)
    score = m1.scoreboard(path)
    assert score["passed_gates"] == 9
    assert score["certified_checkpoints"] == 1


def test_nine_passes_and_invalidation(monkeypatch, tmp_path):
    monkeypatch.setattr(m1.subprocess, "check_output", lambda *a, **k: SHA)
    path = tmp_path / "passes.tsv"
    for gate in m1.GATES:
        m1.record_pass(class_key="druid", level=60, spec="balance",
                       gate=gate, report={"status": "PASS", "reasons": []},
                       path=path)
    assert m1.scoreboard(path)["certified_checkpoints"] == 1
    assert m1.main(["--ledger", str(path), "--invalidate",
                    "druid", "60", "balance", "P3"]) == 0
    assert m1.scoreboard(path)["certified_checkpoints"] == 0


def _behavior_partial(verified=83, total=103):
    return {"status": "FAIL", "pass_count": verified,
            "reachability_count": total, "behavior_probes_executed": 110,
            "unresolved_count": 2, "coverage_basis": "executed_behavior_assertions",
            "production_engine": "gsim"}


def test_partial_p3_is_visible_but_not_certified(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(m1.subprocess, "check_output", lambda *a, **k: SHA)
    path = tmp_path / "passes.tsv"
    assert m1.record_partial(class_key="druid", level=60, spec="balance",
                             gate="P3", report=_behavior_partial(), path=path)
    score = m1.scoreboard(path)
    assert score["passed_gates"] == 0
    assert score["certified_checkpoints"] == 0
    assert score["partial_gates"][0]["coverage"] == pytest.approx(83 / 103)
    assert score["partial_gates"][0]["pareto_effort"] == pytest.approx(
        .2 + 4 * (83 / 103 - .8))
    assert score["measured_gate_equivalents"] == pytest.approx(83 / 103)
    assert score["measured_percent"] == pytest.approx(100 * 83 / 103 / 1332)
    assert score["measured_fraction"] == pytest.approx((83 / 103) / 1332)
    assert score["measured_percent"] == pytest.approx(100 * score["measured_fraction"])
    assert score["partial_gates"][0]["provisional"]
    assert m1.main(["--ledger", str(path)]) == 0
    output = capsys.readouterr().out
    assert "83/103" in output
    assert (f"M1 measured progress: {score['measured_percent']:.4f}% "
            f"(float={score['measured_fraction']:.10f}; diagnostic, NOT PASS)") in output


def test_partial_rejects_blocked_or_only_source_data(monkeypatch, tmp_path):
    monkeypatch.setattr(m1.subprocess, "check_output", lambda *a, **k: SHA)
    path = tmp_path / "passes.tsv"
    for report in (
        {"status": "BLOCKED", "pass_count": 83, "reachability_count": 103,
         "behavior_probes_executed": 110},
        {"status": "FAIL", "pass_count": 83, "reachability_count": 103,
         "behavior_probes_executed": 0},
        {"status": "FAIL", "pass_count": 120, "reachability_count": 103,
         "behavior_probes_executed": 110},
        {"status": "FAIL", "pass_count": 103, "reachability_count": 103,
         "behavior_probes_executed": 110},
    ):
        assert not m1.record_partial(class_key="druid", level=60,
                                     spec="balance", gate="P3",
                                     report=report, path=path)
    assert not path.exists()


def test_full_pass_supersedes_partial_and_partial_cannot_erase_it(monkeypatch, tmp_path):
    monkeypatch.setattr(m1.subprocess, "check_output", lambda *a, **k: SHA)
    path = tmp_path / "passes.tsv"
    assert m1.record_partial(class_key="druid", level=60, spec="balance",
                             gate="P3", report=_behavior_partial(), path=path)
    m1.record_pass(class_key="druid", level=60, spec="balance",
                   gate="P3", report={"status": "PASS", "reasons": []}, path=path)
    assert m1.scoreboard(path)["passed_gates"] == 1
    assert not m1.record_partial(class_key="druid", level=60, spec="balance",
                                 gate="P3", report=_behavior_partial(90), path=path)
    score = m1.scoreboard(path)
    assert not score["partial_gates"]
    assert score["measured_gate_equivalents"] == 1


def test_old_pass_only_ledger_is_backwards_compatible(tmp_path):
    path = tmp_path / "old.tsv"
    path.write_text("\t".join(m1.PASS_FIELDS) + "\n" +
                    "\t".join(("druid", "60", "balance", "P2",
                               "2026-11-02T00:00:00+00:00", SHA, "", "")) + "\n")
    assert m1.scoreboard(path)["passed_gates"] == 0




def test_public_gate_cli_rejects_retired_p1_p2():
    assert wf_gate.GATES == tuple(f"P{i}" for i in range(3, 7)) + tuple(
        f"P7.{i}" for i in range(1, 6))
    for gate in ("P1", "P2"):
        with pytest.raises(SystemExit):
            wf_gate.main(["--class", "druid", "--level", "60", "--gate", gate])


def test_retired_history_cannot_be_invalidated(tmp_path):
    path = tmp_path / "old.tsv"
    path.write_text("\t".join(m1.PASS_FIELDS) + "\n" +
                    "\t".join(("druid", "60", "balance", "P2",
                               "2026-11-02T00:00:00+00:00", SHA, "", "")) + "\n")
    with pytest.raises(SystemExit):
        m1.main(["--ledger", str(path), "--invalidate",
                 "druid", "60", "balance", "P2"])
    assert ("druid", "60", "balance", "P2") in m1._rows(path)



def test_materially_invalidated_partial_receipt_can_be_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(m1.subprocess, "check_output", lambda *a, **k: SHA)
    path = tmp_path / "m1.tsv"
    assert m1.record_partial(
        class_key="mage", level=30, spec="unrestricted", gate="P3",
        report=_behavior_partial(46, 160), path=path)
    key = ("mage", "30", "unrestricted", "P3")
    assert key in m1._rows(path)
    assert m1.main(["--ledger", str(path), "--invalidate",
                    "mage", "30", "unrestricted", "P3"]) == 0
    assert key not in m1._rows(path)


def test_partial_watermark_is_monotonic_but_logs_lower_current_measurement(
        monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(m1.subprocess, "check_output", lambda *a, **k: SHA)
    path = tmp_path / "m1.tsv"
    def record(n, d=100):
        return m1.record_partial(
            class_key="druid", level=60, spec="balance", gate="P3",
            report=_behavior_partial(n, d), path=path)
    assert record(1)
    assert record(50)
    assert not record(25)
    assert "M1_REGRESSION_OR_SCOPE_CHANGE" in capsys.readouterr().out
    assert m1.scoreboard(path)["partial_gates"][0]["verified"] == 50
    assert record(100)  # Full measured subcomponent is NOT a whole gate PASS.
    assert m1.scoreboard(path)["passed_gates"] == 0
    assert m1.scoreboard(path)["partial_gates"][0]["coverage"] == 1.0


def test_p7_actual_coupled_dps_is_partial_even_when_ui_gate_blocked(
        monkeypatch, tmp_path):
    monkeypatch.setattr(m1.subprocess, "check_output", lambda *a, **k: SHA)
    path = tmp_path / "m1.tsv"
    report = dict(status="BLOCKED", reasons=["UI_AUDIT_PENDING"],
                  production_engine="pinned_mythicsim_rust_gsim_2d",
                  native_source_revision="pinned", source_request_raw_sha256="source",
                  world_damage_events=20, world_boundaries=400,
                  saved_reference_dps=800., world_dps=720.,
                  iterations=1000, stochastic_rng=True,
                  selected_validation="1000_native_and_live_stochastic_fights")
    assert not m1.record_partial(class_key="druid", level=60, spec="balance",
                                 gate="P7.1", report={**report, "iterations": 3,
                                    "selected_validation": "bounded_native_live_source_diagnostic"},
                                 path=path)
    assert m1.record_partial(class_key="druid", level=60, spec="balance",
                             gate="P7.1", report=report, path=path)
    row = m1.scoreboard(path)["partial_gates"][0]
    assert row["coverage"] == pytest.approx(720. / 792.)
    assert row["provisional"]
    assert m1.scoreboard(path)["passed_gates"] == 0
    assert not m1.record_partial(class_key="druid", level=60, spec="balance",
                                 gate="P7.1", report={**report, "world_damage_events": 0},
                                 path=path)


def test_denominator_shrink_cannot_fake_increased_completion(monkeypatch, tmp_path):
    monkeypatch.setattr(m1.subprocess, "check_output", lambda *a, **k: SHA)
    path = tmp_path / "m1.tsv"
    assert m1.record_partial(
        class_key="druid", level=60, spec="balance", gate="P3",
        report=_behavior_partial(70, 100), path=path)
    assert not m1.record_partial(
        class_key="druid", level=60, spec="balance", gate="P3",
        report=_behavior_partial(20, 20), path=path)
    saved = m1.scoreboard(path)["partial_gates"][0]
    assert (saved["verified"], saved["applicable"]) == (70, 100)


def test_concurrent_actions_merge_disjoint_real_gate_receipts(monkeypatch, tmp_path):
    """A newer M1 update cannot discard a separate source-executed gate."""
    from shutil import copyfile
    monkeypatch.setattr(m1.subprocess, "check_output", lambda *a, **k: SHA)
    base, measured, latest, out = (
        tmp_path / x for x in ("base.tsv", "measured.tsv", "latest.tsv", "out.tsv"))
    assert m1.record_partial(class_key="druid", level=60, spec="balance",
        gate="P3", report=_behavior_partial(70, 100), path=base)
    copyfile(base, measured)
    copyfile(base, latest)
    assert m1.record_partial(class_key="druid", level=60, spec="balance",
        gate="P3", report=_behavior_partial(90, 100), path=measured)
    m1.record_pass(class_key="druid", level=60, spec="balance", gate="P4",
        report={"status": "PASS", "reasons": []}, path=latest)
    m1.merge_concurrent_gate_results(base, measured, latest, out)
    score = m1.scoreboard(out)
    assert score["passed_gates"] == 1
    assert score["partial_gates"][0]["verified"] == 90


def test_concurrent_action_cannot_downgrade_existing_pass_or_better_fraction(
        monkeypatch, tmp_path):
    from shutil import copyfile
    monkeypatch.setattr(m1.subprocess, "check_output", lambda *a, **k: SHA)
    base, measured, latest, out = (
        tmp_path / x for x in ("base.tsv", "measured.tsv", "latest.tsv", "out.tsv"))
    m1.record_partial(class_key="druid", level=60, spec="balance",
        gate="P3", report=_behavior_partial(10, 100), path=base)
    copyfile(base, measured)
    copyfile(base, latest)
    m1.record_partial(class_key="druid", level=60, spec="balance",
        gate="P3", report=_behavior_partial(60, 100), path=measured)
    m1.record_partial(class_key="druid", level=60, spec="balance",
        gate="P3", report=_behavior_partial(95, 100), path=latest)
    m1.merge_concurrent_gate_results(base, measured, latest, out)
    assert m1.scoreboard(out)["partial_gates"][0]["verified"] == 95
    m1.record_pass(class_key="druid", level=60, spec="balance", gate="P3",
        report={"status": "PASS", "reasons": []}, path=latest)
    m1.merge_concurrent_gate_results(base, measured, latest, out)
    assert m1.scoreboard(out)["passed_gates"] == 1
    assert m1.scoreboard(out)["partial_gates"] == []


def test_concurrent_action_never_republishes_implicit_invalidation(tmp_path):
    from shutil import copyfile
    base, measured, latest, out = (
        tmp_path / x for x in ("base.tsv", "measured.tsv", "latest.tsv", "out.tsv"))
    base.write_text("\t".join(m1.FIELDS) + "\n")
    copyfile(base, measured)
    copyfile(base, latest)
    assert m1.merge_concurrent_gate_results(base, measured, latest, out) == {}



def test_p7_discovery_partial_uses_only_frozen_stochastic_mean():
    from tools.wf_gate_coverage import measured_p7_dps_proximity

    report = {
        "status": "FAIL", "production_engine": "pinned_mythicsim_rust_gsim_2d",
        "native_source_revision": "pinned", "source_request_raw_sha256": "source",
        "world_damage_events": 20, "world_boundaries": 400,
        "saved_reference_dps": 800.0,
        # An excellent three-fight balanced search screen is NOT the final.
        "winner_live_dps": 900.0,
    }
    assert measured_p7_dps_proximity("P7.2", report) is None
    assert measured_p7_dps_proximity("P7.3", report) is None
    assert measured_p7_dps_proximity("P7.4", report) is None

    report.update(
        frozen_stochastic_iterations=1000,
        frozen_request_raw_sha256="frozen-source",
        frozen_stochastic_world_damage_events=2000,
        frozen_stochastic_world_boundaries=4000,
        frozen_stochastic_world_dps=760.0,
    )
    for gate in ("P7.2", "P7.3", "P7.4"):
        observed = measured_p7_dps_proximity(gate, report)
        assert observed["dps_objective_actual"] == pytest.approx(760.0)
        assert observed["dps_objective_required"] == pytest.approx(792.0)
        assert observed["dps_objective_proximity_percent"] == pytest.approx(95.96)
        assert not observed["dps_objective_gate_pass"]


def test_p75_partial_requires_accepted_prior_and_frozen_holdout():
    from tools.wf_gate_coverage import measured_p7_dps_proximity

    report = {
        "status": "BLOCKED", "production_engine": "pinned_mythicsim_rust_gsim_2d",
        "native_source_revision": "pinned", "source_request_raw_sha256": "source",
        "world_damage_events": 20, "world_boundaries": 400,
        "saved_reference_dps": 800.0,
        "joint_cold_world_dps": 1000.0,
        "frozen_stochastic_iterations": 1000,
        "frozen_request_raw_sha256": "winner",
        "frozen_stochastic_world_damage_events": 2000,
        "frozen_stochastic_world_boundaries": 4000,
        "frozen_stochastic_world_dps": 820.0,
    }
    # A strong native/world winner is not enough to invent the accepted prior.
    assert measured_p7_dps_proximity("P7.5", report) is None
    report["strongest_accepted_compatible_prior_dps"] = 850.0
    proximity = measured_p7_dps_proximity("P7.5", report)
    assert proximity["dps_objective_actual"] == pytest.approx(820.0)
    assert proximity["dps_objective_required"] == pytest.approx(790.5)
    assert not proximity["dps_objective_gate_pass"]


def test_materially_invalidated_partial_receipt_can_be_removed(monkeypatch, tmp_path):
    """Merge may remove a PARTIAL only after verifying material incompatibility."""
    monkeypatch.setattr(m1.subprocess, "check_output", lambda *a, **k: SHA)
    path = tmp_path / "passes.tsv"
    assert m1.record_partial(
        class_key="mage", level=30, spec="unrestricted", gate="P3",
        report=_behavior_partial(46, 160), path=path)
    assert m1.scoreboard(path)["measured_gate_equivalents"] == pytest.approx(46 / 160)
    assert m1.main(["--ledger", str(path), "--invalidate",
                    "mage", "30", "unrestricted", "P3"]) == 0
    assert m1._rows(path) == {}
    assert m1.scoreboard(path)["measured_gate_equivalents"] == 0
