"""Fail-closed source-port tests for required typed Rust RNG callsites."""
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from port_native_typed_rng import (
    add_explicit_mode_to_test_calls, edit, migrate_test_simulate_calls,
    one_or_paid_recovery_descendant,
)
from port_native_paid_recovery import (
    CLASSES_SIGNATURE_TYPED_NEW,
    PREPARED_SIGNATURE_TYPED_NEW,
    PREPARED_CALL_TYPED_NEW,
    CLI_TYPED_NEW,
)


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

    def test_accepts_only_exact_typed_paid_recovery_descendants(self):
        """The final RNG audit runs after paid recovery and must remain fail-closed."""
        cases = (
            (
                "classes.rs",
                "    target_count: usize,\n) -> Result<serde_json::Value, String> {",
                "    target_count: usize,\n    rng_mode: crate::core::rng::RngMode,\n) -> Result<serde_json::Value, String> {",
                CLASSES_SIGNATURE_TYPED_NEW,
            ),
            (
                "prepared-signature.rs",
                "pub fn native_two_world_targets(prepared: &PreparedV2, target_count: usize)",
                "pub fn native_two_world_targets(prepared: &PreparedV2, target_count: usize, rng_mode: crate::core::rng::RngMode)",
                PREPARED_SIGNATURE_TYPED_NEW,
            ),
            (
                "prepared-call.rs",
                "crate::classes::native_two_world_targets(prepared, target_count)",
                "crate::classes::native_two_world_targets(prepared, target_count, rng_mode)",
                PREPARED_CALL_TYPED_NEW,
            ),
            (
                "main-condition.rs",
                'if args.len() != 5 || args[1] != "--infile" || args[3] != "--targets" {',
                'if args.len() != 7 || args[1] != "--infile" || args[3] != "--targets" || args[5] != "--rng-mode" {',
                CLI_TYPED_NEW,
            ),
            (
                "main-call.rs",
                "let report = native_two_world_targets(&prepared, target_count)",
                "let mode = RngMode::parse_cli(&args[6])?;\\n        let report = native_two_world_targets(&prepared, target_count, mode)",
                CLI_TYPED_NEW,
            ),
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name, old, new, paid in cases:
                path = root / name
                path.write_text(paid)
                one_or_paid_recovery_descendant(root, name, old, new, paid)
                self.assertEqual(path.read_text(), paid)
                forged = paid.replace("recovery_ns: i64", "forged_ns: i64", 1)
                path.write_text(forged)
                with self.assertRaises(RuntimeError):
                    one_or_paid_recovery_descendant(root, name, old, new, paid)


if __name__ == "__main__":
    unittest.main()
