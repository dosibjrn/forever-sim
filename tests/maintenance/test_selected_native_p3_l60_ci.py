"""Selected-engine L60 no-record P3 CI must not add source-count acceptance gates.

Exercise the *actual inline readers* with Forever transport receipts. Native
refusal, search breadth and paid-attempt counts are observations, not a
separate MythicSim legality check or P3 acceptance criterion.
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
    ("Run Mage Arcane L60 unified-options native P3 (no record)", "mage", "arcane"),
    ("Run Mage Fire L60 selected-native P3 (no record)", "mage", "fire"),
    ("Run Mage Frost L60 selected-native P3 (no record)", "mage", "frost"),
    ("Run Paladin Retribution L60 selected-native P3 (no record)", "paladin", "retribution"),
    ("Run Paladin Protection L60 selected-native TPS P3 (no record)", "paladin", "protection"),
)


def _reader(step: str) -> str:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    section = workflow.split(f"      - name: {step}\n", 1)[1]
    match = re.search(r"(?ms)^ {10,12}python - [^\n]+ <<'PY'\n(.*?)\n          PY$", section)
    assert match, f"missing no-record receipt reader: {step}"
    return textwrap.dedent(match.group(1))


def _run(step, class_key, spec, status, tmp_path, monkeypatch, *,
         rows=None, level=60, exit_code=None):
    gate = {
        "class": class_key, "level": level, "spec": spec, "gate": "P3",
        "status": status,
        "reasons": ["NATIVE_SOURCE_REFUSED"],
        "results": rows if rows is not None else [],
    }
    report = tmp_path / "p3.json"
    report.write_text(json.dumps(gate), encoding="utf-8")
    code = (0 if status == "PASS" else 1) if exit_code is None else exit_code
    monkeypatch.setattr(sys, "argv", ["-", str(report), str(code)])
    exec(compile(_reader(step), str(WORKFLOW), "exec"), {"__name__": "__main__"})


@pytest.mark.parametrize("step,class_key,spec", STEPS)
@pytest.mark.parametrize("status", ("BLOCKED", "FAIL", "PASS"))
def test_native_outcome_and_changed_search_breadth_do_not_veto_no_record_ci(
        step, class_key, spec, status, tmp_path, monkeypatch, capsys):
    # A future Rust/Forever implementation can perform more than the old 44
    # attempts or use an additional paid source search without becoming invalid.
    # Receipt metadata may be absent or describe a partial/refused native run.
    _run(step, class_key, spec, status, tmp_path, monkeypatch, rows=[{
        "item_options_source": "MYTHICSIM_NATIVE_GET_OPTIONS",
        "real_source_search_evaluated": 93,
        "native_equipped_paid_attempts": 72,
        "native_equipped_paid_receipt": {
            "status": "refused",
            "paid_attempts": 5,
            "native_slot_evaluations": [],
        },
    }])
    assert status in capsys.readouterr().out


@pytest.mark.parametrize("step,class_key,spec", STEPS)
@pytest.mark.parametrize("status", ("BLOCKED", "FAIL"))
def test_native_refusal_without_per_candidate_rows_is_reportable(
        step, class_key, spec, status, tmp_path, monkeypatch, capsys):
    _run(step, class_key, spec, status, tmp_path, monkeypatch)
    assert status in capsys.readouterr().out


@pytest.mark.parametrize("step,class_key,spec", STEPS)
def test_no_record_still_rejects_wrong_exit_code(
        step, class_key, spec, tmp_path, monkeypatch):
    with pytest.raises(AssertionError):
        _run(step, class_key, spec, "PASS", tmp_path, monkeypatch, exit_code=1)


@pytest.mark.parametrize("step,class_key,spec", STEPS)
def test_no_record_still_rejects_wrong_checkpoint(
        step, class_key, spec, tmp_path, monkeypatch):
    with pytest.raises(AssertionError):
        _run(step, class_key, spec, "FAIL", tmp_path, monkeypatch, level=20)
