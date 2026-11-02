"""Real P6 paid-replay outcomes must remain inspectable in the no-record CLI.

The fixture checks only report serialization; it does not invent replay kills,
certify P6 or bypass the real CombatRuntime.
"""
import json

from tools import wf_gate


def test_p6_no_record_cli_exposes_bounded_paid_leg_failures(monkeypatch, capsys):
    report = {
        "status": "FAIL",
        "reasons": ["P6_INCOMPLETE_SOURCE_PAID_100MOB_REPLAY"],
        "production_engine": "gsim_CombatRuntime",
        "pass_count": 100, "reachability_count": 200,
        "coverage_basis": "executed_behavior_assertions",
        "source_replay_results": [
            {"cold_search_budget_s": 4.0, "status": "COMPLETE",
             "mob_completed": 100, "count": 100, "mean_s_per_mob": 10.0,
             "events": 111, "private_bulk_trace": "do not copy"},
            {"cold_search_budget_s": 6.0,
             "status": "BLOCKED_EVALUATION_COMPUTE_BUDGET",
             "reason": "actual deadline", "mob_completed": 0,
             "paid_screens": 5, "private_bulk_trace": "do not copy"},
        ],
    }
    monkeypatch.setattr(wf_gate, "_run_live_gate", lambda *args: report)
    rc = wf_gate.main(["--class", "druid", "--level", "60",
                       "--spec", "balance", "--gate", "P6"])
    output = json.loads(capsys.readouterr().out)
    assert rc == 1 and output["status"] == "FAIL"
    rows = output["results"][0]["source_replay_results"]
    assert rows == [
        {"cold_search_budget_s": 4.0, "status": "COMPLETE",
         "count": 100, "mob_completed": 100,
         "mean_s_per_mob": 10.0, "events": 111},
        {"cold_search_budget_s": 6.0,
         "status": "BLOCKED_EVALUATION_COMPUTE_BUDGET",
         "reason": "actual deadline", "mob_completed": 0,
         "paid_screens": 5},
    ]
    assert "private_bulk_trace" not in str(output)
    assert output["results"][0]["pass_count"] == 100
    assert output["results"][0]["reachability_count"] == 200


def test_p6_receipt_invalid_nonfinite_and_large_payload_cannot_leak():
    rows = [{"status": "X" * 300, "reason": "Y" * 400,
             "events": float("inf"), "count": True,
             "bulk": "private"}] * 5
    receipts = wf_gate._p6_replay_receipts({"source_replay_results": rows})
    assert len(receipts) == 2
    assert receipts[0] == {"status": "X" * 240, "reason": "Y" * 240}
    assert wf_gate._p6_replay_receipts({}) is None
    assert wf_gate._p6_replay_receipts({"source_replay_results": {}}) is None
