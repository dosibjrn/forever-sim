#!/usr/bin/env python3
"""Fast packaging regression for the production Rust lethal-world-ACK port.

The real Rust cargo regression still runs in check-selected-rust-source.
"""
import unittest

from port_native_world_lethal_ack import (
    BEFORE_TEST, LEGACY_ACK_NEW, LEGACY_ACK_OLD, LEGACY_TEST_NEW,
    LEGACY_TEST_OLD, NEW, OLD, TESTS, port_source,
)


def original_bridge():
    # Source slice copied from the already-selected Rust method and the
    # pre-guard preserved-world test. No mock gameplay or acceptance verdict.
    return (
        "pub(crate) fn begin_next_target(at_ns: i64) {\n"
        + OLD + "\n}\n"
        + "mod persistent_next_target_tests {\n"
        + LEGACY_TEST_OLD + "\n"
        + LEGACY_ACK_OLD + "\n}\n"
        + BEFORE_TEST + "\n"
    )


class LethalAckPortTests(unittest.TestCase):
    def test_upgrades_existing_rust_clock_test_and_is_idempotent(self):
        updated = port_source(original_bridge())
        self.assertIn(NEW, updated)
        self.assertIn(LEGACY_TEST_NEW, updated)
        self.assertIn(LEGACY_ACK_NEW, updated)
        self.assertIn(TESTS, updated)
        self.assertNotIn(LEGACY_TEST_OLD, updated)
        self.assertNotIn(LEGACY_ACK_OLD, updated)
        self.assertEqual(port_source(updated), updated)

    def test_rejects_partial_bridge_test_migration(self):
        broken = original_bridge().replace(LEGACY_ACK_OLD, LEGACY_ACK_NEW)
        with self.assertRaisesRegex(ValueError, "tests/entry anchor"):
            port_source(broken)

    def test_rejects_missing_or_duplicate_method_anchors(self):
        with self.assertRaisesRegex(ValueError, "source anchor"):
            port_source(original_bridge().replace(OLD, "", 1))
        with self.assertRaisesRegex(ValueError, "source anchor"):
            port_source(original_bridge().replace(OLD, OLD + OLD, 1))


if __name__ == "__main__":
    unittest.main()
