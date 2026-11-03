"""Only the Forever-owned native layout request/response contract is tested."""
from __future__ import annotations

import copy
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import json

from src.engine_client.native_talent_layout import (
    NativeTalentLayoutError,
    load_druid_talent_layout,
)


SAMPLE = {
    "schema_version": 1,
    "class": "druid",
    "ruleset": "forever",
    "trees": [
        {"key": "balance", "talents": [
            {"field": "native_first", "name": "First", "max_ranks": 5, "in_proto": True},
        ]},
        {"key": "feral", "talents": [
            {"field": "native_second", "name": "Second", "max_ranks": 1, "in_proto": False},
        ]},
    ],
}


class NativeLayoutWireTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.binary = Path(self.temp.name) / "forever-engine"
        self.binary.touch()

    def call(self, payload=SAMPLE, *, returncode=0):
        with patch(
            "src.engine_client.native_talent_layout.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=returncode,
                stdout=json.dumps(payload), stderr="native diagnostic",
            ),
        ) as run:
            if returncode:
                with self.assertRaisesRegex(
                    NativeTalentLayoutError, "NATIVE_TALENT_LAYOUT_CLI_REFUSED"
                ):
                    load_druid_talent_layout(self.binary)
                return
            layout = load_druid_talent_layout(self.binary)
            run.assert_called_once_with(
                [str(self.binary), "talent-layout", "--class", "druid"],
                capture_output=True, text=True, timeout=10.0, check=False,
            )
            return layout

    def test_preserves_native_order_and_metadata_without_legality_decision(self):
        layout = self.call()
        self.assertEqual(list(layout), ["balance", "feral"])
        self.assertEqual(layout["balance"][0]["field"], "native_first")
        self.assertEqual(layout["feral"][0]["max_ranks"], 1)
        self.assertIs(layout["feral"][0]["in_proto"], False)

    def test_native_refusal_is_not_replaced_with_python_source_fallback(self):
        self.call(returncode=3)

    def test_malformed_or_ambiguous_wire_is_rejected(self):
        cases = []
        duplicate = copy.deepcopy(SAMPLE)
        duplicate["trees"][1]["talents"][0]["field"] = "native_first"
        cases.append(duplicate)
        bool_rank = copy.deepcopy(SAMPLE)
        bool_rank["trees"][0]["talents"][0]["max_ranks"] = True
        cases.append(bool_rank)
        duplicate_tree = copy.deepcopy(SAMPLE)
        duplicate_tree["trees"][1]["key"] = "balance"
        cases.append(duplicate_tree)
        bad_version = copy.deepcopy(SAMPLE)
        bad_version["schema_version"] = 2
        cases.append(bad_version)
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(NativeTalentLayoutError):
                    self.call(case)

    def test_missing_binary_and_timeout_are_explicit(self):
        with self.assertRaisesRegex(NativeTalentLayoutError, "BINARY_MISSING"):
            load_druid_talent_layout(Path(self.temp.name) / "missing")
        with patch(
            "src.engine_client.native_talent_layout.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="forever-engine", timeout=0.1),
        ):
            with self.assertRaisesRegex(NativeTalentLayoutError, "CLI_FAILED:TimeoutExpired"):
                load_druid_talent_layout(self.binary, timeout_seconds=0.1)


if __name__ == "__main__":
    unittest.main()
