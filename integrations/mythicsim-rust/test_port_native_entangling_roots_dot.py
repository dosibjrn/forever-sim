#!/usr/bin/env python3
"""Fail-closed and idempotent native Rust source-port guards; not gate acceptance."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "native_roots_dot", ROOT / "port_native_entangling_roots_dot.py")
port = importlib.util.module_from_spec(spec)
spec.loader.exec_module(port)


class NativeRootsDotPortTest(unittest.TestCase):
    def test_all_source_anchors_apply_once_and_are_idempotent(self):
        patches = {
            "src/classes/druid/prepare/balance.rs": port.PREP_PATCHES,
            "src/classes/druid/agent.rs": port.AGENT_PATCHES,
            "src/classes/druid/prepared/coverage.rs": port.COVERAGE_PATCHES,
            "src/contracts/prepared_v2.rs": port.CONTRACT_PATCHES,
            "src/classes/druid/prepare/export.rs": port.EXPORT_PATCHES,
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path, rules in patches.items():
                dest = root / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text("\n".join(old for old, _, _ in rules))
            dest = root / "tests/classes/druid/prepare.rs"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("// native test suite\n")
            self.assertEqual(port.main(["port", tmp]), 0)
            first = {p: (root / p).read_bytes() for p in port.PATHS}
            self.assertEqual(port.main(["port", tmp]), 0)
            self.assertEqual(first, {p: (root / p).read_bytes() for p in port.PATHS})
            self.assertIn("0.25 * f64::from", (root / list(patches)[0]).read_text())
            self.assertIn("EntanglingRoots {}", (root / "src/contracts/prepared_v2.rs").read_text())
            self.assertIn('"kind": "entangling_roots"', (root / "src/classes/druid/prepare/export.rs").read_text())
            self.assertIn('"entangling_roots",', (root / "src/classes/druid/prepared/coverage.rs").read_text())

    def test_typed_rng_source_uses_explicit_mode_and_is_idempotent(self):
        typed_source = (
            "// typed RNG API already present in the selected engine" + chr(10)
            + "let report = forever_engine::simulate_prepared(&prepared, forever_engine::RngMode::Stochastic);" + chr(10)
        )
        first = port.port_text("tests/classes/druid/prepare.rs", typed_source)
        self.assertIn(port.RUST_RUNTIME_TEST_TYPED, first)
        self.assertNotIn(port.RUST_RUNTIME_TEST, first)
        self.assertEqual(first, port.port_text("tests/classes/druid/prepare.rs", first))

    def test_existing_typed_rank_runtime_test_is_recognized(self):
        existing = """fn forever_roots_native_periodic_ticks_change_with_rank() {
    let report = forever_engine::simulate_prepared(&prepared, forever_engine::RngMode::Stochastic);
    let (base, base_log) = run(0);
    let (improved, improved_log) = run(3);
    assert!(base_log.contains("Casting {SpellID: 9853}"));
    assert!(improved_log.contains("Casting {SpellID: 9853}"));
    assert!(improved > base);
}
"""
        result = port.port_text("tests/classes/druid/prepare.rs", existing)
        self.assertEqual(
            result.count("fn forever_roots_native_periodic_ticks_change_with_rank()"),
            1,
        )
        self.assertIn(port.RUST_TEST, result)
        self.assertEqual(
            result,
            port.port_text("tests/classes/druid/prepare.rs", result),
        )

    def test_conflicting_same_name_runtime_test_still_fails_closed(self):
        existing = (
            "fn forever_roots_native_periodic_ticks_change_with_rank() { "
            "assert!(true); }"
        )
        with self.assertRaisesRegex(
            ValueError, "NATIVE_ROOTS_TEST_SOURCE_DRIFT"
        ):
            port.port_text("tests/classes/druid/prepare.rs", existing)

    def test_missing_native_anchor_is_not_silently_accepted(self):
        path = "src/classes/druid/agent.rs"
        initial = "\n".join(old for old, _, _ in port.AGENT_PATCHES)
        with self.assertRaisesRegex(ValueError, "SOURCE_DRIFT"):
            port.port_text(path, initial.replace("    InsectSwarm,", "    Unexpected,"))


if __name__ == "__main__":
    unittest.main()
