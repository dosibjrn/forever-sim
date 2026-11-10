"""Verify Rust-source Decisions recovery is not lost at the 2D receipt boundary.

A real vendor recovery step can finish before the next scheduled native mana
tick. The Rust engine counts that paid food/water time; the Forever wire
adapter must classify the same verified receipt without inventing ticks.
"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


def _bridge():
    path = (Path(__file__).resolve().parents[1] /
            "integrations/mythicsim-rust/live_two_world_pulls.py")
    spec = spec_from_file_location("work1_decisions_vendor_receipts", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _receipts(*, ns=1_500_000_000, ticks=0, food=0.0, water=0.0):
    windows = [
        {"native_passive_recovery_ns": 0,
         "native_passive_recovery_ticks": 0,
         "food_seconds": 0.0, "water_seconds": 0.0,
         "food_health_gain": 0.0, "water_mana_gain": 0.0,
         "decisions_full_recovery": False},
        {"native_passive_recovery_ns": ns,
         "native_passive_recovery_ticks": ticks,
         "food_seconds": food, "water_seconds": water,
         "food_health_gain": food * 10.0,
         "water_mana_gain": water * 10.0,
         "decisions_full_recovery": True},
    ]
    kills = [
        {"world_kill_clock_ns": 2_000_000_000},
        {"world_kill_clock_ns": 6_000_000_000},
    ]
    return windows, kills


@pytest.mark.parametrize("vendor", [{"food": 1.0}, {"water": 1.0},
                                    {"food": 1.0, "water": 1.5}])
def test_decisions_vendor_time_is_paid_even_with_zero_native_mana_ticks(vendor):
    bridge = _bridge()
    windows, kills = _receipts(**vendor)
    verified = bridge._native_food_water_receipts(windows, required=True)
    assert verified["native_food_water_observed"] is True
    assert bridge._native_paid_recovery_receipts(
        windows, kills, decisions=True)["paid_recovery"] is True
    # Without the requested Decisions policy, a fixed passive-rest receipt
    # cannot take credit for vendor actions.
    assert bridge._native_paid_recovery_receipts(
        windows, kills)["paid_recovery"] is False


def test_decisions_no_actual_vendor_or_mana_tick_does_not_claim_recovery():
    bridge = _bridge()
    windows, kills = _receipts()
    bridge._native_food_water_receipts(windows, required=True)
    result = bridge._native_paid_recovery_receipts(windows, kills, decisions=True)
    assert result["native_passive_recovery_observed"] is True
    assert result["paid_recovery"] is False


def test_native_passive_tick_still_counts_for_both_recovery_policies():
    bridge = _bridge()
    windows, kills = _receipts(ticks=1)
    for decisions in (True, False):
        assert bridge._native_paid_recovery_receipts(
            windows, kills, decisions=decisions)["paid_recovery"] is True


@pytest.mark.parametrize("ns,food,water", [
    (0, 0.1, 0.0),
    (100_000_000, 0.2, 0.0),
    (100_000_000, 0.0, 0.2),
])
def test_vendor_time_exceeding_native_recovery_clock_is_rejected(ns, food, water):
    bridge = _bridge()
    windows, _ = _receipts(ns=ns, food=food, water=water)
    with pytest.raises(AssertionError, match="FOOD_WATER_CLOCK_INVALID"):
        bridge._native_food_water_receipts(windows, required=True)


def test_no_native_recovery_clock_cannot_be_paid_just_by_vendor_label():
    bridge = _bridge()
    windows, kills = _receipts(ns=0, food=1.0)
    assert bridge._native_paid_recovery_receipts(
        windows, kills, decisions=True)["paid_recovery"] is False
    with pytest.raises(AssertionError, match="FOOD_WATER_CLOCK_INVALID"):
        bridge._native_food_water_receipts(windows, required=True)

def test_decisions_native_paid_travel_without_refill_matches_rust_receipt():
    """Regression: real L21 100-target run hit paid_recovery parity veto.

    Rust native_world_recovery_paid considers a charged travel-only gap
    paid if Decisions explicitly reports that no refill was needed. We
    must classify the same source windows without requiring a fictitious
    mana tick or consumable. Neither an omitted decision nor zero clock
    advances may qualify.
    """
    bridge = _bridge()
    windows, kills = _receipts(ns=100_000_000, ticks=0, food=0, water=0)
    windows[1]["decisions_full_recovery"] = False
    assert bridge._native_food_water_receipts(windows, required=True)[
        "native_food_water_observed"] is True
    assert bridge._native_paid_recovery_receipts(
        windows, kills, decisions=True)["paid_recovery"] is True
    assert bridge._native_paid_recovery_receipts(
        windows, kills, decisions=False)["paid_recovery"] is False


@pytest.mark.parametrize("ns,decision,expected", [
    (0, False, False),
    (100_000_000, True, False),
    (100_000_000, None, False),
    (100_000_000, False, True),
])
def test_no_refill_decision_cannot_forge_unpaid_or_requested_rest(
    ns, decision, expected
):
    bridge = _bridge()
    windows, kills = _receipts(ns=ns, ticks=0, food=0, water=0)
    if decision is None:
        del windows[1]["decisions_full_recovery"]
    else:
        windows[1]["decisions_full_recovery"] = decision
    result = bridge._native_paid_recovery_receipts(
        windows, kills, decisions=True)
    assert result["paid_recovery"] is expected
    if decision is None:
        with pytest.raises(AssertionError, match="FOOD_WATER_RECEIPT_INCOMPLETE"):
            bridge._native_food_water_receipts(windows, required=True)
