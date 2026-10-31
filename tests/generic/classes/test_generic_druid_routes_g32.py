from __future__ import annotations

import hashlib
from pathlib import Path

from src.listener import DECISIONS_HTML
from src.v2.decision_dashboard import _generic_decision_payload
from src.v2.decision_result import reports
from src.v2.generic_frontier import (
    GENERIC_DRUID_ROUTE_LEVELS,
    ROUTE_AUTHORITY,
    build_generic_druid_route_frontiers,
    solve_generic_druid_routes,
)

CANONICAL_DB_SHA = "d7d5a8519b227a761312bf4d1da56955b58184239a5a2ed7a06f84eb134dc854"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_g32_route_ready_corridor_uses_only_fully_represented_talent_budgets():
    frontiers = build_generic_druid_route_frontiers()
    assert tuple(f.level for f in frontiers) == (10, 11, 12, 13, 14)
    assert [len(f.candidates) for f in frontiers] == [1, 1, 1, 1, 1]
    assert [f.candidates[0].build.candidate_id for f in frontiers] == [
        "talents:improved_wrath=1",
        "talents:improved_wrath=2",
        "talents:improved_wrath=3",
        "talents:improved_wrath=4",
        "talents:improved_wrath=5",
    ]
    assert all(c.build.spent_points == c.build.available_points for f in frontiers for c in f.candidates)
    assert all(c.metadata["route_ready"] is True for f in frontiers for c in f.candidates)


def test_g32_shared_route_dp_publishes_real_endpoint_continuation_and_regret():
    result = solve_generic_druid_routes()
    assert result.authority == ROUTE_AUTHORITY
    route = result.targets[14]["unconstrained"]
    assert route.status == "available"
    assert route.path is not None
    assert [step.node.talents.candidate_id for step in route.path.steps] == [
        "talents:improved_wrath=1",
        "talents:improved_wrath=2",
        "talents:improved_wrath=3",
        "talents:improved_wrath=4",
        "talents:improved_wrath=5",
    ]
    assert [step.talent_added for step in route.path.steps] == [
        None, "improved_wrath", "improved_wrath", "improved_wrath", "improved_wrath"
    ]
    assert route.path.respecs_used == 0

    endpoint, regret = reports(result, verified_level_cap=14)
    path = endpoint["targets"]["14"]["routes"]["unconstrained"]["path"]
    assert path["allocation"] == "talents:improved_wrath=5"
    assert [x["allocation"] for x in path["steps"]] == [
        "talents:improved_wrath=1",
        "talents:improved_wrath=2",
        "talents:improved_wrath=3",
        "talents:improved_wrath=4",
        "talents:improved_wrath=5",
    ]
    rr = regret["targets"]["14"]["routes"]["unconstrained"]
    assert rr["regret_percent"] == 0.0
    assert rr["authority"] == ROUTE_AUTHORITY
    assert result.targets[14]["balance"].status == "unavailable"


def test_g32_generic_product_enables_bounded_route_navigation_without_legacy_fallback():
    payload = _generic_decision_payload(20)
    gr = payload["generic_routes"]
    assert gr["route_solving"] is True
    assert gr["levels"] == [10, 11, 12, 13, 14]
    assert gr["target_level"] == 14
    assert gr["path"]["allocation"] == "talents:improved_wrath=5"
    assert gr["legacy_fallback"] is False
    assert "dummy" in gr["route_blocker"]
    assert payload["product_surface"]["route_navigation"] is True
    assert payload["endpoint_paths"]["druid"]["targets"]["14"]["routes"]["unconstrained"]["status"] == "available"
    assert payload["spec_regret"]["druid"]["targets"]["14"]["routes"]["unconstrained"]["regret_percent"] == 0.0

    record = next(x for x in payload["decisions"] if str(x["identity"]["class_name"]).lower() == "druid")
    assert record["capability"]["route_solving"] is True
    assert record["capability"]["route_solving_levels"] == [10, 11, 12, 13, 14]
    assert "route_solving" not in record["unsupported_mechanics"]
    assert record["provenance"]["generic_route_solve"]["authority"] == ROUTE_AUTHORITY
    assert record["provenance"]["legacy_fallback"] is False

    assert "Generic route solve" in DECISIONS_HTML
    assert "const CURRENT_SOFTWARE_VERSION='0.11.48.157';" in DECISIONS_HTML


def test_g32_route_solve_preserves_canonical_catalogue_bytes():
    db = Path("data/forever/catalogue/items_2026-09-29.sqlite")
    before = _sha(db)
    assert before == CANONICAL_DB_SHA
    solve_generic_druid_routes()
    assert _sha(db) == before
