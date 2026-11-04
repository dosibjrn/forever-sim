"""Fail-closed source-port tests for required typed Rust RNG callsites."""
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from port_native_typed_rng import (add_explicit_mode_to_test_calls, edit,
                                   ensure_rng_mode_import, migrate_test_simulate_calls)


class TypedRngImportTests(unittest.TestCase):
    def test_adds_mode_to_multiline_legacy_import_and_is_idempotent(self):
        source = (
            "use forever_engine::{\\n"
            "    PreparedError, Refusal,\\n"
            "    Request, Rules, SOURCE_REVISION,\\n"
            "};\\n"
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            path = root / "src/main.rs"
            path.write_text(source)
            ensure_rng_mode_import(root, "src/main.rs")
            migrated = path.read_text()
            self.assertIn("Request, RngMode, Rules", migrated)
            ensure_rng_mode_import(root, "src/main.rs")
            self.assertEqual(path.read_text(), migrated)

    def test_accepts_existing_wrapped_mode_import_unchanged(self):
        source = (
            "use forever_engine::{\\n"
            "    PreparedError, Refusal,\\n"
            "    Request, RngMode, Rules, SOURCE_REVISION,\\n"
            "};\\n"
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            path = root / "src/main.rs"
            path.write_text(source)
            ensure_rng_mode_import(root, "src/main.rs")
            self.assertEqual(path.read_text(), source)


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


    def test_nested_source_anchor_is_idempotent(self):
        """Already-published typed Rust must not gain a duplicate enum."""
        old = "pub(crate) enum RandomRequest { Uniform01, Bernoulli(f64) }"
        new = old + "\n#[derive(Clone, Copy)] pub enum RngMode { Balanced, Stochastic }"
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src/core").mkdir(parents=True)
            path = root / "src/core/rng.rs"
            path.write_text(old)
            edit(root, "src/core/rng.rs", [(old, new, 1)])
            self.assertEqual(path.read_text(), new)
            edit(root, "src/core/rng.rs", [(old, new, 1)])
            self.assertEqual(path.read_text(), new)

    def test_selected_rust_test_call_migration_is_idempotent(self):
        """A fork-sync retry must accept previously migrated Rust tests."""
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tests").mkdir()
            path = root / "tests/explicit.rs"
            path.write_text("let result = simulate_prepared(&prepared);\n")
            first = migrate_test_simulate_calls(root)
            self.assertEqual(first, [("tests/explicit.rs", 1)])
            migrated = path.read_text()
            self.assertIn("forever_engine::RngMode::Stochastic", migrated)
            self.assertEqual(migrate_test_simulate_calls(root), [])
            self.assertEqual(path.read_text(), migrated)


if __name__ == "__main__":
    unittest.main()
