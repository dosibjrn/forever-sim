"""Production wrapper contract for balanced native JOINT receipts."""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_joint_two_class import fingerprint, native_payload, native_score_request


def request():
    return {
        "raid": {"parties": [{"players": [{
            "class": "ClassDruid",
            "equipment": {"items": [{"id": 1001}, {"id": 1002}]},
            "talentsString": "source-build",
            "rotation": {"priorityList": []},
        }]}]},
        "encounter": {"duration": 180, "targets": 1},
        "simOptions": {"iterations": 3, "randomSeed": "47"},
    }


class NativeJointScoringContracts(unittest.TestCase):
    def test_native_request_records_explicit_balanced_mode_and_raw_receipt(self):
        calls = []
        source = request()
        raw = {"result": {"raidMetrics": {"dps": {"avg": 123.5}}}}

        def fake_run(binary, candidate, iterations, seed, rng_mode, deadline):
            calls.append((binary, iterations, seed, rng_mode, deadline))
            return (123.5, raw, 0.0123,
                    fingerprint(native_payload(candidate, iterations, seed)))

        record, actual_raw = native_score_request(
            Path("forever-engine"), source, 40, 731, "balanced",
            time.monotonic() + 5.0, runner=fake_run,
        )
        self.assertEqual(1, len(calls))
        self.assertEqual("balanced", calls[0][3])
        self.assertEqual(40, calls[0][1])
        self.assertEqual(731, calls[0][2])
        self.assertEqual(123.5, record["score"])
        self.assertEqual("balanced", record["rng_mode"])
        self.assertEqual(fingerprint(native_payload(source, 40, 731)),
                         record["effective_request_sha256"])
        self.assertEqual(fingerprint(raw), record["raw_response_sha256"])
        self.assertIs(raw, actual_raw)

    def test_stochastic_mode_is_rejected_before_the_native_runner(self):
        calls = []

        def fake_run(*args):
            calls.append(args)
            raise AssertionError("stochastic must never reach optimizer scorer")

        with self.assertRaisesRegex(
            ValueError, "JOINT_OPTIMIZER_REQUIRES_EXPLICIT_BALANCED_RNG"
        ):
            native_score_request(
                Path("forever-engine"), request(), 40, 731, "stochastic",
                time.monotonic() + 5.0, runner=fake_run,
            )
        self.assertEqual([], calls)


if __name__ == "__main__":
    unittest.main()
