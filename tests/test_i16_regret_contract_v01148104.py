from __future__ import annotations

import pytest

from src.v2.regret import compute_regret
from src.v2.constrained_routes import analyze_constraint


def _candidate(seconds, *, mph, gear):
    return {
        "level": 20, "allocation": gear, "talent_ranks": {}, "tree_points": {},
        "talent_family": "x", "combat_profile": "x", "gear": gear, "pull_size": 1,
        "policy": "x", "mobs_per_hour": mph, "cumulative_objective_s": seconds,
        "steps": [{"level": 20, "talent_ranks": {}, "allocation": gear}],
    }


def test_zero_regret_is_exact_and_has_provenance():
    r = compute_regret(
        baseline_objective_s=100.0, constrained_objective_s=100.0,
        constrained_route="cat", definition={"label": "Feral · Cat", "kind": "generic_constraint", "source": "reference"},
    )
    assert r.regret_seconds == 0.0
    assert r.regret_percent == 0.0
    assert r.constraint_label == "Feral · Cat"
    assert r.constraint_source == "reference"
    assert r.authority == "canonical_level_frontier_dp"


def test_positive_regret_uses_one_central_formula():
    r = compute_regret(
        baseline_objective_s=100.0, constrained_objective_s=105.0,
        constrained_route="weaker", definition={"kind": "generic_constraint", "source": "test"},
    )
    assert r.regret_seconds == pytest.approx(5.0)
    assert r.regret_percent == pytest.approx(5.0)


def test_material_negative_regret_is_correctness_failure():
    with pytest.raises(ValueError, match="beats unrestricted"):
        compute_regret(baseline_objective_s=100.0, constrained_objective_s=99.0, constrained_route="impossible")


def test_constraint_service_analysis_uses_same_regret_contract():
    frontier = {"class": "druid", "levels": [{"level": 20, "candidates": [
        _candidate(100.0, mph=220.0, gear="best"),
        _candidate(104.0, mph=210.0, gear="cat"),
    ]}]}
    out = analyze_constraint(frontier, 20, {"gear": "cat"})
    assert out["status"] == "available"
    assert out["regret_percent"] == pytest.approx(4.0)
    assert out["constraint_label"] == "Current constraint"
    assert out["constraint_source"] == "listener_constraint"
    assert out["regret_authority"] == "best_preserved_frontier_path"


def test_listener_renders_regret_provenance_and_same_authority_explanation():
    html = open("src/listener.py", encoding="utf-8").read()
    assert "Constrained regret" in html
    assert "constraint_source" in html
    assert "regret_authority" in html
    assert "same canonical LevelFrontier + DP authority" in html
