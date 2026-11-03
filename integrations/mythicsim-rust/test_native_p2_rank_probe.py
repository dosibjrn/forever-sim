#!/usr/bin/env python3
"""Selected-pinned-Rust integration tests for the source-legal P2 probe slice."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.wf_gate_p2_native import (  # noqa: E402
    DEFAULT_DB,
    build_source_legal_rank_pair,
    load_source_positions,
    parse_druid_rust_layout,
    run_smoke,
    serialize_source_allocation,
    validate_source_layout,
)


class NativeP2RankProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        engine_root = os.environ.get("FOREVER_MYTHICSIM_RUST_ROOT")
        engine_binary = os.environ.get("FOREVER_MYTHICSIM_RUST_BIN")
        if not engine_root or not engine_binary:
            raise unittest.SkipTest("selected Rust engine root/binary not supplied")
        cls.engine_root = Path(engine_root).resolve()
        cls.engine_binary = Path(engine_binary).resolve()
        cls.source_data, _ = load_source_positions(DEFAULT_DB, 60)
        cls.layout = parse_druid_rust_layout(cls.engine_root)
        validate_source_layout(cls.source_data, cls.layout)
        cls.report = run_smoke(cls.engine_root, cls.engine_binary, DEFAULT_DB, 60)

    def test_selected_rust_layout_not_legacy_python_positions(self) -> None:
        feral = self.layout["feral"]
        restoration = self.layout["restoration"]
        balance = self.layout["balance"]
        self.assertEqual(feral[10]["field"], "predatory_strikes")
        self.assertEqual(feral[1]["field"], "furor")
        self.assertEqual(restoration[1]["field"], "heart_of_the_wild")
        self.assertEqual(balance[15]["field"], "moonkin_form")
        self.assertEqual(feral[11]["kind"], "new_talent")
        self.assertEqual(feral[12]["kind"], "new_talent")
        self.assertEqual(restoration[7]["kind"], "new_talent")

    def test_source_legal_rank_pairs_serialize_into_native_positions(self) -> None:
        before, after = build_source_legal_rank_pair(
            self.source_data, "predatory_strikes", 1, level=60
        )
        before_string = serialize_source_allocation(self.source_data, self.layout, before)
        after_string = serialize_source_allocation(self.source_data, self.layout, after)
        self.assertEqual(after_string.split("-")[1][10], "1")
        self.assertEqual(before_string.split("-")[1][10], "0")

        before, after = build_source_legal_rank_pair(
            self.source_data, "moonkin_form", 1, level=60
        )
        before_string = serialize_source_allocation(self.source_data, self.layout, before)
        after_string = serialize_source_allocation(self.source_data, self.layout, after)
        self.assertEqual(after_string.split("-")[0][15], "1")
        self.assertEqual(before_string.split("-")[0][15], "0")

    def test_selected_rust_prepare_emits_four_rank_receipts_without_gate_credit(self) -> None:
        self.assertEqual(self.report["scope"], "NATIVE_P2_RANK_PROBE_DIAGNOSTIC_NOT_GATE")
        self.assertEqual(self.report["production_engine"], "msim")
        self.assertEqual(self.report["pass_count"], 4)
        self.assertEqual(self.report["applicable_probe_count"], 4)
        self.assertTrue(all(row["status"] == "PASS" for row in self.report["rank_results"]))
        self.assertFalse(self.report["p2_gate_acceptance"])
        self.assertFalse(self.report["m1_recording"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
