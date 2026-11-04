"""Forever-owned 30s snapshot, 300s continuation and native receipt wiring."""
import copy
import hashlib
import json

import pytest

from tools.wf_native_priest_l20_cold import (
    _source_native_builds, native_cold_gate_verdicts, run_native_priest_l20_cold,
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
            options=None, refuse_dense_at=None, full_route_delay=5.0,
            source_request=None):
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
                {"id": action["action"]["castSpell"]["spellId"],
                 "casts": cast_receipts}
                for action in source["raid"]["parties"][0]["players"][0][
                    "rotation"]["priorityList"]],
        }, {})

    def world(_binary, request, *, target_count):
        assert target_count in (2, 100)
        build = json.loads(request.read_text())
        # Two-target paid native/world routes rank the actual 30/300s
        # search; only its frozen finalists run 100-mob routes afterward.
        assert build in paid_builds
        if budget != 300.0:
            assert build == paid_builds[-1]
        if target_count == 100:
            world_builds.append(build)
        now[0] += full_route_delay if target_count == 100 else 5.0
        if first_world_native_failure and target_count == 100 and len(world_builds) == 1:
            raise AssertionError(("RUST_TWO_WORLD_NATIVE_FAILED", 1,
                "prepared input rejected: RUST_MULTI_WORLD_TARGET_NOT_NATIVE_LETHAL",
                1, 56))
        # Real world elapsed time is a measured return value, never inferred
        # from native DPS. Verify the exact field propagation, not mechanics.
        return {
            "native_2d_persistent_actor_verified": True,
            "native_2d_persistent_world_ack_verified": True,
            "native_2d_persistent_paid_recovery": paid_recovery,
            "native_2d_persistent_world_targets_killed": target_count,
            "native_2d_persistent_source_action_events": target_count,
            "native_2d_persistent_source_action_counts_by_target":
                [{"spell:585": 1} for _ in range(target_count)],
            "native_2d_persistent_elapsed_seconds": (
                1100.0 - (paid_builds.index(build) + 1) * 100.0
                if target_count == 100 else
                60.0 - (paid_builds.index(build) + 1) * 2.0),
        }

    receipt = run_native_priest_l20_cold(
        "/native", source_request if source_request is not None else source_path,
        _options() if options is None else options,
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
    assert "P4_P5_SOURCE_TALENT_ACTION_NOT_NATIVE_COMPARED" in result["reasons"]
    assert "P4_FROZEN_WINNER_REAL_100MOB_RECEIPT_INCOMPLETE" in result["reasons"]


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
    assert receipt["native_cold_final_300"]["route_s_per_mob"] == 4.0
    assert receipt["native_cold_gate_accepted"] is False


def test_300s_paid_world_snapshot_survives_deferred_100mob_validation(tmp_path):
    # Five distinct native-paid two-mob routes finish at 8,16,24,32,40s.
    # Full 100-mob source/world evaluation is after search and never
    # retroactively selects a 30s winner.
    receipt, paid, world = _runner(
        tmp_path, budget=300.0, snapshot=30.0)
    assert len(paid) == 5
    assert len(world) == 2  # Only distinct 30s/300s finalists.
    assert all(b in paid for b in world)
    assert receipt["native_cold_search_wall_s"] == 40.0
    assert receipt["native_cold_native_paid_before_30"] == 3
    assert receipt["native_cold_native_paid_after_30"] == 2
    assert receipt["native_cold_30s_paid_selection"]["paid_completed_elapsed_s"] == 24.0
    assert receipt["native_cold_30s_paid_selection"]["route_probe_target_count"] == 2
    assert receipt["native_cold_30s_paid_selection"]["route_probe_s_per_mob"] == 27.0
    assert receipt["native_cold_snapshot_30"]["route_s_per_mob"] == 8.0
    assert receipt["native_cold_final_300"]["route_s_per_mob"] == 6.0
    assert receipt["native_cold_snapshot_30"]["source_build"] == paid[2]
    assert receipt["native_cold_final_300"]["source_build"] == paid[4]
    assert receipt["native_cold_snapshot_30"]["real_100mob_receipt"][
        "native_2d_persistent_world_targets_killed"] == 100
    assert receipt["native_cold_300s_paid_selection"][
        "snapshot_selection_objective"] == "NATIVE_2MOB_PAID_WORLD_SECONDS_PER_MOB"
    assert receipt["native_cold_completed_100mob_finalists"] == 2
    assert receipt["native_cold_300s_reached"] is False
    assert receipt["native_cold_gate_accepted"] is False


def test_slow_100mob_finalist_does_not_retime_paid_30s_route(tmp_path):
    receipt, paid, world = _runner(
        tmp_path, budget=300.0, snapshot=30.0, full_route_delay=170.0)
    # Each 100-mob finalist lasts 170s in fake wall time: the first
    # crosses the true 300s deadline after search. Neither late validation
    # rewrites the 30/300s candidate-selection clock nor creates a winner.
    assert receipt["native_cold_search_wall_s"] == 40.0
    assert receipt["native_cold_30s_paid_selection"][
        "paid_completed_elapsed_s"] == 24.0
    assert receipt["native_cold_snapshot_30"]["source_build"] == paid[2]
    assert receipt["native_cold_final_300"]["source_build"] == paid[4]
    assert len(world) == 2
    assert receipt["native_cold_native_paid_after_30"] == 2



def test_deferred_30s_candidate_refusal_never_invents_world_winner(tmp_path):
    receipt, paid, world = _runner(
        tmp_path, budget=300.0, snapshot=30.0,
        first_world_native_failure=True)
    assert len(paid) == 5
    assert len(world) == 2
    assert receipt["native_cold_30s_paid_selection"] is not None
    assert receipt["native_cold_snapshot_30"] is None
    assert receipt["native_cold_final_300"] is not None
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
    assert len(world) == 2
    assert receipt["native_cold_native_paid_before_30"] == 2
    assert receipt["native_cold_30s_post_search_route"]["status"] == "COMPLETE"
    assert receipt["native_cold_snapshot_30"]["source_build"] in paid
    assert receipt["native_cold_gate_accepted"] is False


def test_cold_source_directory_pays_distinct_source_talent_apl_candidates(tmp_path):
    # This is source request transport, not a Python Warcraft talent audit:
    # MythicSim alone decides whether either proposed whole build is legal.
    folder = tmp_path / "source-native-candidates"
    folder.mkdir()
    first = _source()
    second = _source()
    second_actor = second["raid"]["parties"][0]["players"][0]
    second_actor["talentsString"] = "1-0-0"
    second_actor["rotation"]["priorityList"].append(
        copy.deepcopy(second_actor["rotation"]["priorityList"][0]))
    (folder / "01.json").write_text(json.dumps(first))
    (folder / "02.json").write_text(json.dumps(second))

    receipt, paid, world = _runner(
        tmp_path, budget=300.0, snapshot=30.0, options=_options(),
        max_attempts=2, source_request=folder)
    # A shallow cold budget must pay both distinct source requests BEFORE
    # exploring the deep gear cartesian tail of the first request.
    assert len(paid) == 2  # Both full source requests were actually scored.
    assert paid[0]["raid"] != paid[1]["raid"]
    assert paid[1]["raid"]["parties"][0]["players"][0]["talentsString"] == "1-0-0"
    # The world objective, not the identical native DPS, selects the latter.
    assert receipt["native_cold_30s_paid_selection"]["source_build"] == paid[1]
    assert receipt["native_cold_300s_paid_selection"]["source_build"] == paid[1]
    assert len(world) == 1  # Exactly one identical 100-mob finalist replay.
    assert receipt["native_cold_snapshot_30"]["source_build"] == paid[1]
    assert receipt["native_cold_completed_100mob_finalists"] == 1
    assert receipt["native_cold_gate_accepted"] is False


def test_cold_source_directory_rejects_incomparable_worlds(tmp_path):
    folder = tmp_path / "mismatched-source-worlds"
    folder.mkdir()
    first = _source()
    changed = _source()
    changed["encounter"]["targets"][0]["level"] = 21
    (folder / "01.json").write_text(json.dumps(first))
    (folder / "02.json").write_text(json.dumps(changed))
    with pytest.raises(
            ValueError, match="PRIEST_L20_COLD_COMPARABLE_ENCOUNTER_MISMATCH"):
        _runner(tmp_path, options=[], source_request=folder)


def test_gate_cold_source_directory_forwards_real_source_requests(
        tmp_path, monkeypatch):
    from tools import wf_gate_p4_p5_partial as gate
    from tools import wf_native_priest_l20_cold as cold
    from src.game import native_p3_item_options as items

    source_folder = tmp_path / "source-variants"
    source_folder.mkdir()
    (source_folder / "one.json").write_text(json.dumps(_source()))
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "/native")
    monkeypatch.delenv("FOREVER_P4_P5_PRIEST_L20_SOURCE_REQUEST", raising=False)
    monkeypatch.setenv("FOREVER_P4_P5_PRIEST_L20_SOURCE_REQUEST_DIR",
                       str(source_folder))
    monkeypatch.setenv("FOREVER_P4_P5_PRIEST_L20_LIVE_WORLD", "1")
    monkeypatch.setenv("FOREVER_P4_P5_PRIEST_L20_PERSISTENT_TARGETS", "100")
    monkeypatch.setenv("FOREVER_P4_P5_PRIEST_L20_COLD_SEARCH", "1")
    monkeypatch.setattr(items, "query_native_p3_item_options",
                        lambda *args, **kwargs: {
                            "items": _options(), "status": "ok",
                            "unverified_candidate_count": 0,
                        })
    forwarded = []
    def fake_cold(binary, request, options):
        forwarded.append((binary, request, options))
        return {
            "native_cold_300s_reached": False,
            "native_cold_snapshot_30": None,
            "native_cold_final_300": None,
            "native_cold_native_paid_before_30": 0,
            "native_cold_native_paid_after_30": 0,
            "native_cold_completed_routes_before_30": 0,
            "native_cold_completed_routes_after_30": 0,
            "native_cold_completed_100mob_finalists": 0,
        }
    monkeypatch.setattr(cold, "run_native_priest_l20_cold", fake_cold)
    report = gate._native_cold_options_without_paid_executor(
        "priest", 20, "unrestricted")
    assert forwarded == [("/native", str(source_folder), _options())]
    assert report["status"] == "FAIL"
    assert "P4_P5_NATIVE_COLD_300S_SEARCH_NOT_COMPLETED" in report["reasons"]



def test_cold_normalizes_source_seed_before_deduplicating_paid_builds(tmp_path):
    # Two authored requests with only run-control differences become the
    # same native paid request; do not spend the early cold budget twice.
    folder = tmp_path / "source-policy-seeds"
    folder.mkdir()
    first = _source()
    second = copy.deepcopy(first)
    second["simOptions"]["iterations"] = 47
    second["simOptions"]["randomSeed"] = "999"
    (folder / "a.json").write_text(json.dumps(first))
    (folder / "b.json").write_text(json.dumps(second))
    receipt, paid, world = _runner(
        tmp_path, budget=300.0, snapshot=30.0,
        options=[], max_attempts=2, source_request=folder)
    assert len(paid) == 1
    assert len(world) == 1
    assert len(receipt["native_cold_rows"]) == 1
    assert paid[0]["simOptions"]["iterations"] == 1
    assert paid[0]["simOptions"]["randomSeed"] == "42"
    assert receipt["native_cold_completed_100mob_finalists"] == 1


def test_cold_preserves_distinct_actual_native_apl_cast_identities(tmp_path):
    # A source policy may propose a new action; only native receipts can
    # establish whether it was actually cast. The mocked scorer here tests
    # transport and provenance, not spell availability or legality.
    folder = tmp_path / "source-policy-casts"
    folder.mkdir()
    first = _source()
    second = copy.deepcopy(first)
    second["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"].insert(
        0, {"action": {"castSpell": {"spellId": {"spellId": 970}}}})
    (folder / "a.json").write_text(json.dumps(first))
    (folder / "b.json").write_text(json.dumps(second))
    receipt, paid, world = _runner(
        tmp_path, budget=300.0, snapshot=30.0,
        options=[], max_attempts=2, source_request=folder)
    assert len(paid) == 2
    assert len(receipt["native_cold_rows"]) == 2
    assert receipt["native_cold_rows"][0]["native_source_action_cast_counts"] == {
        '{"spellId":585}': 1}
    assert receipt["native_cold_rows"][1]["native_source_action_cast_counts"] == {
        '{"spellId":585}': 1, '{"spellId":970}': 1}
    assert receipt["native_cold_rows"][1]["native_source_action_ids_cast"] == 2
    assert receipt["native_cold_30s_paid_selection"]["source_build"] == paid[1]
    assert len(world) == 1
    assert receipt["native_cold_gate_accepted"] is False


def test_native_cold_accepts_genuine_window_receipts_not_hardcoded_fail():
    # Test only Forever's receipt classification, never Rust spell mechanics.
    build = _source()
    digest = hashlib.sha256(json.dumps(
        build, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    world = {
        "native_2d_persistent_actor_verified": True,
        "native_2d_persistent_world_ack_verified": True,
        "native_2d_persistent_paid_recovery": True,
        "native_2d_persistent_world_targets_killed": 100,
        "native_2d_persistent_source_action_events": 100,
        "native_2d_persistent_source_action_counts_by_target":
            [{"native:585": 1} for _ in range(100)],
        "native_2d_persistent_elapsed_seconds": 4000.0,
    }
    def selected(elapsed):
        return {"source_request_sha256": digest, "source_build": build,
                "paid_completed_elapsed_s": elapsed}
    def winner():
        return {**selected(4.0), "route_s_per_mob": 40.0,
                "real_100mob_receipt": copy.deepcopy(world)}
    cold = {
        "native_cold_300s_reached": True,
        "native_cold_30s_paid_selection": selected(4.0),
        "native_cold_300s_paid_selection": selected(32.0),
        "native_cold_snapshot_30": winner(),
        "native_cold_final_300": winner(),
        "native_cold_native_paid_after_30": 2,
        "native_cold_paid_world_route_builds": 3,
        # Proven by a source-authored changed talent/APL request with
        # positive actual native ActionID casts, not a guessed rule.
        "native_cold_talent_action_witnesses": [{
            "source_request_sha256": "other-real-paid-candidate",
            "source_talents_changed": True,
            "native_action_id": '{"spellId":15407}',
            "native_casts": 8,
        }],
    }
    verdicts = native_cold_gate_verdicts(cold)
    assert verdicts["P4"] == {"status": "PASS", "reasons": []}
    assert verdicts["P5"] == {"status": "PASS", "reasons": []}
    # P4 cannot borrow the later winner's 100-mob receipt.
    changed = copy.deepcopy(cold)
    changed["native_cold_snapshot_30"]["real_100mob_receipt"][
        "native_2d_persistent_world_targets_killed"] = 99
    assert native_cold_gate_verdicts(changed)["P4"]["status"] == "FAIL"
    assert native_cold_gate_verdicts(changed)["P5"]["status"] == "PASS"
    # A proposed, never-executed unlock has no gate credit.
    changed = copy.deepcopy(cold)
    changed["native_cold_talent_action_witnesses"][0]["native_casts"] = 0
    assert all(v["status"] == "FAIL"
               for v in native_cold_gate_verdicts(changed).values())
    # Post-30 continuation and distinct real paid world routes matter for P5.
    changed = copy.deepcopy(cold)
    changed["native_cold_native_paid_after_30"] = 0
    changed["native_cold_paid_world_route_builds"] = 1
    assert native_cold_gate_verdicts(changed)["P4"]["status"] == "PASS"
    assert native_cold_gate_verdicts(changed)["P5"]["status"] == "FAIL"
    changed = copy.deepcopy(cold)
    changed["native_cold_300s_reached"] = False
    assert all(v["status"] == "FAIL"
               for v in native_cold_gate_verdicts(changed).values())


def test_native_cold_records_only_executed_changed_talent_apl_witness(tmp_path):
    folder = tmp_path / "talent-policy-variants"
    folder.mkdir()
    baseline = _source()
    changed = copy.deepcopy(baseline)
    actor = changed["raid"]["parties"][0]["players"][0]
    actor["talentsString"] = "changed-native-judged-talents"
    actor["rotation"]["priorityList"].insert(
        0, {"action": {"castSpell": {"spellId": {"spellId": 15407}}}})
    (folder / "01-baseline.json").write_text(json.dumps(baseline))
    (folder / "02-talent.json").write_text(json.dumps(changed))
    receipt, paid, _ = _runner(
        tmp_path, budget=300.0, snapshot=30.0, max_attempts=2,
        options=[], source_request=folder)
    assert len(paid) == 2
    witnesses = receipt["native_cold_talent_action_witnesses"]
    assert len(witnesses) == 1
    assert witnesses[0]["native_action_id"] == '{"spellId":15407}'
    assert witnesses[0]["native_casts"] == 1
    assert witnesses[0]["source_talents_changed"] is True
