"""Scenario timing ownership regression after removing the legacy shim."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.scenarios.timing import (
    BASE_BETWEEN_PULL_TRAVEL_S,
    TIMING_CONTRACT_VERSION,
    between_pull_travel_s,
)

ROOT = Path(__file__).resolve().parents[2]


def test_scenario_timing_is_canonical_and_legacy_shim_is_removed():
    legacy = ROOT / "src/shared/leveling/timing.py"
    assert not legacy.exists()
    assert TIMING_CONTRACT_VERSION == "solo_leveling_timing_v1"
    assert BASE_BETWEEN_PULL_TRAVEL_S == pytest.approx(2.2)
    assert between_pull_travel_s() == pytest.approx(2.2)
    assert between_pull_travel_s(speed_multiplier=1.1) == pytest.approx(2.0)
    assert between_pull_travel_s(speed_multiplier=0.0) == pytest.approx(22.0)


def test_active_scenario_timing_consumers_use_canonical_import():
    consumers = (
        "src/optimization/evaluation.py",
        "src/v2/analytic_scorer.py",
        "src/v2/expected_engine.py",
        "src/v2/decision_dashboard.py",
        "src/rulesets/forever/classes/mage/policy.py",
        "src/rulesets/forever/classes/druid/mechanics.py",
        "src/rulesets/forever/classes/hunter/mechanics.py",
        "src/rulesets/forever/classes/paladin/mechanics.py",
    )
    for path in consumers:
        source = (ROOT / path).read_text(encoding="utf-8")
        assert "from src.scenarios.timing import " in source, path
        assert "src.shared.leveling.timing" not in source, path
