"""Selected-engine no-record P3 CI must report native refusals, not veto them.

Run the actual inline Python receipt readers from the workflow with synthetic
Forever-owned gate outputs. This does not revalidate MythicSim game legality.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import textwrap

import pytest

WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github/workflows/rust-submodule-verify.yml"
)
STEPS = (
    ("Run no-record Priest and Mage L20 P3 with native item options", "priest"),
    ("Run no-record Shaman L20 P3 with native item options", "shaman"),
    ("Run no-record Paladin L20 P3 with native player context and item options", "paladin"),
)


def _reader(step: str) -> str:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    section = workflow.split(f"      - name: {step}\n", 1)[1]
    match = re.search(
        r"(?ms)^ {10,12}python - [^\n]+ <<'PY'\n(.*?)\n          PY$",
        section,
    )
    assert match, f"missing real no-record reader for {step}"
    return textwrap.dedent(match.group(1))


def _run_reader(step, class_key, report, exit_code, tmp_path, monkeypatch):
    path = tmp_path / "result.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    argv = ["-", str(path)]
    if class_key == "priest":
        argv.append(class_key)
    argv.append(str(exit_code))
    monkeypatch.setattr(sys, "argv", argv)
    exec(compile(_reader(step), str(WORKFLOW), "exec"), {"__name__": "__main__"})


@pytest.mark.parametrize("step,class_key", STEPS)
@pytest.mark.parametrize("status", ("BLOCKED", "FAIL", "PASS"))
def test_native_refusal_or_zero_candidates_do_not_make_diagnostic_ci_fail(
        step, class_key, status, tmp_path, monkeypatch, capsys):
    # The native result is authoritative. A refusal may not even have a
    # per-candidate row; a FAIL may have zero paid item alternatives.
    report = {
        "class": class_key, "level": 20, "spec": "unrestricted",
        "gate": "P3", "status": status,
        "reasons": ["NATIVE_ITEM_OPTIONS_UNSUPPORTED"],
        "results": [] if status in ("BLOCKED", "FAIL") else [{
            "native_item_options_status": "partial_level_unknown",
            "native_item_options_source": "mythicsim:unrecognized-version",
            "native_equipped_paid_attempts": 0,
            "real_catalogue_legal_items": 0,
            "real_native_representative_items_scored": 0,
            "reasons": ["NATIVE_REFUSAL"],
        }],
    }
    _run_reader(step, class_key, report, 0 if status == "PASS" else 1,
                tmp_path, monkeypatch)
    out = capsys.readouterr().out
    assert "NO_RECORD_NATIVE_P3_OBSERVED" in out
    assert status in out


@pytest.mark.parametrize("step,class_key", STEPS)
def test_no_record_ci_still_catches_false_pass_exit_code(
        step, class_key, tmp_path, monkeypatch):
    report = {
        "class": class_key, "level": 20, "spec": "unrestricted",
        "gate": "P3", "status": "PASS", "results": [{}],
    }
    with pytest.raises(AssertionError):
        _run_reader(step, class_key, report, 1, tmp_path, monkeypatch)


@pytest.mark.parametrize("step,class_key", STEPS)
def test_no_record_ci_still_catches_wrong_checkpoint(
        step, class_key, tmp_path, monkeypatch):
    report = {
        "class": class_key, "level": 60, "spec": "unrestricted",
        "gate": "P3", "status": "FAIL", "results": [{}],
    }
    with pytest.raises(AssertionError):
        _run_reader(step, class_key, report, 1, tmp_path, monkeypatch)
