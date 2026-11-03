"""P7.5 paid unique balanced-screen selection; injected interfaces, not gate evidence."""
import ast
import copy
import hashlib
import json
import random
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import wf_gate_p7_5_live as gate


def _candidate(label):
    return {"simOptions": {"randomSeed": "4242"},
            "raid": {"parties": [{"players": [{
                "equipment": {"items": [{"id": 11}, {"id": 21}]},
                "talentsString": label, "distanceFromTarget": 15,
                "rotation": {"priorityList": [3, 2, 1]},
            }]}]}}



def test_p75_crossover_combines_two_distinct_paid_source_builds():
    """No saved reference seed: gear remains from newly built paid child.

    The second PAID parent contributes a coherent talent/rotation pair, not
    unrelated unscored talent and APL guesses. Neither parent is mutated.
    """
    parent, donor, child = (_candidate(x) for x in ("parent", "donor", "child"))
    child["raid"]["parties"][0]["players"][0]["equipment"]["items"][0]["id"] = 99
    donor_player = donor["raid"]["parties"][0]["players"][0]
    donor_player["rotation"]["priorityList"] = [7, 8, 9]
    original_donor = copy.deepcopy(donor)
    source = SimpleNamespace(
        player=lambda q: q["raid"]["parties"][0]["players"][0])
    assert gate._paid_p75_crossover(
        child, parent, [(771.0, {}, "paid-donor", donor, 800.0)],
        [(900.0, "paid-parent", parent)], source, random.Random(5))
    player = source.player(child)
    assert player["equipment"]["items"][0]["id"] == 99
    assert player["talentsString"] == "donor"
    assert player["rotation"]["priorityList"] == [7, 8, 9]
    assert donor == original_donor
    player["rotation"]["priorityList"].append(10)
    assert source.player(donor)["rotation"]["priorityList"] == [7, 8, 9]

    # A single paid parent must NOT be combined with an unexecuted reference.
    original_child = copy.deepcopy(child)
    assert not gate._paid_p75_crossover(
        child, parent, [], [(900.0, "paid-parent", parent)],
        source, random.Random(5))
    assert child == original_child



def test_p75_crossover_reaches_distinct_paid_balanced_axes_with_finalist_present():
    """A legal paid finalist must not mask a different paid balanced donor.

    Previous selection only admitted balanced donors when NO finalist donor
    survived. This is a candidate-generation reachability regression, not
    evidence of a P7.5 gate PASS or an improved stochastic holdout.
    """
    parent, finalist, balanced, child = (
        _candidate(label) for label in ("parent", "finalist", "balanced", "child"))
    player = lambda request: request["raid"]["parties"][0]["players"][0]
    player(finalist)["rotation"]["priorityList"] = [1, 2]
    player(balanced)["rotation"]["priorityList"] = [8, 9]
    source = SimpleNamespace(player=player)
    balanced_before = copy.deepcopy(balanced)
    finalist_before = copy.deepcopy(finalist)

    class PickLastDistinct:
        def choice(self, rows):
            # Both distinct source-paid routes must remain available.
            assert len(rows) == 2
            assert [row["talentsString"] for row in rows] == [
                "finalist", "balanced"]
            return rows[-1]

    assert gate._paid_p75_crossover(
        child, parent,
        [(800.0, {}, "confirmed-sha", finalist, 810.0)],
        [(790.0, "balanced-sha", balanced),
         (780.0, "duplicate-finalist", copy.deepcopy(finalist))],
        source, PickLastDistinct())
    assert player(child)["talentsString"] == "balanced"
    assert player(child)["rotation"]["priorityList"] == [8, 9]
    assert finalist == finalist_before
    assert balanced == balanced_before


def test_p75_crossover_duplicate_paid_axes_do_not_exhaust_distinct_donor_cap():
    """Repeated paid gear variants must not hide later distinct paid axes."""
    parent, child = (_candidate(x) for x in ("parent", "child"))
    source = SimpleNamespace(
        player=lambda q: q["raid"]["parties"][0]["players"][0])
    candidates = {label: _candidate(label) for label in
                  ("f1", "f2", "f3", "f4", "b1", "b2")}
    # All rows represent genuinely paid builds with distinct request labels.
    # The top three of either queue repeat the same talent/APL axes.
    finalists = [
        (900 - n, {}, f"final-{n}", copy.deepcopy(candidates["f1"]), 910.0)
        for n in range(3)
    ]
    finalists.extend(
        [(897.0, {}, "final-3", candidates["f2"], 907.0),
         (896.0, {}, "final-4", candidates["f3"], 906.0),
         (895.0, {}, "final-5", candidates["f4"], 905.0)])
    balanced = [
        (880 - n, f"balance-{n}", copy.deepcopy(candidates["b1"]))
        for n in range(3)
    ]
    balanced.append((877.0, "balance-3", candidates["b2"]))

    class CheckDistinctPaidDonors:
        def choice(self, rows):
            # Strongest three DISTINCT finalist axes and two balanced axes.
            assert [row["talentsString"] for row in rows] == [
                "f1", "f2", "f3", "b1", "b2"]
            return rows[-1]

    assert gate._paid_p75_crossover(
        child, parent, finalists, balanced, source, CheckDistinctPaidDonors())
    assert source.player(child)["talentsString"] == "b2"


def test_p75_gear_block_crossover_preserves_paid_enchants_without_python_veto():
    """The paid gear proposal must reach native instead of local legality."""
    parent, donor, child = (_candidate(x) for x in ("parent", "donor", "child"))
    items = child["raid"]["parties"][0]["players"][0]["equipment"]["items"]
    paid_items = donor["raid"]["parties"][0]["players"][0]["equipment"]["items"]
    paid_items[:] = [{"id": 71, "enchant": 801},
                     {"id": 72, "enchant": 802}]
    original_donor = copy.deepcopy(donor)
    source = SimpleNamespace(
        player=lambda q: q["raid"]["parties"][0]["players"][0],
        RejectedGear=ValueError)
    assert gate._paid_p75_gear_block_crossover(
        child, parent, [(771.0, {}, "paid-donor", donor, 800.0)],
        [(900.0, "paid-parent", parent)], source, random.Random(5))
    assert items == paid_items
    items[0]["id"] = 999
    assert donor == original_donor

    unsupported = _candidate("candidate-to-forward")
    assert gate._paid_p75_gear_block_crossover(
        unsupported, parent, [(771.0, {}, "paid-donor", donor, 800.0)],
        [], source, random.Random(5))
    assert source.player(unsupported)["equipment"]["items"] == paid_items
    assert not gate._paid_p75_gear_block_crossover(
        _candidate("no-donor"), parent, [], [], source, random.Random(5))


def test_p75_gear_block_uses_paid_balanced_gear_when_finalist_gear_is_identical():
    """Unchanged finalist gear must not suppress a distinct paid donor."""
    parent, finalist, donor, child = (
        _candidate(name) for name in ("parent", "stochastic", "balanced", "child"))
    source = SimpleNamespace(
        player=lambda q: q["raid"]["parties"][0]["players"][0],
        RejectedGear=ValueError)
    assert source.player(finalist)["equipment"] == source.player(child)["equipment"]
    source.player(donor)["equipment"]["items"] = [
        {"id": 71, "enchant": 801}, {"id": 72, "enchant": 802}]
    assert gate._paid_p75_gear_block_crossover(
        child, parent, [(800.0, {}, "paid-finalist", finalist, 900.0)],
        [(900.0, "paid-parent", parent), (780.0, "paid-gear", donor)],
        source, random.Random(5))
    assert source.player(child)["equipment"] == source.player(donor)["equipment"]

    one_slot = _candidate("one-slot")
    source.player(one_slot)["equipment"]["items"][0]["id"] = 91
    fresh = _candidate("fresh")
    before = copy.deepcopy(fresh)
    assert not gate._paid_p75_gear_block_crossover(
        fresh, parent, [(800.0, {}, "paid-one-slot", one_slot, 900.0)],
        [], source, random.Random(5))
    assert fresh == before


def test_p75_gear_block_submits_top_paid_donor_without_local_rules():
    """Do not reject a gear combination based on a second Python ruleset."""
    parent, finalist, alternative, child = (
        _candidate(name) for name in ("parent", "paid-finalist", "paid-balanced", "child"))
    player = lambda q: q["raid"]["parties"][0]["players"][0]
    player(finalist)["equipment"]["items"] = [
        {"id": 91, "enchant": 901}, {"id": 92, "enchant": 902}]
    player(alternative)["equipment"]["items"] = [
        {"id": 71, "enchant": 801}, {"id": 72, "enchant": 802}]
    source = SimpleNamespace(player=player, RejectedGear=ValueError)
    original_finalist = copy.deepcopy(finalist)
    original_alternative = copy.deepcopy(alternative)

    class DeterministicRng:
        def shuffle(self, sequence): pass
        def randint(self, low, high): return low
        def sample(self, sequence, count): return sequence[:count]

    assert gate._paid_p75_gear_block_crossover(
        child, parent,
        [(900.0, {}, "paid-finalist-sha", finalist, 950.0)],
        [(800.0, "paid-balanced-sha", alternative)],
        source, DeterministicRng())
    assert player(child)["equipment"] == player(finalist)["equipment"]
    assert finalist == original_finalist
    assert alternative == original_alternative



def test_p75_gear_block_can_select_paid_balanced_donor_with_finalist_present():
    """A paid finalist must not starve independently paid balanced gear.

    Both donor builds were already scored in this cold search. The old
    operator shuffled each donor family separately but always picked the
    first finalist, so balanced gear was unreachable whenever a finalist
    had two different slots. This tests proposal reachability, not native
    Warcraft legality or a P7.5 DPS PASS.
    """
    parent, finalist, balanced, child = (
        _candidate(label) for label in
        ("parent", "paid-finalist", "paid-balanced", "child"))
    player = lambda req: req["raid"]["parties"][0]["players"][0]
    player(finalist)["equipment"]["items"] = [
        {"id": 91, "enchant": 901}, {"id": 92, "enchant": 902}]
    player(balanced)["equipment"]["items"] = [
        {"id": 71, "enchant": 801}, {"id": 72, "enchant": 802}]
    original_finalist = copy.deepcopy(finalist)
    original_balanced = copy.deepcopy(balanced)

    class PreferLastPaidDonor:
        def shuffle(self, rows):
            if len(rows) > 1:
                rows.reverse()
        def randint(self, low, high):
            return low
        def sample(self, rows, count):
            return rows[:count]

    assert gate._paid_p75_gear_block_crossover(
        child, parent,
        [(900.0, {}, "paid-finalist", finalist, 950.0)],
        [(800.0, "paid-balanced", balanced)],
        SimpleNamespace(player=player), PreferLastPaidDonor())
    assert player(child)["equipment"] == player(balanced)["equipment"]
    assert finalist == original_finalist
    assert balanced == original_balanced


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


def test_p75_freezes_best_paid_screen_without_repeating_seed_independent_balanced_rng(
        monkeypatch, tmp_path):
    """The pinned BalancedRng ignores seed; a second screen adds no information.

    Candidate selection remains balanced-only. The independent stochastic
    holdout measures the frozen winner but never chooses it.
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
        return {"A": 760.0, "B": 770.0}[label]

    def native(binary, path, n, *, rng_mode):
        req = json.loads(path.read_text())
        calls.append(("native", n, rng_mode, player(req)["talentsString"]))
        return {"native_dps": score(req, n, rng_mode)}

    def world(binary, path, distance, iterations, *, rng_mode):
        req = json.loads(path.read_text())
        calls.append(("world", iterations, rng_mode,
                      player(req)["talentsString"]))
        return {"world_mean_dps": score(req, iterations, rng_mode),
                "iterations_done": iterations,
                "native_damage_events": 10, "native_world_ticks": 20}

    production = SimpleNamespace(native_source_control=native, run=world)
    original_crossover = gate._paid_p75_crossover

    def observe_crossover(candidate, parent, finalists, balanced_elites,
                          source, rng):
        operator_rngs.append(rng)
        assert rng is not candidate_rngs[-1]
        search_state = candidate_rngs[-1].getstate()
        for _ in range(20):
            rng.random()
        assert candidate_rngs[-1].getstate() == search_state
        return original_crossover(
            candidate, parent, finalists, balanced_elites, source, rng)

    monkeypatch.setattr(gate, "_paid_p75_crossover", observe_crossover)
    monkeypatch.setattr(gate, "_source_module",
                        lambda path, name: source if "joint_search" in str(path)
                        else production)
    monkeypatch.setattr(gate, "_pinned_source_runtime",
                        lambda *args: (_candidate("reference"),
                                       {"reference_dps": 728.19}, binary))
    monkeypatch.setattr(gate, "_source_native_world_parity",
                        lambda *args, **kwargs: None)
    monkeypatch.setattr(gate, "strongest_accepted_prior",
                        lambda *args, **kwargs: {
                            "dps": 749.5392, "compatible_gates": ["P7.3"],
                            "run_urls": ["https://example.test/accepted"]})
    # Start; pay one 3-fight Balanced screen each for A and B; then observe
    # the full 300s search window. No duplicate seeded Balanced reranks.
    clock = iter((0.0, 0.0, 0.0, 300.0, 300.0))
    monkeypatch.setattr(gate.time, "monotonic", lambda: next(clock, 300.0))
    monkeypatch.setattr(gate.time, "sleep", lambda seconds: None)
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "1")

    result = gate.run_live(tmp_path, "druid", 60, spec="balance")
    assert result["status"] == "PASS", result
    assert result["search_wall_s"] == 300.0
    assert result["cold_balanced_screen_best_dps"] == 900.0
    assert result["selected_balanced_screen_dps"] == 900.0
    assert result["paid_joint_balanced_finalists"] == 0
    assert result["paid_joint_balanced_confirmed"] == 0
    assert result["paid_joint_balanced_deep_confirmed"] == 0
    assert result["frozen_stochastic_world_dps"] == 760.0
    assert result["frozen_source_build"] == {
        "equipment": {"items": [{"id": 11}, {"id": 21}]},
        "talentsString": "A",
        "rotation": {"priorityList": [3, 2, 1]},
    }
    cold_hash = hashlib.sha256(json.dumps(
        _candidate("A"), sort_keys=True).encode()).hexdigest()
    assert result["cold_winner_request_sha256"] == cold_hash
    assert result["selected_balanced_request_sha256"] == cold_hash
    assert result["joint_cold_world_dps"] == 900.0
    assert result["selected_validation"] == "three_balanced_live_screen_only"
    assert calls == [
        ("native", 3, "balanced", "A"),
        ("world", 3, "balanced", "A"),
        ("native", 3, "balanced", "B"),
        ("world", 3, "balanced", "B"),
        ("native", 1000, "stochastic", "A"),
        ("world", 1000, "stochastic", "A"),
    ]
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


def test_p75_full_budget_spends_on_unique_paid_candidates_without_reranks(
        monkeypatch, tmp_path):
    """One deterministic 3-fight screen per candidate leaves the full budget for discovery.

    This exercises the production run_live loop with injected native/world
    interfaces and a virtual 300s clock. It is control-flow coverage, not
    actual gate evidence.
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
    screen_calls = []
    candidate_rngs = []
    operator_rngs = []

    def make_candidate(base, pools, rng, **kwargs):
        requests[0] += 1
        candidate_rngs.append(rng)
        joint_calls.append((requests[0], kwargs.get("elite"),
                            kwargs.get("repair_axes")))
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
        if n == 3:
            screen_calls.append(("native", n, rng_mode,
                                 player(req)["talentsString"]))
        return {"native_dps": 760.0 if n == 1000 else
                780.0 + int(player(req)["talentsString"])}

    def world(binary, path, distance, iterations, *, rng_mode):
        req = json.loads(path.read_text())
        if iterations == 3:
            screen_calls.append(("world", iterations, rng_mode,
                                 player(req)["talentsString"]))
            now[0] = min(300.0, now[0] + 10.0)
        return {
            "world_mean_dps": (760.0 if iterations == 1000 else
                               780.0 + int(player(req)["talentsString"])),
            "iterations_done": iterations,
            "native_damage_events": 20, "native_world_ticks": 40}

    production = SimpleNamespace(native_source_control=native, run=world)
    original_crossover = gate._paid_p75_crossover

    def observe_crossover(candidate, parent, finalists, balanced_elites,
                          source, rng):
        operator_rngs.append(rng)
        assert rng is not candidate_rngs[-1]
        search_state = candidate_rngs[-1].getstate()
        for _ in range(20):
            rng.random()
        assert candidate_rngs[-1].getstate() == search_state
        return original_crossover(
            candidate, parent, finalists, balanced_elites, source, rng)

    monkeypatch.setattr(gate, "_paid_p75_crossover", observe_crossover)
    monkeypatch.setattr(gate, "_source_module",
                        lambda path, name: source if "joint_search" in str(path)
                        else production)
    monkeypatch.setattr(gate, "_pinned_source_runtime",
                        lambda *a: (_candidate("0"),
                                    {"reference_dps": 728.19}, binary))
    monkeypatch.setattr(gate, "_source_native_world_parity",
                        lambda *args, **kwargs: None)
    gear_block_calls = []

    def observe_gear_block(*args):
        gear_block_calls.append(requests[0])
        return False

    monkeypatch.setattr(gate, "_paid_p75_gear_block_crossover",
                        observe_gear_block)
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
    assert result["source_legal_joint_candidates_paid"] == 30
    assert candidate_rngs[0] is candidate_rngs[-1]
    assert len(operator_rngs) == 2  # proposals 13 and 26
    assert len({id(rng) for rng in operator_rngs}) == 2
    assert len(screen_calls) == 60
    world_screens = [label for kind, n, mode, label in screen_calls
                     if kind == "world"]
    assert len(world_screens) == 30
    assert len(set(world_screens)) == 30
    assert result["paid_joint_balanced_finalists"] == 0
    assert result["paid_joint_balanced_confirmed"] == 0
    assert result["paid_joint_balanced_deep_confirmed"] == 0
    # Production run_live must transmit scheduled multi-axis repairs to the
    # source generator using only a PAID elite.
    paid_repairs = {(index, axes) for index, elite, axes in joint_calls
                    if elite is not None and axes is not None}
    assert (7, ("gear", "talents")) in paid_repairs
    assert (14, ("gear", "rotation")) in paid_repairs
    assert (21, ("talents", "rotation")) in paid_repairs
    assert (13, ("gear",)) in paid_repairs  # source-paid crossover
    assert (17, ("gear",)) in paid_repairs  # paid source-validated gear block
    assert 17 in gear_block_calls
    assert (11, ("gear_rebuild",)) in paid_repairs
    assert (22, ("talents_rebuild",)) in paid_repairs
    # The virtual budget finishes before proposal 33; the rotation-rebuild
    # schedule is covered by the pure scheduling assertion above.
    assert all(axes is None for index, elite, axes in joint_calls
               if index % 5 == 0 or elite is None)
    assert result["selected_validation"] == "three_balanced_live_screen_only"
    assert result["frozen_stochastic_iterations"] == 1000
    assert result["frozen_stochastic_world_dps"] == 760.0

def test_p75_cli_preserves_actual_frozen_paid_build(monkeypatch, capsys):
    """A full M1 run must expose the paid winner, not only its opaque hash.

    The P7.5 provider already returns this after the independent freezer;
    the CLI is the artifact read by Work1 after a failed heavy acceptance.
    This is reporting only and cannot turn a FAIL into a PASS.
    """
    from tools import wf_gate as cli

    frozen = {
        "equipment": {"items": [{"id": 11}, {"id": 21, "enchant": 17}]},
        "talentsString": "legal-paid-winner",
        "rotation": {"priorityList": [3, 2, 1]},
    }
    monkeypatch.setattr(cli, "_run_live_gate", lambda *args: {
        "status": "FAIL",
        "reasons": ["P7_5_FROZEN_STOCHASTIC_DPS_BELOW_EXTERNAL_ONLY_FLOOR"],
        "frozen_source_build": frozen,
        "cold_winner_request_sha256": "a" * 64,
        "selected_balanced_request_sha256": "b" * 64,
    })
    rc = cli.main(["--class", "druid", "--level", "60",
                   "--spec", "balance", "--gate", "P7.5"])
    result = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert result["status"] == "FAIL"
    assert result["results"][0]["frozen_source_build"] == frozen
    assert result["results"][0]["cold_winner_request_sha256"] == "a" * 64
    assert result["results"][0]["selected_balanced_request_sha256"] == "b" * 64

def test_paid_p75_talent_apl_crossover_skips_gear_only_finalist_for_paid_apl():
    """A differently geared paid finalist is not an APL/talent donor.

    Regression for the actual P7.5 paid search operator: an unchanged
    talent+rotation transplant used to return True, suppressing the
    independently paid balanced candidate with a genuinely different pair.
    These injected candidates represent paid rows, not a P7 acceptance run.
    """
    player = lambda q: q["raid"]["parties"][0]["players"][0]
    parent = _candidate("reference")
    candidate = copy.deepcopy(parent)
    gear_only = copy.deepcopy(parent)
    player(gear_only)["equipment"]["items"][0]["id"] = 30
    paid_apl = copy.deepcopy(parent)
    player(paid_apl)["talentsString"] = "different-legal-paid-ranks"
    player(paid_apl)["rotation"] = {"priorityList": [3, 1, 2]}
    source = SimpleNamespace(player=player)

    changed = gate._paid_p75_crossover(
        candidate, parent, [(900., {}, "gear-only", gear_only)],
        [(850., "paid-apl", paid_apl)], source, random.Random(23))
    assert changed is True
    assert player(candidate)["talentsString"] == player(paid_apl)["talentsString"]
    assert player(candidate)["rotation"] == player(paid_apl)["rotation"]
    assert player(parent)["talentsString"] == "reference"


def test_paid_p75_talent_apl_crossover_reports_noop_when_only_gear_differs():
    """No real talent/APL donor means no crossover, even with paid gear diversity."""
    player = lambda q: q["raid"]["parties"][0]["players"][0]
    parent = _candidate("reference")
    candidate = copy.deepcopy(parent)
    gear_only = copy.deepcopy(parent)
    player(gear_only)["equipment"]["items"][0]["id"] = 30
    snapshot = copy.deepcopy(candidate)
    changed = gate._paid_p75_crossover(
        candidate, parent, [(900., {}, "gear-only", gear_only)],
        [], SimpleNamespace(player=player), random.Random(23))
    assert changed is False
    assert candidate == snapshot


def test_paid_p75_talent_crossover_uses_fourth_genuine_paid_donor():
    """Three same-axis paid leaders must not mask the fourth real donor."""
    player = lambda q: q["raid"]["parties"][0]["players"][0]
    parent = _candidate("parent")
    child = copy.deepcopy(parent)
    leaders = []
    for i in range(3):
        gear_only = copy.deepcopy(parent)
        player(gear_only)["equipment"]["items"][0]["id"] = 40 + i
        leaders.append((900.0 - i, {}, f"gear-only-{i}", gear_only))
    meaningful = _candidate("different-talents")
    player(meaningful)["rotation"] = {"priorityList": [8, 7, 6]}
    leaders.append((800.0, {}, "paid-distinct-axes", meaningful))
    before_parent = copy.deepcopy(parent)
    before_donor = copy.deepcopy(meaningful)

    assert gate._paid_p75_crossover(
        child, parent, leaders, [], SimpleNamespace(player=player),
        random.Random(17))
    assert player(child)["talentsString"] == "different-talents"
    assert player(child)["rotation"] == {"priorityList": [8, 7, 6]}
    assert parent == before_parent
    assert meaningful == before_donor


def test_paid_p75_gear_crossover_uses_fourth_multi_slot_paid_donor():
    """Three one-slot edits cannot hide a fourth genuinely paid two-slot donor."""
    player = lambda q: q["raid"]["parties"][0]["players"][0]
    parent = _candidate("parent")
    child = copy.deepcopy(parent)
    leaders = []
    for i in range(3):
        one_slot = copy.deepcopy(parent)
        player(one_slot)["equipment"]["items"][0]["id"] = 40 + i
        leaders.append((900.0 - i, {}, f"one-slot-{i}", one_slot))
    meaningful = copy.deepcopy(parent)
    player(meaningful)["equipment"]["items"] = [
        {"id": 71, "enchant": 801}, {"id": 72, "enchant": 802}]
    leaders.append((800.0, {}, "paid-multi-slot", meaningful))
    source = SimpleNamespace(player=player, RejectedGear=ValueError)
    before_parent = copy.deepcopy(parent)
    before_donor = copy.deepcopy(meaningful)

    assert gate._paid_p75_gear_block_crossover(
        child, parent, leaders, [], source, random.Random(17))
    assert player(child)["equipment"] == player(meaningful)["equipment"]
    assert parent == before_parent
    assert meaningful == before_donor


def test_p75_native_control_nonzero_exit_preserves_actionable_binary_diagnostic(
        monkeypatch, tmp_path):
    """Regression: the real source-control subprocess failed with blank stderr.

    This tests failure reporting, not source legality or a gate PASS.
    """
    import importlib.util
    import subprocess
    import pytest

    script = (Path(__file__).resolve().parents[2]
              / "integrations/mythicsim-rust/live_world_probe.py")
    spec = importlib.util.spec_from_file_location("native_control_failure_probe", script)
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)

    request = tmp_path / "paid-source-candidate.json"
    request.write_text(json.dumps({"simOptions": {"iterations": 1}}))

    def rejected_source(command, **kwargs):
        assert command[1] == "sim"
        assert command[command.index("--rng-mode") + 1] == "balanced"
        assert "WOWSIM_RNG_MODE" not in kwargs["env"]
        return subprocess.CompletedProcess(
            command, -9, stdout="native candidate crashed at source prepare", stderr="")

    monkeypatch.setattr(probe.subprocess, "run", rejected_source)
    with pytest.raises(RuntimeError, match="NATIVE_SOURCE_CONTROL_FAILED exit=-9") as err:
        probe.native_source_control(
            tmp_path / "selected-rust", request, 3, rng_mode="balanced")
    assert "request_sha256=" in str(err.value)
    assert "native candidate crashed at source prepare" in str(err.value)


def test_p75_cli_exposes_unique_balanced_screen_receipt(monkeypatch, capsys):
    """CLI reports one paid balanced screen per unique candidate, not reranks."""
    from tools import wf_gate as cli

    monkeypatch.setattr(cli, "_run_live_gate", lambda *args: {
        "status": "FAIL",
        "reasons": ["P7_5_FROZEN_STOCHASTIC_DPS_BELOW_EXTERNAL_ONLY_FLOOR"],
        "cold_balanced_screen_best_dps": 782.0,
        "selected_balanced_screen_dps": 782.0,
        "paid_joint_balanced_finalists": 0,
        "paid_joint_balanced_confirmed": 0,
        "paid_joint_balanced_deep_confirmed": 0,
        "balanced_parent_proposals": 180,
        "selected_validation": "three_balanced_live_screen_only",
        "balanced_finalist_failures": [],
        "frozen_stochastic_iterations": 1000,
        "frozen_stochastic_world_dps": 698.8,
    })
    assert cli.main(["--class", "druid", "--level", "60",
                     "--spec", "balance", "--gate", "P7.5"]) == 1
    result = json.loads(capsys.readouterr().out)
    record = result["results"][0]
    assert result["status"] == "FAIL"
    assert record["cold_balanced_screen_best_dps"] == 782.0
    assert record["selected_balanced_screen_dps"] == 782.0
    assert record["paid_joint_balanced_finalists"] == 0
    assert record["paid_joint_balanced_confirmed"] == 0
    assert record["paid_joint_balanced_deep_confirmed"] == 0
    assert record["balanced_parent_proposals"] == 180
    assert record["selected_validation"] == "three_balanced_live_screen_only"
    assert record["balanced_finalist_failures"] == []
    assert record["frozen_stochastic_iterations"] == 1000
    assert record["frozen_stochastic_world_dps"] == 698.8

def test_p75_cli_exposes_bounded_wf613_operator_diagnostics(monkeypatch, capsys):
    """WF613 telemetry must survive the CLI receipt without affecting verdict."""
    from tools import wf_gate as cli

    monkeypatch.setattr(cli, "_run_live_gate", lambda *args: {
        "status": "FAIL",
        "reasons": ["P7_5_FROZEN_STOCHASTIC_DPS_BELOW_EXTERNAL_ONLY_FLOOR"],
        "search_strategy": "wf613",
        "operator_attempts": {
            "fresh": 5, "gear_large": 2, "talent_rebuild": 1,
            "structural_repair": 3,
        },
        "operator_best_improvements": {
            "fresh": 1, "gear_large": 0, "talent_rebuild": 0,
            "structural_repair": 1,
        },
        "paid_archive_size": 8,
        "best_paid_balanced_world_dps": 733.25,
    })
    assert cli.main(["--class", "druid", "--level", "60",
                     "--spec", "balance", "--gate", "P7.5"]) == 1
    result = json.loads(capsys.readouterr().out)
    record = result["results"][0]
    assert result["status"] == "FAIL"
    assert record["search_strategy"] == "wf613"
    assert record["operator_attempts"] == {
        "fresh": 5, "gear_large": 2, "talent_rebuild": 1,
        "structural_repair": 3,
    }
    assert record["operator_best_improvements"] == {
        "fresh": 1, "gear_large": 0, "talent_rebuild": 0,
        "structural_repair": 1,
    }
    assert record["paid_archive_size"] == 8
    assert record["best_paid_balanced_world_dps"] == 733.25


def test_p75_cli_rejects_malformed_wf613_operator_diagnostics(monkeypatch, capsys):
    """Malformed or unbounded optional telemetry is omitted, not trusted."""
    from tools import wf_gate as cli

    monkeypatch.setattr(cli, "_run_live_gate", lambda *args: {
        "status": "FAIL",
        "reasons": ["P7_5_FROZEN_STOCHASTIC_DPS_BELOW_EXTERNAL_ONLY_FLOOR"],
        "search_strategy": "wf613",
        "operator_attempts": {"fresh": -1},
        "operator_best_improvements": {"fresh": True},
        "paid_archive_size": 49,
        "best_paid_balanced_world_dps": float("inf"),
    })
    assert cli.main(["--class", "druid", "--level", "60",
                     "--spec", "balance", "--gate", "P7.5"]) == 1
    record = json.loads(capsys.readouterr().out)["results"][0]
    assert "operator_attempts" not in record
    assert "operator_best_improvements" not in record
    assert "paid_archive_size" not in record
    assert "best_paid_balanced_world_dps" not in record


def _run_sibling_gate_policy_regression(filename, test_name, monkeypatch, tmp_path):
    """Run the P7.3/P7.4 optimizer-policy fixture in this existing CI suite."""
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path

    path = Path(__file__).with_name(filename)
    spec = spec_from_file_location("_work1_" + filename.removesuffix(".py"), path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    getattr(module, test_name)(monkeypatch, tmp_path)


def test_p73_optimizer_search_is_balanced_before_frozen_stochastic_holdout(
        monkeypatch, tmp_path):
    _run_sibling_gate_policy_regression(
        "test_wf_gate_p7_3_live.py",
        "test_full_p73_freezes_a_unique_talent_winner_before_stochastic_holdout",
        monkeypatch, tmp_path)


def test_p74_optimizer_search_is_balanced_before_frozen_stochastic_holdout(
        monkeypatch, tmp_path):
    _run_sibling_gate_policy_regression(
        "test_wf_gate_p7_4_live.py",
        "test_full_p74_freezes_one_paid_source_gear_winner_for_stochastic_holdout",
        monkeypatch, tmp_path)



def test_p75_unrestricted_search_uses_balanced_until_frozen_holdout():
    source_path = Path(__file__).resolve().parents[2] / "integrations/mythicsim-rust/p75_unrestricted_search.py"
    source = source_path.read_text()
    tree = ast.parse(source)
    expected = {
        "a.screen_iterations": "balanced",
        "140": "balanced",
        "1800": "balanced",
        "a.holdout_iterations": "stochastic",
    }
    observed = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "run" or len(node.args) < 5:
            continue
        if ast.get_source_segment(source, node.args[0]) != "a.binary":
            continue
        iterations = ast.get_source_segment(source, node.args[2])
        observed[iterations] = ast.literal_eval(node.args[4])
    assert observed == expected
    assert "stochastic_fallback" not in source
    assert '"rerank_evidence_schema":"replayable_native_balanced_reranks_v1"' in source
    assert "WOWSIM_RNG_MODE" not in source
    assert '"rng_mode":"balanced"' in source
    assert '"holdout_mode":"stochastic"' in source


def test_p73_p74_stochastic_rng_calls_are_confined_to_frozen_holdout():
    """Static guard: optimizer calls are balanced; stochastic calls sit under complete_search."""
    import ast
    from pathlib import Path

    for filename in ("wf_gate_p7_3_live.py", "wf_gate_p7_4_live.py"):
        source = Path(__file__).parents[2] / "tools" / filename
        module = ast.parse(source.read_text())
        run_live = next(
            node for node in module.body
            if isinstance(node, ast.FunctionDef) and node.name == "run_live"
        )
        modes = []
        def visit(node, parents=()):
            if isinstance(node, ast.Call):
                mode = next((kw.value.value for kw in node.keywords
                             if kw.arg == "rng_mode"
                             and isinstance(kw.value, ast.Constant)), None)
                if mode is not None:
                    modes.append(mode)
                    if mode == "stochastic":
                        assert any(
                            isinstance(parent, ast.If)
                            and isinstance(parent.test, ast.Name)
                            and parent.test.id == "complete_search"
                            for parent in parents
                        )
                    elif mode == "balanced":
                        assert any(isinstance(parent, ast.While) for parent in parents)
            for child in ast.iter_child_nodes(node):
                visit(child, parents + (node,))
        visit(run_live)
        assert modes.count("balanced") == 2
        assert modes.count("stochastic") == 2
        assert len(modes) == 4
