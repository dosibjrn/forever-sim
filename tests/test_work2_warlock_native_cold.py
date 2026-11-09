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

    # Cold proposals still start from Rust-sourced whole APL candidates.
    assert cold.actor(propose(random.Random(5))["source"])["rotation"]["priorityList"] in domain["apl"]


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
        row = {"target_count_requested": targets,
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
