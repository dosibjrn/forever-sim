"""Fast bookkeeping tests only; these are NOT P1–P7 acceptance tests."""
from pathlib import Path

import pytest
from tools import m1_progress as m1


SHA = "a" * 40


def test_empty_m1_uses_148_times_11(tmp_path):
    score = m1.scoreboard(tmp_path / "missing.tsv")
    assert (score["passed_gates"], score["total_gates"]) == (0, 1628)
    assert score["certified_checkpoints"] == 0


def test_real_pass_record_is_timestamped_and_deduplicated(monkeypatch, tmp_path):
    monkeypatch.setattr(m1.subprocess, "check_output", lambda *a, **k: SHA)
    path = tmp_path / "passes.tsv"
    for _ in range(2):
        m1.record_pass(class_key="druid", level=60, spec="balance",
                       gate="P2", report={"status": "PASS", "reasons": []},
                       root=tmp_path, path=path)
    rows = m1._rows(path)
    assert len(rows) == 1
    assert next(iter(rows.values()))["passed_at_utc"]
    assert m1.scoreboard(path)["passed_gates"] == 1
    assert m1.scoreboard(path)["gate_percent"] == pytest.approx(100 / 1628)


def test_cannot_stamp_fail_or_blocked(monkeypatch, tmp_path):
    monkeypatch.setattr(m1.subprocess, "check_output", lambda *a, **k: SHA)
    path = tmp_path / "passes.tsv"
    for status in ("FAIL", "BLOCKED"):
        with pytest.raises(ValueError):
            m1.record_pass(class_key="druid", level=60, spec="balance",
                           gate="P2", report={"status": status}, path=path)
    assert not path.exists()


def test_eleven_passes_without_compatible_production_are_not_148(monkeypatch, tmp_path):
    monkeypatch.setattr(m1.subprocess, "check_output", lambda *a, **k: SHA)
    path = tmp_path / "passes.tsv"
    for gate in m1.GATES:
        m1.record_pass(class_key="druid", level=60, spec="balance",
                       gate=gate, report={"status": "PASS", "reasons": []},
                       path=path)
    score = m1.scoreboard(path)
    assert score["passed_gates"] == 11
    assert score["complete_candidates"] == 1
    assert score["certified_checkpoints"] == 0


def test_compatible_eleven_and_invalidation(monkeypatch, tmp_path):
    monkeypatch.setattr(m1.subprocess, "check_output", lambda *a, **k: SHA)
    path = tmp_path / "passes.tsv"
    for gate in m1.GATES:
        m1.record_pass(class_key="druid", level=60, spec="balance",
                       gate=gate, report={"status": "PASS", "reasons": [],
                                          "compatibility_id": "pinned-source+engine-v1"},
                       path=path)
    assert m1.scoreboard(path)["certified_checkpoints"] == 1
    assert m1.main(["--ledger", str(path), "--invalidate",
                    "druid", "60", "balance", "P2"]) == 0
    assert m1.scoreboard(path)["certified_checkpoints"] == 0


def _p2_partial(verified=83, total=103):
    return {"status": "FAIL", "pass_count": verified,
            "reachability_count": total, "behavior_probes_executed": 110,
            "unresolved_count": 2, "coverage_basis": "executed_behavior_assertions"}


def test_partial_p2_is_visible_but_not_certified(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(m1.subprocess, "check_output", lambda *a, **k: SHA)
    path = tmp_path / "passes.tsv"
    assert m1.record_partial(class_key="druid", level=60, spec="balance",
                             gate="P2", report=_p2_partial(), path=path)
    score = m1.scoreboard(path)
    assert score["passed_gates"] == 0
    assert score["certified_checkpoints"] == 0
    assert score["partial_gates"][0]["coverage"] == pytest.approx(83 / 103)
    assert score["partial_gates"][0]["pareto_effort"] == pytest.approx(
        .2 + 4 * (83 / 103 - .8))
    assert score["measured_gate_equivalents"] == pytest.approx(83 / 103)
    assert score["measured_percent"] == pytest.approx(100 * 83 / 103 / 1628)
    assert score["partial_gates"][0]["provisional"]
    assert m1.main(["--ledger", str(path)]) == 0
    assert "83/103" in capsys.readouterr().out


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
                                     spec="balance", gate="P2",
                                     report=report, path=path)
    assert not path.exists()


def test_full_pass_supersedes_partial_and_partial_cannot_erase_it(monkeypatch, tmp_path):
    monkeypatch.setattr(m1.subprocess, "check_output", lambda *a, **k: SHA)
    path = tmp_path / "passes.tsv"
    assert m1.record_partial(class_key="druid", level=60, spec="balance",
                             gate="P2", report=_p2_partial(), path=path)
    m1.record_pass(class_key="druid", level=60, spec="balance",
                   gate="P2", report={"status": "PASS", "reasons": []}, path=path)
    assert m1.scoreboard(path)["passed_gates"] == 1
    assert not m1.record_partial(class_key="druid", level=60, spec="balance",
                                 gate="P2", report=_p2_partial(90), path=path)
    score = m1.scoreboard(path)
    assert not score["partial_gates"]
    assert score["measured_gate_equivalents"] == 1


def test_old_pass_only_ledger_is_backwards_compatible(tmp_path):
    path = tmp_path / "old.tsv"
    path.write_text("\t".join(m1.PASS_FIELDS) + "\n" +
                    "\t".join(("druid", "60", "balance", "P2",
                               "2026-11-02T00:00:00+00:00", SHA, "", "")) + "\n")
    assert m1.scoreboard(path)["passed_gates"] == 1


def test_partial_watermark_is_monotonic_but_logs_lower_current_measurement(
        monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(m1.subprocess, "check_output", lambda *a, **k: SHA)
    path = tmp_path / "m1.tsv"
    def record(n, d=100):
        return m1.record_partial(
            class_key="druid", level=60, spec="balance", gate="P2",
            report=_p2_partial(n, d), path=path)
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
                  saved_reference_dps=800., world_dps=720.)
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
        class_key="druid", level=60, spec="balance", gate="P2",
        report=_p2_partial(70, 100), path=path)
    assert not m1.record_partial(
        class_key="druid", level=60, spec="balance", gate="P2",
        report=_p2_partial(20, 20), path=path)
    saved = m1.scoreboard(path)["partial_gates"][0]
    assert (saved["verified"], saved["applicable"]) == (70, 100)
