"""No-record Rogue/Mage P3 CI reports native outcomes without new source gates.

Execute the workflow's actual inline Python reader against synthetic Forever
receipts. These tests assert only transport and result propagation, not Rust
Warcraft mechanics or P3 acceptance criteria.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import textwrap

import pytest

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/rust-submodule-verify.yml"
STEPS = (
    ("Run no-record Rogue L20 P3 native capability and gate receipt", "rogue", 20),
    ("Run no-record Mage L30 P3 with native item options", "mage", 30),
)


def _reader(step: str) -> str:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    section = workflow.split(f"      - name: {step}\n", 1)[1]
    match = re.search(r"(?ms)^ {10,12}python - [^\n]+ <<'PY'\n(.*?)\n          PY$", section)
    assert match, f"missing inline no-record reader: {step}"
    return textwrap.dedent(match.group(1))


def _run(step, class_key, level, status, tmp_path, monkeypatch,
         *, exit_code=None, checkpoint_level=None, row=None):
    report = {
        "class": class_key, "level": checkpoint_level or level,
        "spec": "unrestricted", "gate": "P3", "status": status,
        "reasons": ["SOURCE_REFUSAL_CHANGED"],
        "results": [] if row is None else [row],
    }
    result_file = tmp_path / "report.json"
    result_file.write_text(json.dumps(report), encoding="utf-8")
    args = ["-"]
    if class_key == "rogue":
        native = {
            "class": "rogue", "level": 20, "spec": "unrestricted", "slot": "all",
            "status": "refused",
            "refusal": {"code": "RUST_SOURCE_REJECTED_NEW_KIND"},
            "items": [],
        }
        native_file = tmp_path / "native.json"
        native_file.write_text(json.dumps(native), encoding="utf-8")
        args.append(str(native_file))
    args.extend([str(result_file), str(
        exit_code if exit_code is not None else (0 if status == "PASS" else 1))])
    monkeypatch.setattr(sys, "argv", args)
    exec(compile(_reader(step), str(WORKFLOW), "exec"), {"__name__": "__main__"})


@pytest.mark.parametrize("step,class_key,level", STEPS)
@pytest.mark.parametrize("status", ("BLOCKED", "FAIL", "PASS"))
def test_genuine_native_outcomes_do_not_trigger_extra_diagnostic_gates(
        step, class_key, level, status, tmp_path, monkeypatch, capsys):
    _run(step, class_key, level, status, tmp_path, monkeypatch,
         row=None if status == "BLOCKED" else {
             "native_item_options_status": "partial_level_unknown",
             "native_item_options_source": "engine:changed-protocol",
             "native_equipped_paid_attempts": 0,
             "pass_count": 0, "reachability_count": 0,
             "reasons": ["RUST_REFUSED_WITHOUT_A_PAID_ITEM"],
         })
    output = capsys.readouterr().out
    assert "NO_RECORD_NATIVE_P3_OBSERVED" in output
    assert status in output


@pytest.mark.parametrize("step,class_key,level", STEPS)
def test_ci_still_rejects_inconsistent_pass_exit_code(
        step, class_key, level, tmp_path, monkeypatch):
    with pytest.raises(AssertionError):
        _run(step, class_key, level, "PASS", tmp_path, monkeypatch, exit_code=1)


@pytest.mark.parametrize("step,class_key,level", STEPS)
def test_ci_still_rejects_wrong_checkpoint(
        step, class_key, level, tmp_path, monkeypatch):
    with pytest.raises(AssertionError):
        _run(step, class_key, level, "FAIL", tmp_path, monkeypatch,
             checkpoint_level=level + 1)
