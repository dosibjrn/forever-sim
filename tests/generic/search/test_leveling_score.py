import pytest

from src.optimization.leveling_score import score_combat_cycle
from src.shared.leveling.objective import combat_result, representative_hp


def test_score_combat_cycle_preserves_expected_kill_recovery_and_travel_math():
    result = score_combat_cycle(
        target_hp=484,
        dps=121,
        mana_spent=120,
        mana_pool=100,
        regen_per_s=10,
        travel_s=2,
        rotation="test-rotation",
        profile="test-profile",
        flags=["approximate"],
        details={"source": "fixture"},
    )

    assert result["kill_s"] == pytest.approx(400)
    assert result["recovery_s"] == pytest.approx(1020)
    assert result["travel_s"] == pytest.approx(200)
    assert result["total_s"] == pytest.approx(1620)
    assert result["dps"] == 121.0
    assert result["mana_spent_per_mob"] == 120.0
    assert result["rotation"] == "test-rotation"
    assert result["profile"] == "test-profile"
    assert result["approximation_flags"] == ["approximate"]
    assert result["source"] == "fixture"


def test_score_combat_cycle_keeps_recovery_override_and_nonnegative_travel():
    result = score_combat_cycle(
        target_hp=10,
        dps=100,
        mana_spent=1000,
        mana_pool=0,
        regen_per_s=0,
        travel_s=-5,
        rotation="test-rotation",
        profile="test-profile",
        flags=[],
        recovery_s_override=2,
    )

    assert result["kill_s"] == pytest.approx(10)
    assert result["recovery_s"] == pytest.approx(200)
    assert result["travel_s"] == pytest.approx(0)
    assert result["total_s"] == pytest.approx(210)


def test_legacy_combat_result_is_an_identity_preserving_optimizer_facade():
    inputs = {
        "dps": 121,
        "mana_spent": 120,
        "mana_pool": 100,
        "regen_per_s": 10,
        "travel_s": 2,
        "rotation": "test-rotation",
        "profile": "test-profile",
        "flags": ["approximate"],
        "details": {"source": "fixture"},
    }

    legacy = combat_result(level=20, **inputs)
    optimizer = score_combat_cycle(target_hp=representative_hp(20), **inputs)

    assert legacy == optimizer
