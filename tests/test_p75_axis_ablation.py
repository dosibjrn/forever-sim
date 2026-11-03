from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest


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
        assert candidate["raid"] == reference["raid"]
    assert reference == original


def test_axis_ablation_rejects_unknown_axis():
    with pytest.raises(ValueError, match="Unknown historical axes"):
        MODULE.compose_candidate(
            _request(), _build("search"), _build("historical"),
            ("stochastic",), iterations=5
        )
