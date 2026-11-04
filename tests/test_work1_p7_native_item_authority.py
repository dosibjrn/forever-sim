"""Work1 P7.4: native MythicSim owns item legality, Python only proposes IDs."""
from __future__ import annotations

import copy
import importlib
import random
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from tools import wf_gate_p7_4_live as gate


def test_native_authoritative_p74_pool_does_not_call_python_item_rules(monkeypatch):
    source = Path(__file__).resolve().parents[1] / "integrations/mythicsim-rust"
    monkeypatch.syspath_prepend(str(source))
    gear = importlib.import_module("p74_gear_search")

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        connection.execute(
            "CREATE TABLE items (item_id INTEGER, slot TEXT, spell_power REAL, "
            "intellect REAL, hit REAL, crit REAL, spirit REAL)"
        )
        source_slots = {
            name for slot in gear.SLOTS
            for name in gear.SOURCE_SLOTS.get(slot, (slot,))
        }
        for index, slot in enumerate(sorted(source_slots), 1):
            connection.execute(
                "INSERT INTO items VALUES (?, ?, 1, 0, 0, 0, 0)",
                (index, slot),
            )
        # This deliberately has no local level/class/armor metadata. It is a
        # proposal, not a Python-certified legal item; native sim decides.
        connection.execute(
            "INSERT INTO items VALUES (99999, 'head', 10000, 0, 0, 0, 0)"
        )

        def forbidden_python_rule(*args, **kwargs):
            raise AssertionError("native-authoritative proposal called Python item rules")

        validator = SimpleNamespace(connection=connection, item=forbidden_python_rule)
        pool, exclusions = gear.candidate_pool(
            validator, limit=None, independent_enchants=True,
            native_authoritative=True,
        )
        assert pool[0][0] == 99999
        assert 99999 in pool[0]
        assert exclusions == {}
    finally:
        connection.close()


def test_p74_native_authoritative_cold_candidate_skips_python_validator():
    base = {"raid": {"parties": [{"players": [{
        "equipment": {"items": [{"id": 10}, {"id": 20}]},
        "talentsString": "fixed",
        "rotation": {"priorityList": []},
    }]}]}}
    original = copy.deepcopy(base)

    def forbidden_validate(*args, **kwargs):
        raise AssertionError("Python GearValidator must not veto native candidates")

    def swap(request, ids):
        result = copy.deepcopy(request)
        items = result["raid"]["parties"][0]["players"][0]["equipment"]["items"]
        for item, item_id in zip(items, ids):
            item["id"] = item_id
        return result

    candidate = gate._cold_gear(
        base, SimpleNamespace(validate=forbidden_validate),
        SimpleNamespace(_swap=swap, preflight=lambda *args: True,
                        RejectedGear=ValueError),
        random.Random(1), pool={0: [11], 1: [21]},
        native_authoritative=True,
    )
    assert [item["id"] for item in
            candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"]] == [11, 21]
    assert base == original


def test_p74_native_refusal_stops_before_live_world(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "0")
    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_text("fake binary; native call is mocked")
    upstream = binary.parents[2]
    (upstream / "data").mkdir()
    (upstream / "data/items.jsonl").write_text("{}\n")
    (upstream / "data/enchants.jsonl").write_text("{}\n")

    base = {"raid": {"parties": [{"players": [{
        "class": "ClassDruid", "distanceFromTarget": 15,
        "equipment": {"items": [{"id": 100 + i} for i in range(16)]},
        "talentsString": "fixed",
        "rotation": {"priorityList": [{"action": 1}]},
    }]}]}}
    monkeypatch.setattr(
        gate, "_pinned_source_runtime",
        lambda *args: (base, {"reference_dps": 728.19}, binary),
    )
    monkeypatch.setattr(gate, "_source_native_world_parity", lambda *args, **kwargs: None)

    proposal_calls = []
    def pinned_rust_candidate_pool(items_path, enchants_path):
        proposal_calls.append((items_path, enchants_path))
        return (
            {i: [200 + i] for i in range(16)},
            {i: [None] for i in range(16)},
            {"unique_item_options": 16, "unique_enchant_options": 0},
        )

    gear = SimpleNamespace(
        pinned_rust_candidate_pool=pinned_rust_candidate_pool,
        RejectedGear=ValueError,
    )
    native_calls = []
    world_calls = []

    def cold_candidate(request, validator, gear_search, rng, **kwargs):
        assert kwargs["native_authoritative"] is True
        result = copy.deepcopy(request)
        result["raid"]["parties"][0]["players"][0]["equipment"]["items"][0]["id"] += (
            len(native_calls) + 1
        )
        return result

    def native(binary, path, iterations, *, rng_mode):
        native_calls.append((iterations, rng_mode))
        raise RuntimeError("NATIVE_INVALID_TEST_REFUSAL")

    def world(*args, **kwargs):
        world_calls.append((args, kwargs))
        raise AssertionError("native-refused candidate reached live world")

    production = SimpleNamespace(native_source_control=native, run=world)
    monkeypatch.setattr(gate, "_cold_gear", cold_candidate)
    monkeypatch.setattr(
        gate, "_source_module",
        lambda path, name: gear if "p74_gear_search" in str(path) else production,
    )

    report = gate.run_live(tmp_path, "druid", 60, spec="balance")
    assert report["status"] == "FAIL"
    assert proposal_calls == [(upstream / "data/items.jsonl", upstream / "data/enchants.jsonl")]
    assert native_calls == [(3, "balanced")] * 3
    assert world_calls == []
