"""Actual blocking acceptance test: source-legal ranks must execute, not just exist."""
from tests.test_wf430_p2_whole_gate_26point_tdd import audit

def test_all_structurally_reachable_source_ranks_have_executors_and_apply():
    result = audit()
    assert result["source_rank_total"] == 148
    assert result["reachable_without_executor"] == 0, [
        (row["talent_id"], row["rank"]) for row in result["structural_witnesses"]
        if row["status"] == "RED_NO_EXECUTOR"
    ]
    assert result["rank_application_failure_count"] == 0
    assert result["source_prerequisite_or_curve_unverified_count"] == 0
    assert result["unresolved_reachability_count"] == 0
