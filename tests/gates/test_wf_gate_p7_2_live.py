"""P7.2 cold APL mutation contract; no fake gate acceptance or saved-run PASS."""
import copy
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

def test_full_p72_holds_frozen_candidate_out_of_balanced_search(monkeypatch, tmp_path):
    """--heavy runs real producer twice in separate RNG modes; no fake PASS."""
    import os
    from tools import wf_gate_p7_2_live as p72
    base = _request()
    base["raid"]["parties"][0]["players"][0].update({
        "class": "ClassDruid", "distanceFromTarget": 15})
    calls = []
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "1")
    # A controlled 300-second clock tests the routing only; real elapsed time,
    # source legality and source Rust/world execution are NOT proved by this unit.
    clock = iter([0.0, 0.0, 300.0, 300.0, 300.0])
    monkeypatch.setattr(p72.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(p72, "_pinned_source_runtime",
                        lambda *args: (base, {"reference_dps": 728.19}, tmp_path / "binary"))
    monkeypatch.setattr(p72, "_source_native_world_parity",
                        lambda native, live, n, **kw: None)
    source = SimpleNamespace(
        mutate_apl=lambda a, s, rng, cold: list(reversed(s)))
    def native(binary, path, n, *, rng_mode):
        calls.append(("native", n, rng_mode))
        return {"native_dps": 730.0 if rng_mode == "balanced" else 729.0}
    def world(binary, path, distance, iterations, *, rng_mode):
        calls.append(("world", iterations, rng_mode))
        return {"world_mean_dps": 730.0 if rng_mode == "balanced" else 729.0,
                "native_damage_events": 9, "native_world_ticks": 15,
                "iterations_done": iterations}
    producer = SimpleNamespace(native_source_control=native, run=world)
    monkeypatch.setattr(p72, "_source_module",
                        lambda path, name: source if "apl_mutation" in str(path)
                        else producer)
    from tools.wf_gate import _run_live_gate
    report = _run_live_gate(tmp_path, "druid", 60, "balance", "P7.2", "")
    assert calls == [
        ("native", 3, "balanced"), ("world", 3, "balanced"),
        ("native", 1000, "stochastic"), ("world", 1000, "stochastic")]
    assert report["frozen_stochastic_iterations"] == 1000
    assert report["frozen_stochastic_world_dps"] == 729.0
    assert report["status"] == "PASS"  # mocked call routing, not a production gate run
    assert report["runtime_proof"]["executed"] is True
    assert report["runtime_proof"]["source_revision"] == report["frozen_request_raw_sha256"]
    assert report["reasons"] == []
    assert report["independent_300s_search_completed"] is True


def test_paid_elite_choice_uses_diverse_balanced_archive_and_keeps_cold_restart():
    elites = [(100.0 - index, {"candidate": index}) for index in range(22)]

    class ChoiceSpy:
        candidates = None

        def choice(self, candidates):
            self.candidates = list(candidates)
            return candidates[-1]

    spy = ChoiceSpy()
    assert gate._paid_elite_choice(elites, spy, 5) is None
    assert gate._paid_elite_choice([], spy, 6) is None
    selected = gate._paid_elite_choice(elites, spy, 6)
    assert spy.candidates == elites[:18]
    assert selected is elites[17][1]


def test_full_p72_explores_paid_balanced_elite_archive_then_freezes_best_screen(
        monkeypatch, tmp_path):
    """Routing test only: paid parents are Balanced; stochastic cannot rerank."""
    import json
    import os
    from pathlib import Path
    from tools import wf_gate_p7_2_live as p72

    base = _request()
    base["raid"]["parties"][0]["players"][0].update({
        "class": "ClassDruid", "distanceFromTarget": 15})
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "1")
    # Start + six candidate loop conditions, then the 300s wall window.
    # Removed per-step timestamps must not change the candidate sequence.
    clock = iter([0.0] * 7 + [300.0, 300.0])
    monkeypatch.setattr(p72.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(
        p72, "_pinned_source_runtime",
        lambda *args: (base, {"reference_dps": 728.19}, tmp_path / "binary"))
    monkeypatch.setattr(
        p72, "_source_native_world_parity",
        lambda native, live, n, **kw: None)

    mutations = []

    def mutate(actions, source_actions, rng, cold):
        parent_id = None
        if actions is not None:
            assert cold is False
            parent_id = actions[0]["action"]["castSpell"]["spellId"]["spellId"]
        else:
            assert cold is True
        candidate_id = 100 + len(mutations) + 1
        mutations.append((parent_id, cold, candidate_id))
        return [{"action": {"castSpell": {
            "spellId": {"spellId": candidate_id}}}}]

    source = SimpleNamespace(mutate_apl=mutate)
    balanced_scores = {
        101: 710.0, 102: 720.0, 103: 715.0,
        104: 718.0, 105: 700.0, 106: 717.0,
    }
    calls = []

    def candidate_id(path):
        request = json.loads(Path(path).read_text())
        return request["raid"]["parties"][0]["players"][0][
            "rotation"]["priorityList"][0]["action"]["castSpell"]["spellId"]["spellId"]

    def native(binary, path, iterations, *, rng_mode):
        selected_id = candidate_id(path)
        calls.append(("native", iterations, rng_mode, selected_id))
        return {"native_dps": (900.0 if rng_mode == "stochastic"
                               else balanced_scores[selected_id])}

    def world(binary, path, distance, iterations, *, rng_mode):
        selected_id = candidate_id(path)
        calls.append(("world", iterations, rng_mode, selected_id))
        return {
            "world_mean_dps": (900.0 if rng_mode == "stochastic"
                               else balanced_scores[selected_id]),
            "native_damage_events": 10,
            "native_world_ticks": 20,
            "iterations_done": iterations,
        }

    producer = SimpleNamespace(native_source_control=native, run=world)
    monkeypatch.setattr(
        p72, "_source_module",
        lambda path, name: source if "apl_mutation" in str(path) else producer)

    from tools.wf_gate import _run_live_gate
    report = _run_live_gate(tmp_path, "druid", 60, "balance", "P7.2", "")

    assert len(mutations) == 6
    assert [cold for _, cold, _ in mutations] == [
        True, False, False, False, True, False]
    paid_ids = set()
    for parent_id, cold, candidate_id_value in mutations:
        if not cold:
            assert parent_id in paid_ids
        paid_ids.add(candidate_id_value)

    balanced_calls = [call for call in calls if call[2] == "balanced"]
    stochastic_calls = [call for call in calls if call[2] == "stochastic"]
    assert len(balanced_calls) == 12
    assert {call[3] for call in balanced_calls} == {101, 102, 103, 104, 105, 106}
    assert stochastic_calls == [
        ("native", 1000, "stochastic", 102),
        ("world", 1000, "stochastic", 102),
    ]
    assert report["winner_live_dps"] == 720.0
    assert report["frozen_stochastic_world_dps"] == 900.0
    assert report["search_rng_mode"] == "balanced"
    assert report["source_legal_cold_candidates_paid"] == 6
    assert report["status"] == "PASS"  # mocked routing, not production acceptance


def test_invalid_full_p72_mode_is_blocked(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "yes")
    monkeypatch.setattr(gate, "_pinned_source_runtime",
                        lambda *a: (_request(), {"reference_dps": 728.19},
                                     tmp_path / "binary"))
    report = gate.run_live(tmp_path, "druid", 60, spec="balance")
    assert report["status"] == "BLOCKED"
    assert "P7_2_INVALID_FULL_SOURCE_SEARCH_MODE" in report["reasons"]
