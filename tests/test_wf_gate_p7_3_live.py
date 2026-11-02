"""P7.3 source-talent cold discovery contract, never a synthetic PASS."""
import copy
import random
from types import SimpleNamespace
import pytest
from tools import wf_gate_p7_3_live as gate


def _reference():
    return {"raid": {"parties": [{"players": [{
        "talentsString": "old", "equipment": {"items": [{"id": 17}]},
        "rotation": {"priorityList": [{"action": {"castSpell": {"spellId": 1}}}]},
    }]}]}}


def test_cold_talent_discovery_preserves_full_gear_apl_and_original():
    original = _reference()
    baseline = copy.deepcopy(original)
    source = SimpleNamespace(random_build=lambda rng: [[1, 2], [0], [0]],
                             validate=lambda ranks: True,
                             encode=lambda ranks: "independent_legal")
    new = gate._cold_talents(original, random.Random(647003), source)
    assert new != original
    assert new["raid"]["parties"][0]["players"][0]["talentsString"] == "independent_legal"
    assert new["raid"]["parties"][0]["players"][0]["rotation"] == baseline["raid"]["parties"][0]["players"][0]["rotation"]
    assert new["raid"]["parties"][0]["players"][0]["equipment"] == baseline["raid"]["parties"][0]["players"][0]["equipment"]
    assert original == baseline


def test_illegal_source_talents_cannot_run():
    source = SimpleNamespace(random_build=lambda rng: None,
                             validate=lambda ranks: False)
    with pytest.raises(ValueError, match="ALLOCATION_ILLEGAL"):
        gate._cold_talents(_reference(), random.Random(1), source)


def test_saved_identity_mismatch_fails_closed(tmp_path):
    report = gate.run_live(tmp_path, "priest", 60, spec="holy")
    assert report["status"] == "BLOCKED"
    assert "P7_3_PINNED_REFERENCE_NOT_SELECTED_FOR_CHECKPOINT" in report["reasons"]


def test_full_p73_freezes_a_unique_talent_winner_before_stochastic_holdout(
        monkeypatch, tmp_path):
    """Tests real-producer call routing, NOT a 300s or 1000-fight acceptance."""
    import json
    import hashlib
    from tools import wf_gate_p7_3_live as p73

    base = _reference()
    base["raid"]["parties"][0]["players"][0].update({
        "class": "ClassDruid", "distanceFromTarget": 15})
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "1")
    # Two attempts, same source talents; then a 300-second end boundary.
    clock = iter([0.0, 0.0, 0.0, 300.0, 300.0])
    monkeypatch.setattr(p73.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(
        p73, "_pinned_source_runtime",
        lambda *args: (base, {"reference_dps": 728.19}, tmp_path / "binary"))
    monkeypatch.setattr(
        p73, "_source_native_world_parity", lambda *a, **kw: None)
    source = SimpleNamespace(
        random_build=lambda rng: [[1], [0], [0]],
        validate=lambda ranks: True,
        encode=lambda ranks: "cold-source-legal")
    calls = []
    def native(binary, path, n, *, rng_mode):
        calls.append(("native", n, rng_mode, path.read_text()))
        return {"native_dps": 730.0}
    def world(binary, path, distance, iterations, *, rng_mode):
        calls.append(("world", iterations, rng_mode, path.read_text()))
        return {"world_mean_dps": 729.0,
                "native_damage_events": 10, "native_world_ticks": 15,
                "iterations_done": iterations}
    producer = SimpleNamespace(native_source_control=native, run=world)
    monkeypatch.setattr(
        p73, "_source_module",
        lambda path, name: source if "p73_talent" in str(path) else producer)

    report = p73.run_live(tmp_path, "druid", 60, spec="balance")
    assert [(kind, n, mode) for kind, n, mode, _ in calls] == [
        ("native", 3, "balanced"), ("world", 3, "balanced"),
        ("native", 1000, "stochastic"), ("world", 1000, "stochastic")]
    assert json.loads(calls[0][3]) == json.loads(calls[3][3])
    assert report["cold_unique_source_requests"] == 1
    assert report["source_legal_cold_candidates_paid"] == 1
    assert report["independent_300s_search_completed"] is True
    assert report["frozen_stochastic_iterations"] == 1000
    assert report["frozen_stochastic_reference_floor_met"] is True
    assert report["status"] == "PASS"  # mocked routing, not real native/world evidence
    assert report["reasons"] == []


def test_p73_invalid_full_search_flag_blocks_without_running(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "maybe")
    monkeypatch.setattr(
        gate, "_pinned_source_runtime",
        lambda *a: (_reference(), {"reference_dps": 728.19},
                     tmp_path / "binary"))
    report = gate.run_live(tmp_path, "druid", 60, spec="balance")
    assert report == {"status": "BLOCKED",
                      "reasons": ["P7_3_INVALID_FULL_SOURCE_SEARCH_MODE"]}
