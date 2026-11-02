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
