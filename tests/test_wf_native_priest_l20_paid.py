"""Transport-only regressions for the active Priest L20 native P4/P5 path."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tools.wf_native_priest_l20_paid import score_source_priest_l20


def _request():
    return {
        "raid": {"parties": [{"players": [{
            "class": "ClassPriest", "level": 20, "race": "RaceHuman",
            "talentsString": "0-0-0", "equipment": {"items": []},
            "rotation": {"type": "TypeAPL", "priorityList": [
                {"action": {"castSpell": {"spellId": {"spellId": 585}}}},
            ]},
        }]}]},
        "encounter": {"duration": 30, "targets": [{"level": 20}]},
        "simOptions": {"iterations": 1, "randomSeed": "42"},
    }


def test_paid_native_source_request_transport_and_exact_cast_identity(tmp_path):
    request = _request()
    path = tmp_path / "source-priest-l20.json"
    path.write_text(json.dumps(request))
    calls = []

    def scorer(binary, candidate, **kwargs):
        calls.append((binary, copy.deepcopy(candidate), kwargs))
        return {
            "effective_request_sha256": "exact-native-paid-request",
            "score": 26.5, "rng_mode": "balanced",
            "native_action_cast_receipts": [
                {"id": {"spellId": 585}, "casts": 3},
                {"id": {"spellId": 585, "tag": 1}, "casts": 9},
                {"id": {"spellId": 2050}, "casts": 5},
                {"id": {"spellId": 585}, "casts": True},
            ],
        }, {"result": "native output preserved by scorer"}

    result = score_source_priest_l20(
        "/selected/native", path, score_request=scorer)
    assert len(calls) == 1
    binary, passed, kwargs = calls[0]
    assert str(binary) == "/selected/native"
    assert passed == request
    assert kwargs["rng_mode"] == "balanced"
    assert kwargs["iterations"] == 1
    assert kwargs["seed"] == 42
    assert kwargs["objective"] == "DPS"
    assert result["native_paid_whole_builds"] == 1
    assert result["native_source_action_casts"] == 3
    assert result["native_source_action_ids_cast"] == 1
    assert result["native_request_sha256"] == "exact-native-paid-request"
    assert result["native_actor_requested_level"] == 20
    assert result["native_2d_screen_complete"] is False
    assert json.loads(path.read_text()) == request


@pytest.mark.parametrize("change,code", [
    (lambda r: r["raid"]["parties"][0]["players"][0].update(level=60),
     "P4_P5_NATIVE_PRIEST_L20_SOURCE_REQUEST_REQUIRED"),
    (lambda r: r["raid"]["parties"][0]["players"][0].update(level=True),
     "P4_P5_NATIVE_PRIEST_L20_SOURCE_REQUEST_REQUIRED"),
    (lambda r: r["raid"]["parties"][0]["players"][0].update(**{"class": "ClassMage"}),
     "P4_P5_NATIVE_PRIEST_L20_SOURCE_REQUEST_REQUIRED"),
    (lambda r: r["raid"]["parties"][0]["players"][0]["rotation"].update(priorityList=[]),
     "P4_P5_NATIVE_SOURCE_APL_CAST_REQUIRED"),
])
def test_native_source_guard_refuses_unproven_actor_or_no_cast(tmp_path, change, code):
    request = _request()
    change(request)
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(request))
    with pytest.raises(ValueError, match=code):
        score_source_priest_l20("/selected/native", path,
            score_request=lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("must not invoke native on invalid request")))


def test_p4_p5_paid_native_receipt_does_not_claim_2d_completion(tmp_path, monkeypatch):
    from tools import wf_gate_p4_p5_partial as gate
    from src.game.native_p3_item_options import query_native_p3_item_options
    from src.game import native_p3_item_options
    from tools import wf_native_priest_l20_paid

    source = tmp_path / "source.json"
    source.write_text(json.dumps(_request()))
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "/selected/native")
    monkeypatch.setenv("FOREVER_P4_P5_PRIEST_L20_SOURCE_REQUEST", str(source))
    monkeypatch.setattr(native_p3_item_options, "query_native_p3_item_options",
                        lambda *a, **k: {
                            "status": "ok", "items": [{"item_id": 25, "slot": "chest"}],
                            "unverified_candidate_count": 0,
                        })
    monkeypatch.setattr(wf_native_priest_l20_paid, "score_native_priest_l20_item_candidates",
                        lambda *a, **k: {
                            "native_paid_whole_builds": 1,
                            "native_source_action_casts": 2,
                            "native_2d_screen_complete": False,
                            "native_request_sha256": "native-sha",
                        })
    report = gate._native_cold_options_without_paid_executor(
        "priest", 20, "unrestricted")
    assert report["status"] == "BLOCKED"
    assert report["paid_candidates"] == 1
    assert report["screen_complete_candidates"] == 0
    assert report["coverage_scope_complete"] is False
    assert report["reasons"] == ["P4_P5_NATIVE_2D_100MOB_SCREEN_NOT_CONNECTED"]
    assert "pass_count" not in report
    assert report["native_source_action_casts"] == 2


def test_bounded_source_candidate_frontier_scores_distinct_native_builds(tmp_path):
    from tools.wf_native_priest_l20_paid import score_source_priest_l20_candidates

    first = _request()
    alternate = copy.deepcopy(first)
    # Only proposal axes change; native decides whether the build is legal.
    alternate["raid"]["parties"][0]["players"][0]["talentsString"] = "1-0-0"
    for name, value in (("a.json", first), ("b.json", alternate),
                        ("c-duplicate.json", first)):
        (tmp_path / name).write_text(json.dumps(value))
    scored = []

    def scorer(binary, candidate, **kwargs):
        scored.append(copy.deepcopy(candidate))
        return {
            "effective_request_sha256": "native-score-" + str(len(scored)),
            "score": 20.0 + len(scored), "rng_mode": "balanced",
            "native_action_cast_receipts": [
                {"id": {"spellId": 585}, "casts": 2},
                {"id": {"spellId": 585, "tag": 1}, "casts": 7}],
        }, {}

    result = score_source_priest_l20_candidates(
        "/native", tmp_path, score_request=scorer)
    assert len(scored) == 2
    assert scored == [first, alternate]
    assert result["native_paid_whole_builds"] == 2
    assert result["native_source_action_casts"] == 4
    assert result["native_candidate_requests_attempted"] == 2
    assert [r["candidate"] for r in result["native_candidate_receipts"]] == [
        "a.json", "b.json"]
    assert all(r["status"] == "NATIVE_PAID"
               for r in result["native_candidate_receipts"])
    assert result["native_2d_screen_complete"] is False


def test_bounded_source_frontier_reports_native_refusals_without_credit(tmp_path):
    from tools.wf_native_priest_l20_paid import score_source_priest_l20_candidates

    invalid = _request()
    invalid["raid"]["parties"][0]["players"][0]["level"] = 60
    (tmp_path / "a-invalid.json").write_text(json.dumps(invalid))
    valid = _request()
    (tmp_path / "b-valid.json").write_text(json.dumps(valid))
    scored = []

    def scorer(binary, candidate, **kwargs):
        scored.append(candidate)
        raise RuntimeError("NATIVE_INVALID_TALENTS")

    result = score_source_priest_l20_candidates(
        "/native", tmp_path, score_request=scorer)
    assert len(scored) == 1
    assert result["native_paid_whole_builds"] == 0
    assert result["native_source_action_casts"] == 0
    assert [r["status"] for r in result["native_candidate_receipts"]] == [
        "NATIVE_REFUSED", "NATIVE_REFUSED"]
    assert result["native_2d_screen_complete"] is False


def test_p4_p5_gate_uses_paid_source_candidate_directory_without_m1_credit(
        tmp_path, monkeypatch):
    from tools import wf_gate_p4_p5_partial as gate
    from src.game import native_p3_item_options
    from tools import wf_native_priest_l20_paid

    (tmp_path / "a.json").write_text(json.dumps(_request()))
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "/native")
    monkeypatch.delenv("FOREVER_P4_P5_PRIEST_L20_SOURCE_REQUEST", raising=False)
    monkeypatch.setenv("FOREVER_P4_P5_PRIEST_L20_SOURCE_REQUEST_DIR", str(tmp_path))
    monkeypatch.setattr(native_p3_item_options, "query_native_p3_item_options",
                        lambda *a, **k: {
                            "status": "ok", "items": [{"item_id": 25, "slot": "chest"}],
                            "unverified_candidate_count": 0,
                        })
    calls = []
    monkeypatch.setattr(
        wf_native_priest_l20_paid, "score_source_priest_l20_candidates",
        lambda binary, directory: (
            calls.append((binary, directory)) or {
                "native_paid_whole_builds": 2, "native_source_action_casts": 4,
                "native_2d_screen_complete": False,
                "native_candidate_receipts": [],
            }))
    report = gate._native_cold_options_without_paid_executor(
        "priest", 20, "unrestricted")
    assert calls == [("/native", str(tmp_path))]
    assert report["status"] == "BLOCKED"
    assert report["paid_candidates"] == 2
    assert report["screen_complete_candidates"] == 0
    assert report["coverage_scope_complete"] is False
    assert report["reasons"] == ["P4_P5_NATIVE_2D_100MOB_SCREEN_NOT_CONNECTED"]
    assert "pass_count" not in report


def test_item_options_create_actual_native_paid_gear_requests_without_slot_rules(
        tmp_path):
    from tools.wf_native_priest_l20_paid import score_native_priest_l20_item_candidates

    source = _request()
    source_file = tmp_path / "source.json"
    source_file.write_text(json.dumps(source))
    evaluated = []

    def scorer(binary, candidate, **kwargs):
        evaluated.append(copy.deepcopy(candidate))
        return {
            "effective_request_sha256": "native-" + str(len(evaluated)),
            "score": 5.0 + len(evaluated), "rng_mode": "balanced",
            "native_action_cast_receipts": [
                {"id": {"spellId": 585}, "casts": 2}],
        }, {}

    receipt = score_native_priest_l20_item_candidates(
        "/native", source_file, [
            {"item_id": 102, "slot": "chest"},
            {"item_id": 103, "slot": "chest"},  # Same slot: do not spend again.
            {"item_id": 104, "slot": "head"},
            {"item_id": 105, "slot": "neck"},
        ], score_request=scorer, max_paid_builds=4)
    assert len(evaluated) == 4
    assert [request["raid"]["parties"][0]["players"][0]["equipment"]["items"]
            for request in evaluated] == [
                [], [{"id": 102}], [{"id": 102}, {"id": 104}],
                [{"id": 102}, {"id": 104}, {"id": 105}]]
    assert all(request["encounter"] == source["encounter"]
               for request in evaluated)
    assert all(request["raid"]["parties"][0]["players"][0]["level"] == 20
               for request in evaluated)
    assert receipt["native_item_options_proposed"] == 3
    assert receipt["native_item_option_source_slots_proposed"] == ["chest", "head", "neck"]
    assert receipt["native_paid_whole_builds"] == 4
    assert receipt["native_source_action_casts"] == 8
    assert receipt["native_2d_screen_complete"] is False
    assert json.loads(source_file.read_text()) == source


def test_native_item_proposals_do_not_overwrite_an_already_equipped_source(
        tmp_path):
    from tools.wf_native_priest_l20_paid import score_native_priest_l20_item_candidates

    source = _request()
    source["raid"]["parties"][0]["players"][0]["equipment"]["items"] = [
        {"id": 123}]
    source_file = tmp_path / "equipped.json"
    source_file.write_text(json.dumps(source))
    with pytest.raises(ValueError, match="REQUIRE_EMPTY_SOURCE_GEAR"):
        score_native_priest_l20_item_candidates(
            "/native", source_file, [{"item_id": 456, "slot": "head"}],
            score_request=lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("must not silently replace source gear")))


def test_l20_live_world_uses_exact_source_request_target_and_native_ack(tmp_path):
    from hashlib import sha256
    from tools.wf_native_priest_l20_paid import couple_source_priest_l20_world

    source = _request()
    actor = source["raid"]["parties"][0]["players"][0]
    actor["distanceFromTarget"] = 20
    source["encounter"]["targets"][0]["stats"] = [0] * 32 + [10000]
    path = tmp_path / "l20-source.json"
    path.write_text(json.dumps(source))
    invocations = []

    def real_world_boundary(binary, request_path, **kwargs):
        invocations.append((binary, request_path, kwargs))
        return {
            "source_request_raw_sha256": sha256(request_path.read_bytes()).hexdigest(),
            "source_request_proto_sha256": "actual-prepared-native-id",
            "iterations_done": 1, "native_world_ticks": 7,
            "native_damage_events": 3,
            "source_action_events_before": {"native-action-585": 2},
            "world_target_lethal_fights": 0,
        }

    report = couple_source_priest_l20_world(
        "/selected/rust", path, world_run=real_world_boundary)
    assert len(invocations) == 1
    assert str(invocations[0][0]) == "/selected/rust"
    assert invocations[0][1] == path
    assert invocations[0][2] == {
        "distance": 20.0, "iterations": 1, "rng_mode": "balanced",
        "expected_target_level": 20,
    }
    assert report["native_2d_fight_ack_complete"] is True
    assert report["native_2d_world_damage_events"] == 3
    assert report["native_2d_source_action_events"] == {"native-action-585": 2}
    assert report["native_2d_screen_complete"] is False
    assert json.loads(path.read_text()) == source

    def wrong_identity(binary, request_path, **kwargs):
        return {**real_world_boundary(binary, request_path, **kwargs),
                "source_request_raw_sha256": "unrelated-request"}
    with pytest.raises(RuntimeError, match="RECEIPT_INCOMPLETE"):
        couple_source_priest_l20_world(
            "/selected/rust", path, world_run=wrong_identity)


def test_l20_world_requires_real_source_level_and_distance(tmp_path):
    from tools.wf_native_priest_l20_paid import couple_source_priest_l20_world

    source = _request()
    source["encounter"]["targets"][0]["level"] = 63
    source["raid"]["parties"][0]["players"][0]["distanceFromTarget"] = 20
    path = tmp_path / "invalid-world.json"
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError, match="WORLD_ACTOR_TARGET_OR_DISTANCE_INVALID"):
        couple_source_priest_l20_world(
            "/native", path, world_run=lambda *a, **k: pytest.fail(
                "non-L20 target must not reach world"))
    source["encounter"]["targets"][0]["level"] = 20
    source["raid"]["parties"][0]["players"][0]["distanceFromTarget"] = 0
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError, match="WORLD_ACTOR_TARGET_OR_DISTANCE_INVALID"):
        couple_source_priest_l20_world(
            "/native", path, world_run=lambda *a, **k: pytest.fail(
                "invalid world distance must not run"))


def test_selected_paid_l20_native_candidate_is_sent_to_one_live_world_screen(tmp_path):
    from tools.wf_native_priest_l20_paid import score_source_priest_l20_candidates

    first = _request()
    better = copy.deepcopy(first)
    better["raid"]["parties"][0]["players"][0]["talentsString"] = "1-0-0"
    better["simOptions"]["randomSeed"] = "913"
    (tmp_path / "a.json").write_text(json.dumps(first))
    (tmp_path / "b.json").write_text(json.dumps(better))
    seen = []

    def scorer(binary, candidate, **kwargs):
        from hashlib import sha256
        score = 21. if candidate["raid"]["parties"][0]["players"][0]["talentsString"] == "1-0-0" else 10.
        effective = copy.deepcopy(candidate)
        effective["simOptions"].update(iterations=1, randomSeed="42")
        return {
            "effective_request_sha256": sha256(json.dumps(
                effective, sort_keys=True, separators=(",", ":")
            ).encode()).hexdigest(),
            "score": score, "rng_mode": "balanced",
            "native_action_cast_receipts": [
                {"id": {"spellId": 585}, "casts": 2}],
        }, {}

    def world_screen(binary, request_path):
        seen.append(json.loads(request_path.read_text()))
        return {"native_2d_fight_ack_complete": True,
                "native_2d_world_target_killed": True,
                "native_2d_screen_complete": False,
                "native_2d_world_ticks": 3}

    result = score_source_priest_l20_candidates(
        "/native", tmp_path, score_request=scorer, world_screen=world_screen)
    expected_live = copy.deepcopy(better)
    expected_live["simOptions"].update(iterations=1, randomSeed="42")
    assert seen == [expected_live]
    assert result["native_paid_whole_builds"] == 2
    assert result["native_2d_live_ack_attempted"] == 1
    assert result["native_2d_live_ack_verified"] == 1
    assert result["native_2d_live_world_kills"] == 1
    assert result["native_2d_screen_complete"] is False
    assert "pass_count" not in result
    assert result["native_candidate_receipts"][1]["native_2d_fight"][
        "native_2d_fight_ack_complete"] is True


def test_native_paid_world_refusal_does_not_grant_completion(tmp_path):
    from tools.wf_native_priest_l20_paid import score_source_priest_l20_candidates
    (tmp_path / "a.json").write_text(json.dumps(_request()))

    def scorer(binary, candidate, **kwargs):
        from hashlib import sha256
        effective = copy.deepcopy(candidate)
        effective["simOptions"].update(iterations=1, randomSeed="42")
        return {
            "effective_request_sha256": sha256(json.dumps(
                effective, sort_keys=True, separators=(",", ":")
            ).encode()).hexdigest(),
            "score": 12., "rng_mode": "balanced",
            "native_action_cast_receipts": [
                {"id": {"spellId": 585}, "casts": 1}],
        }, {}

    def world_screen(binary, request_path):
        raise RuntimeError("RUST_WORLD_DAMAGE_ACK_EVENTS_MISMATCH")

    result = score_source_priest_l20_candidates(
        "/native", tmp_path, score_request=scorer, world_screen=world_screen)
    assert result["native_paid_whole_builds"] == 1
    assert result["native_2d_live_ack_attempted"] == 1
    assert result["native_2d_live_ack_verified"] == 0
    assert result["native_2d_screen_complete"] is False
    assert "ACK_EVENTS_MISMATCH" in result["native_candidate_receipts"][0][
        "native_2d_fight_error"]


def test_target_health_probe_preserves_p7_default_but_accepts_explicit_l20():
    from tools.wf_gsim_go_live_range_probe import source_target_health_from_request

    source = _request()
    source["encounter"]["targets"][0]["stats"] = [0] * 32 + [10000]
    raw = json.dumps(source).encode()
    with pytest.raises(ValueError, match="SOURCE_DPS_TARGET_LEVEL_MISMATCH"):
        source_target_health_from_request(raw)
    assert source_target_health_from_request(
        raw, expected_target_level=20) == 10000.
    source["encounter"]["targets"][0]["level"] = 63
    assert source_target_health_from_request(json.dumps(source).encode()) == 10000.


def test_paid_world_retries_another_source_build_without_polluting_frontier(tmp_path):
    """One failed source-native 2D ACK must not discard other paid candidates."""
    from hashlib import sha256
    from tools.wf_native_priest_l20_paid import score_source_priest_l20_candidates

    baseline = _request()
    preferred = copy.deepcopy(baseline)
    preferred["raid"]["parties"][0]["players"][0]["talentsString"] = "1-0-0"
    preferred["simOptions"]["randomSeed"] = "913"
    (tmp_path / "a.json").write_text(json.dumps(baseline))
    (tmp_path / "b.json").write_text(json.dumps(preferred))
    attempted = []

    def scorer(binary, candidate, **kwargs):
        # Keep the identity of the exact native-paid normalized source request.
        effective = copy.deepcopy(candidate)
        effective["simOptions"].update(iterations=1, randomSeed="42")
        native_sha = sha256(json.dumps(
            effective, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        is_preferred = effective["raid"]["parties"][0]["players"][0][
            "talentsString"] == "1-0-0"
        return {
            "effective_request_sha256": native_sha,
            "score": 30.0 if is_preferred else 20.0,
            "rng_mode": "balanced",
            "native_action_cast_receipts": [
                {"id": {"spellId": 585}, "casts": 2},
            ],
        }, {}

    def world_screen(binary, request_path):
        assert request_path.parent != tmp_path
        assert request_path.is_file()
        observed = json.loads(request_path.read_text())
        attempted.append(observed)
        if observed["raid"]["parties"][0]["players"][0]["talentsString"] == "1-0-0":
            # A native-only high scorer is not necessarily world-executable.
            return {"native_2d_fight_ack_complete": False}
        return {
            "native_2d_fight_ack_complete": True,
            "native_2d_world_ticks": 5,
            "native_2d_screen_complete": False,
        }

    report = score_source_priest_l20_candidates(
        "/selected/native", tmp_path, score_request=scorer,
        world_screen=world_screen)
    assert len(attempted) == 2
    assert attempted[0]["simOptions"]["randomSeed"] == "42"
    assert attempted[0]["raid"]["parties"][0]["players"][0]["talentsString"] == "1-0-0"
    assert attempted[1]["raid"]["parties"][0]["players"][0]["talentsString"] == "0-0-0"
    assert report["native_paid_whole_builds"] == 2
    assert report["native_2d_live_ack_attempted"] == 2
    assert report["native_2d_live_ack_verified"] == 1
    assert report["native_2d_screen_complete"] is False
    rows = report["native_candidate_receipts"]
    assert rows[1]["native_2d_fight_error"] == "PRIEST_L20_PAID_WORLD_ACK_NOT_VERIFIED"
    assert rows[0]["native_2d_fight"]["native_2d_fight_ack_complete"] is True
    # Critical for cold P4/P5: no synthetic candidate becomes a new input.
    assert sorted(path.name for path in tmp_path.iterdir()) == ["a.json", "b.json"]
    assert json.loads((tmp_path / "b.json").read_text()) == preferred


def test_nonlethal_world_ack_tries_next_paid_build_for_a_real_kill(tmp_path):
    """A live ACK is not a kill: continue the bounded paid source frontier."""
    from hashlib import sha256
    from tools.wf_native_priest_l20_paid import score_source_priest_l20_candidates

    first = _request()
    second = copy.deepcopy(first)
    second["raid"]["parties"][0]["players"][0]["talentsString"] = "1-0-0"
    (tmp_path / "a.json").write_text(json.dumps(first))
    (tmp_path / "b.json").write_text(json.dumps(second))
    observed = []

    def scorer(binary, candidate, **kwargs):
        effective = copy.deepcopy(candidate)
        effective["simOptions"].update(iterations=1, randomSeed="42")
        key = sha256(json.dumps(
            effective, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return {
            "effective_request_sha256": key,
            "score": (30. if candidate["raid"]["parties"][0]["players"][0][
                "talentsString"] == "0-0-0" else 20.),
            "rng_mode": "balanced",
            "native_action_cast_receipts": [
                {"id": {"spellId": 585}, "casts": 3}],
        }, {}

    def world_screen(binary, request_path):
        current = json.loads(request_path.read_text())
        observed.append(current)
        return {
            "native_2d_fight_ack_complete": True,
            "native_2d_world_target_killed": len(observed) == 2,
            "native_2d_world_ticks": 7,
            "native_2d_screen_complete": False,
        }

    result = score_source_priest_l20_candidates(
        "/native", tmp_path, score_request=scorer, world_screen=world_screen)
    assert len(observed) == 2
    assert result["native_2d_live_ack_attempted"] == 2
    assert result["native_2d_live_ack_verified"] == 2
    assert result["native_2d_live_world_kills"] == 1
    rows = result["native_candidate_receipts"]
    assert rows[0]["native_2d_fight"]["native_2d_world_target_killed"] is False
    assert rows[1]["native_2d_fight"]["native_2d_world_target_killed"] is True
    assert result["native_2d_screen_complete"] is False
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.json", "b.json"]


def test_selected_priest_l20_target_uses_declared_classic_proxy_hp():
    """Keep the paid source scenario on a real L20 proxy, not a 10k smoke boss."""
    from tools.wf_gsim_go_live_range_probe import source_target_health_from_request

    source_path = (Path(__file__).resolve().parents[1]
        / "integrations/mythicsim-rust/fixtures/priest-l20-native-smite.request.json")
    request = source_path.read_bytes()
    source = json.loads(request)
    assert source["encounter"]["duration"] == 90
    assert source["encounter"]["targets"][0]["level"] == 20
    assert "CMaNGOS Classic-proxy" in source["encounter"]["targets"][0]["name"]
    # Explicit CMaNGOS BaseHealthExp0 L20 ordinary-melee proxy, not verified
    # Forever-server creature HP (see src/scenarios/leveling_targets.py).
    assert source_target_health_from_request(
        request, expected_target_level=20) == 484.


def test_world_frontier_reaches_third_paid_build_and_returns_lethal_source_identity(tmp_path):
    """Two genuine nonlethal 2D ACKs must not hide a third paid source kill."""
    from hashlib import sha256
    from tools.wf_native_priest_l20_paid import score_source_priest_l20_candidates

    for name in ("a", "b", "c"):
        candidate = _request()
        candidate["raid"]["parties"][0]["players"][0]["name"] = name
        (tmp_path / f"{name}.json").write_text(json.dumps(candidate))
    seen_world = []

    def scorer(binary, request, **kwargs):
        effective = copy.deepcopy(request)
        effective["simOptions"].update(iterations=1, randomSeed="42")
        key = sha256(json.dumps(
            effective, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        name = request["raid"]["parties"][0]["players"][0]["name"]
        return {
            "effective_request_sha256": key,
            "score": {"a": 30., "b": 20., "c": 10.}[name],
            "rng_mode": "balanced",
            "native_action_cast_receipts": [
                {"id": {"spellId": 585}, "casts": 2}],
        }, {}

    def world_screen(binary, source_path):
        name = json.loads(source_path.read_text())["raid"]["parties"][0][
            "players"][0]["name"]
        seen_world.append(name)
        return {
            "native_2d_fight_ack_complete": True,
            "native_2d_world_target_killed": name == "c",
            "native_2d_screen_complete": False,
        }

    retained_calls = []

    def persistent_world(binary, source_path):
        name = json.loads(source_path.read_text())["raid"]["parties"][0][
            "players"][0]["name"]
        retained_calls.append(name)
        return {
            "native_2d_persistent_actor_verified": True,
            "native_2d_persistent_world_ack_verified": True,
            "native_2d_persistent_world_targets_killed": 2,
            "native_2d_screen_complete": False,
        }

    result = score_source_priest_l20_candidates(
        "/native", tmp_path, score_request=scorer, world_screen=world_screen,
        persistent_world=persistent_world, max_paid_builds=3)
    assert result["native_paid_whole_builds"] == 3
    assert retained_calls == ["c"]
    assert result["native_2d_persistent_attempted"] == 1
    assert result["native_2d_persistent_verified"] == 1
    assert result["native_2d_persistent_targets_killed"] == 2
    assert seen_world == ["a", "b", "c"]
    assert result["native_2d_live_ack_attempted"] == 3
    assert result["native_2d_live_ack_verified"] == 3
    assert result["native_2d_live_world_kills"] == 1
    assert result["native_2d_live_kill_candidate"] == "c.json"
    assert result["native_2d_live_kill_request_sha256"] == (
        result["native_candidate_receipts"][2]["native_request_sha256"])
    assert result["native_2d_screen_complete"] is False
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "a.json", "b.json", "c.json"]


def test_priest_l20_persistent_world_prepares_exact_native_actor_and_reuses_one_session(
        tmp_path, monkeypatch):
    """The paid source is prepared by Rust, then one retained two-mob run executes."""
    import subprocess
    from tools.wf_native_priest_l20_paid import couple_source_priest_l20_persistent_world

    source = _request()
    source["encounter"]["targets"][0]["stats"] = [0] * 41
    source["encounter"]["targets"][0]["stats"][32] = 484
    path = tmp_path / "source.json"
    path.write_text(json.dumps(source))
    prepared_requests = []

    def prepare(args, **kwargs):
        assert args[1:3] == ["prepare", "--request"]
        assert kwargs["check"] is True
        prepared_requests.append(json.loads(Path(args[3]).read_text()))
        Path(args[5]).write_text(json.dumps({
            "player": {"class": "ClassPriest", "level": 20},
            "request_sha256": "a" * 64,
        }))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", prepare)
    world_calls = []

    def native_world(binary, prepared, *, mob_health, target_count, rng_mode):
        world_calls.append((json.loads(prepared.read_text()), mob_health, target_count, rng_mode))
        return {
            "continuous_native_actor": True, "actual_2d_ack": True,
            "world_targets_killed": 2, "native_windows": [{}, {}],
            "world_ticks": 42, "paid_recovery": False,
            "native_actor_mana_after_world_kills": [180., 145.],
            "minimum_native_actor_health": 320.,
            "world_elapsed_seconds": 17.5,
            "gsim_route_paid_movement_s": 2.5,
            "native_health_damage": {"observed": True, "damage_taken": 8., "damage_events": 1},
        }

    receipt = couple_source_priest_l20_persistent_world(
        "/selected/native", path, world_run=native_world)
    assert prepared_requests == [source]
    assert world_calls == [({
        "player": {"class": "ClassPriest", "level": 20},
        "request_sha256": "a" * 64,
    }, 484.0, 2, "balanced")]
    assert receipt["native_2d_persistent_world_targets_killed"] == 2
    assert receipt["native_2d_persistent_actor_verified"] is True
    assert receipt["native_2d_persistent_mana_after_kills"] == [180., 145.]
    assert receipt["native_2d_persistent_min_actor_health"] == 320.
    assert receipt["native_2d_persistent_elapsed_seconds"] == 17.5
    assert receipt["native_2d_persistent_paid_movement_seconds"] == 2.5
    assert receipt["native_2d_persistent_native_health_damage"]["damage_taken"] == 8.
    assert receipt["native_2d_screen_complete"] is False


def test_priest_l20_persistent_world_rejects_reset_fights_as_continuous(
        tmp_path, monkeypatch):
    import subprocess
    from tools.wf_native_priest_l20_paid import couple_source_priest_l20_persistent_world

    source = _request()
    source["encounter"]["targets"][0]["stats"] = [0] * 41
    source["encounter"]["targets"][0]["stats"][32] = 484
    path = tmp_path / "source.json"
    path.write_text(json.dumps(source))

    def prepare(args, **kwargs):
        Path(args[5]).write_text(json.dumps({
            "player": {"class": "ClassPriest", "level": 20},
            "request_sha256": "b" * 64,
        }))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", prepare)
    with pytest.raises(RuntimeError, match="PERSISTENT_NATIVE_WORLD_RECEIPT_INCOMPLETE"):
        couple_source_priest_l20_persistent_world(
            "/selected/native", path, world_run=lambda *a, **kw: {
                "continuous_native_actor": False, "actual_2d_ack": True,
                "world_targets_killed": 2, "native_windows": [{}, {}],
                "paid_recovery": False,
            })


def test_paid_lethal_candidate_falls_back_when_retained_actor_cannot_finish(tmp_path):
    """A one-target kill must not hide another paid build's persistent success."""
    from hashlib import sha256
    from tools.wf_native_priest_l20_paid import score_source_priest_l20_candidates

    for name in ("a", "b"):
        candidate = _request()
        candidate["raid"]["parties"][0]["players"][0]["name"] = name
        (tmp_path / f"{name}.json").write_text(json.dumps(candidate))
    live_calls = []
    retained_calls = []

    def scorer(binary, request, **kwargs):
        effective = copy.deepcopy(request)
        effective["simOptions"].update(iterations=1, randomSeed="42")
        key = sha256(json.dumps(
            effective, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        name = request["raid"]["parties"][0]["players"][0]["name"]
        return {
            "effective_request_sha256": key,
            "score": 30. if name == "a" else 20.,
            "rng_mode": "balanced",
            "native_action_cast_receipts": [{"id": {"spellId": 585}, "casts": 3}],
        }, {}

    def world_screen(binary, request_path):
        name = json.loads(request_path.read_text())["raid"]["parties"][0][
            "players"][0]["name"]
        live_calls.append(name)
        return {
            "native_2d_fight_ack_complete": True,
            "native_2d_world_target_killed": True,
            "native_2d_screen_complete": False,
        }

    def persistent_world(binary, request_path, *, target_count):
        name = json.loads(request_path.read_text())["raid"]["parties"][0][
            "players"][0]["name"]
        retained_calls.append((name, target_count))
        if name == "a":
            raise RuntimeError("RUST_TWO_WORLD_KILLS_NOT_COMPLETED")
        return {
            "native_2d_persistent_actor_verified": True,
            "native_2d_persistent_world_ack_verified": True,
            "native_2d_persistent_world_targets_killed": target_count,
            # Mocked transport receipts: these prove forwarding/refusal only,
            # not a real source-native 100-target world execution.
            "native_2d_persistent_source_action_events": target_count,
            "native_2d_persistent_source_action_counts_by_target": [
                {"spellId:585": 1} for _ in range(target_count)],
            "native_2d_screen_complete": False,
        }

    result = score_source_priest_l20_candidates(
        "/native", tmp_path, score_request=scorer, world_screen=world_screen,
        persistent_world=persistent_world, max_paid_builds=2,
        persistent_target_count=100)
    assert live_calls == ["a", "b"]
    assert retained_calls == [("a", 100), ("b", 100)]
    assert result["native_paid_whole_builds"] == 2
    assert result["native_2d_live_world_kills"] == 2
    assert result["native_2d_live_kill_candidate"] == "a.json"
    assert result["native_2d_persistent_attempted"] == 2
    assert result["native_2d_persistent_verified"] == 1
    assert result["native_2d_persistent_targets_killed"] == 100
    assert result["native_2d_persistent_target_goal"] == 100
    assert result["native_2d_persistent_candidate"] == "b.json"
    rows = result["native_candidate_receipts"]
    assert rows[0]["native_2d_persistent_error"] == "RUST_TWO_WORLD_KILLS_NOT_COMPLETED"
    assert rows[1]["native_2d_persistent_world"]["native_2d_persistent_actor_verified"]
    assert result["native_2d_persistent_request_sha256"] == rows[1]["native_request_sha256"]
    assert result["native_2d_live_kill_request_sha256"] == rows[0]["native_request_sha256"]
    assert result["native_2d_screen_complete"] is False
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.json", "b.json"]


@pytest.mark.parametrize("reported_kills", [2, 100])
def test_priest_paid_100_target_request_rejects_short_or_actionless_receipt(
        tmp_path, reported_kills):
    """The selected source build must achieve ALL requested persistent kills."""
    from hashlib import sha256
    from tools.wf_native_priest_l20_paid import score_source_priest_l20_candidates

    path = tmp_path / "source.json"
    path.write_text(json.dumps(_request()), encoding="utf-8")

    def scorer(binary, request, **kwargs):
        effective = copy.deepcopy(request)
        effective["simOptions"].update(iterations=1, randomSeed="42")
        key = sha256(json.dumps(
            effective, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return {
            "effective_request_sha256": key,
            "score": 15.0, "rng_mode": "balanced",
            "native_action_cast_receipts": [{"id": {"spellId": 585}, "casts": 4}],
        }, {}

    def persistent(binary, request_path, *, target_count):
        assert target_count == 100
        # A real two-mob success is not a verified 100-mob screen.
        return {
            "native_2d_persistent_actor_verified": True,
            "native_2d_persistent_world_ack_verified": True,
            "native_2d_persistent_world_targets_killed": reported_kills,
            "native_2d_screen_complete": False,
        }

    result = score_source_priest_l20_candidates(
        "/native", tmp_path, score_request=scorer,
        world_screen=lambda *a: {
            "native_2d_fight_ack_complete": True,
            "native_2d_world_target_killed": True,
        }, persistent_world=persistent, persistent_target_count=100)
    assert result["native_paid_whole_builds"] == 1
    assert result["native_2d_live_world_kills"] == 1
    assert result["native_2d_persistent_attempted"] == 1
    assert result["native_2d_persistent_verified"] == 0
    assert result["native_2d_persistent_targets_killed"] == 0
    assert result["native_2d_persistent_target_goal"] == 100
    assert result["native_2d_screen_complete"] is False
    assert result["native_candidate_receipts"][0]["native_2d_persistent_error"] == (
        "PRIEST_L20_PERSISTENT_WORLD_RECEIPT_INVALID")


@pytest.mark.parametrize("target_count", [1, 101, True, 2.5])
def test_priest_native_persistent_target_count_is_bounded(tmp_path, target_count):
    from tools.wf_native_priest_l20_paid import score_source_priest_l20_candidates

    (tmp_path / "source.json").write_text(json.dumps(_request()))
    with pytest.raises(ValueError, match="P4_P5_NATIVE_PERSISTENT_TARGET_COUNT_INVALID"):
        score_source_priest_l20_candidates(
            "/native", tmp_path, persistent_target_count=target_count)


@pytest.mark.parametrize(
    ("source_events", "expected_error"),
    [(0, "PRIEST_L20_PERSISTENT_NATIVE_SOURCE_ACTIONS_MISSING"),
     (3, None),
     (-1, "PRIEST_L20_PERSISTENT_NATIVE_SOURCE_ACTION_RECEIPT_INVALID")],
)
def test_priest_100_target_persistent_world_carries_native_source_action_windows(
        tmp_path, monkeypatch, source_events, expected_error):
    """A paid 100-target screen keeps per-kill native action evidence intact."""
    import subprocess
    from tools.wf_native_priest_l20_paid import couple_source_priest_l20_persistent_world

    source = _request()
    source["encounter"]["targets"][0]["stats"] = [0] * 41
    source["encounter"]["targets"][0]["stats"][32] = 484
    request = tmp_path / "source.json"
    request.write_text(json.dumps(source), encoding="utf-8")

    def native_prepare(args, **kwargs):
        assert args[1] == "prepare"
        Path(args[5]).write_text(json.dumps({
            "player": {"class": "ClassPriest", "level": 20},
            "request_sha256": "c" * 64,
        }), encoding="utf-8")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", native_prepare)

    def world_run(binary, prepared, *, mob_health, target_count, rng_mode):
        assert target_count == 100
        assert mob_health == 484.
        assert rng_mode == "balanced"
        return {
            "continuous_native_actor": True,
            "actual_2d_ack": True,
            "world_targets_killed": 100,
            "native_windows": [
                {"index": index, "source_action_counts":
                    ({"spellId:585": source_events} if index == 19 else {})}
                for index in range(100)
            ],
            "world_ticks": 600,
            "paid_recovery": False,
        }

    if expected_error:
        with pytest.raises(RuntimeError, match=expected_error):
            couple_source_priest_l20_persistent_world(
                "/selected/native", request, target_count=100, world_run=world_run)
    else:
        receipt = couple_source_priest_l20_persistent_world(
            "/selected/native", request, target_count=100, world_run=world_run)
        assert receipt["native_2d_persistent_source_action_events"] == 3
        windows = receipt["native_2d_persistent_source_action_counts_by_target"]
        assert len(windows) == 100
        assert windows[19] == {"spellId:585": 3}
        assert all(not counts for index, counts in enumerate(windows) if index != 19)
        assert receipt["native_2d_persistent_paid_recovery"] is False
        assert receipt["native_2d_screen_complete"] is False
