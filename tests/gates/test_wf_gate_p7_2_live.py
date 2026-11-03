"""P7.2 cold APL mutation contract; no fake gate acceptance or saved-run PASS."""
import copy
import json
import random
from types import SimpleNamespace

import pytest
from tools import wf_gate_p7_2_live as gate


def _request():
    return {
        "raid": {"parties": [{"players": [{
            "equipment": {"items": [{"id": 14}]},
            "talentsString": "source-legal",
            "rotation": {"priorityList": [
                {"action": {"castSpell": {"spellId": {"spellId": 1}}}},
                {"action": {"castSpell": {"spellId": {"spellId": 2}}}},
                {"action": {"castSpell": {"spellId": {"spellId": 3}}}},
            ]},
        }]}]}
    }


def test_cold_apl_keeps_actual_gear_talents_and_saved_request_unmodified():
    base = _request()
    original = copy.deepcopy(base)
    def mutation(actions, source_actions, rng, cold):
        assert actions is None and cold
        return list(reversed(source_actions))
    result = gate._cold_apl(base, random.Random(3),
                            SimpleNamespace(mutate_apl=mutation))
    assert result != base
    assert base == original
    assert result["raid"]["parties"][0]["players"][0]["equipment"] == (
        base["raid"]["parties"][0]["players"][0]["equipment"])
    assert result["raid"]["parties"][0]["players"][0]["talentsString"] == (
        base["raid"]["parties"][0]["players"][0]["talentsString"])


def test_independently_rediscovered_reference_apl_remains_eligible():
    base = _request()
    candidate = gate._cold_apl(base, random.Random(3),
                               SimpleNamespace(mutate_apl=lambda a, s, r, cold: copy.deepcopy(s)))
    assert candidate == base
    assert candidate is not base


def test_p72_paid_parent_uses_balanced_archive_and_keeps_cold_restarts():
    best_request = _request()
    elite_request = copy.deepcopy(best_request)
    finalist_request = copy.deepcopy(best_request)
    elite_request["raid"]["parties"][0]["players"][0]["talentsString"] = "paid-elite"
    finalist_request["raid"]["parties"][0]["players"][0]["talentsString"] = "paid-finalist"
    best = (900.0, {}, "screen-best", best_request)
    elites = [(890.0, "elite-a", best_request),
              (880.0, "elite-b", elite_request)]
    finalists = [(910.0, {}, "finalist-a", finalist_request, 900.0)]

    class PickLast:
        @staticmethod
        def choice(rows):
            return rows[-1]

    assert gate._paid_p72_parent(
        best, finalists, 5, PickLast(), balanced_elites=elites) is None
    assert gate._paid_p72_parent(
        best, [], 3, PickLast(), balanced_elites=elites) is elite_request
    assert gate._paid_p72_parent(
        best, finalists, 4, PickLast(), balanced_elites=[]) is finalist_request


def test_p72_paid_finalist_only_calls_balanced_native_and_world(monkeypatch, tmp_path):
    request = _request()
    observed = []

    def native(binary, path, n, *, rng_mode):
        saved = json.loads(path.read_text())
        observed.append(("native", n, rng_mode, saved["simOptions"]["randomSeed"]))
        return {"native_dps": 750.0}

    def world(binary, path, distance, iterations, *, rng_mode):
        saved = json.loads(path.read_text())
        observed.append(("world", iterations, rng_mode,
                         saved["simOptions"]["randomSeed"]))
        return {"world_mean_dps": 750.0, "iterations_done": iterations,
                "native_damage_events": 9, "native_world_ticks": 15}

    monkeypatch.setattr(gate, "_source_native_world_parity",
                        lambda *args, **kwargs: None)
    production = SimpleNamespace(native_source_control=native, run=world)
    score, live = gate._paid_p72_balanced_finalist(
        production, tmp_path / "selected-engine", request, 15,
        seeds=("101", "202"), stage="finalist")
    assert score == 750.0
    assert live["iterations_done"] == 3
    assert observed == [
        ("native", 3, "balanced", "101"),
        ("world", 3, "balanced", "101"),
        ("native", 3, "balanced", "202"),
        ("world", 3, "balanced", "202"),
    ]


def test_p72_freeze_prefers_deepest_paid_balanced_finalist():
    screen = _request()
    a, b = copy.deepcopy(screen), copy.deepcopy(screen)
    a["raid"]["parties"][0]["players"][0]["talentsString"] = "A"
    b["raid"]["parties"][0]["players"][0]["talentsString"] = "B"
    screen_best = (999.0, {"screen": True}, "screen", screen)
    finalists = [
        (730.0, {"live": "A"}, "a", a, 990.0),
        (720.0, {"live": "B"}, "b", b, 980.0),
    ]
    frozen = gate._freeze_paid_p72_balanced_winner(
        screen_best, finalists, confirmed={"b"}, deep_confirmed={"a"})
    assert frozen[0] == 730.0
    assert frozen[2] == "a"
    assert frozen[3]["raid"]["parties"][0]["players"][0]["talentsString"] == "A"
    assert frozen[4] == 990.0
    assert frozen[5] == "paid_6x3_balanced_live_native_deep_confirmed_finalist"


def test_wrong_checkpoint_refuses_before_any_native_run(tmp_path):
    report = gate.run_live(tmp_path, "priest", 60, spec="holy")
    assert report["status"] == "BLOCKED"
    assert report["reasons"] == ["P7_2_PINNED_REFERENCE_NOT_SELECTED_FOR_CHECKPOINT"]


def test_p72_rejects_equal_native_world_dps_if_fight_duration_differs(monkeypatch, tmp_path):
    """A visually correct mean DPS cannot hide source timeline divergence."""
    import json
    from pathlib import Path
    from tools import wf_gate_p7_2_live as p72
    baseline = _request()
    player = baseline["raid"]["parties"][0]["players"][0]
    player.update({"class": "ClassDruid", "distanceFromTarget": 15})
    monkeypatch.setattr(
        p72, "_pinned_source_runtime",
        lambda *args: (baseline, {"reference_dps": 728.19}, tmp_path / "binary"))
    source = SimpleNamespace(mutate_apl=lambda a, actions, rng, cold: list(reversed(actions)))
    producer = SimpleNamespace(
        native_source_control=lambda binary, request, n, *, rng_mode: {
            "iterations": n, "first_duration_s": 120.0, "native_dps": 730.0},
        run=lambda binary, request, distance, iterations, *, rng_mode: {
            "iterations_done": iterations,
            "per_iteration": [
                {"iteration_index": i, "duration_s": 119.0,
                 "world_dps": 730.0, "world_applied_damage": 86870.0}
                for i in range(iterations)],
            "sampled_duration_s": 119.0,
            "native_dps": 730.0, "world_mean_dps": 730.0,
            "native_damage_events": 10, "native_world_ticks": 20})
    monkeypatch.setattr(p72, "_source_module",
                        lambda path, name: source if "apl_mutation" in str(path) else producer)
    report = p72.run_live(tmp_path, "druid", 60, spec="balance")
    assert report["status"] == "FAIL"
    assert report["reasons"] == [
        "P7_2_NO_EXECUTED_SOURCE_LEGAL_COLD_APL_WORLD_CANDIDATE"]
    assert any("FIRST_DURATION_DIVERGED" in error
               for error in report["cold_candidate_failures"])
    assert "winner_live_dps" not in report

def test_full_p72_confirms_paid_balanced_finalists_before_stochastic_holdout(
        monkeypatch, tmp_path):
    """The screen leader cannot bypass paid Balanced confirmation; holdout is last."""
    from tools import wf_gate_p7_2_live as p72

    base = _request()
    base["raid"]["parties"][0]["players"][0].update({
        "class": "ClassDruid", "distanceFromTarget": 15})
    calls = []
    clock = [0.0]
    perf = [0.0]
    screen_world = [0]
    finalist_world = [0]
    confirmation_world = [0]

    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "1")
    monkeypatch.setattr(p72.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(p72.time, "perf_counter", lambda: perf[0])
    monkeypatch.setattr(p72.time, "sleep",
                        lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(
        p72, "_pinned_source_runtime",
        lambda *args: (base, {"reference_dps": 728.19,
                              "selected_engine_revision": "test-pin"},
                       tmp_path / "binary"))
    monkeypatch.setattr(p72, "_source_native_world_parity",
                        lambda *args, **kwargs: None)
    monkeypatch.setattr(
        p72, "_executed_p7_runtime_proof",
        lambda gate_name, sha, **kwargs: {
            "runtime_proof": {"executed": True, "source_revision": sha}})

    generated = [0]
    def mutate(actions, source_actions, rng, cold):
        offset = generated[0] % 3
        generated[0] += 1
        return source_actions[offset:] + source_actions[:offset]

    source = SimpleNamespace(mutate_apl=mutate)

    def spell_id(request):
        return request["raid"]["parties"][0]["players"][0]["rotation"][
            "priorityList"][0]["action"]["castSpell"]["spellId"]["spellId"]

    def score(request, path, rng_mode):
        if rng_mode == "stochastic":
            return 725.0
        identity = spell_id(request)
        if path.name == "source-cold-candidate.json":
            return {1: 721.0, 2: 720.0, 3: 719.0}[identity]
        if path.name == "paid-balanced-finalist.json":
            return {1: 690.0, 2: 731.0, 3: 710.0}[identity]
        if path.name == "paid-balanced-confirmation.json":
            return {1: 695.0, 2: 735.0, 3: 712.0}[identity]
        raise AssertionError(f"unexpected paid P7.2 request: {path.name}")

    def native(binary, path, n, *, rng_mode):
        request = json.loads(path.read_text())
        calls.append(("native", n, rng_mode, path.name, spell_id(request)))
        return {"native_dps": score(request, path, rng_mode)}

    def world(binary, path, distance, iterations, *, rng_mode):
        request = json.loads(path.read_text())
        calls.append(("world", iterations, rng_mode, path.name, spell_id(request)))
        if rng_mode == "balanced":
            perf[0] += 0.01
            if path.name == "source-cold-candidate.json":
                screen_world[0] += 1
                if screen_world[0] == 3:
                    clock[0] = 120.0
            elif path.name == "paid-balanced-finalist.json":
                finalist_world[0] += 1
                if finalist_world[0] in (2, 4):
                    clock[0] = 120.0 + 10.0 * finalist_world[0]
                elif finalist_world[0] == 6:
                    clock[0] = 260.0
            elif path.name == "paid-balanced-confirmation.json":
                confirmation_world[0] += 1
                if confirmation_world[0] in (2, 4):
                    clock[0] = 260.0 + 5.0 * confirmation_world[0]
                elif confirmation_world[0] == 6:
                    clock[0] = 300.0
        return {"world_mean_dps": score(request, path, rng_mode),
                "iterations_done": iterations,
                "native_damage_events": 9, "native_world_ticks": 15}

    production = SimpleNamespace(native_source_control=native, run=world)
    monkeypatch.setattr(
        p72, "_source_module",
        lambda path, name: source if "apl_mutation" in str(path) else production)

    report = p72.run_live(tmp_path, "druid", 60, spec="balance")

    assert report["status"] == "PASS"  # mocked routing, not production acceptance
    assert report["cold_balanced_screen_best_dps"] == 721.0
    assert report["winner_screen_dps"] == 720.0
    assert report["winner_live_dps"] == 733.0
    assert report["paid_balanced_finalists"] == 3
    assert report["paid_balanced_confirmed_finalists"] == 3
    assert report["paid_balanced_deep_confirmed_finalists"] == 0
    assert report["balanced_parent_proposals"] == 2
    assert report["selected_validation"] == (
        "paid_4x3_balanced_live_native_confirmed_finalist")
    assert report["cold_winner_apl"][0]["action"]["castSpell"]["spellId"]["spellId"] == 2
    assert report["frozen_stochastic_iterations"] == 1000
    assert report["frozen_stochastic_world_dps"] == 725.0
    assert report["runtime_proof"]["executed"] is True
    assert report["runtime_proof"]["source_revision"] == report["frozen_request_raw_sha256"]
    assert report["reasons"] == []
    assert report["independent_300s_search_completed"] is True
    assert all(row[2] == "balanced" for row in calls[:-2])
    assert [(row[0], row[1], row[2]) for row in calls[-2:]] == [
        ("native", 1000, "stochastic"), ("world", 1000, "stochastic")]
    assert [row[4] for row in calls[-2:]] == [2, 2]


def test_invalid_full_p72_mode_is_blocked(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "yes")
    monkeypatch.setattr(gate, "_pinned_source_runtime",
                        lambda *a: (_request(), {"reference_dps": 728.19},
                                     tmp_path / "binary"))
    report = gate.run_live(tmp_path, "druid", 60, spec="balance")
    assert report["status"] == "BLOCKED"
    assert "P7_2_INVALID_FULL_SOURCE_SEARCH_MODE" in report["reasons"]
