from __future__ import annotations

import copy
import importlib.util
import random
from pathlib import Path

import pytest

from tools import wf_gate_p7_5_live as P75


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/diagnostics/replay_historical_wf678_winner.py"
SPEC = importlib.util.spec_from_file_location("p75_axis_ablation_diagnostic", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


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


def test_axis_ablation_replaces_only_requested_axes_and_preserves_scenario():
    reference = _request()
    original = copy.deepcopy(reference)
    baseline = _build("search")
    historical = _build("historical")

    cases = {
        (): ("search", "search", "search"),
        ("gear",): ("historical", "search", "search"),
        ("talents",): ("search", "historical", "search"),
        ("apl",): ("search", "search", "historical"),
        ("gear", "talents"): ("historical", "historical", "search"),
        ("gear", "apl"): ("historical", "search", "historical"),
        ("talents", "apl"): ("search", "historical", "historical"),
        ("gear", "talents", "apl"): ("historical", "historical", "historical"),
    }
    for selected, expected in cases.items():
        candidate = MODULE.compose_candidate(
            reference, baseline, historical, selected, iterations=5)
        player = MODULE.player(candidate)
        actual = (
            player["equipment"]["items"][0]["id"].split("-")[0],
            player["talentsString"].split("-")[0],
            player["rotation"]["priorityList"][0]["id"].split("-")[0],
        )
        assert actual == expected, (selected, actual, expected)
        assert candidate["simOptions"]["iterations"] == 5
        assert candidate["simOptions"]["randomSeed"] == "1179706472"
        assert candidate["encounter"] == reference["encounter"]
        reference_player = MODULE.player(reference)
        for key in set(reference_player) - {"equipment", "talentsString", "rotation"}:
            assert player[key] == reference_player[key]
    assert reference == original


def test_axis_ablation_rejects_unknown_axis():
    with pytest.raises(ValueError, match="Unknown historical axes"):
        MODULE.compose_candidate(
            _request(), _build("search"), _build("historical"),
            ("stochastic",), iterations=5
        )


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
