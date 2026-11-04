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


def test_full_p72_explores_paid_native_elites_without_retired_holdout(
        monkeypatch, tmp_path):
    """Optional long exploration cannot reintroduce a P7.2 stochastic gate."""
    import json
    from pathlib import Path
    from tools import wf_gate_p7_2_live as p72

    base = _request()
    base["raid"]["parties"][0]["players"][0].update({
        "class": "ClassDruid", "distanceFromTarget": 15})
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "1")
    clock = iter([0.0] * 7 + [300.0, 300.0])
    monkeypatch.setattr(p72.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(
        p72, "_pinned_source_runtime",
        lambda *args, **kwargs: (
            base, {"reference_dps": 728.19, "selected_engine_revision": "pinned"},
            tmp_path / "binary"))

    mutations = []
    def mutate(actions, source_actions, rng, cold):
        if actions is not None:
            assert cold is False
        else:
            assert cold is True
        candidate_id = 100 + len(mutations) + 1
        mutations.append((actions is not None, candidate_id))
        return [{"action": {"castSpell": {
            "spellId": {"spellId": candidate_id}}}}]

    source = SimpleNamespace(mutate_apl=mutate)
    balanced_scores = {101: 710.0, 102: 720.0, 103: 715.0,
                       104: 718.0, 105: 700.0, 106: 717.0}
    calls = []
    def native(binary, path, iterations, *, rng_mode):
        request = json.loads(Path(path).read_text())
        candidate_id = request["raid"]["parties"][0]["players"][0][
            "rotation"]["priorityList"][0]["action"]["castSpell"]["spellId"]["spellId"]
        calls.append((iterations, rng_mode, candidate_id))
        return {"native_dps": balanced_scores[candidate_id],
                "iterations": iterations}

    producer = SimpleNamespace(native_source_control=native)
    monkeypatch.setattr(
        p72, "_source_module",
        lambda path, name: source if "apl_mutation" in str(path) else producer)

    report = p72.run_live(tmp_path, "druid", 60, spec="balance")
    assert len(mutations) == 6
    assert len(calls) == 6
    assert all(n == 3 and mode == "balanced" for n, mode, _ in calls)
    assert report["winner_native_dps"] == 720.0
    assert report["source_legal_cold_candidates_paid"] == 6
    assert report["independent_300s_search_completed"] is True
    assert "frozen_stochastic_iterations" not in report
    assert report["status"] == "PASS"  # mocked transport, not a gate measurement


def test_invalid_full_p72_mode_is_blocked(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "yes")
    monkeypatch.setattr(
        gate, "_pinned_source_runtime",
        lambda *a, **kw: (_request(), {"reference_dps": 728.19},
                          tmp_path / "binary"))
    report = gate.run_live(tmp_path, "druid", 60, spec="balance")
    assert report["status"] == "BLOCKED"
    assert "P7_2_INVALID_FULL_SOURCE_SEARCH_MODE" in report["reasons"]
