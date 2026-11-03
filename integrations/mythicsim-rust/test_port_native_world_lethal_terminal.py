#!/usr/bin/env python3
"""Fail-closed source port tests; no combat simulation or M1 gate claim."""
import unittest

from port_native_world_lethal_terminal import (
    BRIDGE_ANCHOR, BRIDGE_FUNCTION, FINISH_OLD, FINISH_NEW,
    FIGHT_LOOP_OLD, FIGHT_LOOP_NEW, STEP_OLD, STEP_NEW,
    TESTS, port_bridge, port_fight,
)

def original_fight():
    return "prefix\n" + FIGHT_LOOP_OLD + "middle\n" + STEP_OLD + "suffix\n"

def original_bridge():
    return ("prefix\n" + BRIDGE_ANCHOR + FINISH_OLD
            + "middle\npub(crate) fn due(next_native_ns: i64, end_ns: i64) -> Option<i64> {\n"
            + "suffix\n")


class LethalWorldTerminalPortTests(unittest.TestCase):
    def test_fight_port_and_second_run_are_idempotent(self):
        updated = port_fight(original_fight())
        self.assertIn(FIGHT_LOOP_NEW, updated)
        self.assertIn(STEP_NEW, updated)
        self.assertEqual(updated, port_fight(updated))

    def test_bridge_port_and_second_run_are_idempotent(self):
        updated = port_bridge(original_bridge())
        self.assertIn(BRIDGE_FUNCTION, updated)
        self.assertIn(FINISH_NEW, updated)
        self.assertIn(TESTS, updated)
        self.assertEqual(updated, port_bridge(updated))

    def test_missing_or_duplicate_source_anchor_rejected(self):
        with self.assertRaisesRegex(ValueError, "LOOP_ANCHOR_DRIFT"):
            port_fight(original_fight().replace(FIGHT_LOOP_OLD, ""))
        with self.assertRaisesRegex(ValueError, "STEP_ANCHOR_DRIFT"):
            port_fight(original_fight().replace(STEP_OLD, STEP_OLD + STEP_OLD))
        with self.assertRaisesRegex(ValueError, "FINISH_ANCHOR_DRIFT"):
            port_bridge(original_bridge().replace(FINISH_OLD, ""))

    def test_partial_or_tampered_bridges_rejected(self):
        changed = port_bridge(original_bridge()).replace(
            "RUST_WORLD_LETHAL_DURATION_NOT_ACK_CLOCK", "WRONG_CLOCK")
        with self.assertRaisesRegex(ValueError, "FINISH_ANCHOR_DRIFT"):
            port_bridge(changed)
        changed = port_bridge(original_bridge()).replace(
            "assert!(!acknowledged_lethal());", "assert!(acknowledged_lethal());", 1)
        with self.assertRaisesRegex(ValueError, "TEST_ANCHOR_DRIFT"):
            port_bridge(changed)


if __name__ == "__main__":
    unittest.main()
