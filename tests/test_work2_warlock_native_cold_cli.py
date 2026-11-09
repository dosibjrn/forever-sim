"""Regression for genuine paid Warlock P4/P5 cold CLI completion.

Mock only Forever's CLI scheduling/receipt handoff; no native mechanics
or synthetic gameplay PASS is asserted.
"""
import copy
import json
import sys

import pytest

from tools import wf_warlock_l20_native_cold as cold


def _report():
    return {
        "native_search": {"status": "RAN"},
        "native_paid_screen_count": 2,
        "cold_300_reached": True,
        "snapshot_30": {"candidate_sha256": "early"},
        "final_300": {"candidate_sha256": "late"},
        "finalists": {
            "30s": {"status": "COMPLETED_100_REAL_NATIVE_GSIM_KILLS"},
            "300s": {"status": "COMPLETED_100_REAL_NATIVE_GSIM_KILLS"},
        },
        "p6_comparison": {
            "status": "MEASURED_PAID_100_MOB_FINALISTS",
            "within_one_percent": False,
        },
        "gate_recorded": False,
        "p4_p5_p6_pass": False,
    }


@pytest.mark.parametrize("missing", [
    "snapshot", "final", "cold_300", "finalist", "comparison",
])
def test_cold_producer_refuses_incomplete_paid_evidence(missing):
    result = _report()
    if missing == "snapshot":
        result["snapshot_30"] = None
    elif missing == "final":
        result["final_300"] = None
    elif missing == "cold_300":
        result["cold_300_reached"] = False
    elif missing == "finalist":
        result["finalists"]["300s"]["status"] = "INCOMPLETE_100_NATIVE_FINALIST"
    elif missing == "comparison":
        result["p6_comparison"] = None
    assert not cold.cold_search_has_paid_finalist_evidence(result)


def test_producer_completion_is_distinct_from_p6_saturation():
    report = _report()
    assert cold.cold_search_has_paid_finalist_evidence(report)
    assert report["p6_comparison"]["within_one_percent"] is False
    assert report["gate_recorded"] is False


@pytest.mark.parametrize("complete", [False, True])
def test_cold_cli_exit_code_matches_actual_paid_evidence(
    monkeypatch, tmp_path, capsys, complete,
):
    binary = tmp_path / "engine"
    binary.write_bytes(b"native test engine")
    source = tmp_path / "actor.json"
    source.write_text(json.dumps({"native_source": "input-only"}) + "\n")
    report = _report()
    if not complete:
        report["snapshot_30"] = None

    def fake_run_cold(reference, options, **kwargs):
        assert reference == {"native_source": "input-only"}
        assert options == {"source_revision": "native-test"}
        return copy.deepcopy(report)

    monkeypatch.setattr(cold, "query_native_options",
                        lambda *args: {"source_revision": "native-test"})
    monkeypatch.setattr(cold, "run_cold", fake_run_cold)
    monkeypatch.setattr(sys, "argv", [
        "wf_warlock_l20_native_cold.py", "--binary", str(binary),
        "--source", str(source), "--out", str(tmp_path / "receipts"),
    ])
    if complete:
        cold.main()
    else:
        with pytest.raises(SystemExit) as exit_info:
            cold.main()
        assert exit_info.value.code == 1

    stdout = capsys.readouterr().out
    assert "WARLOCK_NATIVE_COLD_PAID_SEARCH" in stdout
    status = ("COMPLETED_PAID_FINALISTS" if complete
              else "INCOMPLETE_PAID_FINALIST_EVIDENCE")
    assert status in stdout
    assert '"p6_within_one_percent": false' in stdout
