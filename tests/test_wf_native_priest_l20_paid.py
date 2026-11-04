"""Transport-only regressions for the active Priest L20 native P4/P5 path."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tools.wf_native_priest_l20_paid import (
    score_source_priest_l20,
    score_source_priest_l20_candidates,
)


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



def test_refused_native_builds_do_not_exhaust_paid_whole_build_budget(tmp_path):
    """Only successful native executions spend the bounded paid-build slots."""
    from tools.wf_native_priest_l20_paid import score_source_priest_l20_candidates

    source = _request()
    for index in range(5):
        candidate = copy.deepcopy(source)
        candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"] = [
            {"id": 1000 + index}]
        (tmp_path / f"{index:03d}.json").write_text(json.dumps(candidate))
    attempted = []

    def scorer(binary, candidate, **kwargs):
        item = candidate["raid"]["parties"][0]["players"][0][
            "equipment"]["items"][0]["id"]
        attempted.append(item)
        if item < 1002:
            raise RuntimeError("NATIVE_INVALID_EQUIPMENT")
        return {
            "effective_request_sha256": f"native-paid-{item}",
            "score": float(item), "rng_mode": "balanced",
            "native_action_cast_receipts": [
                {"id": {"spellId": 585}, "casts": 1}],
        }, {}

    receipt = score_source_priest_l20_candidates(
        "/native", tmp_path, score_request=scorer,
        max_paid_builds=2, budget_s=6.0)
    assert attempted == [1000, 1001, 1002, 1003]
    assert [row["status"] for row in receipt["native_candidate_receipts"]] == [
        "NATIVE_REFUSED", "NATIVE_REFUSED", "NATIVE_PAID", "NATIVE_PAID"]
    assert receipt["native_candidate_requests_attempted"] == 4
    assert receipt["native_paid_whole_builds"] == 2
    assert receipt["native_source_action_casts"] == 2
    assert receipt["native_2d_screen_complete"] is False




def test_native_item_backups_fill_paid_slots_after_source_refusals(tmp_path):
    """Rust-sourced same-slot alternatives remain reachable after refusals."""
    from tools.wf_native_priest_l20_paid import score_native_priest_l20_item_candidates

    source_file = tmp_path / "source.json"
    source = _request()
    source_file.write_text(json.dumps(source))
    options = [{"item_id": 2000 + index, "slot": "trinket"}
               for index in range(5)]
    attempted = []

    def scorer(binary, candidate, **kwargs):
        items = candidate["raid"]["parties"][0]["players"][0][
            "equipment"]["items"]
        item = items[0]["id"] if items else None
        attempted.append(item)
        if item is None or item == 2000:
            raise RuntimeError("NATIVE_INVALID_BUILD")
        return {
            "effective_request_sha256": f"native-paid-{item}",
            "score": float(item), "rng_mode": "balanced",
            "native_action_cast_receipts": [
                {"id": {"spellId": 585}, "casts": 1}],
        }, {}

    receipt = score_native_priest_l20_item_candidates(
        "/native", source_file, options, score_request=scorer,
        max_paid_builds=2, budget_s=6.0)
    assert attempted == [None, 2000, 2001, 2002]
    assert receipt["native_paid_whole_builds"] == 2
    assert receipt["native_candidate_requests_attempted"] == 4
    assert receipt["native_item_options_proposed"] == 5
    assert receipt["native_item_option_alternative_builds_proposed"] == 4
    assert receipt["native_source_action_casts"] == 2
    assert receipt["native_2d_screen_complete"] is False
    assert json.loads(source_file.read_text()) == source



def test_refused_first_native_build_does_not_poison_comparable_world(tmp_path):
    """The first *paid* build anchors the scenario, not an invalid JSON candidate."""
    from tools.wf_native_priest_l20_paid import score_source_priest_l20_candidates

    refused = _request()
    refused["raid"]["parties"][0]["players"][0]["level"] = 60
    refused["encounter"]["targets"][0]["level"] = 60
    valid = _request()
    mismatched = copy.deepcopy(valid)
    mismatched["encounter"]["targets"][0]["level"] = 21
    for name, request in (("a-refused.json", refused),
                          ("b-valid.json", valid),
                          ("c-mismatched.json", mismatched)):
        (tmp_path / name).write_text(json.dumps(request))
    actual_native = []

    def scorer(binary, request, **kwargs):
        actual_native.append(copy.deepcopy(request))
        return {
            "effective_request_sha256": "native-paid-priest-l20",
            "score": 9.0, "rng_mode": "balanced",
            "native_action_cast_receipts": [
                {"id": {"spellId": 585}, "casts": 2}],
        }, {}

    receipt = score_source_priest_l20_candidates(
        "/native", tmp_path, score_request=scorer)
    assert actual_native == [valid]
    assert [r["status"] for r in receipt["native_candidate_receipts"]] == [
        "NATIVE_REFUSED", "NATIVE_PAID", "NATIVE_REFUSED"]
    assert "P4_P5_NATIVE_PRIEST_L20_SOURCE_REQUEST_REQUIRED" in (
        receipt["native_candidate_receipts"][0]["reason"])
    assert "P4_P5_NATIVE_CANDIDATE_ENCOUNTER_MISMATCH" in (
        receipt["native_candidate_receipts"][2]["reason"])
    assert receipt["native_paid_whole_builds"] == 1
    assert receipt["native_source_action_casts"] == 2
    assert receipt["native_2d_screen_complete"] is False
    assert json.loads((tmp_path / "b-valid.json").read_text()) == valid


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



def test_subprocess_timeout_refuses_one_candidate_without_losing_next_paid_build(tmp_path):
    """A failed native child must not abort the independent paid frontier."""
    import subprocess

    first = _request()
    second = copy.deepcopy(first)
    second["raid"]["parties"][0]["players"][0]["equipment"]["items"] = [
        {"id": 12345}]
    (tmp_path / "a-source.json").write_text(json.dumps(first))
    (tmp_path / "b-source.json").write_text(json.dumps(second))
    attempted = []

    def scorer(binary, candidate, **kwargs):
        attempted.append(copy.deepcopy(candidate))
        if len(attempted) == 1:
            raise subprocess.TimeoutExpired(["forever-engine", "sim"], 0.01)
        return {
            "effective_request_sha256": "second-native-paid-request",
            "score": 9.0, "rng_mode": "balanced",
            "native_action_cast_receipts": [
                {"id": {"spellId": 585}, "casts": 3}],
        }, {}

    result = score_source_priest_l20_candidates(
        "/native", tmp_path, score_request=scorer, budget_s=6.0)
    assert len(attempted) == 2
    assert [r["status"] for r in result["native_candidate_receipts"]] == [
        "NATIVE_REFUSED", "NATIVE_PAID"]
    assert "timed out" in result["native_candidate_receipts"][0]["reason"]
    assert result["native_paid_whole_builds"] == 1
    assert result["native_source_action_casts"] == 3
    assert result["native_2d_screen_complete"] is False
    assert json.loads((tmp_path / "a-source.json").read_text()) == first
    assert json.loads((tmp_path / "b-source.json").read_text()) == second


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



def test_native_paid_frontier_exposes_fuller_build_before_four_paid_slots(tmp_path):
    """A real native/world attempt must reach more than just 1-3 equipped slots.

    Native ItemSparse supplies the inventory, and only the paid Rust scorer
    decides whether the resulting full build executes; no Python item rules.
    """
    from tools.wf_native_priest_l20_paid import score_native_priest_l20_item_candidates

    source = _request()
    path = tmp_path / "source.json"
    path.write_text(json.dumps(source))
    seen = []

    def scorer(binary, candidate, **kwargs):
        items = [item["id"] for item in candidate["raid"]["parties"][0][
            "players"][0]["equipment"]["items"]]
        seen.append(items)
        return {
            "effective_request_sha256": f"native-build-{len(seen)}",
            "score": float(len(seen)), "rng_mode": "balanced",
            "native_action_cast_receipts": [
                {"id": {"spellId": 585}, "casts": 2}],
        }, {}

    options = [
        {"item_id": 201 + index, "slot": slot}
        for index, slot in enumerate(
            ["trinket", "shoulder", "legs", "finger", "waist", "ranged"])
    ]
    receipt = score_native_priest_l20_item_candidates(
        "/native", path, options, score_request=scorer,
        max_paid_builds=4, budget_s=6.0)

    # Earlier native budget: [] / [201] / [201, 202] / [201, 202, 203].
    # The same four paid requests now include a native-judged five-slot
    # distinct prefix/suffix builds before the budget runs out.
    assert seen == [
        [], [201, 202, 203, 204, 205], [202, 203, 204, 205, 206], [201]]
    assert receipt["native_item_options_proposed"] == 6
    assert receipt["native_item_option_dense_builds_proposed"] == 2
    assert receipt["native_item_option_alternative_builds_proposed"] == 0
    assert receipt["native_paid_whole_builds"] == 4
    assert receipt["native_source_action_casts"] == 8
    assert receipt["native_2d_screen_complete"] is False
    assert json.loads(path.read_text()) == source


@pytest.mark.parametrize(
    ("options", "expected_builds", "expected_alternatives"),
    [
        (
            [{"item_id": 102, "slot": "chest"},
             {"item_id": 103, "slot": "chest"},
             {"item_id": 104, "slot": "chest"},
             {"item_id": 105, "slot": "chest"}],
            [[], [102], [103], [104]], 2,
        ),
        (
            [{"item_id": 102, "slot": "chest"},
             {"item_id": 103, "slot": "chest"},
             {"item_id": 104, "slot": "head"},
             {"item_id": 105, "slot": "head"}],
            [[], [102], [102, 104], [103, 104]], 1,
        ),
    ],
)
def test_native_item_options_use_spare_paid_budget_for_same_slot_alternatives(
        tmp_path, options, expected_builds, expected_alternatives):
    """A short native slot list must not waste available whole-build evaluations."""
    from tools.wf_native_priest_l20_paid import score_native_priest_l20_item_candidates

    source = _request()
    path = tmp_path / "source.json"
    path.write_text(json.dumps(source))
    evaluated = []

    def scorer(binary, candidate, **kwargs):
        evaluated.append(copy.deepcopy(candidate))
        return {
            "effective_request_sha256": "native-" + str(len(evaluated)),
            "score": float(len(evaluated)), "rng_mode": "balanced",
            "native_action_cast_receipts": [
                {"id": {"spellId": 585}, "casts": 1}],
        }, {}

    receipt = score_native_priest_l20_item_candidates(
        "/native", path, options, score_request=scorer, max_paid_builds=4)
    actual = [
        [item["id"] for item in request["raid"]["parties"][0][
            "players"][0]["equipment"]["items"]]
        for request in evaluated
    ]
    assert actual == expected_builds
    assert receipt["native_paid_whole_builds"] == 4
    assert receipt["native_item_options_proposed"] == 3
    assert receipt["native_item_option_alternative_builds_proposed"] == expected_alternatives
    assert receipt["native_2d_screen_complete"] is False
    assert json.loads(path.read_text()) == source


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


def test_nonlethal_single_fight_ack_still_runs_retained_native_actor(tmp_path):
    """Only the retained native world decides whether two sourced mobs die.

    The separate one-fight smoke can be nonlethal without pre-vetoing a
    genuinely paid candidate's continuous native/2D execution.
    """
    from hashlib import sha256
    from tools.wf_native_priest_l20_paid import score_source_priest_l20_candidates

    source = _request()
    (tmp_path / "source.json").write_text(json.dumps(source))
    retained = []

    def scorer(binary, request, **kwargs):
        effective = copy.deepcopy(request)
        effective["simOptions"].update(iterations=1, randomSeed="42")
        key = sha256(json.dumps(
            effective, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return {
            "effective_request_sha256": key, "score": 8.75,
            "rng_mode": "balanced",
            "native_action_cast_receipts": [
                {"id": {"spellId": 585}, "casts": 3},
            ],
        }, {}

    def one_fight(binary, request_path):
        return {
            "native_2d_fight_ack_complete": True,
            "native_2d_world_target_killed": False,
            "native_2d_screen_complete": False,
        }

    def continuous(binary, request_path):
        retained.append(json.loads(request_path.read_text()))
        return {
            "native_2d_persistent_actor_verified": True,
            "native_2d_persistent_world_ack_verified": True,
            "native_2d_persistent_world_targets_killed": 2,
            "native_2d_screen_complete": False,
        }

    result = score_source_priest_l20_candidates(
        "/native", tmp_path, score_request=scorer,
        world_screen=one_fight, persistent_world=continuous)
    assert len(retained) == 1
    assert retained[0]["raid"]["parties"][0]["players"][0]["class"] == "ClassPriest"
    assert result["native_paid_whole_builds"] == 1
    assert result["native_2d_live_world_kills"] == 0
    assert result["native_2d_persistent_attempted"] == 1
    assert result["native_2d_persistent_verified"] == 1
    assert result["native_2d_persistent_targets_killed"] == 2
    assert result["native_2d_persistent_request_sha256"] == (
        result["native_candidate_receipts"][0]["native_request_sha256"])
    assert result["native_2d_screen_complete"] is False


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
        if name != "c":
            # The continuous native actor can fail even after a valid one-fight
            # ACK. This must not discard the next already-paid candidate.
            raise RuntimeError("NATIVE_RETAINED_ACTOR_DID_NOT_KILL")
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
    assert retained_calls == ["a", "b", "c"]
    assert result["native_2d_persistent_attempted"] == 3
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
            "native_combat_mana_regen_observed": True,
            "native_combat_mana_regen_actual_gain_by_target": [2.5, 4.],
            "native_combat_mana_regen_events_by_target": [1, 2],
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
    assert receipt["native_2d_persistent_combat_mana_regen_observed"] is True
    assert receipt["native_2d_persistent_combat_mana_regen_gains"] == [2.5, 4.]
    assert receipt["native_2d_persistent_combat_mana_regen_events"] == [1, 2]
    assert receipt["native_2d_persistent_paid_recovery"] is False
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


@pytest.mark.parametrize("one_fight_mode", ["omitted", "raises", "no_ack"])
def test_retained_100_target_native_world_is_not_vetoed_by_one_fight_probe(
        tmp_path, one_fight_mode):
    """Only the real retained actor decides its 100-target outcome.

    A separate one-fight probe can be absent, refused or fail without
    preventing native-paid source candidates from reaching the true 2D run.
    The mock receipt below never certifies a P4/P5 gate.
    """
    from hashlib import sha256
    from tools.wf_native_priest_l20_paid import score_source_priest_l20_candidates

    source = _request()
    (tmp_path / "source.json").write_text(json.dumps(source))
    retained_requests = []

    def native_paid(binary, candidate, **kwargs):
        effective = copy.deepcopy(candidate)
        effective["simOptions"].update(iterations=1, randomSeed="42")
        return {
            "effective_request_sha256": sha256(json.dumps(
                effective, sort_keys=True, separators=(",", ":")
            ).encode()).hexdigest(),
            "score": 12.0,
            "rng_mode": "balanced",
            "native_action_cast_receipts": [
                {"id": {"spellId": 585}, "casts": 3}],
        }, {}

    def retained(binary, path, *, target_count):
        assert target_count == 100
        retained_requests.append(json.loads(path.read_text()))
        return {
            "native_2d_persistent_actor_verified": True,
            "native_2d_persistent_world_ack_verified": True,
            "native_2d_persistent_world_targets_killed": 100,
            "native_2d_persistent_source_action_events": 100,
            "native_2d_persistent_source_action_counts_by_target": [
                {"spellId:585": 1} for _ in range(100)],
            "native_2d_screen_complete": False,
        }

    def one_fight(binary, path):
        if one_fight_mode == "raises":
            raise RuntimeError("INDEPENDENT_ONE_FIGHT_DIAGNOSTIC_FAILED")
        return {"native_2d_fight_ack_complete": False}

    result = score_source_priest_l20_candidates(
        "/selected/native", tmp_path, score_request=native_paid,
        world_screen=None if one_fight_mode == "omitted" else one_fight,
        persistent_world=retained, persistent_target_count=100)

    expected = copy.deepcopy(source)
    expected["simOptions"].update(iterations=1, randomSeed="42")
    assert retained_requests == [expected]
    assert result["native_paid_whole_builds"] == 1
    assert result["native_2d_persistent_attempted"] == 1
    assert result["native_2d_persistent_verified"] == 1
    assert result["native_2d_persistent_targets_killed"] == 100
    assert result["native_2d_live_ack_attempted"] == (
        0 if one_fight_mode == "omitted" else 1)
    assert result["native_2d_live_ack_verified"] == 0
    assert result["native_2d_screen_complete"] is False
    row = result["native_candidate_receipts"][0]
    assert row["native_2d_persistent_world"]["native_2d_persistent_world_targets_killed"] == 100
    if one_fight_mode == "raises":
        assert row["native_2d_fight_error"] == "INDEPENDENT_ONE_FIGHT_DIAGNOSTIC_FAILED"
    elif one_fight_mode == "no_ack":
        assert row["native_2d_fight_error"] == "PRIEST_L20_PAID_WORLD_ACK_NOT_VERIFIED"
    else:
        assert "native_2d_fight_error" not in row
    assert sorted(p.name for p in tmp_path.iterdir()) == ["source.json"]
    assert json.loads((tmp_path / "source.json").read_text()) == source


@pytest.mark.parametrize("target_count", [2, 100])
def test_priest_p4_p5_full_screen_skips_redundant_one_fight_smoke(
        tmp_path, monkeypatch, target_count):
    """The real 100-mob producer reaches the retained native world directly."""
    from tools import wf_gate_p4_p5_partial as gate
    from src.game import native_p3_item_options
    from tools import wf_native_priest_l20_paid as priest

    request = tmp_path / "source.json"
    request.write_text(json.dumps(_request()))
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "/native")
    monkeypatch.setenv("FOREVER_P4_P5_PRIEST_L20_SOURCE_REQUEST", str(request))
    monkeypatch.delenv("FOREVER_P4_P5_PRIEST_L20_SOURCE_REQUEST_DIR", raising=False)
    monkeypatch.setenv("FOREVER_P4_P5_PRIEST_L20_LIVE_WORLD", "1")
    monkeypatch.setenv("FOREVER_P4_P5_PRIEST_L20_PERSISTENT_TARGETS", str(target_count))
    monkeypatch.setattr(
        native_p3_item_options, "query_native_p3_item_options",
        lambda *a, **k: {
            "status": "ok", "items": [{"item_id": 25, "slot": "chest"}],
            "unverified_candidate_count": 0,
        })
    calls = []

    def scorer(binary, request_file, options, **kwargs):
        calls.append((binary, request_file, options, kwargs))
        return {"native_paid_whole_builds": 1,
                "native_source_action_casts": 2,
                "native_2d_screen_complete": False,
                "native_2d_persistent_verified": 0}

    monkeypatch.setattr(priest, "score_native_priest_l20_item_candidates", scorer)
    report = gate._native_cold_options_without_paid_executor(
        "priest", 20, "unrestricted")
    assert len(calls) == 1
    binary, request_file, options, forwarded = calls[0]
    assert binary == "/native"
    assert request_file == str(request)
    assert options == [{"item_id": 25, "slot": "chest"}]
    assert forwarded["persistent_world"] is priest.couple_source_priest_l20_persistent_world
    assert forwarded["persistent_target_count"] == target_count
    assert forwarded["world_screen"] is (
        None if target_count == 100 else priest.couple_source_priest_l20_world)
    assert report["paid_candidates"] == 1
    assert report["status"] == "BLOCKED"
    assert report["screen_complete_candidates"] == 0
    assert "pass_count" not in report


@pytest.mark.parametrize(("native_receipt", "expected_reason"), [
    (
        {
            "native_2d_persistent_verified": 0,
            "native_2d_persistent_targets_killed": 0,
            "native_candidate_receipts": [{
                "status": "NATIVE_PAID",
                "native_2d_persistent_error": "RUST_TWO_WORLD_KILLS_NOT_COMPLETED",
            }],
        },
        "P4_P5_NATIVE_2D_100MOB_FAILED:RUST_TWO_WORLD_KILLS_NOT_COMPLETED",
    ),
    (
        {
            "native_2d_persistent_verified": 1,
            "native_2d_persistent_targets_killed": 100,
            "native_candidate_receipts": [{
                "status": "NATIVE_PAID",
                "native_2d_persistent_world": {
                    "native_2d_persistent_world_targets_killed": 100,
                    "native_2d_persistent_paid_recovery": False,
                },
            }],
        },
        "P4_P5_NATIVE_PAID_RECOVERY_AND_COLD_SEARCH_NOT_COMPLETE",
    ),
    (
        {
            "native_2d_persistent_verified": 1,
            "native_2d_persistent_targets_killed": 100,
            "native_candidate_receipts": [{
                "status": "NATIVE_PAID",
                "native_2d_persistent_world": {
                    "native_2d_persistent_world_targets_killed": 100,
                    "native_2d_persistent_paid_recovery": True,
                },
            }],
        },
        "P4_P5_NATIVE_100MOB_PAID_RECOVERY_VERIFIED_COLD_SEARCH_NOT_COMPLETE",
    ),
])
def test_p4_p5_native_100mob_gate_exposes_real_outcome_without_fake_pass(
        tmp_path, monkeypatch, native_receipt, expected_reason):
    """The gate sees the native-world result, not a generic missing bridge."""
    from src.game import native_p3_item_options
    from tools import wf_gate_p4_p5_partial as gate
    from tools import wf_native_priest_l20_paid

    source = tmp_path / "source.json"
    source.write_text(json.dumps(_request()))
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "/selected/native")
    monkeypatch.setenv("FOREVER_P4_P5_PRIEST_L20_SOURCE_REQUEST", str(source))
    monkeypatch.setenv("FOREVER_P4_P5_PRIEST_L20_LIVE_WORLD", "1")
    monkeypatch.setenv("FOREVER_P4_P5_PRIEST_L20_PERSISTENT_TARGETS", "100")
    monkeypatch.delenv("FOREVER_P4_P5_PRIEST_L20_SOURCE_REQUEST_DIR", raising=False)
    monkeypatch.setattr(native_p3_item_options, "query_native_p3_item_options",
                        lambda *a, **k: {
                            "status": "ok",
                            "items": [{"item_id": 25, "slot": "chest"}],
                            "unverified_candidate_count": 0,
                        })
    calls = []

    def scorer(*args, **kwargs):
        calls.append(kwargs)
        return {
            "native_paid_whole_builds": 1,
            "native_source_action_casts": 2,
            "native_2d_screen_complete": False,
            **native_receipt,
        }

    monkeypatch.setattr(wf_native_priest_l20_paid,
                        "score_native_priest_l20_item_candidates", scorer)
    report = gate._native_cold_options_without_paid_executor(
        "priest", 20, "unrestricted")

    assert len(calls) == 1
    assert calls[0]["persistent_target_count"] == 100
    assert calls[0]["world_screen"] is None
    assert report["status"] == (
        "FAIL" if expected_reason.startswith("P4_P5_NATIVE_2D_100MOB_FAILED:")
        else "BLOCKED")
    assert report["reasons"] == [expected_reason]
    assert report["native_2d_screen_complete"] is False
    assert report["screen_complete_candidates"] == 0
    assert "pass_count" not in report


def test_priest_retained_world_preserves_native_regen_without_claiming_paid_rest():
    """Actual Rust mana-tick receipts are distinct from between-pull recovery."""
    from importlib.util import module_from_spec, spec_from_file_location
    script = (Path(__file__).resolve().parents[1] /
              "integrations/mythicsim-rust/live_two_world_pulls.py")
    spec = spec_from_file_location("work1_priest_native_mana_receipts", script)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    windows = [
        {"index": 0, "actor_mana": 180.,
         "native_combat_mana_regen_actual_gain": 2.5,
         "native_combat_mana_regen_events": 1},
        {"index": 1, "actor_mana": 145.,
         "native_combat_mana_regen_actual_gain": 4.,
         "native_combat_mana_regen_events": 2},
    ]
    receipt = module._native_mana_continuity(windows, 2)
    assert receipt["native_actor_mana_after_world_kills"] == [180., 145.]
    assert receipt["native_combat_mana_regen_observed"] is True
    assert receipt["native_combat_mana_regen_actual_gain_by_target"] == [2.5, 4.]
    assert receipt["native_combat_mana_regen_events_by_target"] == [1, 2]
    assert "paid_recovery" not in receipt

    # A prior selected fork without these native fields must remain unknown.
    older = module._native_mana_continuity(
        [{"index": 0, "actor_mana": 180.},
         {"index": 1, "actor_mana": 145.}], 2)
    assert "native_combat_mana_regen_observed" not in older
    assert "native_combat_mana_regen_actual_gain_by_target" not in older
    assert "native_combat_mana_regen_events_by_target" not in older


@pytest.mark.parametrize("broken,reason", [
    ({"native_combat_mana_regen_actual_gain": 1.},
     "RUST_MULTI_WORLD_NATIVE_REGEN_RECEIPT_INCOMPLETE"),
    ({"native_combat_mana_regen_actual_gain": -1.,
      "native_combat_mana_regen_events": 1},
     "RUST_MULTI_WORLD_NATIVE_REGEN_RECEIPT_INVALID"),
    ({"native_combat_mana_regen_actual_gain": 1.,
      "native_combat_mana_regen_events": 0},
     "RUST_MULTI_WORLD_NATIVE_REGEN_RECEIPT_INVALID"),
    ({"native_combat_mana_regen_actual_gain": 1.,
      "native_combat_mana_regen_events": True},
     "RUST_MULTI_WORLD_NATIVE_REGEN_RECEIPT_INVALID"),
])
def test_priest_retained_world_refuses_incomplete_native_regen_receipts(broken, reason):
    from importlib.util import module_from_spec, spec_from_file_location
    script = (Path(__file__).resolve().parents[1] /
              "integrations/mythicsim-rust/live_two_world_pulls.py")
    spec = spec_from_file_location("work1_priest_native_mana_bad", script)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    windows = [
        {"index": 0, "actor_mana": 180.,
         "native_combat_mana_regen_actual_gain": 2.,
         "native_combat_mana_regen_events": 1},
        {"index": 1, "actor_mana": 145., **broken},
    ]
    with pytest.raises(AssertionError, match=reason):
        module._native_mana_continuity(windows, 2)


@pytest.mark.parametrize(("native_failure", "expected"), [
    (
        AssertionError(("RUST_TWO_WORLD_KILLS_NOT_COMPLETED", None,
                        [{"target_id": "m1"}, {"target_id": "m0"}], 32)),
        "RUST_TWO_WORLD_KILLS_NOT_COMPLETED:completed=2:native_damage_events=32",
    ),
    (
        AssertionError(("RUST_TWO_WORLD_NATIVE_FAILED", 1,
                        "native mana exhausted on third target")),
        "RUST_TWO_WORLD_NATIVE_FAILED:exit=1:native mana exhausted on third target",
    ),
    (
        AssertionError(("RUST_TWO_WORLD_NATIVE_FAILED", 1,
                        "prepared input rejected: RUST_MULTI_WORLD_TARGET_NOT_NATIVE_LETHAL",
                        2, 32)),
        "RUST_TWO_WORLD_NATIVE_FAILED:exit=1:completed=2:native_damage_events=32:"
        "prepared input rejected: RUST_MULTI_WORLD_TARGET_NOT_NATIVE_LETHAL",
    ),
    (
        RuntimeError("RUST_NATIVE_PREPARE_REFUSED"),
        "RUST_NATIVE_PREPARE_REFUSED",
    ),
])
def test_100_target_native_failure_keeps_causal_reason(native_failure, expected):
    """An actual 100-target producer failure must not lose its error prefix.

    These are formatting regressions only, never synthetic P4/P5 receipts.
    """
    from tools.wf_native_priest_l20_paid import _native_world_error
    assert _native_world_error(native_failure) == expected


@pytest.mark.parametrize(("native_failure", "expected_reason"), [
    ((
        "RUST_TWO_WORLD_KILLS_NOT_COMPLETED", None,
        [{"target_id": "m1"}, {"target_id": "m0"}], 32,
    ), "RUST_TWO_WORLD_KILLS_NOT_COMPLETED:completed=2:native_damage_events=32"),
    ((
        "RUST_TWO_WORLD_NATIVE_FAILED", 1,
        "prepared input rejected: RUST_MULTI_WORLD_TARGET_NOT_NATIVE_LETHAL",
        2, 32,
    ), "RUST_TWO_WORLD_NATIVE_FAILED:exit=1:completed=2:native_damage_events=32:"
       "prepared input rejected: RUST_MULTI_WORLD_TARGET_NOT_NATIVE_LETHAL"),
])
def test_failed_100_target_native_actor_preserves_actual_world_kills(
        tmp_path, native_failure, expected_reason):
    """Actual native nonzero exit still preserves already ACKed kills; no PASS."""
    from hashlib import sha256
    from tools.wf_native_priest_l20_paid import score_source_priest_l20_candidates

    (tmp_path / "candidate.json").write_text(json.dumps(_request()))

    def scorer(binary, request, **kwargs):
        effective = copy.deepcopy(request)
        effective["simOptions"].update(iterations=1, randomSeed="42")
        digest = sha256(json.dumps(
            effective, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return {
            "effective_request_sha256": digest,
            "score": 13.,
            "rng_mode": "balanced",
            "native_action_cast_receipts": [{"id": {"spellId": 585}, "casts": 3}],
        }, {}

    def failed_world(binary, request_path, *, target_count):
        assert target_count == 100
        raise AssertionError(native_failure)

    result = score_source_priest_l20_candidates(
        "/selected/native", tmp_path, score_request=scorer,
        persistent_world=failed_world, persistent_target_count=100,
        max_paid_builds=1,
    )
    row = result["native_candidate_receipts"][0]
    assert result["native_paid_whole_builds"] == 1
    assert result["native_2d_persistent_attempted"] == 1
    assert result["native_2d_persistent_verified"] == 0
    assert result["native_2d_persistent_targets_killed"] == 0
    assert result["native_2d_persistent_max_observed_kills"] == 2
    assert row["native_2d_persistent_observed_kills"] == 2
    assert row["native_2d_persistent_error"] == expected_reason
    assert result["native_2d_screen_complete"] is False


@pytest.mark.parametrize("refuse_first_dense", [False, True])
def test_priest_native_item_frontier_pays_distinct_dense_builds_before_sparse_fallbacks(
        tmp_path, refuse_first_dense):
    """Different native-sourced whole builds get scarce paid slots; Rust can refuse.

    This tests Forever's proposal ordering only, not item legality or game
    effects. An invalid dense build must leave the remaining paid budget open.
    """
    from tools.wf_native_priest_l20_paid import score_native_priest_l20_item_candidates

    source_file = tmp_path / "priest-source.json"
    source_file.write_text(json.dumps(_request()), encoding="utf-8")
    options = [
        {"item_id": 2000 + index, "slot": f"native_slot_{index}"}
        for index in range(12)
    ]
    attempted = []

    def scorer(binary, request, **kwargs):
        ids = [
            item["id"] for item in request["raid"]["parties"][0][
                "players"][0]["equipment"]["items"]
        ]
        attempted.append(ids)
        if refuse_first_dense and ids == list(range(2000, 2005)):
            raise RuntimeError("RUST_REFUSED_DENSE_BUILD")
        return {
            "effective_request_sha256": f"native-{len(attempted)}",
            "score": float(len(ids) + 1), "rng_mode": "balanced",
            "native_action_cast_receipts": [
                {"id": {"spellId": 585}, "casts": 1}],
        }, {}

    result = score_native_priest_l20_item_candidates(
        "/selected/native", source_file, options, score_request=scorer,
        max_paid_builds=4, budget_s=6.0)
    expected = [
        [], list(range(2000, 2005)), list(range(2007, 2012)),
        list(range(2000, 2010)),
    ]
    if refuse_first_dense:
        expected.append([2000])
    assert attempted == expected
    assert result["native_paid_whole_builds"] == 4
    assert result["native_candidate_requests_attempted"] == len(expected)
    # The bounded proposal frontier includes three distinct dense builds,
    # but the companion producer caps the total proposed JSON requests.
    assert result["native_item_options_proposed"] == 12
    assert result["native_item_option_alternative_builds_proposed"] == 0
    assert result["native_item_option_dense_builds_proposed"] == 3
    assert result["native_2d_screen_complete"] is False
    assert json.loads(source_file.read_text(encoding="utf-8")) == _request()


def test_native_paid_recovery_requires_actual_rust_ticks_and_ack_clock():
    from importlib.util import module_from_spec, spec_from_file_location

    # The selected native/2D runner is a script rather than an import package.
    runner = Path(__file__).resolve().parents[1] / (
        "integrations/mythicsim-rust/live_two_world_pulls.py")
    spec = spec_from_file_location("test_paid_world_runner", runner)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    kills = [{"world_kill_clock_ns": 5_000_000_000},
             {"world_kill_clock_ns": 19_000_000_000}]
    windows = [{"native_passive_recovery_ns": 0,
                "native_passive_recovery_ticks": 0},
               {"native_passive_recovery_ns": 12_000_000_000,
                "native_passive_recovery_ticks": 6}]
    paid = module._native_paid_recovery_receipts(windows, kills)
    assert paid["paid_recovery"] is True
    assert paid["native_passive_recovery_ns_by_target"] == [0, 12_000_000_000]
    windows[1]["native_passive_recovery_ticks"] = 0
    assert module._native_paid_recovery_receipts(windows, kills)["paid_recovery"] is False
    windows[1]["native_passive_recovery_ticks"] = 6
    windows[1]["native_passive_recovery_ns"] = 15_000_000_000
    with pytest.raises(AssertionError, match="RECOVERY_CLOCK_INVALID"):
        module._native_paid_recovery_receipts(windows, kills)

