"""Fail-closed analysis of the genuine live checkpoint CLI response."""
from __future__ import annotations

import pytest

from tools.wf_checkpoint_druid_balance_l60 import GATES, analyze_live_result


def report(status="BLOCKED"):
    rows=[]
    for gate in GATES:
        row={"gate":gate,"status":status,
             "reasons":[] if status=="PASS" else ["NOT_EXECUTED"]}
        if status=="PASS" and gate not in ("P1","P2"):
            row["runtime_proof"]={"executed":True,"engine_revision":"r","source_revision":"s",
                                  "run_id":"genuine-provider-required"}
        rows.append(row)
    return {"class":"druid","level":60,"spec":"balance","gate":"all",
            "results":rows}


def test_incomplete_live_checkpoint_not_certified():
    result=analyze_live_result(report())
    assert result["checkpoint"] == "druid:L60:balance"
    assert result["pending"] == list(GATES)
    assert result["live_gate_pass_count"] == 0
    assert result["checkpoint_certified"] is False


def test_all_declared_green_still_needs_real_evidence_and_review():
    result=analyze_live_result(report("PASS"))
    assert result["all_live_providers_pass"]
    assert result["checkpoint_certified"] is False


def test_missing_gate_rejected():
    value=report()
    value["results"].pop()
    with pytest.raises(ValueError, match="MISSING_OR_REORDERED_REAL_GATES"):
        analyze_live_result(value)


def test_forged_runtime_metadata_rejected():
    value=report("PASS")
    value["results"][6].pop("runtime_proof")
    with pytest.raises(ValueError, match="NO_REAL_RUNTIME_PROOF:P7.1"):
        analyze_live_result(value)


def test_partial_or_inconsistent_pass_rejected():
    value=report("PASS")
    value["results"][3]["reasons"]=["search did not finish"]
    with pytest.raises(ValueError, match="FAKE_GATE_PASS_WITH_FAILURES:P4"):
        analyze_live_result(value)
