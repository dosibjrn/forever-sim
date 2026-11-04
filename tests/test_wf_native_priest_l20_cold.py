"""Forever-owned 30s snapshot, 300s continuation and native receipt wiring."""
import copy
import hashlib
import json

from tools.wf_native_priest_l20_cold import (
    _source_native_builds, run_native_priest_l20_cold,
)


def _source():
    return {
        "raid": {"parties": [{"players": [{
            "class": "ClassPriest", "level": 20, "race": "RaceHuman",
            "equipment": {"items": []}, "talentsString": "0-0-0",
            "rotation": {"priorityList": [
                {"action": {"castSpell": {"spellId": {"spellId": 585}}}},
            ]},
        }]}]},
        "encounter": {"duration": 30, "targets": [{"level": 20}]},
        "simOptions": {"iterations": 1, "randomSeed": "42"},
    }


def _options():
    return [{"item_id": i, "slot": s} for i, s in (
        (11, "head"), (12, "head"), (21, "chest"), (22, "chest"))]


def _runner(tmp_path, *, budget=40.0, snapshot=10.0, max_attempts=100,
            paid_recovery=True, native_identity=True,
            first_world_native_failure=False, cast_receipts=1,
            options=None, refuse_dense_at=None):
    source_path = tmp_path / "source.json"
    source_path.write_text(json.dumps(_source()))
    now = [0.0]
    paid_builds = []
    world_builds = []

    def clock():
        return now[0]

    def paid(_binary, source, **kwargs):
        now[0] += 3.0
        paid_builds.append(copy.deepcopy(source))
        if refuse_dense_at is not None and len(
                source["raid"]["parties"][0]["players"][0]["equipment"]["items"]
        ) >= refuse_dense_at:
            raise RuntimeError("MythicSim UNSUPPORTED: level-20 rating conversion source")
        digest = hashlib.sha256(json.dumps(
            source, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        return ({
            "effective_request_sha256": digest if native_identity else "wrong",
            "score": 10.0, "rng_mode": "balanced",
            "native_action_cast_receipts": [
                {"id": {"spellId": 585}, "casts": cast_receipts}],
        }, {})

    def world(_binary, request, *, target_count):
        assert target_count == 100
        build = json.loads(request.read_text())
        # The real 30/300s search validates its frozen source-paid 30s
        # candidate after discovery; short regression runs still validate
        # each current paid proposal immediately.
        assert build in paid_builds
        if budget != 300.0:
            assert build == paid_builds[-1]
        world_builds.append(build)
        now[0] += 5.0
        if first_world_native_failure and len(world_builds) == 1:
            raise AssertionError(("RUST_TWO_WORLD_NATIVE_FAILED", 1,
                "prepared input rejected: RUST_MULTI_WORLD_TARGET_NOT_NATIVE_LETHAL",
                1, 56))
        # Real world elapsed time is a measured return value, never inferred
        # from native DPS. Verify the exact field propagation, not mechanics.
        return {
            "native_2d_persistent_actor_verified": True,
            "native_2d_persistent_world_ack_verified": True,
            "native_2d_persistent_paid_recovery": paid_recovery,
            "native_2d_persistent_world_targets_killed": 100,
            "native_2d_persistent_source_action_events": 100,
            "native_2d_persistent_source_action_counts_by_target":
                [{"spell:585": 1} for _ in range(100)],
            "native_2d_persistent_elapsed_seconds":
                1100.0 - len(world_builds) * 100.0,
        }

    receipt = run_native_priest_l20_cold(
        "/native", source_path, _options() if options is None else options,
        score_request=paid, world_screen=world, clock=clock, budget_s=budget,
        snapshot_s=snapshot, max_attempts=max_attempts)
    return receipt, paid_builds, world_builds


def test_one_cold_native_100mob_search_freezes_real_30s_winner(tmp_path):
    receipt, paid, world = _runner(tmp_path)
    assert len(paid) == len(world) == 5
    assert receipt["native_cold_300s_reached"] is True
    assert receipt["native_cold_300s_overrun"] is False
    assert receipt["native_cold_native_paid_before_30"] == 1
    assert receipt["native_cold_native_paid_after_30"] == 4
    assert receipt["native_cold_snapshot_30"]["route_s_per_mob"] == 10.0
    assert receipt["native_cold_final_300"]["route_s_per_mob"] == 6.0
    assert receipt["native_cold_snapshot_30"]["source_build"]["raid"] != (
        receipt["native_cold_final_300"]["source_build"]["raid"])
    assert receipt["native_cold_gate_accepted"] is False
    receipt["native_cold_final_300"]["real_100mob_receipt"][
        "native_2d_persistent_source_action_counts_by_target"][0]["spell:585"] = 0
    assert receipt["native_cold_snapshot_30"]["real_100mob_receipt"][
        "native_2d_persistent_source_action_counts_by_target"][0]["spell:585"] == 1


def test_exhausted_or_short_cold_search_cannot_claim_300s(tmp_path):
    receipt, paid, world = _runner(tmp_path, max_attempts=1)
    assert len(paid) == len(world) == 1
    assert receipt["native_cold_300s_reached"] is False
    assert receipt["native_cold_snapshot_30"] is None
    assert receipt["native_cold_final_300"] is not None
    assert receipt["native_cold_gate_accepted"] is False


def test_native_100mob_lethal_failure_is_isolated_and_next_build_is_paid(tmp_path):
    receipt, paid, world = _runner(
        tmp_path, first_world_native_failure=True)
    assert len(paid) == len(world) == 5
    assert receipt["native_cold_rows"][0]["status"] == "NATIVE_PAID"
    assert receipt["native_cold_rows"][0][
        "native_2d_persistent_observed_kills"] == 1
    assert "RUST_TWO_WORLD_NATIVE_FAILED:exit=1:completed=1:native_damage_events=56" in (
        receipt["native_cold_rows"][0]["reason"])
    assert receipt["native_cold_snapshot_30"] is None
    assert receipt["native_cold_final_300"]["route_s_per_mob"] == 6.0
    assert receipt["native_cold_completed_routes_after_30"] == 4
    assert receipt["native_cold_gate_accepted"] is False


def test_native_request_mismatch_never_reaches_world(tmp_path):
    receipt, paid, world = _runner(
        tmp_path, max_attempts=2, native_identity=False)
    assert len(paid) == 2
    assert world == []
    assert receipt["native_cold_final_300"] is None
    assert all("IDENTITY_MISMATCH" in row["reason"]
               for row in receipt["native_cold_rows"])


def test_native_world_without_paid_recovery_cannot_win(tmp_path):
    receipt, paid, world = _runner(tmp_path, paid_recovery=False)
    assert len(world) == 5
    assert receipt["native_cold_snapshot_30"] is None
    assert receipt["native_cold_final_300"] is None
    assert receipt["native_cold_completed_routes_before_30"] == 0
    assert receipt["native_cold_gate_accepted"] is False


def test_cold_opt_in_uses_one_real_producer_and_does_not_grant_gate_pass(
        tmp_path, monkeypatch):
    from tools import wf_gate_p4_p5_partial as gate
    from tools import wf_native_priest_l20_cold as cold
    from src.game import native_p3_item_options as items

    request = tmp_path / "source.json"
    request.write_text(json.dumps(_source()))
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "/native")
    monkeypatch.setenv("FOREVER_P4_P5_PRIEST_L20_SOURCE_REQUEST", str(request))
    monkeypatch.setenv("FOREVER_P4_P5_PRIEST_L20_LIVE_WORLD", "1")
    monkeypatch.setenv("FOREVER_P4_P5_PRIEST_L20_PERSISTENT_TARGETS", "100")
    monkeypatch.setenv("FOREVER_P4_P5_PRIEST_L20_COLD_SEARCH", "1")
    monkeypatch.setattr(items, "query_native_p3_item_options",
                        lambda *a, **k: {
                            "items": _options(), "status": "ok",
                            "unverified_candidate_count": 0,
                        })
    calls = []
    def fake_cold(*args):
        calls.append(args)
        return {
            "native_cold_300s_reached": True,
            "native_cold_300s_overrun": True,
            "native_cold_snapshot_30": {"route_s_per_mob": 10.0},
            "native_cold_final_300": {"route_s_per_mob": 9.5},
            "native_cold_native_paid_before_30": 2,
            "native_cold_native_paid_after_30": 2,
            "native_cold_completed_routes_before_30": 1,
            "native_cold_completed_routes_after_30": 2,
        }
    monkeypatch.setattr(cold, "run_native_priest_l20_cold", fake_cold)
    result = gate._native_cold_options_without_paid_executor(
        "priest", 20, "unrestricted")
    assert len(calls) == 1
    assert result["status"] == "FAIL"
    assert result["paid_candidates"] == 4
    assert result["screen_complete_candidates"] == 3
    assert result["reasons"] == [
        "P4_P5_NATIVE_COLD_PRODUCER_EXECUTED_GATE_NOT_ACCEPTED"]


def test_native_equipped_builds_precede_naked_baseline():
    builds = list(_source_native_builds(_source(), _options()))
    equipped = [b["raid"]["parties"][0]["players"][0]["equipment"]["items"]
                for b in builds]
    assert equipped[0] == [{"id": 11}, {"id": 21}]
    assert equipped[-1] == []
    assert len(equipped) == len({json.dumps(x, sort_keys=True) for x in equipped})


def test_late_100mob_completion_cannot_displace_in_budget_native_winner(tmp_path):
    # Five paid + 100-mob source/world calls finish at 8,16,24,32,40s.
    # The final native world session began before 36s, ended after cutoff.
    receipt, paid, world = _runner(tmp_path, budget=36.0, snapshot=10.0)
    assert len(paid) == len(world) == 5
    assert receipt["native_cold_300s_reached"] is True
    assert receipt["native_cold_300s_overrun"] is True
    assert receipt["native_cold_native_paid_before_30"] == 1
    assert receipt["native_cold_native_paid_after_30"] == 3
    assert receipt["native_cold_completed_routes_before_30"] == 1
    assert receipt["native_cold_completed_routes_after_30"] == 3
    assert receipt["native_cold_snapshot_30"]["route_s_per_mob"] == 10.0
    assert receipt["native_cold_final_300"]["route_s_per_mob"] == 7.0
    assert receipt["native_cold_final_300"]["paid_completed_elapsed_s"] == 32.0
    assert receipt["native_cold_rows"][-1]["paid_completed_elapsed_s"] == 40.0
    assert receipt["native_cold_gate_accepted"] is False


def test_paid_native_no_source_cast_cannot_count_as_cold_paid_build(tmp_path):
    receipt, paid, world = _runner(tmp_path, cast_receipts=0)
    assert len(paid) == 5
    assert world == []
    assert receipt["native_cold_native_paid_before_30"] == 0
    assert receipt["native_cold_native_paid_after_30"] == 0
    assert receipt["native_cold_final_300"] is None
    assert all(row["status"] == "NATIVE_NO_SOURCE_CAST"
               for row in receipt["native_cold_rows"])


def test_real_native_rating_refusals_do_not_starve_sparse_paid_proposals(tmp_path):
    # Real cold run #41893190218 refused 4095 full-build combinations
    # with the same native UNSUPPORTED L20 rating-conversion reason. Exercise
    # Forever's response handling only; the fixture does not assert Warcraft
    # item legality or supply a Python rating/stat catalogue.
    options = [
        {"item_id": 11, "slot": "head"},
        {"item_id": 21, "slot": "chest"},
        {"item_id": 31, "slot": "legs"},
    ]
    receipt, paid, world = _runner(
        tmp_path, options=options, refuse_dense_at=2,
        max_attempts=7, budget=40.0, snapshot=10.0)
    sizes = [
        len(build["raid"]["parties"][0]["players"][0]["equipment"]["items"])
        for build in paid
    ]
    assert sizes == [3, 2, 2, 2, 1, 1, 0]
    assert len(world) == 3  # Only native-accepted candidates reach 2D.
    assert all(row["status"] == "NATIVE_REFUSED"
               and "UNSUPPORTED" in row["reason"]
               for row in receipt["native_cold_rows"][:4])
    assert all(row["status"] == "COMPLETE"
               for row in receipt["native_cold_rows"][4:])
    assert receipt["native_cold_completed_routes_after_30"] == 3
    assert receipt["native_cold_snapshot_30"] is None
    assert receipt["native_cold_final_300"]["route_s_per_mob"] == 8.0
    assert receipt["native_cold_gate_accepted"] is False


def test_300s_source_paid_snapshot_survives_deferred_100mob_validation(tmp_path):
    # The production 30/300 clock must not spend the first window executing
    # a possibly >30s route before any genuinely paid candidate is frozen.
    receipt, paid, world = _runner(
        tmp_path, budget=300.0, snapshot=30.0)
    assert len(paid) == 5
    assert len(world) == 1  # Only the *selected* 30s candidate replayed.
    assert world[0] in paid
    assert receipt["native_cold_search_wall_s"] == 15.0
    assert receipt["native_cold_native_paid_before_30"] == 5
    assert receipt["native_cold_native_paid_after_30"] == 0
    assert receipt["native_cold_30s_paid_selection"]["paid_completed_elapsed_s"] == 3.0
    assert receipt["native_cold_30s_post_search_route"]["status"] == "COMPLETE"
    assert receipt["native_cold_snapshot_30"]["route_s_per_mob"] == 10.0
    assert receipt["native_cold_snapshot_30"]["real_100mob_receipt"][
        "native_2d_persistent_world_targets_killed"] == 100
    assert receipt["native_cold_300s_reached"] is False  # Exhausted, not a 300s pass.
    assert receipt["native_cold_gate_accepted"] is False


def test_deferred_30s_candidate_refusal_never_invents_world_winner(tmp_path):
    receipt, paid, world = _runner(
        tmp_path, budget=300.0, snapshot=30.0,
        first_world_native_failure=True)
    assert len(paid) == 5
    assert len(world) == 1
    assert receipt["native_cold_30s_paid_selection"] is not None
    assert receipt["native_cold_snapshot_30"] is None
    assert receipt["native_cold_30s_post_search_route"]["status"] == "WORLD_INCOMPLETE"
    assert receipt["native_cold_30s_post_search_route"][
        "native_2d_persistent_observed_kills"] == 1
    assert "RUST_MULTI_WORLD_TARGET_NOT_NATIVE_LETHAL" in (
        receipt["native_cold_30s_post_search_route"]["reason"])
    assert receipt["native_cold_gate_accepted"] is False


def test_deferred_native_sparse_refusals_still_freeze_paid_30s_build(tmp_path):
    # Native rating UNSUPPORTED decisions are not second-guessed by Python.
    # A viable sparse proposal can still be selected and authentically
    # 100-mob-qualified after the immutable 30s discovery window.
    options = [
        {"item_id": 11, "slot": "head"},
        {"item_id": 21, "slot": "chest"},
        {"item_id": 31, "slot": "legs"},
    ]
    receipt, paid, world = _runner(
        tmp_path, budget=300.0, snapshot=30.0, options=options,
        refuse_dense_at=2, max_attempts=7)
    assert len(paid) == 7
    assert len(world) == 1
    assert receipt["native_cold_native_paid_before_30"] == 3
    assert receipt["native_cold_30s_post_search_route"]["status"] == "COMPLETE"
    assert receipt["native_cold_snapshot_30"]["source_build"] in paid
    assert receipt["native_cold_gate_accepted"] is False
