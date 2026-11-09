"""Work2 native 30/300 cold-search transport, snapshot and finalist tests.

Mocks only Forever's existing native/gsim invocation and generic scheduler.
No Python gameplay or native source-eligibility oracle.
"""
from __future__ import annotations

import copy
import json
import random
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import wf_warlock_l20_native_cold as cold
from native_options import native_equipment_proposals


def source():
    return {
        "raid": {"parties": [{"players": [{
            "class": "ClassWarlock", "race": "RaceTroll",
            "talentsString": "110-0-0",
            "equipment": {"items": [{"id": 100}, {"id": 200}]},
            "rotation": {"priorityList": [
                {"action": {"castSpell": {"spellId": {"spellId": 686}}}},
                {"action": {"castSpell": {"spellId": {"spellId": 172}}}},
            ]},
        }]}]},
        "encounter": {"targets": [{"level": 20}]},
        "simOptions": {"randomSeed": "42", "iterations": 1},
    }


def options():
    return {
        "class": "warlock", "level": 20, "source_revision": "test-only",
        "spells": [{"spell_id": 686}, {"spell_id": 172}, {"spell_id": 999}],
        "items": [
            {"item_id": 100, "eligibility": "native_eligible",
             "native": {"item_id": 100, "slot": "head"}},
            {"item_id": 101, "eligibility": "native_eligible",
             "native": {"item_id": 101, "slot": "head"}},
            {"item_id": 300, "eligibility": "proficiency_unverified",
             "native": None},
        ],
        "talents": {"points_available": 11, "trees": []},
    }


def test_cold_search_proposes_original_native_request_first_then_challengers():
    """A paid 30s search may try the supplied build before any Rust proposal.

    This schedules an actual native evaluation; it does not grant the baseline
    a score or make it legal in Python. Subsequent proposals remain exploratory.
    """
    reference = source()
    unchanged = copy.deepcopy(reference)
    action = {"action": {"castSpell": {"spellId": {"spellId": 999}}}}
    domain = {
        "gear": {}, "talents": ["101-0-0"], "apl": [[action]],
        "recovery": [(0.7, 0.25)],
    }
    propose, _mutate = cold.candidate_factory(reference, domain)

    first = propose(random.Random(41))
    assert first == {
        "source": unchanged,
        "recovery": {"health_threshold": 0.5, "mana_threshold": 0.1},
    }
    # Neither the submitted candidate nor subsequent exploration may modify
    # the caller's frozen, source-selected reference.
    first["source"]["raid"]["parties"][0]["players"][0]["talentsString"] = "other"
    challengers = [propose(random.Random(seed)) for seed in range(20)]
    assert any(challenger["source"] != unchanged
               or challenger["recovery"] != {
                   "health_threshold": 0.5, "mana_threshold": 0.1,
               } for challenger in challengers)
    assert reference == unchanged


def test_native_life_tap_proposals_have_safe_hp_and_mana_conditions(monkeypatch):
    """Search must not create an unconditional Life Tap from native options."""
    reference = source()
    saved = copy.deepcopy(reference)
    opts = options()
    opts["spells"] = [
        {"spell_id": 1455, "name": "Life Tap"},
        {"spell_id": 686, "name": "Shadow Bolt"},
    ]
    monkeypatch.setattr(
        cold, "proposals_from_native_talents",
        lambda _opts, _source, _seed: iter([{"talents": "110-0-0"}]))
    domain = cold.native_candidate_domain(reference, opts, seed=3)
    life_taps = [
        action for action in domain["apl_actions"]
        if action["action"]["castSpell"]["spellId"]["spellId"] == 1455
    ]
    assert len(life_taps) == 4
    expected = {(20, 50), (20, 70), (40, 50), (40, 70)}
    observed = set()
    for action in life_taps:
        terms = action["action"]["condition"]["and"]["vals"]
        assert len(terms) == 2
        mana, health = (terms[0]["cmp"], terms[1]["cmp"])
        assert mana["lhs"] == {"currentManaPercent": {}}
        assert mana["op"] == "OpLt"
        assert health["lhs"] == {"currentHealthPercent": {}}
        assert health["op"] == "OpGt"
        observed.add((
            int(mana["rhs"]["const"]["val"].rstrip("%")),
            int(health["rhs"]["const"]["val"].rstrip("%")),
        ))
        assert [action] in domain["apl"]  # real reachable standalone candidate
    assert observed == expected
    assert reference == saved
    assert any("condition" not in action["action"]
               for action in domain["apl_actions"]
               if action["action"]["castSpell"]["spellId"]["spellId"] == 686)


def test_cold_proposals_use_single_nonempty_native_recovery_dimension():
    """Sparse Rust options cannot veto paid recovery sampling in Python."""
    reference = source()
    unchanged = copy.deepcopy(reference)
    domain = {"gear": {}, "talents": [], "apl": [], "pets": [],
              "recovery": [(0.7, 0.25)]}
    propose, mutate = cold.candidate_factory(reference, domain)
    first = propose(random.Random(3))
    assert first["source"] == unchanged
    second = propose(random.Random(3))
    assert second["source"] == unchanged
    assert second["recovery"] == {
        "health_threshold": 0.7, "mana_threshold": 0.25}
    assert mutate(first, random.Random(5))["recovery"] == second["recovery"]
    assert reference == unchanged


def test_no_native_mutation_options_preserves_source_without_crashing():
    """No alternative is not a Python invalid-build verdict or IndexError."""
    reference = source()
    saved = copy.deepcopy(reference)
    domain = {"gear": {}, "talents": [], "apl": [], "pets": [],
              "recovery": []}
    propose, mutate = cold.candidate_factory(reference, domain)
    frozen = propose(random.Random(1))
    again = propose(random.Random(2))
    assert again == frozen
    assert mutate(frozen, random.Random(3)) == frozen
    assert reference == saved


def test_native_spell_candidates_can_replace_or_stand_alone_in_apl(monkeypatch):
    """Search may replace the saved filler; only Rust judges executable casts."""
    reference = source()
    original = copy.deepcopy(reference)
    monkeypatch.setattr(
        cold, "proposals_from_native_talents",
        lambda _options, _source, _seed: iter([{"talents": "110-0-0"}]))
    domain = cold.native_candidate_domain(reference, options(), seed=11)
    original_apl = cold.actor(reference)["rotation"]["priorityList"]
    native_spell = {"action": {"castSpell": {"spellId": {"spellId": 999}}}}
    assert [native_spell] in domain["apl"]
    assert [native_spell, original_apl[1]] in domain["apl"]
    assert [original_apl[0], native_spell] in domain["apl"]
    assert [native_spell, *original_apl] in domain["apl"]
    assert reference == original  # proposal generation never mutates saved build

    # The existing generic search factory can actually select the new APL.
    only_apl = {"gear": {}, "talents": ["110-0-0"],
                "apl": [[native_spell]], "recovery": [(0.5, 0.1)]}
    propose, _mutate = cold.candidate_factory(reference, only_apl)
    assert any(
        cold.actor(propose(random.Random(seed))["source"])["rotation"][
            "priorityList"] == [native_spell]
        for seed in range(20)
    )



def test_native_apl_mutations_recombine_two_new_rust_spell_actions(monkeypatch):
    """The paid search can build multi-spell challengers, not only fixed APLs."""
    reference = source()
    original = copy.deepcopy(reference)
    native = options()
    native["spells"].extend([{"spell_id": 998}, {"spell_id": 999}])
    monkeypatch.setattr(
        cold, "proposals_from_native_talents",
        lambda _options, _source, _seed: iter([{"talents": "110-0-0"}]))
    domain = cold.native_candidate_domain(reference, native, seed=5)
    propose, mutate = cold.candidate_factory(reference, domain)

    class AplOnlyRng:
        def __init__(self, spell_id, slot, operation="replace"):
            self.spell_id, self.slot, self.operation = spell_id, slot, operation

        def randint(self, _lo, _hi):
            return 1

        def sample(self, axes, count):
            assert "apl" in axes and count == 1
            return ["apl"]

        def random(self):
            return 0.0

        def choice(self, values):
            if values is domain["apl_actions"]:
                return next(
                    item for item in values
                    if item["action"]["castSpell"]["spellId"]["spellId"] ==
                    self.spell_id)
            assert values == ("replace", "insert")
            return self.operation

        def randrange(self, stop):
            assert self.slot < stop
            return self.slot

    candidate = {"source": copy.deepcopy(reference),
                 "recovery": {"health_threshold": 0.5, "mana_threshold": 0.1}}
    first = mutate(candidate, AplOnlyRng(999, 0))
    combined = mutate(first, AplOnlyRng(998, 1))
    actions = cold.actor(combined["source"])["rotation"]["priorityList"]
    new_ids = [a["action"]["castSpell"]["spellId"]["spellId"] for a in actions]
    assert new_ids == [999, 998]
    assert actions not in domain["apl"]  # unreachable by old whole-APL draws
    assert reference == original
    assert cold.actor(first["source"])["rotation"]["priorityList"] != actions
    inserted = mutate(combined, AplOnlyRng(999, 2, "insert"))
    assert len(cold.actor(inserted["source"])["rotation"]["priorityList"]) == 3

    # The first paid proposal is the frozen source, not a pretend mutation.
    assert cold.actor(propose(random.Random(5))["source"])[
        "rotation"]["priorityList"] == cold.actor(reference)[
        "rotation"]["priorityList"]
    # With an actual APL-only Rust domain, the next cold proposal changes it.
    apl_only = dict(domain, gear={}, talents=[], pets=[], recovery=[])
    propose_apl, _ = cold.candidate_factory(reference, apl_only)
    propose_apl(random.Random(5))  # genuine frozen first paid proposal
    assert cold.actor(propose_apl(random.Random(5))["source"])[
        "rotation"]["priorityList"] in domain["apl"]



def test_native_apl_elite_mutations_reorder_and_remove_without_resetting():
    """An elite can reposition/prune Rust-action proposals in one paid trial."""
    reference = source()
    original = copy.deepcopy(reference)
    native_action = {"action": {"castSpell": {"spellId": {"spellId": 999}}}}
    domain = {
        "gear": {}, "talents": ["110-0-0"],
        "apl": [cold.actor(reference)["rotation"]["priorityList"]],
        "apl_actions": [native_action],
        "recovery": [(0.5, 0.1)],
    }
    _, mutate = cold.candidate_factory(reference, domain)
    candidate = {
        "source": copy.deepcopy(reference),
        "recovery": {"health_threshold": 0.5, "mana_threshold": 0.1},
    }
    rotation = cold.actor(candidate["source"])["rotation"]["priorityList"]
    rotation.insert(1, copy.deepcopy(native_action))

    class AplEditRng:
        def __init__(self, operation, slots):
            self.operation, self.slots, self.random_count = (
                operation, iter(slots), 0)

        def randint(self, _lo, _hi):
            return 1

        def sample(self, axes, count):
            assert "apl" in axes and count == 1
            return ["apl"]

        def random(self):
            self.random_count += 1
            return 0.0 if self.random_count == 1 else 0.99

        def choice(self, values):
            assert values == ("move", "remove")
            return self.operation

        def randrange(self, stop):
            index = next(self.slots)
            assert index < stop
            return index

    moved = mutate(candidate, AplEditRng("move", [1, 0]))
    ids = lambda c: [
        action["action"]["castSpell"]["spellId"]["spellId"]
        for action in cold.actor(c["source"])["rotation"]["priorityList"]
    ]
    assert ids(candidate) == [686, 999, 172]
    assert ids(moved) == [999, 686, 172]
    pruned = mutate(moved, AplEditRng("remove", [1]))
    assert ids(pruned) == [999, 172]
    assert ids(moved) == [999, 686, 172]
    assert reference == original
    # The native candidate is still just a proposed APL, not a Python verdict.
    assert cold.actor(pruned["source"])["rotation"]["priorityList"] != domain["apl"][0]



def test_rust_pet_options_reach_cold_and_elite_native_requests(monkeypatch):
    """Only source enum values enter native protojson; Rust judges eligibility."""
    reference = source()
    player = cold.actor(reference)
    player["warlock"] = {"options": {"classOptions": {
        "summon": 1, "sacrificeSummon": False}}}
    saved = copy.deepcopy(reference)
    native = options()
    native["pets"] = [
        {"summon": "NoSummon", "proto_enum_value": 0,
         "eligibility": "native_prepare_and_combat_required"},
        {"summon": "Felhunter", "proto_enum_value": 4,
         "eligibility": "native_prepare_and_combat_required"},
        {"summon": "Felhunter", "proto_enum_value": 4,
         "eligibility": "native_prepare_and_combat_required"},
    ]
    monkeypatch.setattr(
        cold, "proposals_from_native_talents",
        lambda _options, _source, _seed: iter([{"talents": "110-0-0"}]))
    domain = cold.native_candidate_domain(reference, native, seed=17)
    assert domain["pets"] == [0, 4]  # zero is a real native enum option
    propose, mutate = cold.candidate_factory(reference, domain)

    class PetOnlyRng:
        def randint(self, _lo, _hi):
            return 1

        def sample(self, axes, count):
            assert count == 1 and "pet" in axes
            return ["pet"]

        def choice(self, values):
            assert values is domain["pets"]
            return 4

    candidate = {"source": copy.deepcopy(reference),
                 "recovery": {"health_threshold": 0.5, "mana_threshold": 0.1}}
    changed = mutate(candidate, PetOnlyRng())
    selected = cold.actor(changed["source"])["warlock"]["options"]["classOptions"]
    assert selected == {"summon": 4, "sacrificeSummon": False}
    assert cold.actor(candidate["source"])["warlock"]["options"][
        "classOptions"]["summon"] == 1
    assert reference == saved
    assert changed["recovery"] == candidate["recovery"]
    # Real cold proposals, not only an isolated mutation, explore the pet axis.
    assert any(cold.actor(propose(random.Random(seed))["source"])["warlock"][
        "options"]["classOptions"].get("summon") in (0, 4)
        and cold.actor(propose(random.Random(seed))["source"])["warlock"][
            "options"]["classOptions"].get("summon") != 1
        for seed in range(40))

    no_pets = dict(domain, pets=[])
    without, _ = cold.candidate_factory(reference, no_pets)
    assert cold.actor(without(random.Random(3))["source"])["warlock"] == (
        player["warlock"])


def test_unverified_items_enter_cold_native_candidate_proposals():
    requests = native_equipment_proposals(options(), cold.actor(source())[
        "equipment"]["items"])
    assert {"id": 300} in requests[0]
    assert {"id": 300} in requests[1]
    assert {"id": 101} in requests[0]
    # This checks proposal reachability, never asserts native gear legality.
    domain = {"gear": requests, "talents": ["110-0-0", "101-0-0"],
              "apl": [source()["raid"]["parties"][0]["players"][0][
                  "rotation"]["priorityList"]], "recovery": [(0.5, 0.1)]}
    propose, mutate = cold.candidate_factory(source(), domain)
    candidates = [propose(random.Random(seed)) for seed in range(10)]
    assert any(cold.actor(c["source"])["equipment"]["items"] !=
               cold.actor(source())["equipment"]["items"] for c in candidates)
    assert all(c["recovery"]["health_threshold"] == 0.5 for c in candidates)
    assert mutate(candidates[0], random.Random(7))["source"]["encounter"] == (
        source()["encounter"])


def test_30s_snapshot_cannot_be_replaced_by_a_better_paid_300s_candidate(
    tmp_path, monkeypatch
):
    binary = tmp_path / "binary"
    binary.write_bytes(b"mock binary provenance")
    now = [0.0]
    base = source()
    early = {"source": copy.deepcopy(base),
             "recovery": {"health_threshold": 0.5, "mana_threshold": 0.1}}
    late = copy.deepcopy(early)
    cold.actor(late["source"])["talentsString"] = "101-0-0"
    calls = []

    def mock_chain(_binary, candidate, _out, *, targets, timeout):
        calls.append((targets, cold.identity(candidate)))
        return {"seconds_per_mob": (
            12.0 if candidate["source"] == early["source"] else 8.0),
            "world_targets_killed": targets}

    def mock_search(**kwargs):
        now[0] = 12.0
        kwargs["evaluate"](early, iterations=1, seed=9, rng_mode="balanced")
        now[0] = 65.0
        kwargs["evaluate"](late, iterations=1, seed=9, rng_mode="balanced")
        now[0] = 300.0
        return {"status": "RAN", "best_candidate": late,
                "best_score": -8.0, "elapsed_s": 300.0, "paid_candidates": 2}

    monkeypatch.setattr(cold, "search_native", mock_search)
    monkeypatch.setattr(cold, "native_candidate_domain", lambda *args: {
        "gear": {}, "talents": ["110-0-0"], "apl": [],
        "recovery": [(0.5, 0.1)]})
    result = cold.run_cold(
        base, options(), binary=binary, out=tmp_path / "out", seed=9,
        budget_s=300.0, snapshot_s=30.0, clock=lambda: now[0],
        chain=mock_chain)
    assert result["snapshot_30"]["candidate_sha256"] == cold.identity(early)
    assert result["final_300"]["candidate_sha256"] == cold.identity(late)
    assert result["native_paid_screen_count"] == 2
    assert result["screen_targets"] == 2
    assert result["finalist_targets"] == 100
    assert result["cold_300_reached"] is True
    assert result["finalists"]["30s"]["seconds_per_mob"] == 12.0
    assert result["finalists"]["300s"]["seconds_per_mob"] == 8.0
    assert result["p6_comparison"]["status"] == "MEASURED_PAID_100_MOB_FINALISTS"
    assert result["p6_comparison"]["t30_over_t300"] == 1.5
    assert result["p6_comparison"]["within_one_percent"] is False
    assert result["late_paid_screen_count"] == 0
    assert [n for n, _ in calls] == [2, 2, 100, 100]
    assert result["gate_recorded"] is False
    assert result["p4_p5_p6_pass"] is False
    assert (tmp_path / "out/cold_summary.json").exists()


def test_identical_cold_winners_reuse_one_real_hundred_target_receipt(
    tmp_path, monkeypatch
):
    binary = tmp_path / "binary"
    binary.write_bytes(b"source-native binary")
    now = [0.0]
    build = {"source": source(), "recovery": {
        "health_threshold": 0.5, "mana_threshold": 0.1}}
    calls = []

    def mock_chain(_binary, candidate, _out, *, targets, timeout):
        calls.append(targets)
        return {"seconds_per_mob": 9.0}

    def mock_search(**kwargs):
        now[0] = 10.0
        kwargs["evaluate"](build, iterations=1, seed=2, rng_mode="balanced")
        now[0] = 300.0
        return {"status": "RAN", "best_candidate": build,
                "best_score": -9.0, "elapsed_s": 300.0, "paid_candidates": 1}

    monkeypatch.setattr(cold, "search_native", mock_search)
    monkeypatch.setattr(cold, "native_candidate_domain", lambda *args: {
        "gear": {}, "talents": [], "apl": [],
        "recovery": [(0.5, 0.1)]})
    result = cold.run_cold(
        source(), options(), binary=binary, out=tmp_path / "out",
        clock=lambda: now[0], chain=mock_chain)
    assert calls == [2, 100]
    assert result["p6_comparison"]["within_one_percent"] is True
    assert result["p6_comparison"]["t30_over_t300"] == 1.0
    assert (result["finalists"]["30s"]["candidate_sha256"]
            == result["finalists"]["300s"]["candidate_sha256"])


def test_paid_screen_completed_after_budget_does_not_replace_300s_winner(
    tmp_path, monkeypatch
):
    binary = tmp_path / "binary"
    binary.write_bytes(b"exact engine bytes")
    now = [0.0]
    early = {"source": source(), "recovery": {
        "health_threshold": 0.5, "mana_threshold": 0.1}}
    late = copy.deepcopy(early)
    cold.actor(late["source"])["talentsString"] = "101-0-0"
    attempts = []

    def native_paid(_binary, candidate, _out, *, targets, timeout):
        attempts.append((targets, cold.identity(candidate)))
        # Started at t=299, but a paid native call completes at 301.
        if targets == 2 and candidate["source"] == late["source"]:
            now[0] = 301.0
        return {"seconds_per_mob": (
            2.0 if candidate["source"] == late["source"] else 12.0)}

    def search(**kwargs):
        now[0] = 20.0
        kwargs["evaluate"](early, iterations=1, seed=3, rng_mode="balanced")
        now[0] = 299.0
        kwargs["evaluate"](late, iterations=1, seed=3, rng_mode="balanced")
        now[0] = 302.0
        return {"status": "RAN", "best_candidate": late,
                "best_score": -2.0, "elapsed_s": 302.0, "paid_candidates": 2}

    monkeypatch.setattr(cold, "search_native", search)
    monkeypatch.setattr(cold, "native_candidate_domain", lambda *args: {
        "gear": {}, "talents": [], "apl": [],
        "recovery": [(0.5, 0.1)]})
    result = cold.run_cold(
        source(), options(), binary=binary, out=tmp_path / "out",
        clock=lambda: now[0], chain=native_paid)
    assert result["native_paid_screen_count"] == 1
    assert result["late_paid_screen_count"] == 1
    assert result["distinct_paid_candidates"] == 1
    assert result["snapshot_30"]["candidate_sha256"] == cold.identity(early)
    assert result["final_300"]["candidate_sha256"] == cold.identity(early)
    assert result["finalists"]["30s"]["candidate_sha256"] == cold.identity(early)
    assert result["finalists"]["300s"]["candidate_sha256"] == cold.identity(early)
    assert result["p6_comparison"]["within_one_percent"] is True
    assert [n for n, _ in attempts] == [2, 2, 100]
    assert result["native_search"]["best_score"] == -2.0  # untrusted late best




def test_two_target_screen_finishing_after_snapshot_is_not_backdated(
    tmp_path, monkeypatch
):
    binary = tmp_path / "binary"
    binary.write_bytes(b"selected native engine fixture")
    now = [0.0]
    build = {"source": source(), "recovery": {
        "health_threshold": 0.5, "mana_threshold": 0.1}}
    paid_targets = []

    def paid(_binary, _candidate, _out, *, targets, timeout):
        paid_targets.append(targets)
        if targets == 2:
            # Started before 30s, completed after. This is real paid work,
            # not a P4 snapshot or a fabricated earlier evaluation.
            now[0] = 31.0
        return {"seconds_per_mob": 10.0}

    def search(**kwargs):
        now[0] = 25.0
        kwargs["evaluate"](build, iterations=1, seed=1, rng_mode="balanced")
        now[0] = 300.0
        return {"status": "RAN", "best_candidate": build,
                "best_score": -10.0, "elapsed_s": 300.0,
                "paid_candidates": 1}

    monkeypatch.setattr(cold, "search_native", search)
    monkeypatch.setattr(cold, "native_candidate_domain", lambda *args: {
        "gear": {}, "talents": [], "apl": [], "recovery": [(0.5, 0.1)]})
    result = cold.run_cold(
        source(), options(), binary=binary, out=tmp_path / "out",
        clock=lambda: now[0], chain=paid)
    assert result["screen_targets"] == 2
    assert result["snapshot_30"] is None
    assert result["finalists"]["30s"]["status"] == "NO_PAID_SCREEN_WINNER"
    assert result["final_300"]["candidate_sha256"] == cold.identity(build)
    assert result["finalists"]["300s"]["seconds_per_mob"] == 10.0
    assert result["p6_comparison"] is None
    assert paid_targets == [2, 100]

@pytest.mark.parametrize("targets,complete", [(2, True), (8, True), (100, True),
                                              (2, False), (8, False), (100, False)])
def test_candidate_scorer_uses_existing_native_decisions_and_refuses_unpaid(
    targets, complete, tmp_path, monkeypatch
):
    binary = tmp_path / "engine"
    binary.write_bytes(b"mock")
    observed = []
    def runner(cmd, **_kwargs):
        observed.append(cmd)
        assert "--recovery-policy" in cmd
        assert cmd[cmd.index("--recovery-policy") + 1] == "decisions"
        assert "--variant" in cmd
        assert cmd[cmd.index("--variant") + 1] == "best_apl"
        out = Path(cmd[cmd.index("--out") + 1])
        out.mkdir(parents=True)
        candidate_source = Path(cmd[cmd.index("--source") + 1])
        row = {"target_count_requested": targets,
               "hostile_player_tank_requested": True,
               "native_enemy_attack_prepared": True,
               "original_source_sha256": cold.hashlib.sha256(
                   candidate_source.read_bytes()).hexdigest(),
               "native_binary_sha256": cold.hashlib.sha256(
                   binary.read_bytes()).hexdigest(),
               "recovery_request": {
                   "recovery_policy": "decisions",
                   "health_threshold": 0.7, "mana_threshold": 0.25},
               "status": (f"COMPLETED_{targets}_REAL_NATIVE_GSIM_KILLS"
                          if complete else "INCOMPLETE_UNPAID_NATIVE_RECOVERY"),
               "native_actor_continuity_receipt_complete": complete,
               "native_recovery_clock_accounted": complete,
               "native_recovery_mode": "decisions_food_water" if complete else None,
               "native_2d_paid_objective_eligible": complete and targets == 100,
               "seconds_per_mob": 12.0 if complete else None}
        (out / "summary.json").write_text(json.dumps({"results": [row]}))
        return SimpleNamespace(returncode=0 if complete else 1,
                               stdout="", stderr="")
    monkeypatch.setattr(cold.subprocess, "run", runner)
    build = {"source": source(), "recovery": {
        "health_threshold": 0.7, "mana_threshold": 0.25}}
    if complete:
        receipt = cold.paid_chain(
            binary, build, tmp_path / "attempt", targets=targets, timeout=10.)
        assert receipt["seconds_per_mob"] == 12.
    else:
        with pytest.raises(cold.NativeUnscoredCandidate):
            cold.paid_chain(
                binary, build, tmp_path / "attempt",
                targets=targets, timeout=10.)
    assert len(observed) == 1
    assert (tmp_path / "attempt/candidate.request.json").exists()


def test_one_real_paid_two_target_diagnostic_preserves_wall_and_receipt(tmp_path):
    binary = tmp_path / "engine"
    binary.write_bytes(b"test native binary")
    now = [9.0]
    calls = []

    def native_chain(_binary, candidate, output, *, targets, timeout):
        calls.append((targets, timeout, candidate["recovery"], output))
        now[0] = 34.0
        return {"status": "COMPLETED_2_REAL_NATIVE_GSIM_KILLS",
                "world_targets_killed": 2, "seconds_per_mob": 15.0,
                "native_actor_continuity_receipt_complete": True,
                "native_recovery_clock_accounted": True}

    result = cold.run_paid_two_target_screen(
        source(), binary=binary, out=tmp_path / "measured",
        timeout=90.0, clock=lambda: now[0], chain=native_chain)
    assert calls[0][:3] == (2, 90.0, {
        "health_threshold": 0.5, "mana_threshold": 0.1})
    assert result["elapsed_wall_s"] == 25.0
    assert result["completed_by_30s"] is True
    assert result["native_receipt"]["world_targets_killed"] == 2
    assert result["gate_recorded"] is False
    assert result["p4_p5_p6_pass"] is False
    persisted = json.loads((tmp_path / "measured/two_target_screen_summary.json").read_text())
    assert persisted["status"] == "COMPLETED_2_REAL_NATIVE_GSIM_KILLS"
    assert persisted["elapsed_wall_s"] == 25.0


def test_two_target_diagnostic_refusal_is_not_reported_as_snapshot(tmp_path):
    binary = tmp_path / "engine"
    binary.write_bytes(b"test native binary")
    now = [0.0]

    def refused(_binary, _candidate, _out, *, targets, timeout):
        now[0] = 4.0
        raise cold.NativeUnscoredCandidate(
            "native refused original build",
            raw_response={"status": "INCOMPLETE_UNPAID_NATIVE_RECOVERY",
                          "world_targets_killed": 1})

    result = cold.run_paid_two_target_screen(
        source(), binary=binary, out=tmp_path / "refused",
        clock=lambda: now[0], chain=refused)
    assert result["status"] == "NATIVE_TWO_TARGET_SCREEN_UNSCORED"
    assert result["native_receipt"]["world_targets_killed"] == 1
    assert result["completed_by_30s"] is False
    assert json.loads((tmp_path / "refused/two_target_screen_summary.json").read_text())[
        "gate_recorded"] is False


def test_two_target_diagnostic_late_completion_is_measured_not_backdated(tmp_path):
    binary = tmp_path / "engine"
    binary.write_bytes(b"test native binary")
    now = [4.0]

    def slow_paid(_binary, _candidate, _out, *, targets, timeout):
        now[0] = 36.0
        return {"status": "COMPLETED_2_REAL_NATIVE_GSIM_KILLS",
                "world_targets_killed": 2, "seconds_per_mob": 7.0}

    result = cold.run_paid_two_target_screen(
        source(), binary=binary, out=tmp_path / "late",
        clock=lambda: now[0], chain=slow_paid)
    assert result["status"] == "COMPLETED_2_REAL_NATIVE_GSIM_KILLS"
    assert result["elapsed_wall_s"] == 32.0
    assert result["completed_by_30s"] is False




def test_native_refusal_preserves_its_screen_directory_and_next_paid_receipt(
    tmp_path, monkeypatch
):
    """An unscored source proposal cannot contaminate the next paid screen."""
    binary = tmp_path / "engine"
    binary.write_bytes(b"native engine")
    now = [0.0]
    refused = {"source": source(), "recovery": {
        "health_threshold": 0.5, "mana_threshold": 0.1}}
    completed = copy.deepcopy(refused)
    cold.actor(completed["source"])["talentsString"] = "101-0-0"
    screens = []

    def native_paid(_binary, candidate, out, *, targets, timeout):
        if targets == 2:
            screens.append(out)
            if candidate == refused:
                (out / "world").mkdir(parents=True)
                (out / "world" / "summary.json").write_text(
                    json.dumps({"results": [{"status": "NATIVE_REFUSAL"}]}))
                raise cold.NativeUnscoredCandidate(
                    "Rust refused this candidate",
                    raw_response={"status": "NATIVE_REFUSAL"})
            # The previously refused native receipt must never be reused.
            assert not (out / "world" / "summary.json").exists()
        return {"seconds_per_mob": 9.0}

    def search(**kwargs):
        now[0] = 5.0
        with pytest.raises(cold.NativeUnscoredCandidate):
            kwargs["evaluate"](refused, iterations=1, seed=3,
                               rng_mode="balanced")
        now[0] = 15.0
        kwargs["evaluate"](completed, iterations=1, seed=3,
                           rng_mode="balanced")
        now[0] = 300.0
        return {"status": "RAN", "best_candidate": completed,
                "best_score": -9.0, "elapsed_s": 300.0,
                "paid_candidates": 1, "unscored_candidates": 1}

    monkeypatch.setattr(cold, "search_native", search)
    monkeypatch.setattr(cold, "native_candidate_domain", lambda *args: {
        "gear": {}, "talents": [], "apl": [],
        "recovery": [(0.5, 0.1)]})
    result = cold.run_cold(
        source(), options(), binary=binary, out=tmp_path / "cold",
        clock=lambda: now[0], chain=native_paid)
    assert screens == [tmp_path / "cold/screens/00000",
                       tmp_path / "cold/screens/00001"]
    assert json.loads((screens[0] / "world/summary.json").read_text())[
        "results"][0]["status"] == "NATIVE_REFUSAL"
    assert result["native_screen_attempt_count"] == 2
    assert result["native_screen_unscored_count"] == 1
    failure = result["native_screen_unscored_samples"][0]
    assert failure["candidate_sha256"] == cold.identity(refused)
    assert failure["native_receipt_path"] == "screens/00000/world/summary.json"
    assert failure["native_response_status"] == "NATIVE_REFUSAL"
    assert result["native_paid_screen_count"] == 1
    assert result["snapshot_30"]["candidate_sha256"] == cold.identity(completed)
    assert result["finalists"]["30s"]["status"] == (
        "COMPLETED_100_REAL_NATIVE_GSIM_KILLS")
    assert result["p4_p5_p6_pass"] is False



def test_paid_chain_does_not_consume_previous_successful_run_receipt(
    tmp_path, monkeypatch
):
    """An old completed 100-mob receipt cannot stand in for a new paid run."""
    binary = tmp_path / "engine"
    binary.write_bytes(b"engine-current")
    out = tmp_path / "retry"
    world = out / "world"
    world.mkdir(parents=True)
    summary = world / "summary.json"
    summary.write_text(json.dumps({"results": [{
        "status": "COMPLETED_100_REAL_NATIVE_GSIM_KILLS",
        "seconds_per_mob": 1.0}]}))
    monkeypatch.setattr(
        cold.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout="", stderr=""))
    candidate = {"source": source(), "recovery": {
        "health_threshold": 0.5, "mana_threshold": 0.1}}
    with pytest.raises(RuntimeError, match="did not emit a structured receipt"):
        cold.paid_chain(binary, candidate, out, targets=100, timeout=10.0)
    assert not summary.exists()


@pytest.mark.parametrize("wrong_field", [
    "original_source_sha256", "native_binary_sha256", "recovery_request"
])
def test_paid_chain_refuses_mismatched_native_paid_provenance(
    tmp_path, monkeypatch, wrong_field
):
    """Only exact current source, engine and paid-policy receipts are scored."""
    binary = tmp_path / "engine"
    binary.write_bytes(b"native-engine-current")
    candidate = {"source": source(), "recovery": {
        "health_threshold": 0.7, "mana_threshold": 0.25}}
    def runner(cmd, **_kwargs):
        candidate_source = Path(cmd[cmd.index("--source") + 1])
        out = Path(cmd[cmd.index("--out") + 1])
        out.mkdir(parents=True, exist_ok=True)
        row = {
            "target_count_requested": 100,
            "status": "COMPLETED_100_REAL_NATIVE_GSIM_KILLS",
            "native_actor_continuity_receipt_complete": True,
            "native_recovery_clock_accounted": True,
            "native_recovery_mode": "decisions_food_water",
            "native_2d_paid_objective_eligible": True,
            "seconds_per_mob": 11.0,
            "original_source_sha256": cold.hashlib.sha256(
                candidate_source.read_bytes()).hexdigest(),
            "native_binary_sha256": cold.hashlib.sha256(
                binary.read_bytes()).hexdigest(),
            "recovery_request": {
                "recovery_policy": "decisions",
                "health_threshold": 0.7, "mana_threshold": 0.25},
        }
        row[wrong_field] = "from-an-incompatible-run"
        (out / "summary.json").write_text(json.dumps({"results": [row]}))
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(cold.subprocess, "run", runner)
    with pytest.raises(cold.NativeUnscoredCandidate, match="provenance") as exc:
        cold.paid_chain(binary, candidate, tmp_path / "candidate",
                        targets=100, timeout=10.0)
    assert exc.value.raw_response[wrong_field] == "from-an-incompatible-run"



def test_hundred_target_paid_baseline_runs_once_without_cold_search(
    tmp_path, monkeypatch
):
    binary = tmp_path / "engine"
    binary.write_bytes(b"selected native binary")
    reference = source()
    saved = copy.deepcopy(reference)
    now = [4.0]
    calls = []
    def native_paid(_binary, candidate, out, *, targets, timeout):
        calls.append((targets, timeout, copy.deepcopy(candidate), out))
        now[0] = 17.0
        return {
            "status": "COMPLETED_100_REAL_NATIVE_GSIM_KILLS",
            "world_targets_killed": 100,
            "seconds_per_mob": 19.5,
            "native_actor_continuity_receipt_complete": True,
            "native_recovery_clock_accounted": True,
        }

    report = cold.run_paid_hundred_target_baseline(
        reference, binary=binary, out=tmp_path / "baseline",
        health_threshold=0.7, mana_threshold=0.25,
        timeout=1200.0, clock=lambda: now[0], chain=native_paid)
    assert len(calls) == 1
    assert calls[0][0:2] == (100, 1200.0)
    assert calls[0][2]["recovery"] == {
        "health_threshold": 0.7, "mana_threshold": 0.25}
    assert calls[0][3] == tmp_path / "baseline" / "paid"
    assert reference == saved
    assert report["elapsed_wall_s"] == 13.0
    assert report["seconds_per_mob"] == 19.5
    assert report["status"] == "COMPLETED_100_REAL_NATIVE_GSIM_KILLS"
    assert report["native_receipt"]["world_targets_killed"] == 100
    assert report["gate_recorded"] is False
    assert report["p4_p5_p6_pass"] is False
    saved_report = json.loads(
        (tmp_path / "baseline/hundred_target_baseline_summary.json").read_text())
    assert saved_report["seconds_per_mob"] == 19.5


def test_hundred_target_paid_baseline_preserves_native_refusal(tmp_path):
    binary = tmp_path / "engine"
    binary.write_bytes(b"selected native binary")
    def refused(_binary, _candidate, _out, *, targets, timeout):
        assert targets == 100
        raise cold.NativeUnscoredCandidate(
            "native refused after 43 kills",
            raw_response={"status": "INCOMPLETE_UNPAID_NATIVE_RECOVERY",
                          "world_targets_killed": 43})
    result = cold.run_paid_hundred_target_baseline(
        source(), binary=binary, out=tmp_path / "refusal", chain=refused)
    assert result["status"] == "NATIVE_HUNDRED_TARGET_BASELINE_UNSCORED"
    assert result["seconds_per_mob"] is None
    assert result["native_receipt"]["world_targets_killed"] == 43
    assert result["p4_p5_p6_pass"] is False


def test_hundred_target_paid_baseline_rejects_invalid_budget_before_native(
    tmp_path
):
    binary = tmp_path / "engine"
    binary.write_bytes(b"selected native binary")
    def should_not_run(*_args, **_kwargs):
        raise AssertionError("native must not run")
    with pytest.raises(ValueError, match="INVALID_PAID_BASELINE_ARGUMENT"):
        cold.run_paid_hundred_target_baseline(
            source(), binary=binary, out=tmp_path / "invalid",
            health_threshold=float("nan"), chain=should_not_run)


def test_hundred_target_baseline_cli_bypasses_cold_native_options(
    tmp_path, monkeypatch, capsys
):
    binary = tmp_path / "engine"
    binary.write_bytes(b"selected native binary")
    request = tmp_path / "request.json"
    request.write_text(json.dumps(source()))
    def no_options(*_args):
        raise AssertionError("frozen baseline must not start cold options")
    monkeypatch.setattr(cold, "query_native_options", no_options)
    called = []
    def baseline(reference, *, binary, out, timeout, health_threshold,
                 mana_threshold):
        called.append((binary, out, timeout, health_threshold, mana_threshold))
        return {"status": "COMPLETED_100_REAL_NATIVE_GSIM_KILLS",
                "elapsed_wall_s": 3.5, "seconds_per_mob": 12.0}
    monkeypatch.setattr(cold, "run_paid_hundred_target_baseline", baseline)
    monkeypatch.setattr(cold.sys, "argv", [
        "wf_warlock_l20_native_cold.py", "--binary", str(binary),
        "--source", str(request), "--out", str(tmp_path / "baseline"),
        "--hundred-target-baseline", "--baseline-timeout", "900",
        "--health-threshold", "0.7", "--mana-threshold", "0.25",
    ])
    cold.main()
    assert called == [(binary, tmp_path / "baseline", 900.0, 0.7, 0.25)]
    assert "WARLOCK_NATIVE_HUNDRED_TARGET_PAID_BASELINE" in capsys.readouterr().out

def test_cold_finalist_partial_native_refusal_keeps_real_100_target_evidence(
    tmp_path, monkeypatch
):
    """An incomplete hostile replay stays unscored but remains diagnosable."""
    binary = tmp_path / "engine"
    binary.write_bytes(b"exact native engine")
    now = [0.0]
    first = {"source": source(), "recovery": {
        "health_threshold": 0.5, "mana_threshold": 0.1}}
    second = copy.deepcopy(first)
    cold.actor(second["source"])["talentsString"] = "101-0-0"
    refused_receipt = {
        "status": "INCOMPLETE_OR_NATIVE_REFUSAL",
        "target_count_requested": 100,
        "killed": 43,
        "native_recovery_clock_accounted": True,
        "native_recovery_seconds": 74.0,
        "native_health_damage_proven": True,
    }
    calls = []

    def native_paid(_binary, candidate, out, *, targets, timeout):
        calls.append((targets, cold.identity(candidate)))
        if targets == 2:
            return {"seconds_per_mob": 12.0 if candidate == first else 8.0}
        if candidate == first:
            (out / "world").mkdir(parents=True, exist_ok=True)
            (out / "world" / "summary.json").write_text(
                json.dumps({"results": [refused_receipt]}))
            raise cold.NativeUnscoredCandidate(
                "native chain stopped after 43/100 ACKs",
                raw_response=copy.deepcopy(refused_receipt))
        return {"seconds_per_mob": 9.0, "world_targets_killed": 100}

    def search(**kwargs):
        now[0] = 10.0
        kwargs["evaluate"](first, iterations=1, seed=4, rng_mode="balanced")
        now[0] = 90.0
        kwargs["evaluate"](second, iterations=1, seed=4, rng_mode="balanced")
        now[0] = 300.0
        return {"status": "RAN", "best_candidate": second,
                "best_score": -8.0, "elapsed_s": 300.0, "paid_candidates": 2}

    monkeypatch.setattr(cold, "search_native", search)
    monkeypatch.setattr(cold, "native_candidate_domain", lambda *args: {
        "gear": {}, "talents": [], "apl": [],
        "recovery": [(0.5, 0.1)]})
    result = cold.run_cold(
        source(), options(), binary=binary, out=tmp_path / "cold",
        clock=lambda: now[0], chain=native_paid)
    assert [count for count, _ in calls] == [2, 2, 100, 100]
    rejected = result["finalists"]["30s"]
    assert rejected["status"] == "INCOMPLETE_100_NATIVE_FINALIST"
    assert rejected["native_response_status"] == "INCOMPLETE_OR_NATIVE_REFUSAL"
    assert rejected["native_receipt"] == refused_receipt
    assert rejected["native_receipt"]["killed"] == 43
    assert rejected["native_receipt_path"] == (
        "finalists/" + cold.identity(first) + "/world/summary.json")
    assert "seconds_per_mob" not in rejected
    assert result["finalists"]["300s"]["seconds_per_mob"] == 9.0
    assert result["p6_comparison"] is None
    assert result["gate_recorded"] is False
    assert result["p4_p5_p6_pass"] is False
    persisted = json.loads((tmp_path / "cold/cold_summary.json").read_text())
    assert persisted["finalists"]["30s"]["native_receipt"] == refused_receipt
    assert persisted["p6_comparison"] is None


def test_paid_world_scenario_preserves_explicit_hostile_source_parameters():
    """The changed-hostile 100-target native request must retain attack inputs."""
    from tools import wf_warlock_l20_100mob as paid_world

    reference = source()
    cold.actor(reference)["equipment"]["items"] = [{"id": 100}] * 17
    target = reference["encounter"]["targets"][0]
    target.update({
        "name": "Explicit attacking source L20 target",
        "stats": [0] * 40,
        "swingSpeed": 0.75,
        "minBaseDamage": 4,
        "tankIndex": 0,
    })
    target["stats"][32] = 765.0  # source-provided HP, not the generic proxy
    before = copy.deepcopy(reference)
    scenario = paid_world.create_scenario(reference, variant="best_apl")
    native_target = scenario["encounter"]["targets"][0]
    assert native_target["name"] == "Explicit attacking source L20 target"
    assert native_target["swingSpeed"] == 0.75
    assert native_target["minBaseDamage"] == 4
    assert native_target["stats"][32] == 765.0
    assert native_target["tankIndex"] == 0
    assert scenario["encounter"]["duration"] == 30
    assert reference == before  # no source mutation across paid candidates


def test_paid_world_scenario_uses_proxy_attacks_only_when_not_supplied():
    """Existing stationary fixture with absent attack fields retains defaults."""
    from tools import wf_warlock_l20_100mob as paid_world

    reference = source()
    cold.actor(reference)["equipment"]["items"] = [{"id": 100}] * 17
    reference["encounter"]["targets"][0]["stats"] = [0] * 40
    scenario = paid_world.create_scenario(reference, variant="best_apl")
    native_target = scenario["encounter"]["targets"][0]
    assert native_target["name"] == "CMaNGOS Classic-proxy ordinary L20 enemy"
    assert native_target["swingSpeed"] == 2.0
    assert native_target["minBaseDamage"] == 20.0
    assert native_target["stats"][32] == paid_world.representative_hp(20)
    assert reference["encounter"]["targets"][0]["stats"][32] == 0
    assert "swingSpeed" not in reference["encounter"]["targets"][0]



@pytest.mark.parametrize("source_hp,observed_hp,scorable", [
    (765.0, 765.0, True),  # exact source-selected hostile target
    (765.0, 484.0, False),  # old Classic proxy must not be scored as hostile
    (765.0, None, False),  # missing world HP cannot prove scenario identity
    (765.0, float("nan"), False),
    (484.0, 484.0, True),  # unchanged legacy proxy remains supported
])
def test_paid_world_receipt_requires_actual_world_hp_match_source(
    source_hp, observed_hp, scorable
):
    """Classify the Forever-owned native/2D HP transport, not Rust mechanics."""
    from tools import wf_warlock_l20_100mob as paid_world

    receipt = {
        "world_targets_killed": 100,
        "world_seconds_per_target_paid_recovery": 12.0,
        "world_target_hp": observed_hp,
        "paid_recovery": False,
        "native_recovery_clock_accounted": True,
        "native_recovery_mode": "decisions_food_water",
        "native_food_water_observed": True,
        "native_food_seconds_total": 0,
        "native_water_seconds_total": 0,
        "native_food_health_gain_total": 0,
        "native_water_mana_gain_total": 0,
    }
    status, completed = paid_world.classify_native_chain(
        receipt, 100, recovery_policy="decisions", expected_world_hp=source_hp)
    assert completed is scorable
    assert status == ("COMPLETED_100_REAL_NATIVE_GSIM_KILLS" if scorable
                      else "NATIVE_WORLD_TARGET_HEALTH_MISMATCH")


def test_paid_world_refusal_receipt_identifies_actual_hostile_target(
    tmp_path, monkeypatch
):
    """Even on a native refusal, the saved request must not claim proxy HP/damage."""
    from tools import wf_warlock_l20_100mob as paid_world

    reference = source()
    cold.actor(reference)["equipment"]["items"] = [{"id": 100}] * 17
    target = reference["encounter"]["targets"][0]
    target.update({
        "name": "Source-selected hostile",
        "stats": [0] * 40,
        "minBaseDamage": 4,
        "swingSpeed": 0.75,
    })
    target["stats"][32] = 765
    request = tmp_path / "hostile.json"
    request.write_text(json.dumps(reference))
    binary = tmp_path / "native-engine"
    binary.write_bytes(b"native selected source test stub")
    out = tmp_path / "paid"

    def native_prepare(command, **_kwargs):
        prepared_path = Path(command[command.index("--outfile") + 1])
        prepared_path.write_text(json.dumps({"player": {
            "class": "ClassWarlock", "race": "RaceTroll", "level": 20,
            "stats": {"Health": 1894, "Mana": 2173},
        }}))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    world_requests = []
    def native_refusal(*_args, **kwargs):
        world_requests.append(kwargs)
        raise RuntimeError("simulated native transport refusal")

    monkeypatch.setattr(paid_world.subprocess, "run", native_prepare)
    monkeypatch.setattr(paid_world, "native_world_chain", native_refusal)
    monkeypatch.setattr(paid_world.sys, "argv", [
        "wf_warlock_l20_100mob.py", "--binary", str(binary),
        "--source", str(request), "--out", str(out),
        "--variant", "best_apl", "--targets", "100",
        "--recovery-policy", "decisions",
    ])
    with pytest.raises(SystemExit, match="No variant completed"):
        paid_world.main()

    receipt = json.loads((out / "summary.json").read_text())["results"][0]
    submitted = json.loads(
        (out / "best_apl/source_request.json").read_text()
    )["encounter"]["targets"][0]
    assert world_requests[0]["mob_health"] == 765
    assert world_requests[0]["classic_mob_level"] is None
    assert submitted["stats"][32] == receipt["mob_hp_native_scenario"] == 765
    assert receipt["mob_hp_classic_proxy"] is None
    assert receipt["scenario_min_base_damage"] == 4
    assert receipt["scenario_swing_speed"] == 0.75
    assert receipt["scenario_target_name"] == "Source-selected hostile"
    assert receipt["status"] == "INCOMPLETE_OR_NATIVE_REFUSAL"
    assert receipt["native_2d_paid_objective_eligible"] is False
    assert reference["encounter"]["targets"][0]["stats"][32] == 765


@pytest.mark.parametrize("targets", [2, 100])
def test_cold_paid_chain_scores_complete_zero_hit_route_without_extra_gate(
    tmp_path, monkeypatch, targets
):
    """Avoiding all player damage is not grounds to refuse a paid mob route.

    The native world still owns whether 100 different kills, resources, and
    paid recovery really completed. This test only checks Forever transport.
    """
    binary = tmp_path / "engine"
    binary.write_bytes(b"native Warlock engine")
    candidate = {"source": source(), "recovery": {
        "health_threshold": 0.5, "mana_threshold": 0.1}}
    submitted = []

    def native_runner(command, **_kwargs):
        submitted.append(command)
        assert "--require-native-health-damage" not in command
        source_path = Path(command[command.index("--source") + 1])
        out = Path(command[command.index("--out") + 1])
        out.mkdir(parents=True, exist_ok=True)
        row = {
            "target_count_requested": targets,
            "hostile_player_tank_requested": True,
            "native_enemy_attack_prepared": True,
            "original_source_sha256": cold.hashlib.sha256(
                source_path.read_bytes()).hexdigest(),
            "native_binary_sha256": cold.hashlib.sha256(
                binary.read_bytes()).hexdigest(),
            "recovery_request": {"recovery_policy": "decisions",
                                 "health_threshold": 0.5,
                                 "mana_threshold": 0.1},
            "status": f"COMPLETED_{targets}_REAL_NATIVE_GSIM_KILLS",
            "native_actor_continuity_receipt_complete": True,
            "native_recovery_clock_accounted": True,
            "native_recovery_mode": "decisions_food_water",
            "native_2d_paid_objective_eligible": targets == 100,
            "seconds_per_mob": 12.0,
            "native_health_damage": {"observed": True, "damage_taken": 0.0,
                                     "damage_events": 0},
        }
        (out / "summary.json").write_text(json.dumps({"results": [row]}))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cold.subprocess, "run", native_runner)
    receipt = cold.paid_chain(binary, candidate, tmp_path / "attempt",
                              targets=targets, timeout=30.0)
    assert receipt["seconds_per_mob"] == 12.0
    assert receipt["native_health_damage"]["damage_events"] == 0
    assert receipt["native_2d_paid_objective_eligible"] is (targets == 100)
    assert len(submitted) == 1


def test_real_native_domain_with_no_changed_source_options_is_recovery_only(
    monkeypatch,
):
    """The production domain builder must not disguise the saved APL/talents
    as native challenger axes when Rust supplies no distinct alternative.
    Recovery remains a genuine paid candidate policy change.
    """
    reference = source()
    saved = copy.deepcopy(reference)
    player = cold.actor(reference)
    player["rotation"]["priorityList"] = player["rotation"]["priorityList"][:1]
    saved = copy.deepcopy(reference)
    native = options()
    native["items"] = []
    native["spells"] = []
    native["pets"] = []
    monkeypatch.setattr(
        cold, "proposals_from_native_talents",
        lambda _options, _source, _seed: iter([
            {"talents": player["talentsString"]},
            {"talents": player["talentsString"]},
        ]),
    )
    domain = cold.native_candidate_domain(reference, native, seed=19)
    assert domain["gear"] == {}
    assert domain["talents"] == []
    assert domain["apl"] == []
    assert domain["apl_actions"] == []
    assert domain["pets"] == []

    propose, mutate = cold.candidate_factory(reference, domain)
    baseline = propose(random.Random(7))
    assert baseline["source"] == saved
    challenger = propose(random.Random(7))
    assert challenger["source"] == saved
    assert challenger["recovery"] != baseline["recovery"]
    assert mutate(baseline, random.Random(7))["recovery"] != baseline["recovery"]
    assert reference == saved


def test_distinct_native_talent_proposal_survives_source_baseline_filter(
    monkeypatch,
):
    reference = source()
    native = options()
    native["items"] = []
    native["spells"] = []
    monkeypatch.setattr(
        cold, "proposals_from_native_talents",
        lambda _options, _source, _seed: iter([
            {"talents": "110-0-0"},
            {"talents": "101-0-0"},
            {"talents": "101-0-0"},
        ]),
    )
    domain = cold.native_candidate_domain(reference, native, seed=11)
    assert domain["talents"] == ["101-0-0"]
    assert cold.actor(reference)["talentsString"] == "110-0-0"


def test_unseeded_native_fixture_can_propose_gear_without_a_saved_winner(monkeypatch):
    """Empty native equipment must not collapse the cold gear axis to zero."""
    reference = source()
    player = cold.actor(reference)
    player["talentsString"] = "0-0-0"
    player["equipment"]["items"] = []
    player["rotation"]["priorityList"] = [
        {"action": {"castSpell": {"spellId": {"spellId": 686}}}}
    ]
    frozen = copy.deepcopy(reference)
    monkeypatch.setattr(cold, "proposals_from_native_talents",
                        lambda *_args: iter(()))
    domain = cold.native_candidate_domain(reference, options(), seed=9)
    assert domain["gear"] == {}
    assert {row["id"] for row in domain["gear_insertions"]} == {
        100, 101, 300,
    }  # including Rust-source proficiency-unverified proposals

    # No saved gear or talent winner is injected as the first paid candidate.
    only_native_gear = {
        "gear": {}, "gear_insertions": domain["gear_insertions"],
        "talents": [], "apl": [], "pets": [], "recovery": [],
    }
    propose, mutate = cold.candidate_factory(reference, only_native_gear)
    first = propose(random.Random(4))
    second = propose(random.Random(4))
    assert first["source"] == frozen
    assert second["source"] != frozen
    assert len(cold.actor(second["source"])["equipment"]["items"]) == 1
    assert cold.actor(second["source"])["equipment"]["items"][0] in (
        domain["gear_insertions"])
    # Elite recombination can add a second native item; Rust decides legality.
    combined = None
    for seed in range(40):
        challenger = mutate(second, random.Random(seed))
        if len(cold.actor(challenger["source"])["equipment"]["items"]) == 2:
            combined = challenger
            break
    assert combined is not None
    assert reference == frozen

def test_cold_workflow_inputs_are_unoptimized_native_actor_not_saved_winner():
    """The paid Actions producer must not bootstrap from prior best-paid gear."""
    workflow = (cold.ROOT / ".github/workflows/native-session-ack-regressions.yml"
                ).read_text()
    job = workflow.split("  warlock-l20-cold-30-300:", 1)[1]
    assert "--source ../engine/fixtures/warlock-l20-troll-native.request.json" in job
    assert "warlock-l20-troll-best-paid.request.json" not in job
