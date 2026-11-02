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
