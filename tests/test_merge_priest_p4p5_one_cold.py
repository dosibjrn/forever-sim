"""Merge-owned paired Priest P4/P5 recording reuses one executable cold run."""
import json
from unittest.mock import patch

import pytest

from tools import wf_gate
from tools import wf_gate_p4_p5_partial as source


@pytest.mark.parametrize("p4_status", ["PASS", "FAIL"])
def test_priest_p4_p5_one_cold_two_independent_gate_verdicts(
        tmp_path, monkeypatch, capsys, p4_status):
    binary = tmp_path / "selected-native"
    binary.write_bytes(b"fixture selected native executable identity")
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", str(binary))
    monkeypatch.setenv("FOREVER_P4_P5_PRIEST_L20_SOURCE_REQUEST_DIR",
                       "source-priest-fixture")
    monkeypatch.setenv("FOREVER_P4_P5_PRIEST_L20_LIVE_WORLD", "1")
    monkeypatch.setenv("FOREVER_P4_P5_PRIEST_L20_PERSISTENT_TARGETS", "100")
    monkeypatch.setenv("FOREVER_P4_P5_PRIEST_L20_COLD_SEARCH", "1")
    cold = {
        "native_cold_search_wall_s": 300.12,
        "native_cold_native_paid_before_30": 11,
        "native_cold_native_paid_after_30": 37,
        "native_cold_completed_routes_before_30": 1,
        "native_cold_completed_routes_after_30": 1,
        "native_cold_snapshot_30": {"source_request_sha256": "a" * 64},
        "native_cold_final_300": {"source_request_sha256": "a" * 64},
    }
    verdicts = {
        "P4": {"status": p4_status,
               "reasons": [] if p4_status == "PASS" else ["P4_REAL_WITNESS_MISSING"]},
        "P5": {"status": "PASS", "reasons": []},
    }
    with (
        patch("src.game.native_p3_item_options.query_native_p3_item_options",
              return_value={"items": [{"id": 1}],
                            "unverified_candidate_count": 0,
                            "status": "VALID"}),
        patch("tools.wf_native_priest_l20_cold.run_native_priest_l20_cold",
              return_value=cold) as paid,
        patch("tools.wf_native_priest_l20_cold.native_cold_gate_verdicts",
              return_value=verdicts),
        patch("tools.m1_progress.record_pass") as record,
    ):
        rc = wf_gate.main(["--class", "priest", "--level", "20",
                           "--spec", "unrestricted", "--gate", "P4+P5",
                           "--record-progress"])
    output = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert paid.call_count == 1, "must not pay a second 300s cold search"
    assert [r["gate"] for r in output["results"]] == ["P4", "P5"]
    assert [r["status"] for r in output["results"]] == [p4_status, "PASS"]
    assert rc == (0 if p4_status == "PASS" else 1)
    assert [call.kwargs["gate"] for call in record.call_args_list] == (
        ["P4", "P5"] if p4_status == "PASS" else ["P5"])
    assert source._SHARED_PRIEST_L20_COLD is None


def test_pair_requires_explicit_native_cold_mode():
    with pytest.raises(SystemExit) as error:
        wf_gate.main(["--class", "priest", "--level", "20",
                      "--gate", "P4+P5"])
    assert error.value.code == 2
