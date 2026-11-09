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
    assert result["cold_300_reached"] is True
    assert result["finalists"]["30s"]["seconds_per_mob"] == 12.0
    assert result["finalists"]["300s"]["seconds_per_mob"] == 8.0
    assert result["p6_comparison"]["status"] == "MEASURED_PAID_100_MOB_FINALISTS"
    assert result["p6_comparison"]["t30_over_t300"] == 1.5
    assert result["p6_comparison"]["within_one_percent"] is False
    assert result["late_paid_screen_count"] == 0
    assert [n for n, _ in calls] == [8, 8, 100, 100]
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
    assert calls == [8, 100]
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
        if targets == 8 and candidate["source"] == late["source"]:
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
    assert [n for n, _ in attempts] == [8, 8, 100]
    assert result["native_search"]["best_score"] == -2.0  # untrusted late best


@pytest.mark.parametrize("targets,complete", [(8, True), (100, True),
                                              (8, False), (100, False)])
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
