"""P7.5 paid stochastic finalist selection; injected interfaces, not gate evidence."""
import copy
import json
import random
from pathlib import Path
from types import SimpleNamespace

from tools import wf_gate_p7_5_live as gate


def _candidate(label):
    return {"simOptions": {"randomSeed": "4242"},
            "raid": {"parties": [{"players": [{
                "equipment": {"items": [{"id": 11}, {"id": 21}]},
                "talentsString": label, "distanceFromTarget": 15,
                "rotation": {"priorityList": [3, 2, 1]},
            }]}]}}


def test_p75_paid_stochastic_parent_and_independent_cold_restarts():
    a, b = _candidate("balanced"), _candidate("stochastic")
    balanced = (900.0, {}, "sha-a", a)
    paid = [(770.0, {}, "sha-b", b, 800.0)]
    rng = random.Random(4)
    assert gate._paid_p75_parent(balanced, paid, 1, rng) is b
    assert gate._paid_p75_parent(balanced, paid, 3, rng) is a
    assert gate._paid_p75_parent(balanced, paid, 5, rng) is None
    assert gate._paid_p75_parent(balanced, [], 1, rng) is a
    assert gate._paid_p75_parent(None, paid, 1, rng) is None


def test_p75_independent_stochastic_finalist_beats_balanced_spike(
        monkeypatch, tmp_path):
    """Real production search routing with paid native/world interfaces injected.

    Neither a 300-second wall-clock execution nor a real gate PASS is claimed.
    Before this change the 900-point 3-balanced screen winner was frozen.
    Its 1,000 stochastic DPS is only 650, versus contender B's 770.
    """
    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_text("injected binary")
    for name in ("items.jsonl", "enchants.jsonl"):
        path = binary.parents[2] / "data" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("")
    catalogue = tmp_path / "data/forever/catalogue/items_2026-09-29.sqlite"
    catalogue.parent.mkdir(parents=True)
    catalogue.write_text("injected catalogue")

    class Validator:
        @staticmethod
        def require_sqlite_catalogue(path):
            assert path == catalogue
        def __init__(self, *args):
            pass
        def validate(self, ids, enchants):
            assert ids == [11, 21]
        def close(self):
            pass

    calls = []
    generated = iter(("A", "B"))
    def make_candidate(base, pools, rng, **kwargs):
        return _candidate(next(generated))
    def player(request):
        return request["raid"]["parties"][0]["players"][0]

    source = SimpleNamespace(
        GearValidator=Validator, RejectedGear=ValueError,
        candidate_pool=lambda *args, **kw: ({0: [11], 1: [21]}, {}),
        source_enchant_pools=lambda *args: {0: [None], 1: [None]},
        make_candidate=make_candidate, player=player)
    def score(request, n, rng_mode):
        label = player(request)["talentsString"]
        if rng_mode == "balanced":
            return {"A": 900.0, "B": 800.0}[label]
        return {"A": 650.0, "B": 770.0}[label]
    def native(binary, path, n, *, rng_mode):
        req = json.loads(path.read_text())
        calls.append(("native", n, rng_mode, player(req)["talentsString"]))
        return {"native_dps": score(req, n, rng_mode)}
    def world(binary, path, distance, iterations, *, rng_mode):
        req = json.loads(path.read_text())
        calls.append(("world", iterations, rng_mode, player(req)["talentsString"]))
        return {"world_mean_dps": score(req, iterations, rng_mode),
                "iterations_done": iterations,
                "native_damage_events": 10, "native_world_ticks": 20}
    production = SimpleNamespace(native_source_control=native, run=world)
    def paid_finalist(production, binary, request, distance, *, seeds):
        calls.append(("stochastic_paid", 48, "stochastic",
                      player(request)["talentsString"]))
        return score(request, 48, "stochastic"), {
            "native_damage_events": 10, "native_world_ticks": 20}

    monkeypatch.setattr(gate, "_source_module",
                        lambda path, name: source if "joint_search" in str(path)
                        else production)
    monkeypatch.setattr(gate, "_pinned_source_runtime",
                        lambda *args: (_candidate("reference"),
                                       {"reference_dps": 728.19}, binary))
    monkeypatch.setattr(gate, "_paid_gear_stochastic_finalist", paid_finalist)
    monkeypatch.setattr(gate, "_source_native_world_parity", lambda *a, **kw: None)
    monkeypatch.setattr(gate, "strongest_accepted_prior",
                        lambda *a, **kw: {"dps": 749.5392,
                                          "compatible_gates": ["P7.3"],
                                          "run_urls": ["https://example.test/accepted"]})
    # Start, two balanced-paid builds, two early stochastic reranks,
    # then finish the same 300s clock. The budget helper also reads clock.
    clock = iter((0.0, 0.0, 0.0, 120.0, 120.0,
                  140.0, 140.0, 300.0, 300.0, 300.0))
    monkeypatch.setattr(gate.time, "monotonic", lambda: next(clock, 300.0))
    monkeypatch.setattr(gate.time, "sleep", lambda seconds: None)
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "1")

    result = gate.run_live(tmp_path, "druid", 60, spec="balance")
    assert result["status"] == "PASS", result
    assert result["cold_balanced_screen_best_dps"] == 900.0
    assert result["paid_joint_stochastic_finalists"] == 2
    assert result["frozen_stochastic_world_dps"] == 770.0
    assert result["joint_cold_world_dps"] == 770.0
    assert result["selected_validation"] == (
        "paid_2x24_stochastic_live_native_finalist")
    assert ("native", 1000, "stochastic", "B") in calls
    assert ("world", 1000, "stochastic", "A") not in calls
    assert result["source_legal_joint_candidates_paid"] == 2
