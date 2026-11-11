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
        "native_world_policy": policy, "native_world_target_hp": 100.0,
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


def test_rolling_comparison_holds_recovery_and_switch_policy_constant():
    """A faster mixed-policy result is not a measured rolling-only win."""
    baseline = paid_row(1.0, 45)
    for altered in ("rest_health", "rest_mana", "rest_until",
                    "switch_fraction", "max_live_targets"):
        challenger = rolling_paid_row(elapsed=30)
        policy = challenger["native_world_policy"]
        if altered == "rest_health":
            policy["rest_when_health_below"] = 0.3
        elif altered == "rest_mana":
            policy["rest_when_mana_below"] = 0.3
        elif altered == "rest_until":
            policy["rest_until"] = "other"
        else:
            import copy
            apl = copy.deepcopy(challenger["native_world_apl"])
            if altered == "switch_fraction":
                apl["switch_trigger"]["fraction"] = 0.6
            else:
                apl["max_live_targets"] = 3
            policy["world_apl"] = apl
            challenger["native_world_apl"] = apl
        comparison = measured_world_rolling_head_to_head(
            result_for([baseline, challenger]), level=20)
        assert comparison["status"] == "NATIVE_ROLLING_WORLD_APL_INCOMPLETE"
        assert comparison["winner"] is None


def test_rolling_paid_comparison_reports_real_terminal_recovery_cost():
    comparison = measured_world_rolling_head_to_head(
        result_for([paid_row(1.0, 45), rolling_paid_row(elapsed=38)]),
        level=20,
    )
    assert comparison["status"] == "MEASURED_NATIVE_ROLLING_WORLD_APL_HEAD_TO_HEAD"
    assert comparison["baseline"]["terminal_recovery_seconds"] == 4.0
    assert comparison["rolling"]["terminal_recovery_seconds"] == 4.0
    assert comparison["rolling"]["reused_exact_native_paid_receipt"] is False


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

def test_rolling_paid_overlap_rejects_unjoined_native_and_world_target_ids():
    """A synthetic two-ACK flag is never sufficient to report paid overlap."""
    baseline = paid_row(1.0, 45)
    source = rolling_paid_row()
    overlap = source["native_world_overlap"]
    for invalid in (
        {k: v for k, v in overlap.items()
         if k != "native_target_to_world_id"},
        dict(overlap, native_target_to_world_id={"0": "m1", "1": "m1"}),
        dict(overlap, native_target_to_world_id={"zero": "m1", "1": "m0"}),
        dict(overlap, simultaneously_alive_world_target_ids=["m1", "m1"]),
        dict(overlap, simultaneously_alive_world_target_ids=["m1", "other"]),
    ):
        challenger = rolling_paid_row()
        challenger["native_world_overlap"] = invalid
        comparison = measured_world_rolling_head_to_head(
            result_for([baseline, challenger]), level=20)
        assert comparison["status"] == "NATIVE_ROLLING_WORLD_APL_INCOMPLETE"
        assert comparison["winner"] is None


def test_rolling_paid_cache_rejects_missing_native_world_join():
    """Exact paid cache cannot upgrade a forged/disconnected two-kill receipt."""
    from tools.wf_warlock_native_persistent_optimizer import (
        ROLLING_WORLD_APL_50, _native_rolling_receipt_verified,
    )
    source = rolling_paid_row()
    source["world_kills"] = source["native_world_kills"]
    assert _native_rolling_receipt_verified(source, ROLLING_WORLD_APL_50)
    broken = dict(source)
    broken["native_world_overlap"] = dict(
        source["native_world_overlap"], native_target_to_world_id={
            "0": "m1", "1": "not-killed"})
    assert not _native_rolling_receipt_verified(
        broken, ROLLING_WORLD_APL_50)
    assert not _native_rolling_receipt_verified(
        dict(source, world_kills=[{"target_id": {}, "ack_sha256": "first"},
                                  {"target_id": "m0", "ack_sha256": "second"}]),
        ROLLING_WORLD_APL_50)


def test_rolling_comparison_requires_same_paid_world_scenario_and_distinct_receipts():
    """Same native build with changed mob HP or recycled raw bytes is not a pair."""
    baseline = paid_row(1.0, 45)
    for changed_field, changed_value in (
        ("native_world_target_hp", 150.0),
        ("native_world_target_hp", None),
        ("native_raw_receipt_sha256", "c" * 64),
        ("native_raw_receipt_sha256", "not-a-sha"),
    ):
        challenger = rolling_paid_row(elapsed=12)
        challenger[changed_field] = changed_value
        comparison = measured_world_rolling_head_to_head(
            result_for([baseline, challenger]), level=20)
        assert comparison["status"] == "NATIVE_ROLLING_WORLD_APL_INCOMPLETE"
        assert comparison["winner"] is None
    matched = measured_world_rolling_head_to_head(
        result_for([baseline, rolling_paid_row()]), level=20)
    assert matched["status"] == "MEASURED_NATIVE_ROLLING_WORLD_APL_HEAD_TO_HEAD"
    assert matched["baseline"]["native_world_target_hp"] == 100.0
    assert matched["rolling"]["native_world_target_hp"] == 100.0


def test_serial_paid_cache_rejects_native_applied_rolling_world_apl():
    """Never charge a rolling native result as the untouched serial control."""
    from tools.wf_warlock_native_persistent_optimizer import (
        ROLLING_WORLD_APL_50, _native_rolling_receipt_verified,
    )
    assert _native_rolling_receipt_verified({}, None)
    assert not _native_rolling_receipt_verified(
        {"native_world_apl": ROLLING_WORLD_APL_50}, None)
    assert not _native_rolling_receipt_verified(
        {"native_world_overlap_verified": True}, None)
