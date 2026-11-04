"""Forever-owned native result transport; no Warcraft mechanics revalidation."""
from __future__ import annotations

import copy
import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from subprocess import CompletedProcess

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import native_executor
from native_joint_two_class import native_payload, native_score_request
from native_l60_matrix import fingerprint


def _native_response():
    return {
        "result": {"raidMetrics": {
            "dps": {"avg": 27.5},
            "parties": [{"players": [{"actions": [
                {"id": {"spellId": 585}, "targets": [
                    {"casts": 2}, {"casts": 1}]},
                {"id": {"spellId": 585, "tag": 1}, "targets": [
                    {"casts": 4}]},
                {"id": {"spellId": 17}, "targets": [
                    {"casts": 0}]},
                {"id": {"spellId": 99}, "targets": [
                    {"casts": True}, {"casts": -2}]},
            ]}]}],
        }},
    }


class NativeL20PaidCastTransport(unittest.TestCase):
    def test_preserves_full_native_action_identity_and_positive_counts(self):
        raw = _native_response()
        before = copy.deepcopy(raw)
        self.assertEqual([
            {"id": {"spellId": 585}, "casts": 3},
            {"id": {"spellId": 585, "tag": 1}, "casts": 4},
        ], native_executor.native_action_cast_receipts(raw))
        self.assertEqual(before, raw)
        self.assertEqual([], native_executor.native_action_cast_receipts({}))
        self.assertEqual([], native_executor.native_action_cast_receipts(
            {"result": {"raidMetrics": {"parties": []}}}))

    def test_paid_native_joint_score_keeps_real_cast_receipts(self):
        request = {
            "raid": {"parties": [{"players": [
                {"class": "ClassPriest", "level": 20}]}]},
            "simOptions": {"iterations": 1, "randomSeed": "5"},
        }
        original = copy.deepcopy(request)
        observed = []

        def actual_native_contract(binary, candidate, iterations, seed,
                                   rng_mode, deadline, objective="DPS"):
            self.assertEqual(20, candidate["raid"]["parties"][0]["players"][0]["level"])
            self.assertEqual("balanced", rng_mode)
            self.assertEqual("DPS", objective)
            observed.append(fingerprint(native_payload(candidate, iterations, seed)))
            return 27.5, _native_response(), 0.01, observed[-1]

        record, raw = native_score_request(
            Path("/selected/forever-engine"), request, 2, 41, "balanced",
            time.monotonic() + 5, runner=actual_native_contract)
        self.assertEqual(original, request)
        self.assertEqual(1, len(observed))
        self.assertEqual(observed[0], record["effective_request_sha256"])
        self.assertEqual(27.5, record["score"])
        self.assertEqual(
            native_executor.native_action_cast_receipts(raw),
            record["native_action_cast_receipts"])
        self.assertEqual(2, len(record["native_action_cast_receipts"]))

    def test_selected_native_request_keeps_level_and_gate_flag(self):
        request = {
            "raid": {"parties": [{"players": [
                {"class": "ClassPriest", "level": 20}]}]},
            "simOptions": {"iterations": 1, "randomSeed": "5"},
        }
        original = copy.deepcopy(request)

        def fake_native(argv, **kwargs):
            self.assertIn("--gate", argv)
            self.assertEqual("balanced", argv[argv.index("--rng-mode") + 1])
            submitted = json.loads(
                Path(argv[argv.index("--request") + 1]).read_text())
            self.assertEqual(20, submitted["raid"]["parties"][0]["players"][0]["level"])
            self.assertEqual(2, submitted["simOptions"]["iterations"])
            self.assertEqual("41", submitted["simOptions"]["randomSeed"])
            Path(argv[argv.index("--outfile") + 1]).write_text(
                json.dumps(_native_response()))
            return CompletedProcess(argv, 0, "", "")

        with patch.object(native_executor.subprocess, "run",
                          side_effect=fake_native):
            score, report, elapsed, sha = native_executor.run(
                Path("/selected/forever-engine"), request, 2, 41, "balanced",
                time.monotonic() + 5)
        self.assertEqual(original, request)
        self.assertEqual(27.5, score)
        self.assertGreaterEqual(elapsed, 0)
        self.assertEqual(64, len(sha))
        self.assertEqual(2, len(native_executor.native_action_cast_receipts(report)))


if __name__ == "__main__":
    unittest.main()
