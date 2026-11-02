"""P7.5 source-legal cold joint fixed-value mutation, not a fake PASS."""
import copy
import random
from types import SimpleNamespace

from tools import wf_gate_p7_5_live as gate


def _base():
    return {"raid": {"parties": [{"players": [{
        "equipment": {"items": [{"id": 10}, {"id": 20}]},
        "talentsString": "reference",
        "rotation": {"priorityList": [1, 2, 3]},
    }]}]}}


def test_cold_joint_changes_all_three_dimensions_and_does_not_seed_winner():
    original = _base()
    prior = copy.deepcopy(original)
    def player(obj):
        return obj["raid"]["parties"][0]["players"][0]
    def create(reference, pools, rng, item_names=None):
        q = copy.deepcopy(reference)
        p = player(q)
        p["equipment"]["items"] = [{"id": 11}, {"id": 21}]
        p["talentsString"] = "new-legal-source"
        p["rotation"]["priorityList"] = [3, 2, 1]
        return q
    v = SimpleNamespace(engine={11: {"name": "One"}, 21: {"name": "Two"}},
                        validate=lambda ids, enchants: True)
    source = SimpleNamespace(make_candidate=create, player=player,
                             RejectedGear=ValueError)
    candidate = gate._cold_joint(original, source, v, {}, random.Random(1))
    assert player(candidate)["talentsString"] != player(original)["talentsString"]
    assert player(candidate)["rotation"] != player(original)["rotation"]
    assert player(candidate)["equipment"] != player(original)["equipment"]
    assert original == prior


def test_unrelated_checkpoint_does_not_use_balance_ref(tmp_path):
    report = gate.run_live(tmp_path, "warrior", 40, spec="arms")
    assert report["status"] == "BLOCKED"
    assert "P7_5_PINNED_REFERENCE_NOT_SELECTED_FOR_CHECKPOINT" in report["reasons"]


def test_real_p75_provider_rejects_equal_dps_with_wrong_world_duration(monkeypatch, tmp_path):
    """Negative control: a plausible DPS score cannot bypass causal parity."""
    from pathlib import Path
    import json
    from tools import wf_gate_p7_5_live as p75

    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_text("focused test uses injected production interface")
    for relative in ("data/items.jsonl", "data/enchants.jsonl"):
        path = tmp_path / "upstream" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    catalogue = tmp_path / "data/forever/catalogue/items_2026-09-29.sqlite"
    catalogue.parent.mkdir(parents=True)
    catalogue.write_text("")
    original = _base()
    original["raid"]["parties"][0]["players"][0]["distanceFromTarget"] = 15
    monkeypatch.setattr(p75, "_pinned_source_runtime",
                        lambda *args: (original, {"reference_dps": 728.19}, binary))

    class Validator:
        engine = {11: {"name": "one"}, 21: {"name": "two"}}
        def __init__(self, *args): pass
        def validate(self, ids, enchants): assert ids == [11, 21]
        def close(self): pass

    def player(q):
        return q["raid"]["parties"][0]["players"][0]

    def cold(reference, pools, rng, item_names=None):
        candidate = copy.deepcopy(reference)
        p = player(candidate)
        p["equipment"]["items"] = [{"id": 11}, {"id": 21}]
        p["talentsString"] = "source-legal-cold"
        p["rotation"]["priorityList"] = [3, 2, 1]
        return candidate

    source = SimpleNamespace(
        GearValidator=Validator,
        candidate_pool=lambda validator, limit: ({0: [11], 1: [21]}, {}),
        make_candidate=cold, player=player, RejectedGear=ValueError)
    production = SimpleNamespace(
        native_source_control=lambda binary, path, n: {
            "iterations": n, "first_duration_s": 120.0, "native_dps": 730.0},
        run=lambda binary, path, distance, iterations: {
            "iterations_done": iterations,
            "per_iteration": [{"duration_s": 119.0}] * iterations,
            "sampled_duration_s": 119.0,
            "native_dps": 730.0, "world_mean_dps": 730.0,
            "native_damage_events": 10, "native_world_ticks": 20})
    monkeypatch.setattr(p75, "_source_module",
                        lambda path, name: source if "joint_search" in str(path)
                        else production)
    report = p75.run_live(tmp_path, "druid", 60, spec="balance")
    assert report["status"] == "FAIL"
    assert report["reasons"] == [
        "P7_5_NO_SOURCE_LEGAL_JOINT_CANDIDATE_REACHED_NATIVE_WORLD"]
    assert any("P7_5_P7_1_NATIVE_WORLD_FIRST_DURATION_DIVERGED" in reason
               for reason in report["cold_candidate_failures"])
    assert "joint_cold_world_dps" not in report


def test_shared_source_preflight_uses_exact_p7_gate_reason(tmp_path):
    from tools.wf_gate_p7_2_live import _pinned_source_runtime
    for gate_name in ("P7.2", "P7.3", "P7.4", "P7.5"):
        report = _pinned_source_runtime(
            tmp_path, "priest", 60, "holy", gate_name)
        assert report["status"] == "BLOCKED"
        assert report["reasons"] == [
            gate_name.replace(".", "_") +
            "_PINNED_REFERENCE_NOT_SELECTED_FOR_CHECKPOINT"]
