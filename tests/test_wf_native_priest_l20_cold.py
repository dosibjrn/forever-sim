"""Forever-owned 30s snapshot, 300s continuation and native receipt wiring."""
import copy
import hashlib
import json

from tools.wf_native_priest_l20_cold import run_native_priest_l20_cold


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
            paid_recovery=True, native_identity=True):
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
        digest = hashlib.sha256(json.dumps(
            source, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        return ({
            "effective_request_sha256": digest if native_identity else "wrong",
            "score": 10.0, "rng_mode": "balanced",
            "native_action_cast_receipts": [
                {"id": {"spellId": 585}, "casts": 1}],
        }, {})

    def world(_binary, request, *, target_count):
        assert target_count == 100
        build = json.loads(request.read_text())
        assert build == paid_builds[-1]
        world_builds.append(build)
        now[0] += 5.0
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
        "/native", source_path, _options(), score_request=paid,
        world_screen=world, clock=clock, budget_s=budget,
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
            "native_cold_300s_overrun": False,
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
