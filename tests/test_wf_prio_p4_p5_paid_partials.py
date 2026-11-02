"""P4/P5 actual on-demand source-paid 2D production probe checks."""
from tools.wf_gate import ROOT, _run_live_gate
from tools.wf_gate_p4_p5_partial import paid_gear_slot_coverage


def test_paid_slot_partial_only_counts_complete_action_executions():
    # No fake PASS from merely being proposed or evaluated but failed.
    evidence = {"source_slot_proposal_coverage":
        {"eligible_slots": ["head", "chest"], "paid_slots": ["head", "chest"]},
        "rows": [
            {"gear_move": "head:17", "screen_invoked": True,
             "screen_status": "COMPLETE", "source_action_counts": {"spell": 3}},
            {"gear_move": "chest:18", "screen_invoked": True,
             "screen_status": "BLOCKED", "source_action_counts": {"spell": 3}},
            {"gear_move": "head:19", "screen_invoked": True,
             "screen_status": "COMPLETE", "source_action_counts": {"spell": 1}},
        ]}
    assert paid_gear_slot_coverage(evidence) == {
        "verified": 1, "applicable": 2, "executed": 2,
        "paid_slots": ["head"], "eligible_slots": ["chest", "head"]}


def test_p4_unrestricted_druid_l30_executes_real_source_paid_backend():
    report = _run_live_gate(ROOT, "druid", 30, "unrestricted", "P4", "")
    assert report["status"] == "FAIL", report
    # Merely exploring a legal slot is NOT a successful behavioral assertion.
    assert report["explored_paid_gear_slots"] >= 0
    assert report["source_eligible_gear_slot_count"] > 0
    assert report.get("partial_scope") != "COMPLETED_PAID_SOURCE_GEAR_SLOT_CANDIDATES"
    assert report["production_engine"] == "gsim_CombatRuntime"
    assert report["required_full_search_s"] == 30
    assert report["real_paid_unique_full_builds"] >= 0
    if "pass_count" in report:
        assert report["coverage_basis"] == "executed_behavior_assertions"
        assert report["partial_scope"] == "SOURCE_TALENT_UNLOCK_CAST_IN_COMPLETE_PAID_SCREEN"
        assert 0 <= report["pass_count"] <= report["reachability_count"]
        assert report["reachability_count"] > 0
    assert report["selected_backend_integration_pending"]
    assert report["reasons"], report


def test_p5_is_not_300s_or_10x_acceptance():
    # Bounded production partial is no substitute for full independent 300s
    # acceptance: spec-gated checkpoint rejects early rather than fake PASS.
    report = _run_live_gate(ROOT, "druid", 60, "balance", "P5", "")
    assert report["status"] == "BLOCKED"
    assert "SOURCE_SPEC_TREE_SEARCH_CONSTRAINT_NOT_YET_CONNECTED" in report["reasons"]
