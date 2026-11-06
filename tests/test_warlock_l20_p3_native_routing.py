"""Warlock L20 P3 must use selected native gear, not naked-kill discovery."""
from __future__ import annotations

import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from src.game.native_p3_item_options import NativeItemOptionsError
from tools.wf_gate_p3_live import run_live


class WarlockL20P3NativeRoutingTests(TestCase):
    def test_missing_native_binary_reports_correct_capability_not_actor_died(self):
        with patch.dict(os.environ, {}, clear=True):
            result = run_live(Path("."), "warlock", 20)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["reasons"], ["P3_NATIVE_ITEM_OPTIONS_BINARY_REQUIRED"])
        self.assertNotIn("actor_died", str(result))
        self.assertNotIn("source_naked_stage", result)

    def test_pinned_rust_refusal_replaces_naked_kill_false_gate(self):
        with patch.dict(os.environ, {
            "FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN": "/tmp/selected-forever-engine",
        }):
            with patch(
                "src.game.native_p3_item_options.query_native_p3_item_options",
                side_effect=NativeItemOptionsError(
                    "P3_NATIVE_ITEM_OPTIONS_REFUSED:NATIVE_ITEM_OPTIONS_UNSUPPORTED_CLASS"),
            ) as query:
                result = run_live(Path("."), "warlock", 20, spec="unrestricted")
        query.assert_called_once_with(
            "/tmp/selected-forever-engine", "warlock", 20,
            spec="unrestricted", slot="all",
        )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["real_source_search_attempts"], 0)
        self.assertEqual(result["reasons"], [
            "P3_NATIVE_ITEM_OPTIONS_REFUSED:NATIVE_ITEM_OPTIONS_UNSUPPORTED_CLASS",
        ])
        self.assertNotIn("BLOCKED_NO_NAKED_SUCCESS", str(result))

    def test_native_item_options_alone_cannot_award_p3_pass(self):
        with patch.dict(os.environ, {
            "FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN": "/tmp/selected-forever-engine",
        }):
            with patch(
                "src.game.native_p3_item_options.query_native_p3_item_options",
                return_value={"items": [{"item_id": 123}]},
            ):
                result = run_live(Path("."), "warlock", 20)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["native_item_candidate_count"], 1)
        self.assertEqual(result["reasons"], [
            "P3_WARLOCK_L20_NATIVE_EQUIPPED_SCORING_NOT_EXECUTED",
        ])
        self.assertEqual(result["real_source_search_evaluated"], 0)
