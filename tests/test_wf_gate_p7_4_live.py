"""P7.4 source-legal cold gear mutation contract, never a fake gate PASS."""
import copy
import random
from types import SimpleNamespace
from tools import wf_gate_p7_4_live as gate


def test_cold_gear_requires_nonreference_legal_native_candidate():
    base = {"raid": {"parties": [{"players": [{
        "equipment": {"items": [{"id": 10}, {"id": 20}]},
        "talentsString": "source",
        "rotation": {"priorityList": []},
    }]}]}}
    original = copy.deepcopy(base)
    calls = []
    validator = SimpleNamespace(validate=lambda ids: calls.append(ids))
    search = SimpleNamespace(
        candidate_pool=lambda v, limit: ({0: [11], 1: [21]}, {}),
        RejectedGear=ValueError,
        _swap=lambda req, ids: {
            **copy.deepcopy(req),
            "raid": {"parties": [{"players": [{
                **copy.deepcopy(req["raid"]["parties"][0]["players"][0]),
                "equipment": {"items": [{"id": v} for v in ids]}
            }]}]}}
    )
    row = gate._cold_gear(base, validator, search, random.Random(1))
    assert calls == [[11, 21]]
    assert row["raid"]["parties"][0]["players"][0]["equipment"]["items"] == (
        [{"id": 11}, {"id": 21}])
    assert base == original


def test_wrong_reference_never_reaches_native(tmp_path):
    report = gate.run_live(tmp_path, "priest", 60, spec="holy")
    assert report["status"] == "BLOCKED"
    assert "P7_4_PINNED_REFERENCE_NOT_SELECTED_FOR_CHECKPOINT" in report["reasons"]


def test_full_p74_freezes_one_paid_source_gear_winner_for_stochastic_holdout(
        monkeypatch, tmp_path):
    """Producer routing regression; mocked backend is NOT a P7.4 acceptance run."""
    import hashlib
    import json
    from pathlib import Path
    from types import SimpleNamespace

    base = {"raid": {"parties": [{"players": [{
        "class": "ClassDruid",
        "distanceFromTarget": 15,
        "equipment": {"items": [{"id": 10}, {"id": 20}]},
        "talentsString": "fixed-talents",
        "rotation": {"priorityList": [{"action": {"castSpell": {"spellId": 1}}}]},
    }]}]}}
    original = copy.deepcopy(base)
    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_text("fake executable; never invoked")
    upstream = binary.parents[2]
    (upstream / "data").mkdir()
    (upstream / "data/items.jsonl").write_text("")
    (upstream / "data/enchants.jsonl").write_text("")
    catalogue = tmp_path / "data/forever/catalogue/items_2026-09-29.sqlite"
    catalogue.parent.mkdir(parents=True)
    catalogue.write_text("fake catalogue; validator injected")

    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "1")
    clock = iter([0.0, 0.0, 300.0, 300.0])
    monkeypatch.setattr(gate.time, "monotonic", lambda: next(clock, 300.0))
    monkeypatch.setattr(gate, "_pinned_source_runtime",
                        lambda *a: (base, {"reference_dps": 728.19}, binary))
    monkeypatch.setattr(gate, "_source_native_world_parity",
                        lambda *a, **kw: None)

    pool_calls = []
    class Validator:
        @staticmethod
        def require_sqlite_catalogue(path):
            assert path == catalogue

        def __init__(self, *args):
            assert args[-1] is base

        def validate(self, ids, enchants=None):
            assert ids == [11, 21]
            if enchants is not None:
                assert len(enchants) == 2

        def close(self):
            pass

    def candidate_pool(validator, limit):
        pool_calls.append(limit)
        return ({0: [11], 1: [21]}, {})

    def swap(request, ids):
        result = copy.deepcopy(request)
        for slot, iid in zip(
                result["raid"]["parties"][0]["players"][0]["equipment"]["items"],
                ids):
            slot["id"] = iid
        return result

    gear = SimpleNamespace(
        GearValidator=Validator, candidate_pool=candidate_pool, _swap=swap,
        preflight=lambda reference, candidate: True,
        source_enchant_pools=lambda validator, pools: {0: [None, 201], 1: [None]},
        RejectedGear=ValueError)
    calls = []
    def native(binary, path, n, *, rng_mode):
        calls.append(("native", n, rng_mode, path.read_text()))
        return {"native_dps": 730.0}

    def world(binary, path, distance, iterations, *, rng_mode):
        assert distance == 15
        calls.append(("world", iterations, rng_mode, path.read_text()))
        return {"world_mean_dps": 729.0, "iterations_done": iterations,
                "native_damage_events": 12, "native_world_ticks": 25}

    producer = SimpleNamespace(native_source_control=native, run=world)
    monkeypatch.setattr(gate, "_source_module",
                        lambda path, name: gear if "p74_gear_search" in str(path)
                        else producer)

    report = gate.run_live(tmp_path, "druid", 60, spec="balance")
    assert pool_calls == [None], "Full search must keep all admitted source items"
    assert [(kind, n, mode) for kind, n, mode, _ in calls] == [
        ("native", 3, "balanced"), ("world", 3, "balanced"),
        ("native", 1000, "stochastic"), ("world", 1000, "stochastic")]
    assert json.loads(calls[0][3]) == json.loads(calls[3][3])
    assert report["frozen_request_raw_sha256"] == hashlib.sha256(
        calls[3][3].encode()).hexdigest()
    assert report["cold_unique_source_requests"] == 1
    assert report["source_legal_cold_candidates_paid"] == 1
    assert report["independent_300s_search_completed"] is True
    assert report["frozen_stochastic_iterations"] == 1000
    assert report["frozen_stochastic_reference_floor_met"] is True
    assert report["status"] == "PASS"  # mocked routing, not real source/native proof
    assert report["reasons"] == []
    assert base == original


def test_p74_invalid_full_search_flag_blocks_before_source_work(
        monkeypatch, tmp_path):
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "invalid")
    monkeypatch.setattr(
        gate, "_pinned_source_runtime",
        lambda *a: ({}, {"reference_dps": 728.19}, tmp_path / "binary"))
    report = gate.run_live(tmp_path, "druid", 60, spec="balance")
    assert report == {"status": "BLOCKED",
                      "reasons": ["P7_4_INVALID_FULL_SOURCE_SEARCH_MODE"]}


def test_full_cold_p74_can_free_enchant_without_changing_fixed_axes():
    """Pre-fix: unchanged reference item IDs could never gain a new enchant."""
    base = {"raid": {"parties": [{"players": [{
        "equipment": {"items": [{"id": 100+i} for i in range(16)]},
        "talentsString": "fixed-talents",
        "rotation": {"priorityList": [{"action": 1}]},
    }]}]}}
    original = copy.deepcopy(base)
    checked = []
    def validate(ids, enchants=None):
        checked.append((ids, enchants))
        assert ids == [100+i for i in range(16)]
        assert enchants == [411] + [None]*15
    def swap(reference, ids):
        q = copy.deepcopy(reference)
        for item, iid in zip(q["raid"]["parties"][0]["players"][0]["equipment"]["items"], ids):
            item["id"] = iid
        return q
    search = SimpleNamespace(_swap=swap, preflight=lambda *a: True,
                             RejectedGear=ValueError)
    pools = {i: [100+i] for i in range(16)}
    enchants = {i: ([411] if i == 0 else [None]) for i in range(16)}
    winner = gate._cold_gear(
        base, SimpleNamespace(validate=validate), search, random.Random(1),
        pool=pools, enchant_pools=enchants)
    player = winner["raid"]["parties"][0]["players"][0]
    assert player["equipment"]["items"][0] == {"id": 100, "enchant": 411}
    assert player["talentsString"] == "fixed-talents"
    assert player["rotation"] == {"priorityList": [{"action": 1}]}
    assert len(checked) == 1
    assert base == original
