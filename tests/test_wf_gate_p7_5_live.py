"""P7.5 direct native-world joint producer: no saved seed, no false PASS."""
import copy
import json
import random
from types import SimpleNamespace

import pytest

from tools import wf_gate_p7_5_live as gate


def _request():
    return {"raid": {"parties": [{"players": [{
        "equipment": {"items": [{"id": 10}]},
        "talentsString": "saved",
        "rotation": {"priorityList": [{"action": {"castSpell": {"spellId": 1}}}]},
        "distanceFromTarget": 15,
    }]}]}}


def test_cold_joint_frees_gear_talents_apl_without_mutating_saved_request():
    original = _request()
    before = copy.deepcopy(original)
    seen = []
    def make(base, pools, rng, elite, item_names):
        assert elite is None
        assert pools == {0: [11]}
        result = copy.deepcopy(base)
        p = result["raid"]["parties"][0]["players"][0]
        p["equipment"]["items"][0]["id"] = 11
        p["talentsString"] = "legal"
        p["rotation"]["priorityList"] = [{"action": {"castSpell": {"spellId": 2}}}]
        return result
    joint = SimpleNamespace(make_candidate=make, parse=lambda s: s,
                            validate=lambda s: s == "legal")
    validator = SimpleNamespace(validate=lambda ids, enchants: seen.append(
        (ids, enchants)))
    candidate = gate._cold_joint(
        original, {0: [11]}, random.Random(670), joint, validator, {})
    assert original == before
    assert seen == [([11], [0])]
    assert candidate != original


def test_joint_rejects_reference_seed_or_illegal_source_talents():
    original = _request()
    joint = SimpleNamespace(make_candidate=lambda *a, **k: copy.deepcopy(original))
    with pytest.raises(ValueError, match="DID_NOT_FREE_ALL_THREE_AXES"):
        gate._cold_joint(original, {}, random.Random(1), joint,
                         SimpleNamespace(), {})
    changed = copy.deepcopy(original)
    p = changed["raid"]["parties"][0]["players"][0]
    p["equipment"]["items"][0]["id"] = 11
    p["talentsString"] = "illegal"
    p["rotation"]["priorityList"] = []
    joint = SimpleNamespace(make_candidate=lambda *a, **k: changed,
                            parse=lambda s: s, validate=lambda s: False)
    with pytest.raises(ValueError, match="SOURCE_TALENTS_ILLEGAL"):
        gate._cold_joint(original, {}, random.Random(1), joint,
                         SimpleNamespace(), {})


def test_wrong_checkpoint_refuses_without_native_execution(tmp_path):
    result = gate.run_live(tmp_path, "priest", 60, spec="holy")
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == [
        "P7_5_PINNED_REFERENCE_NOT_SELECTED_FOR_CHECKPOINT"]


def test_paid_cold_joint_production_is_still_fail_not_holdout(monkeypatch, tmp_path):
    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_text("not executed by the focused orchestration test")
    for name in ("data/items.jsonl", "data/enchants.jsonl"):
        p = tmp_path / "upstream" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")
    catalogue = tmp_path / "data/forever/catalogue/items_2026-09-29.sqlite"
    catalogue.parent.mkdir(parents=True)
    catalogue.write_text("")
    base = _request()
    monkeypatch.setattr(gate, "_pinned_source_runtime",
                        lambda *a: (base, {"reference_dps": 728.1936126415858}, binary))
    class Validator:
        rows = {11: {"name": "source item"}}
        def __init__(self, *a): pass
        def validate(self, ids, enchants): assert ids == [11]
        def close(self): pass
    def make_candidate(base, pools, rng, elite, item_names):
        result = copy.deepcopy(base)
        p = result["raid"]["parties"][0]["players"][0]
        p["equipment"]["items"][0]["id"] = 11
        p["talentsString"] = "legal"
        p["rotation"]["priorityList"] = []
        return result
    joint = SimpleNamespace(
        GearValidator=Validator,
        candidate_pool=lambda validator, limit: ({0: [11]}, {}),
        make_candidate=make_candidate,
        parse=lambda s: s,
        validate=lambda s: s == "legal")
    native = lambda binary, path, n: {
        "iterations": n, "first_duration_s": 120.0, "native_dps": 730.0}
    live = lambda binary, path, distance, iterations: {
        "iterations_done": iterations,
        "per_iteration": [{"duration_s": 120.0}] * iterations,
        "native_damage_events": 10, "native_world_ticks": 20,
        "sampled_duration_s": 120.0, "native_dps": 730.0,
        "world_mean_dps": 730.0}
    production = SimpleNamespace(native_source_control=native, run=live)
    monkeypatch.setattr(gate, "_source_module",
                        lambda path, name: joint if "joint_search" in str(path)
                        else production)
    result = gate.run_live(tmp_path, "druid", 60, spec="balance")
    assert result["status"] == "FAIL"
    assert result["source_legal_cold_candidates_paid"] == 3
    assert result["winner_live_dps"] == 730.0
    assert result["world_damage_events"] == 10
    assert result["source_gear_talents_apl_all_free"] is True
    assert "holdout_mean_dps" not in result
    assert "strongest_accepted_compatible_prior_dps" not in result
    assert "P7_5_STRONGEST_ACCEPTED_COMPATIBLE_PRIOR_NOT_AVAILABLE" in result["reasons"]
