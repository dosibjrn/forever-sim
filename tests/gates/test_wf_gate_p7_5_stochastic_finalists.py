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


def test_p75_paid_joint_axes_cycle_only_on_seventh_proposal():
    """Both-axis paid neighborhoods extend the one-axis search, not cold starts."""
    assert gate._p75_paid_joint_axes(1) is None
    assert gate._p75_paid_joint_axes(5) is None
    assert gate._p75_paid_joint_axes(6) is None
    assert gate._p75_paid_joint_axes(7) == ("gear", "talents")
    assert gate._p75_paid_joint_axes(14) == ("gear", "rotation")
    assert gate._p75_paid_joint_axes(21) == ("talents", "rotation")
    assert gate._p75_paid_joint_axes(28) == ("gear", "talents")
    # Every eleventh paid-parent proposal rebuilds one complete source axis;
    # the seventh-proposal two-axis schedule still takes precedence at 77.
    assert gate._p75_paid_rebuild_axes(1) is None
    assert gate._p75_paid_rebuild_axes(11) == ("gear_rebuild",)
    assert gate._p75_paid_rebuild_axes(22) == ("talents_rebuild",)
    assert gate._p75_paid_rebuild_axes(33) == ("rotation_rebuild",)
    assert gate._p75_paid_rebuild_axes(44) == ("gear_rebuild",)
    # Every fifth proposal is STILL an independent paid-parent-free restart.
    paid = _candidate("paid")
    balanced = (800.0, {}, "paid-sha", paid)
    for index in (5, 10, 15, 20, 35):
        assert gate._paid_p75_parent(
            balanced, [], index, random.Random(9)) is None


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


def test_p75_archive_parent_escapes_single_balanced_leader():
    """A third local proposal can mutate another truly paid legal build.

    Before this repair every early local proposal descended from A, so
    the search had to escape a 3-fight outlier using only 1/5 cold restarts.
    This is a routing regression, not a simulated P7.5 acceptance.
    """
    a, b, c = (_candidate(label) for label in ("a", "b", "c"))
    best = (900.0, {}, "sha-a", a)
    archive = [(900.0, "sha-a", a), (899.0, "sha-b", b),
               (850.0, "sha-c", c)]

    class PickSecond:
        def choice(self, rows):
            return rows[1] if len(rows) > 1 else rows[0]

    pick = PickSecond()
    assert gate._paid_p75_parent(
        best, [], 3, pick, balanced_elites=archive) is b
    assert gate._paid_p75_parent(
        best, [], 1, pick, balanced_elites=archive) is a
    assert gate._paid_p75_parent(
        best, [], 5, pick, balanced_elites=archive) is None

    # Once real stochastic screens exist they still own most local moves;
    # balanced archive diversity remains only the every-third branch.
    stochastic = [(770.0, {}, "sha-c", c, 830.0)]
    assert gate._paid_p75_parent(
        best, stochastic, 1, pick, balanced_elites=archive) is c
    assert gate._paid_p75_parent(
        best, stochastic, 3, pick, balanced_elites=archive) is b
    assert gate._paid_p75_parent(
        best, stochastic, 5, pick, balanced_elites=archive) is None


def test_p75_deep_confirms_two_real_paid_leaders_before_freeze(
        monkeypatch, tmp_path):
    """RED before the repair: P7.5 stopped at 96 paid fights per leader.

    Exercise the production run_live search loop with injected native/world
    interfaces and a virtual 300s clock. Every 24-fight scorer is charged
    before final 1000-fight holdout; the saved reference never seeds a build.
    This is a control-flow regression, NOT actual gate evidence.
    """
    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_text("injected engine")
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

    now = [0.0]
    requests = [0]
    joint_calls = []
    paid_seeds = []
    deep_seeds = ("1955181", "1955207")

    def make_candidate(base, pools, rng, **kwargs):
        requests[0] += 1
        joint_calls.append((requests[0], kwargs.get("elite"),
                            kwargs.get("repair_axes")))
        if requests[0] > 40:
            # An unexpected nonterminating mock search must fail assertions,
            # not hang CI on a virtual clock.
            now[0] = 300.0
        return _candidate(str(requests[0]))

    def player(req):
        return req["raid"]["parties"][0]["players"][0]

    source = SimpleNamespace(
        GearValidator=Validator, RejectedGear=ValueError,
        candidate_pool=lambda *a, **kw: ({0: [11], 1: [21]}, {}),
        source_enchant_pools=lambda *a: {0: [None], 1: [None]},
        make_candidate=make_candidate, player=player)

    def native(binary, path, n, *, rng_mode):
        req = json.loads(path.read_text())
        return {"native_dps": 760.0 if n == 1000 else
                780.0 + int(player(req)["talentsString"])}

    def world(binary, path, distance, iterations, *, rng_mode):
        req = json.loads(path.read_text())
        if iterations == 3:
            now[0] = min(260.0, now[0] + 10.0)
        return {
            "world_mean_dps": (760.0 if iterations == 1000 else
                               780.0 + int(player(req)["talentsString"])),
            "iterations_done": iterations,
            "native_damage_events": 20, "native_world_ticks": 40}

    def paid_finalist(production, binary, request, distance, *, seeds):
        paid_seeds.append(seeds)
        if seeds == deep_seeds and paid_seeds.count(deep_seeds) == 2:
            now[0] = 300.0
        return 770.0 + int(player(request)["talentsString"]), {
            "native_damage_events": 20, "native_world_ticks": 40}

    production = SimpleNamespace(native_source_control=native, run=world)
    monkeypatch.setattr(gate, "_source_module",
                        lambda path, name: source if "joint_search" in str(path)
                        else production)
    monkeypatch.setattr(gate, "_pinned_source_runtime",
                        lambda *a: (_candidate("0"),
                                    {"reference_dps": 728.19}, binary))
    monkeypatch.setattr(gate, "_paid_gear_stochastic_finalist", paid_finalist)
    monkeypatch.setattr(gate, "_source_native_world_parity",
                        lambda *args, **kwargs: None)
    monkeypatch.setattr(gate, "strongest_accepted_prior",
                        lambda *args, **kwargs: {
                            "dps": 749.5, "compatible_gates": ["P7.3"],
                            "run_urls": ["https://example.test/accepted"]})
    monkeypatch.setattr(gate.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(gate.time, "sleep", lambda seconds: None)
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "1")

    result = gate.run_live(tmp_path, "druid", 60, spec="balance")
    assert result["status"] == "PASS", result
    assert result["search_wall_s"] == 300.0
    assert result["paid_joint_stochastic_confirmed"] >= 5
    assert result["paid_joint_stochastic_deep_confirmed"] == 2
    # Production run_live must really transmit scheduled two-axis repairs
    # to the existing source legality generator using only a PAID elite.
    paid_repairs = {(index, axes) for index, elite, axes in joint_calls
                    if elite is not None and axes is not None}
    assert (7, ("gear", "talents")) in paid_repairs
    assert (14, ("gear", "rotation")) in paid_repairs
    assert (21, ("talents", "rotation")) in paid_repairs
    assert (11, ("gear_rebuild",)) in paid_repairs
    assert (22, ("talents_rebuild",)) in paid_repairs
    assert (33, ("rotation_rebuild",)) in paid_repairs
    assert all(axes is None for index, elite, axes in joint_calls
               if index % 5 == 0 or elite is None)
    assert paid_seeds.count(deep_seeds) == 2
    assert result["selected_validation"] == (
        "paid_6x24_stochastic_live_native_deep_confirmed_finalist")
    assert result["frozen_stochastic_iterations"] == 1000
    assert result["frozen_stochastic_world_dps"] == 760.0
