"""Feral L60 native P3 no-record CI reports refusals without adding a gate.

Execute the actual selected-engine workflow's inline receipt reader. Its
independent options probe and returned candidate count are diagnostics, not
preconditions for the approved P3 outcome.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import textwrap

import pytest

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/rust-submodule-verify.yml"
STEP = "Run Druid Feral L60 unified-options native P3 (no record)"


def _reader() -> str:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    section = workflow.split(f"      - name: {STEP}\n", 1)[1]
    match = re.search(r"(?ms)^ {10,12}python - [^\n]+ <<'PY'\n(.*?)\n          PY$", section)
    assert match, "missing Feral no-record reader in selected-engine workflow"
    return textwrap.dedent(match.group(1))


def _run(tmp_path, monkeypatch, *, status: str, options_status: str = "ok",
         rows=None, gate_rc: int | None = None, level: int = 60):
    options = tmp_path / "options.json"
    options.write_text(json.dumps({
        "class": "druid", "level": 60, "status": options_status,
        "refusal": {"code": "UNSUPPORTED"} if options_status == "refused" else None,
    }), encoding="utf-8")
    report = tmp_path / "gate.json"
    report.write_text(json.dumps({
        "class": "druid", "level": level, "spec": "feral", "gate": "P3",
        "status": status, "reasons": ["NATIVE_REJECTED"],
        "results": [] if rows is None else rows,
    }), encoding="utf-8")
    # No prepared actor receipt: preparation is an independent diagnostic.
    prepared = tmp_path / "not-prepared.json"
    rc = (0 if status == "PASS" else 1) if gate_rc is None else gate_rc
    monkeypatch.setattr(sys, "argv", [
        "-", str(options), str(prepared), str(report), "1", str(rc),
    ])
    exec(compile(_reader(), str(WORKFLOW), "exec"), {"__name__": "__main__"})


@pytest.mark.parametrize("status,options_status,rows", [
    ("BLOCKED", "refused", None),
    ("FAIL", "ok", None),
    ("PASS", "refused", [{"native_equipped_paid_attempts": 72}]),
])
def test_feral_no_record_reports_actual_gate_result(
        status, options_status, rows, tmp_path, monkeypatch, capsys):
    _run(tmp_path, monkeypatch, status=status, options_status=options_status,
         rows=rows)
    output = capsys.readouterr().out
    assert "FERAL_L60_P3_NO_RECORD" in output
    assert f"gate {status}" in output
    assert "native_refusal" in output


def test_feral_no_record_rejects_wrong_exit_code(tmp_path, monkeypatch):
    with pytest.raises(AssertionError):
        _run(tmp_path, monkeypatch, status="PASS", gate_rc=1)


def test_feral_no_record_rejects_wrong_checkpoint(tmp_path, monkeypatch):
    with pytest.raises(AssertionError):
        _run(tmp_path, monkeypatch, status="FAIL", level=20)
