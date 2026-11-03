"""Native failure receipts preserve non-object JSON responses for audit.

The native executor can return malformed stdout (a string) or parse valid JSON
that is not an object (for example, a list). Both are execution errors, and
Forever must retain the original payload rather than silently dropping it.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "integrations" / "mythicsim-rust"))

import native_executor as native_exec
from native_joint_two_class import _write_native_failure, fingerprint


class NativeExecutorFailureReceiptMaintenance(unittest.TestCase):
    def test_non_object_native_responses_are_preserved_in_failure_receipts(self):
        effective = {"simOptions": {"iterations": 40, "randomSeed": "731"}}
        request_sha = fingerprint(effective)
        raw_values = ("malformed native stdout", ["native", "non-object", "response"])

        for raw in raw_values:
            with self.subTest(raw_type=type(raw).__name__):
                with tempfile.TemporaryDirectory() as directory:
                    exc = native_exec.NativeExecutionError(
                        "native response was not an object",
                        raw_response=raw,
                        elapsed_s=0.125,
                        request_sha256=request_sha,
                        returncode=0,
                        stdout=raw if isinstance(raw, str) else json.dumps(raw),
                        stderr="",
                    )
                    receipt = _write_native_failure(
                        Path(directory), request_sha, effective, exc
                    )
                    response_path = Path(directory) / (
                        "failed_" + request_sha + ".response.json"
                    )
                    request_path = Path(directory) / ("failed_" + request_sha + ".json")

                    self.assertTrue(response_path.is_file())
                    self.assertEqual(
                        raw, json.loads(response_path.read_text(encoding="utf-8"))
                    )
                    self.assertEqual(
                        effective, json.loads(request_path.read_text(encoding="utf-8"))
                    )
                    self.assertEqual(fingerprint(raw), receipt["raw_response_sha256"])
                    self.assertEqual(response_path.name, receipt["response_file"])
                    self.assertEqual(0.125, receipt["native_duration_s"])
                    self.assertEqual("ERROR", receipt["native_status"])
