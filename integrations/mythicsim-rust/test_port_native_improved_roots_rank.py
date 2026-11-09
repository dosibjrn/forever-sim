#!/usr/bin/env python3
"""Strict source-port regression: rank intake is real Rust, not a Python game model."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "native_improved_roots_rank", ROOT / "port_native_improved_roots_rank.py"
)
port = importlib.util.module_from_spec(spec)
spec.loader.exec_module(port)


class ImprovedRootsRankSourcePortTest(unittest.TestCase):
    def test_first_application_and_idempotent_second(self):
        initial = "\n".join((port.COMMENT_OLD, port.FIELD_OLD, port.READ_OLD))
        changed = port.port_text(initial)
        self.assertNotEqual(initial, changed)
        self.assertEqual(changed, port.port_text(changed))
        self.assertIn("pub improved_entangling_roots: i32", changed)
        self.assertIn('improved_entangling_roots: m.i32("improved_entangling_roots")', changed)
        self.assertIn("effect\n/// remains unmodelled", changed)
        self.assertIn("fn native_improved_roots_rank_intake()", changed)
        self.assertIn(port.RUST_TEST, changed)
        self.assertNotIn("native_improved_roots_rank_intake_moonkin_form_behavior", changed)
        self.assertNotIn("native_improved_roots_rank_intake_predatory_strikes_behavior", changed)
        self.assertIn('"0000004"', changed)

    def test_existing_rank_port_stays_intact_without_retired_p2_injection(self):
        initial = "\n".join((port.COMMENT_NEW, port.FIELD_NEW, port.READ_NEW))
        initial += "\n\n" + port.RUST_TEST
        self.assertEqual(port.port_text(initial), initial)
        self.assertNotIn("native_improved_roots_rank_intake_moonkin_form_behavior",
                         port.port_text(initial))
        self.assertNotIn("native_improved_roots_rank_intake_predatory_strikes_behavior",
                         port.port_text(initial))

    def test_previously_published_extended_rank_test_is_not_rewritten(self):
        initial = "\n".join((port.COMMENT_NEW, port.FIELD_NEW, port.READ_NEW))
        legacy = port.RUST_TEST[:-1] + (
            "    #[test]\n"
            "    fn native_improved_roots_rank_intake_moonkin_form_behavior() {}\n"
            "}\n"
        )
        source = initial + "\n\n" + legacy
        self.assertEqual(port.port_text(source), source)

    def test_missing_source_anchor_fails_closed(self):
        initial = "\n".join((port.COMMENT_OLD, port.FIELD_OLD, port.READ_OLD))
        with self.assertRaisesRegex(ValueError, "SOURCE_DRIFT"):
            port.port_text(initial.replace(port.READ_OLD, "unexpected reader"))
        with self.assertRaisesRegex(ValueError, "SOURCE_DRIFT"):
            port.port_text(initial.replace(port.FIELD_OLD, "unexpected field schema"))

    def test_real_filesystem_target_and_second_application(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "src/classes/druid/prepare/talents.rs"
            path.parent.mkdir(parents=True)
            path.write_text("\n".join((port.COMMENT_OLD, port.FIELD_OLD, port.READ_OLD)))
            self.assertEqual(port.main(["port", directory]), 0)
            first = path.read_bytes()
            self.assertEqual(port.main(["port", directory]), 0)
            self.assertEqual(first, path.read_bytes())


if __name__ == "__main__":
    unittest.main()
