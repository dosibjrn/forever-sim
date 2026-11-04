"""Transport-only regressions for the active Priest L20 native P4/P5 path."""
from __future__ import annotations

import copy
import json

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
        ], score_request=scorer, max_paid_builds=3)
    assert len(evaluated) == 3
    assert [request["raid"]["parties"][0]["players"][0]["equipment"]["items"]
            for request in evaluated] == [
                [], [{"id": 102}], [{"id": 104}]]
    assert all(request["encounter"] == source["encounter"]
               for request in evaluated)
    assert all(request["raid"]["parties"][0]["players"][0]["level"] == 20
               for request in evaluated)
    assert receipt["native_item_options_proposed"] == 2
    assert receipt["native_item_option_source_slots_proposed"] == ["chest", "head"]
    assert receipt["native_paid_whole_builds"] == 3
    assert receipt["native_source_action_casts"] == 6
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
