"""Forever contract tests for a genuinely paired native rest-policy result.

Synthetic receipts here exercise reporting only, not Rust combat or ACK proof.
The paid workflow runs the exact pinned source-native evaluator separately.
"""
import json

from src.v2.native_range_optimizer import (
    main, measured_world_rest_head_to_head, measured_world_rolling_head_to_head,
)


def paid_row(threshold, elapsed, *, source="a" * 64, pet="Succubus"):
    policy = {
        "pull_mode": "serial", "rest_when_health_below": threshold,
        "rest_when_mana_below": threshold,
        "rest_until": "full_when_triggered",
        "terminal_full_hp_and_mana": True,
    }
    return {
        "status": "MEASURED_NATIVE_FULLY_RECOVERED",
        "candidate_id": f"rest-{threshold}",
        "level": 20, "mob_count": 2, "targets_killed": 2,
        "rng_mode": "balanced", "iterations": 1,
        "native_prepared": True, "native_world_ack": True,
        "source_request_sha256": source, "engine_binary_sha256": "b" * 64,
        "native_full_recovery_paid": True, "recover_to_full": True,
        "terminal_hp": 100.0, "terminal_max_hp": 100.0,
        "terminal_mana": 200.0, "terminal_max_mana": 200.0,
        "elapsed_seconds": elapsed, "terminal_recovery_seconds": 4.0,
        "talents": "111-000-000", "pet": pet,
        "gear": [{"id": 10}], "apl": {"priorityList": ["corruption"]},
        "native_world_policy": policy,
        "proposal_axis": "world_rest_30pct" if threshold == 0.3 else "talent",
        "native_raw_receipt_file": f"runs/rest-{threshold}.native.json",
        "native_raw_receipt_sha256": ("c" if threshold == 1.0 else "d") * 64,
        "reused_exact_native_paid_receipt": False,
    }


def result_for(rows, rejected=()):
    return {
        "mob_count": 2, "rng_mode": "balanced", "iterations": 1,
        "independent_level_rankings": {"20": [
            {"source_request_sha256": row["source_request_sha256"],
             "engine_binary_sha256": row["engine_binary_sha256"],
             "native_elapsed_seconds": row["elapsed_seconds"],
             "terminal_recovery_seconds": row["terminal_recovery_seconds"],
             "talents": row["talents"], "pet": row["pet"],
             "gear": row["gear"], "apl": row["apl"],
             "native_world_policy": row["native_world_policy"],
             "receipt": row}
            for row in rows
        ]},
        "rejected_native_attempts": list(rejected),
    }


def test_paid_same_source_policy_pair_has_exact_ranked_receipts():
    report = result_for([paid_row(1.0, 43), paid_row(0.3, 39)])
    comparison = measured_world_rest_head_to_head(report, level=20)
    assert comparison["status"] == "MEASURED_NATIVE_REST_HEAD_TO_HEAD"
    assert comparison["winner"] == "thirty_percent"
    assert comparison["full_minus_thirty_elapsed_seconds"] == 4.0
    assert comparison["baseline"]["charged_elapsed_seconds"] == 43
    assert comparison["thirty_percent"]["terminal_recovery_seconds"] == 4
    assert comparison["baseline"]["native_raw_receipt_sha256"] == "c" * 64
    assert comparison["thirty_percent"]["native_raw_receipt_sha256"] == "d" * 64
    assert comparison["baseline"]["source_request_sha256"] == (
        comparison["thirty_percent"]["source_request_sha256"])


def test_unmatched_source_or_actor_is_not_a_fake_policy_win():
    for challenger in (paid_row(0.3, 30, source="e" * 64),
                       paid_row(0.3, 30, pet="Felhunter")):
        comparison = measured_world_rest_head_to_head(
            result_for([paid_row(1.0, 43), challenger]), level=20)
        assert comparison["status"] == "NATIVE_REST_HEAD_TO_HEAD_INCOMPLETE"
        assert comparison["winner"] is None


def test_missing_original_native_receipt_is_not_paid_evidence():
    challenger = paid_row(0.3, 30)
    challenger.pop("native_raw_receipt_sha256")
    comparison = measured_world_rest_head_to_head(
        result_for([paid_row(1.0, 43), challenger]), level=20)
    assert comparison["status"] == "NATIVE_REST_HEAD_TO_HEAD_INCOMPLETE"


def test_ranked_clocks_must_equal_original_native_paid_receipt():
    # Rankings are mutable projections; neither the winning clock nor
    # terminal recovery may disagree with the raw native evaluator result.
    # A stale fast ranking must never turn a slower native policy into a win.
    for projection, bad_value in (
        ("native_elapsed_seconds", 1.0),
        ("terminal_recovery_seconds", 0.0),
    ):
        report = result_for([paid_row(1.0, 43), paid_row(0.3, 49)])
        report["independent_level_rankings"]["20"][1][projection] = bad_value
        comparison = measured_world_rest_head_to_head(report, level=20)
        assert comparison["status"] == "NATIVE_REST_HEAD_TO_HEAD_INCOMPLETE"
        assert comparison["winner"] is None
        assert comparison["thirty_percent_paid_candidates"] == 0


def test_native_refusal_without_applied_policy_object_is_preserved():
    # Rust can refuse before it can acknowledge any applied thresholds.
    # Do not drop the proposal-axis refusal or crash on a null policy.
    refusal = {
        "level": 20, "proposal_axis": "world_rest_30pct",
        "native_world_policy": None, "native_refusal_code": "NATIVE_POLICY_REFUSED",
        "native_refusal": "source-native evaluator declined threshold",
    }
    comparison = measured_world_rest_head_to_head(
        result_for([paid_row(1.0, 43)], rejected=[refusal]), level=20)
    assert comparison["status"] == "NATIVE_REST_HEAD_TO_HEAD_INCOMPLETE"
    assert comparison["winner"] is None
    assert comparison["thirty_percent_refusals"] == [refusal]


def test_exact_cli_records_refusal_and_exits_nonzero_for_one_sided_paid_result(
        tmp_path):
    baseline = paid_row(1.0, 42)
    refusal = {
        "status": "NATIVE_API_CANDIDATE_REFUSED", "candidate_id": "rest-0.3",
        "level": 20, "native_prepared": True,
        "proposal_axis": "world_rest_30pct",
        "native_refusal_code": "native_world_recovery_threshold_refused",
        "native_refusal": "Rust did not acknowledge 30% thresholds",
        "native_world_policy": paid_row(0.3, 39)["native_world_policy"],
    }

    def evaluator(**request):
        assert request["level"] == 20
        assert request["budget"] == 2
        return [baseline, refusal]

    out = tmp_path / "rest.json"
    args = [
        "--class", "warlock", "--tree", "unconstrained",
        "--start-level", "20", "--end-level", "20", "--level-stride", "1",
        "--n-mobs", "2", "--budget", "2", "--rng", "balanced",
        "--backend", "rust", "--compare-world-rest-30", "--out", str(out),
    ]
    assert main(args, evaluate=evaluator) == 2
    recorded = json.loads(out.read_text())
    assert len(recorded["ranked_alternatives"]) == 1  # partial native sample remains
    comparison = recorded["world_rest_head_to_head"]
    assert comparison["status"] == "NATIVE_REST_HEAD_TO_HEAD_INCOMPLETE"
    assert comparison["winner"] is None
    assert comparison["thirty_percent_refusals"][0]["native_refusal_code"] == (
        "native_world_recovery_threshold_refused")


def test_exact_cli_succeeds_only_with_genuinely_paired_paid_native_rows(tmp_path):
    def evaluator(**request):
        assert request["level"] == 20
        return [paid_row(1.0, 43), paid_row(0.3, 39)]

    out = tmp_path / "complete.json"
    assert main([
        "--class", "warlock", "--tree", "unconstrained",
        "--start-level", "20", "--end-level", "20", "--level-stride", "1",
        "--n-mobs", "2", "--budget", "2", "--rng", "balanced",
        "--backend", "rust", "--compare-world-rest-30", "--out", str(out),
    ], evaluate=evaluator) == 0
    assert json.loads(out.read_text())["world_rest_head_to_head"]["winner"] == (
        "thirty_percent")


def rolling_paid_row(*, elapsed=38.0, acknowledged=True):
    """Synthetic transport-only receipt; no native overlap proof asserted here."""
    from tools.wf_warlock_native_persistent_optimizer import ROLLING_WORLD_APL_50

    row = paid_row(1.0, elapsed)
    row["candidate_id"] = "rolling-50"
    row["proposal_axis"] = "world_rolling_50pct"
    row["native_raw_receipt_sha256"] = "e" * 64
    row["native_world_policy"] = dict(
        row["native_world_policy"], pull_mode="rolling",
        world_apl=ROLLING_WORLD_APL_50,
    )
    if acknowledged:
        row.update({
            "native_world_apl": ROLLING_WORLD_APL_50,
            "native_world_overlap_verified": True,
            "native_world_overlap": {
                "max_concurrent_alive_targets": 2,
                "simultaneously_alive_world_target_ids": ["m1", "m0"],
                "native_target_to_world_id": {"0": "m1", "1": "m0"},
                "old_target_dot_ticks_after_switch_acked": 1,
            },
            "native_world_kills": [
                {"target_id": "m1", "ack_sha256": "first"},
                {"target_id": "m0", "ack_sha256": "second"},
            ],
        })
    return row


def test_rolling_head_to_head_requires_original_paid_overlap_and_build_identity():
    baseline = paid_row(1.0, 45)
    for challenger in (
        rolling_paid_row(acknowledged=False),
        rolling_paid_row(acknowledged=True) | {"native_world_kills": []},
        rolling_paid_row(acknowledged=True) | {"source_request_sha256": "c" * 64},
    ):
        report = result_for([baseline, challenger])
        comparison = measured_world_rolling_head_to_head(report, level=20)
        assert comparison["status"] == "NATIVE_ROLLING_WORLD_APL_INCOMPLETE"
        assert comparison["winner"] is None
    report = result_for([baseline, rolling_paid_row()])
    comparison = measured_world_rolling_head_to_head(report, level=20)
    assert comparison["status"] == "MEASURED_NATIVE_ROLLING_WORLD_APL_HEAD_TO_HEAD"
    assert comparison["winner"] == "rolling"
    assert comparison["serial_minus_rolling_elapsed_seconds"] == 7.0
    assert comparison["rolling"]["native_world_kills"][0]["ack_sha256"] == "first"


def test_rolling_cli_refuses_unacknowledged_native_overlap_even_with_serial_win(
        tmp_path):
    refusal = {
        "status": "NATIVE_API_CANDIDATE_REFUSED",
        "candidate_id": "rolling-50", "level": 20,
        "native_prepared": True, "proposal_axis": "world_rolling_50pct",
        "native_refusal_code": "native_world_rolling_unsupported",
        "native_refusal": "Rust serial scheduler cannot switch before lethal",
        "native_world_policy": rolling_paid_row()["native_world_policy"],
    }
    def evaluate(**request):
        assert request["level"] == 20
        assert request["budget"] == 2
        return [paid_row(1.0, 45), refusal]
    path = tmp_path / "rolling.json"
    rc = main([
        "--class", "warlock", "--tree", "unconstrained",
        "--start-level", "20", "--end-level", "20", "--level-stride", "1",
        "--n-mobs", "2", "--budget", "2", "--rng", "balanced",
        "--backend", "rust", "--compare-world-rolling-50", "--out", str(path),
    ], evaluate=evaluate)
    assert rc == 2
    result = json.loads(path.read_text())
    assert result["ranked_alternatives"]
    head = result["world_rolling_head_to_head"]
    assert head["status"] == "NATIVE_ROLLING_WORLD_APL_INCOMPLETE"
    assert head["rolling_refusals"][0]["native_refusal_code"] == (
        "native_world_rolling_unsupported")
    assert head["winner"] is None
