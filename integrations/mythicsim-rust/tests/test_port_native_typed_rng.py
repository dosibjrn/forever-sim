"""Fail-closed source-port tests for required typed Rust RNG callsites."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from port_native_typed_rng import add_explicit_mode_to_test_calls


class TypedRngTestCallMigrationTests(unittest.TestCase):
    def test_migrates_simple_and_nested_legacy_calls(self):
        source = """
let first = simulate_prepared(&prepared).unwrap();
let second = forever_engine::simulate_prepared(
    &serde_json::from_value(value).unwrap()
).unwrap();
"""
        migrated, count = add_explicit_mode_to_test_calls(source)
        self.assertEqual(count, 2)
        self.assertIn(
            "simulate_prepared(&prepared, forever_engine::RngMode::Stochastic)",
            migrated,
        )
        self.assertIn(
            "simulate_prepared(\n    &serde_json::from_value(value).unwrap(), "
            "forever_engine::RngMode::Stochastic\n)",
            migrated,
        )

    def test_preserves_existing_explicit_mode_and_is_idempotent(self):
        source = (
            "simulate_prepared(&prepared, forever_engine::RngMode::Balanced);\n"
            "simulate_prepared(&other, forever_engine::RngMode::Stochastic);\n"
        )
        migrated, count = add_explicit_mode_to_test_calls(source)
        self.assertEqual(count, 0)
        self.assertEqual(migrated, source)
        again, second_count = add_explicit_mode_to_test_calls(migrated)
        self.assertEqual(second_count, 0)
        self.assertEqual(again, source)

    def test_ignores_nested_commas_inside_single_argument(self):
        source = "simulate_prepared(&build_request(a, b).unwrap()).unwrap();"
        migrated, count = add_explicit_mode_to_test_calls(source)
        self.assertEqual(count, 1)
        self.assertIn(
            "simulate_prepared(&build_request(a, b).unwrap(), "
            "forever_engine::RngMode::Stochastic)",
            migrated,
        )


if __name__ == "__main__":
    unittest.main()
