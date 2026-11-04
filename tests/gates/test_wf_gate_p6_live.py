"""P6 actual paid replay evidence contract, not a mock P6 acceptance gate."""
from tools import wf_gate_p6_live as p6
from tools.wf_gate import _run_live_gate, ROOT


def test_partial_counts_only_really_killed_mobs():
    assert p6._mob_kills({"status": "COMPLETE", "count": 100}) == 100
    assert p6._mob_kills({"status": "BLOCKED_ACTOR_DIED", "mob_completed": 23}) == 23
    assert p6._mob_kills({"status": "COMPLETE", "count": 99}) == 0
    assert p6._mob_kills({"status": "COMPLETE", "count": True}) == 0
    assert p6._mob_kills({"status": "BLOCKED", "count": 1000}) == 0


def test_constrained_p6_bounded_paid_search_preserves_source_bound_profile(monkeypatch):
    """A named P6 spec must reach the real bounded-search entry with 31 points.

    This mocked routing test is not paid 100-mob or selected native/2D proof.
    """
    from src.game.data.forever import registry, gear
    from src.v2 import source_bounded_joint_frontier as frontier

    ir = object()
    stage = {"source_stage": True}
    calls = []
    monkeypatch.setattr(registry, "build_game_ir_slice", lambda **_: ir)
    monkeypatch.setattr(gear, "available_gear_roles", lambda _: ["druid_balance"])
    monkeypatch.setattr(frontier, "source_cold_start_stage",
                        lambda **_: stage)

    def cold_search(**params):
        calls.append(params)
        return {"screen_complete_candidates": 0}

    monkeypatch.setattr(frontier, "search_bounded_joint_frontier", cold_search)
    report = p6.run_live(ROOT, "druid", 60, spec="balance")
    assert report["status"] == "FAIL"
    assert "P6_SELECTED_NATIVE_2D_BACKEND_NOT_VERIFIED" in report["reasons"]
    assert len(calls) == 2
    assert [c["max_cpu_s"] for c in calls] == [4., 6.]
    assert all(c["spec_tree"] == "balance" and c["min_spec_points"] == 31
               and c["source_ir"] is ir and c["seed_stage"] is stage
               and c["search_only"] is True for c in calls)


def test_p6_unknown_product_profile_fails_closed_before_search(monkeypatch):
    from src.game.data.forever import registry
    def unexpected_ir(**_):
        raise AssertionError("No source search without a pinned profile")
    monkeypatch.setattr(registry, "build_game_ir_slice", unexpected_ir)
    report = p6.run_live(ROOT, "druid", 60, spec="nonexistent")
    assert report == {
        "status": "BLOCKED",
        "reasons": ["P6_SOURCE_SPEC_PRODUCT_PROFILE_NOT_CONFIGURED"],
    }


def test_p6_bounded_replay_rejects_ambiguous_or_invalid_paid_receipts(monkeypatch):
    """The production P6 caller must not silently score a corrupted 100-mob row.

    Contract controls only; this is not a source-hydrated CombatRuntime replay.
    """
    from src.v2 import source_bounded_joint_frontier as frontier

    search = {"validation_shortlist": [{"source_candidate": "one"}],
              "bonus_talent_points": 0, "pack_size": 2}
    valid = {"status": "COMPLETE", "count": 100, "mob_completed": 100,
             "full_s_per_mob": 12.5, "events": 5000}
    examples = [
        ([valid, valid], "AMBIGUOUS_SOURCE_PAID_REPLAY", 0),
        (["malformed"], "AMBIGUOUS_SOURCE_PAID_REPLAY", 0),
        ([{**valid, "full_s_per_mob": float("nan")}],
         "INVALID_COMPLETE_PAID_REPLAY", 0),
        ([{**valid, "full_s_per_mob": float("inf")}],
         "INVALID_COMPLETE_PAID_REPLAY", 0),
        ([{**valid, "full_s_per_mob": 0.0}],
         "INVALID_COMPLETE_PAID_REPLAY", 0),
        ([{**valid, "count": 99}],
         "INVALID_COMPLETE_PAID_REPLAY", 0),
        ([valid], "COMPLETE", 100),
    ]
    for rows, expected_status, expected_kills in examples:
        monkeypatch.setattr(
            frontier, "replay_joint_shortlist_100mob",
            lambda *args, _rows=rows, **kwargs: {"rows": _rows})
        result = p6._replay_first_paid_winner(
            search, source_ir=None, seed_stage=None,
            class_key="druid", level=30)
        assert result["status"] == expected_status
        assert result["mob_completed"] == expected_kills
        if expected_status == "COMPLETE":
            assert result["mean_s_per_mob"] == 12.5
            assert result["events"] == 5000


def test_p6_bounded_ratio_requires_a_finite_paid_100mob_replay():
    valid = {"status": "COMPLETE", "count": 100, "mob_completed": 100,
             "mean_s_per_mob": 12.5}
    assert p6._complete_finite_paid_replay(valid)
    for bad in (float("nan"), float("inf"), 0.0, -1.0, None, True):
        assert not p6._complete_finite_paid_replay(
            {**valid, "mean_s_per_mob": bad})
    for invalid in ({"count": 99}, {"mob_completed": 99},
                    {"status": "BLOCKED_ACTOR_DIED"}, {"count": True}):
        assert not p6._complete_finite_paid_replay({**valid, **invalid})


def test_priest_p6_uses_native_shared_cold_receipt_not_legacy_gameir(
        monkeypatch, tmp_path):
    from tools import wf_gate_p4_p5_partial as native
    import hashlib
    binary = tmp_path / "forever-engine"
    binary.write_bytes(b"selected-executed-native-binary")
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", str(binary))
    monkeypatch.setenv("FOREVER_P4_P5_PRIEST_L20_COLD_SEARCH", "1")
    monkeypatch.setenv("GITHUB_RUN_ID", "987654")
    request = {"encounter": {"targets": [{"level": 20}]},
               "simOptions": {"iterations": 1, "randomSeed": "42"},
               "raid": {"parties": [{"players": [{
                   "class": "ClassPriest", "level": 20, "race": "RaceHuman"}]}]}}
    import json
    digest = hashlib.sha256(json.dumps(
        request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    selection = lambda elapsed: {"source_request_sha256": digest,
                                 "source_build": request,
                                 "paid_completed_elapsed_s": elapsed}
    world = {"native_2d_persistent_actor_verified": True,
             "native_2d_persistent_world_ack_verified": True,
             "native_2d_persistent_paid_recovery": True,
             "native_2d_persistent_world_targets_killed": 100,
             "native_2d_persistent_source_action_events": 100,
             "native_2d_persistent_source_action_counts_by_target":
                 [{"native:585": 1} for _ in range(100)],
             "native_2d_persistent_elapsed_seconds": 4201.0}
    winner = {**selection(5.), "route_s_per_mob": 42.01,
              "real_100mob_receipt": world}
    cold = {"native_cold_300s_reached": True,
            "native_cold_native_paid_after_30": 1,
            "native_cold_paid_world_route_builds": 2,
            "native_cold_30s_paid_selection": selection(5.),
            "native_cold_300s_paid_selection": selection(40.),
            "native_cold_snapshot_30": winner,
            "native_cold_final_300": winner}
    calls = []
    def native_producer(*args, **kwargs):
        calls.append((args, kwargs))
        return cold
    monkeypatch.setattr(native, "_native_cold_options_without_paid_executor",
                        native_producer)
    report = p6.run_live(ROOT, "priest", 20, spec="unrestricted")
    assert report["status"] == "PASS"
    assert report["source_replay_T30_T300"] == 1.0
    assert report["source_replay_300s_nonregression"] is True
    assert report["runtime_proof"]["run_id"] == "987654"
    assert report["runtime_proof"]["engine_revision"].endswith(
        hashlib.sha256(binary.read_bytes()).hexdigest())
    assert len(calls) == 1
    assert calls[0][1]["gate"] == "P4"

    # A native receipt refusal remains a genuine P6 FAIL, not a fake PASS.
    cold["native_cold_final_300"]["route_s_per_mob"] = 39.0
    assert p6.run_live(ROOT, "priest", 20)["status"] == "FAIL"


