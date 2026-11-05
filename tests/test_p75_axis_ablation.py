from __future__ import annotations

import copy
import random

from types import SimpleNamespace

from tools import wf_gate_p7_5_live as P75


def _player(request):
    """Extract the candidate player without importing a retired diagnostic."""
    return request["raid"]["parties"][0]["players"][0]


MODULE = SimpleNamespace(player=_player)


def _request():
    return {
        "encounter": {"duration": 120, "targets": [{"level": 63}]},
        "raid": {"parties": [{"players": [{
            "equipment": {"items": [{"id": 1}]},
            "talentsString": "reference-talents",
            "rotation": {"prepullActions": [], "priorityList": [{"id": "reference-apl"}]},
        }]}]},
        "simOptions": {"iterations": 10000, "randomSeed": "1179706472"},
    }


def _build(prefix):
    return {
        "equipment": {"items": [{"id": f"{prefix}-gear"}]},
        "talentsString": f"{prefix}-talents",
        "rotation": {"prepullActions": [], "priorityList": [{"id": f"{prefix}-apl"}]},
    }


def _paid_request(prefix):
    request = _request()
    MODULE.player(request).update(_build(prefix))
    return request


def test_p75_paid_apl_crossover_keeps_parent_gear_and_talents():
    # The measured P7.5 ablation improves by ~172 DPS when only the APL is
    # changed. Copy an APL from this cold search's PAID donor independently
    # of its talents, unlike the existing coupled talent+APL crossover.
    parent = _paid_request("parent")
    candidate = copy.deepcopy(parent)
    same_apl = _paid_request("other-talents")
    MODULE.player(same_apl)["rotation"] = copy.deepcopy(MODULE.player(parent)["rotation"])
    donor = _paid_request("paid-apl")
    original = copy.deepcopy(candidate)
    finalists = [(900.0, None, "same-apl", same_apl, 900.0),
                 (700.0, None, "distinct-apl", donor, 700.0)]
    assert P75._paid_p75_apl_crossover(
        candidate, parent, finalists, [], MODULE, random.Random(17))
    assert MODULE.player(candidate)["equipment"] == MODULE.player(original)["equipment"]
    assert MODULE.player(candidate)["talentsString"] == MODULE.player(original)["talentsString"]
    assert MODULE.player(candidate)["rotation"] == MODULE.player(donor)["rotation"]
    assert MODULE.player(parent) == MODULE.player(original)
    MODULE.player(donor)["rotation"]["priorityList"].append({"id": "later-mutation"})
    assert MODULE.player(candidate)["rotation"] != MODULE.player(donor)["rotation"]


def test_p75_paid_apl_crossover_rejects_same_apl_and_empty_paid_pools():
    parent = _paid_request("parent")
    candidate = copy.deepcopy(parent)
    other = _paid_request("different-gear-talents")
    MODULE.player(other)["rotation"] = copy.deepcopy(MODULE.player(parent)["rotation"])
    assert not P75._paid_p75_apl_crossover(
        candidate, parent, [(900.0, None, "same", other, 900.0)],
        [(850.0, "same2", other)], MODULE, random.Random(1))
    assert candidate == parent
    assert not P75._paid_p75_apl_crossover(
        candidate, parent, [], [], MODULE, random.Random(1))
    assert candidate == parent
