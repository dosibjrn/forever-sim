#!/usr/bin/env python3
"""Strict source-port regression; the real selected Rust compiles in CI separately."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "port_native_two_world", ROOT / "port_native_two_world.py")
port = importlib.util.module_from_spec(spec)
spec.loader.exec_module(port)


class TwoWorldPortTests(unittest.TestCase):
    def test_bounded_fight_port_idempotent_and_driven_by_real_lethal_ack(self):
        base = port.OLD_GUARD + "\n" + port.FIGHT_MARKER
        result = port.port_fight(base)
        self.assertIn(port.NEW_GUARD, result)
        self.assertIn("world_bridge::acknowledged_lethal()", result)
        self.assertIn("self.begin_next_target(second_start_ns, second_cap_ns)?", result)
        self.assertIn("world_bridge::finish(first_end_ns", result)
        self.assertIn('"paid_recovery": false', result)
        self.assertEqual(result, port.port_fight(result))

    def test_no_blindly_accepting_malformed_existing_source(self):
        with self.assertRaisesRegex(ValueError, "ANCHOR_DRIFT"):
            port.port_fight("fn irrelevant() {}")
        with self.assertRaisesRegex(ValueError, "ANCHOR_DRIFT"):
            port.port_fight(port.OLD_GUARD * 2 + port.FIGHT_MARKER)
        with self.assertRaisesRegex(ValueError, "PARTIAL"):
            port.port_fight(port.NEW_GUARD + port.FIGHT_MARKER)

    def test_prepared_entry_initializes_one_real_bridge(self):
        source = port.PREPARED_OLD
        actual = port.port_prepared(source)
        self.assertEqual(actual, port.PREPARED_NEW)
        self.assertIn("world_bridge::start(&prepared.request_sha256)", actual)
        self.assertEqual(actual, port.port_prepared(actual))
        with self.assertRaisesRegex(ValueError, "ANCHOR_DRIFT"):
            port.port_prepared("check(prepared)?;")


if __name__ == "__main__":
    unittest.main()
