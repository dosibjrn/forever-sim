"""Forever contract tests for a genuinely paired native rest-policy result.

Synthetic receipts here exercise reporting only, not Rust combat or ACK proof.
The paid workflow runs the exact pinned source-native evaluator separately.
"""
import json

from src.v2.native_range_optimizer import main, measured_world_rest_head_to_head


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
