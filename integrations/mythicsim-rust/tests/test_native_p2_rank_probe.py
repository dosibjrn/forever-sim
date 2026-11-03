#!/usr/bin/env python3
"""Exercise the thin P2 adapter against the exact selected Rust submodule."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from src.game.native_p2_rank_probe import (  # noqa: E402
    parse_native_druid_layout,
    run_native_prepare_pair,
)

ENGINE_ROOT = Path(__file__).resolve().parents[1] / "engine"


class NativeP2PrepareAdapterTest(unittest.TestCase):
    def test_layout_uses_selected_rust_forever_trees_order(self):
        layout = parse_native_druid_layout(ENGINE_ROOT)
        self.assertEqual(layout["feral"][10]["field"], "predatory_strikes")
        self.assertEqual(layout["balance"][15]["field"], "moonkin_form")

    def test_predatory_strikes_rank_pair_uses_native_prepare_cli(self):
        binary = Path(os.environ.get("FOREVER_ENGINE_BINARY", ""))
        if not binary.is_file():
            self.skipTest("FOREVER_ENGINE_BINARY is not built in this test run")

        # The selected Rust engine's own regression uses these first 15 Feral
        # points to reach Predatory Strikes' third-tier row. The pair changes
        # only the one source rank under test.
        before = {
            "ferocity": 5,
            "furor": 5,
            "feral_swiftness": 2,
            "feral_instinct": 3,
        }
        after = {**before, "predatory_strikes": 1}
        result = run_native_prepare_pair(
            binary=binary,
            engine_root=ENGINE_ROOT,
            scenario="cat",
            before_selection=before,
            after_selection=after,
            target_talent_id="predatory_strikes",
            target_rank=1,
        )

        self.assertEqual(result["status"], "PREPARED", result)
        self.assertFalse(result["accepted_for_p2"])
        self.assertTrue(result["engine_identity"])
        before_prepared = result["before"]["prepared"]
        after_prepared = result["after"]["prepared"]
        self.assertEqual(
            before_prepared["player"]["talents"].get("predatory_strikes", 0), 0
        )
        self.assertEqual(
            after_prepared["player"]["talents"].get("predatory_strikes", 0), 1
        )
        self.assertGreater(
            after_prepared["player"]["stats"]["AttackPower"],
            before_prepared["player"]["stats"]["AttackPower"],
        )
        self.assertEqual(
            before_prepared["reference"]["engine_revision"],
            after_prepared["reference"]["engine_revision"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
