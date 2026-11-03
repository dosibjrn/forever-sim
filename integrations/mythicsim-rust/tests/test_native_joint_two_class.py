"""Production wrapper contract for balanced native JOINT receipts."""
from __future__ import annotations

import sys
import time
import unittest
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_joint_two_class import (
    fingerprint, native_payload, native_score_request, select_balanced_winner,
)
from p73_talent_search_v2 import run as native_run


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

    def test_native_runner_surfaces_stdout_and_stderr_on_failure(self):
        completed = SimpleNamespace(
            returncode=2,
            stdout="RUST_NATIVE_BASELINE_REJECTED",
            stderr="native stderr detail",
        )
        with patch("p73_talent_search_v2.subprocess.run", return_value=completed) as mocked:
            with self.assertRaisesRegex(RuntimeError, "RUST_NATIVE_BASELINE_REJECTED") as caught:
                native_run(
                    Path("forever-engine"), request(), 40, 731, "balanced",
                    time.monotonic() + 5.0,
                )
        self.assertIn("native stderr detail", str(caught.exception))
        args, kwargs = mocked.call_args
        self.assertEqual(subprocess.PIPE, kwargs["stdout"])
        self.assertIn("--rng-mode", args[0])
        self.assertEqual("balanced", args[0][-1])

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


class NativeJointWinnerSelectionContracts(unittest.TestCase):
    def test_baseline_wins_when_best_search_candidate_is_worse(self):
        reference = request()
        candidate = request()
        candidate["raid"]["parties"][0]["players"][0]["talentsString"] = "search-build"

        selected, score, source = select_balanced_winner(
            reference, {"rng_mode": "balanced", "score": 123.5}, candidate, 110.0
        )

        self.assertIs(reference, selected)
        self.assertEqual(123.5, score)
        self.assertEqual("baseline", source)

    def test_search_candidate_wins_only_when_it_beats_baseline(self):
        reference = request()
        candidate = request()
        candidate["raid"]["parties"][0]["players"][0]["talentsString"] = "search-build"

        selected, score, source = select_balanced_winner(
            reference, {"rng_mode": "balanced", "score": 123.5}, candidate, 124.0
        )

        self.assertIs(candidate, selected)
        self.assertEqual(124.0, score)
        self.assertEqual("search", source)

    def test_baseline_wins_on_tie_or_empty_search(self):
        reference = request()
        candidate = request()

        for search_candidate, search_score in ((candidate, 123.5), (None, None)):
            selected, score, source = select_balanced_winner(
                reference, {"rng_mode": "balanced", "score": 123.5},
                search_candidate, search_score,
            )
            self.assertIs(reference, selected)
            self.assertEqual(123.5, score)
            self.assertEqual("baseline", source)

    def test_non_balanced_baseline_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError, "JOINT_OPTIMIZER_REQUIRES_EXPLICIT_BALANCED_RNG"
        ):
            select_balanced_winner(
                request(), {"rng_mode": "stochastic", "score": 123.5},
                request(), 124.0,
            )


if __name__ == "__main__":
    unittest.main()
