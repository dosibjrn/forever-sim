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


def test_identical_apl_is_not_called_independent_discovery():
    base = _request()
    with pytest.raises(ValueError, match="IDENTICAL_TO_REFERENCE"):
        gate._cold_apl(base, random.Random(3),
                       SimpleNamespace(mutate_apl=lambda a, s, r, cold: copy.deepcopy(s)))


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
            "per_iteration": [{"duration_s": 119.0}] * iterations,
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
