"""Clock-paid native recovery: zero passive ticks do not imply free time."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                       "integrations/mythicsim-rust"))
from live_two_world_pulls import (
    _native_paid_recovery_receipts, _match_native_paid_recovery_contract,
)


class NativePaidRecoveryClockTests(unittest.TestCase):
    def setUp(self):
        self.windows = [
            {"native_passive_recovery_ns": 0,
             "native_passive_recovery_ticks": 0},
            {"native_passive_recovery_ns": 300_000_000,
             "native_passive_recovery_ticks": 0,
             "food_seconds": 0.3, "food_health_gain": 6.0},
            {"native_passive_recovery_ns": 2_000_000_000,
             "native_passive_recovery_ticks": 1},
        ]
        self.kills = [
            {"world_kill_clock_ns": 1_000_000_000},
            {"world_kill_clock_ns": 1_500_000_000},
            {"world_kill_clock_ns": 4_500_000_000},
        ]

    def test_clock_paid_even_if_one_gap_has_no_passive_tick(self):
        receipt = _native_paid_recovery_receipts(self.windows, self.kills)
        self.assertTrue(receipt["paid_recovery"])
        self.assertEqual(receipt["native_passive_regen_gaps_with_ticks"], 1)
        self.assertEqual(receipt["native_passive_recovery_ticks_by_target"], [0, 0, 1])

    def test_legacy_source_false_and_new_clock_source_true_can_both_be_verified(self):
        receipt = _native_paid_recovery_receipts(self.windows, self.kills)
        # Same real 300-ms gap, but an old pin conflates "paid" with
        # scheduled passive-regeneration events in every gap.
        legacy = _match_native_paid_recovery_contract(
            {"paid_recovery": False}, receipt)
        self.assertFalse(legacy["paid_recovery"])
        self.assertTrue(legacy["native_clock_paid_recovery"])
        self.assertEqual(legacy["paid_recovery_semantics"],
                         "legacy_passive_tick_each_gap")
        modern = _match_native_paid_recovery_contract(
            {"paid_recovery": True,
             "paid_recovery_semantics": "native_clock_elapsed_v2"}, receipt)
        self.assertTrue(modern["paid_recovery"])
        self.assertTrue(modern["native_clock_paid_recovery"])

    def test_native_source_flag_mismatch_and_unknown_version_are_rejected(self):
        receipt = _native_paid_recovery_receipts(self.windows, self.kills)
        with self.assertRaisesRegex(AssertionError, "FLAG_MISMATCH"):
            _match_native_paid_recovery_contract(
                {"paid_recovery": False,
                 "paid_recovery_semantics": "native_clock_elapsed_v2"}, receipt)
        with self.assertRaisesRegex(AssertionError, "SEMANTICS_UNKNOWN"):
            _match_native_paid_recovery_contract(
                {"paid_recovery": True, "paid_recovery_semantics": "future_v3"}, receipt)

    def test_no_clock_payment_is_not_paid(self):
        self.windows[1]["native_passive_recovery_ns"] = 0
        self.assertFalse(
            _native_paid_recovery_receipts(self.windows, self.kills)["paid_recovery"])

    def test_unpaid_gap_cannot_claim_a_native_tick(self):
        self.windows[1].update(native_passive_recovery_ns=0,
                               native_passive_recovery_ticks=1)
        with self.assertRaisesRegex(AssertionError, "RUST_WORLD_PAID_RECOVERY_CLOCK_INVALID"):
            _native_paid_recovery_receipts(self.windows, self.kills)

    def test_clock_must_fit_between_world_kills(self):
        self.windows[1]["native_passive_recovery_ns"] = 700_000_000
        with self.assertRaisesRegex(AssertionError, "RUST_WORLD_PAID_RECOVERY_CLOCK_INVALID"):
            _native_paid_recovery_receipts(self.windows, self.kills)

    def test_old_engine_with_unobserved_clock_remains_unverified(self):
        receipt = _native_paid_recovery_receipts([{}, {}], self.kills[:2])
        self.assertFalse(receipt["paid_recovery"])
        self.assertFalse(receipt["native_passive_recovery_observed"])


if __name__ == "__main__":
    unittest.main()
