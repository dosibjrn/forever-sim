"""P7.3 source-talent cold discovery contract, never a synthetic PASS."""
import copy
import random
from types import SimpleNamespace
import pytest
from tools import wf_gate_p7_3_live as gate


def _reference():
    return {"raid": {"parties": [{"players": [{
        "talentsString": "old", "equipment": {"items": [{"id": 17}]},
        "rotation": {"priorityList": [{"action": {"castSpell": {"spellId": 1}}}]},
    }]}]}}


def test_cold_talent_discovery_preserves_full_gear_apl_and_original():
    original = _reference()
    baseline = copy.deepcopy(original)
    source = SimpleNamespace(random_build=lambda rng: [[1, 2], [0], [0]],
                             validate=lambda ranks: True,
                             encode=lambda ranks: "independent_legal")
    new = gate._cold_talents(original, random.Random(647003), source)
    assert new != original
    assert new["raid"]["parties"][0]["players"][0]["talentsString"] == "independent_legal"
    assert new["raid"]["parties"][0]["players"][0]["rotation"] == baseline["raid"]["parties"][0]["players"][0]["rotation"]
    assert new["raid"]["parties"][0]["players"][0]["equipment"] == baseline["raid"]["parties"][0]["players"][0]["equipment"]
    assert original == baseline


def test_illegal_source_talents_cannot_run():
    source = SimpleNamespace(random_build=lambda rng: None,
                             validate=lambda ranks: False)
    with pytest.raises(ValueError, match="ALLOCATION_ILLEGAL"):
        gate._cold_talents(_reference(), random.Random(1), source)


def test_saved_identity_mismatch_fails_closed(tmp_path):
    report = gate.run_live(tmp_path, "priest", 60, spec="holy")
    assert report["status"] == "BLOCKED"
    assert "P7_3_PINNED_REFERENCE_NOT_SELECTED_FOR_CHECKPOINT" in report["reasons"]


def test_full_p73_freezes_a_unique_talent_winner_before_stochastic_holdout(
