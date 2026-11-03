"""Production wrapper contract for balanced native JOINT receipts."""
from __future__ import annotations

import json
import random
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import p73_talent_search_v2 as p73
from native_joint_two_class import (
    _ensure_native_damage_action, _native_positive_source_casts,
    _write_native_failure, fingerprint, native_payload, native_score_request,
)


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


class NativeDamageAPLAnchorContracts(unittest.TestCase):
    @staticmethod
    def source(spell_id, *, conditional=False):
        action = {"castSpell": {"spellId": {"spellId": spell_id}}}
        if conditional:
            action["condition"] = {"cmp": {"lhs": {"currentManaPercent": {}},
                                             "op": "OpLt",
                                             "rhs": {"const": {"val": "10%"}}}}
        return {"action": action}

    @staticmethod
    def native_response(damaging_id):
        return {"result": {"raidMetrics": {"parties": [{"players": [{
            "actions": [
                {"id": {"spellId": 11689}, "targets": [{"casts": 80}]},
                {"id": {"spellId": damaging_id},
                 "targets": [{"casts": 10, "damage": 800.0}]},
            ]
        }]}]}}}

    def test_warlock_life_tap_only_policy_gets_source_native_damage_action(self):
        # The real #41632564319 artifact contains six 40/40 zero-DPS
        # Warlock policies; Life Tap 11689 was an unconditional non-damage cast.
        source = [self.source(11689), self.source(11713, conditional=True)]
        receipt = self.native_response(11713)
        witnesses = _native_positive_source_casts(source, receipt)
        self.assertEqual([{"spellId": 11713}], witnesses)
        candidate = [self.source(11689) for _ in range(20)]
        repaired = _ensure_native_damage_action(candidate, witnesses, random.Random(1))
        self.assertEqual(20, len(repaired))
        self.assertEqual({"spellId": 11713},
                         repaired[0]["action"]["castSpell"]["spellId"])
        self.assertNotIn("condition", repaired[0]["action"])
        self.assertEqual(20, len(_ensure_native_damage_action(
            repaired, witnesses, random.Random(1))))
        self.assertEqual(11689, candidate[0]["action"]["castSpell"]["spellId"]["spellId"])

    def test_rogue_stealth_and_vanish_cannot_be_only_unconditional_casts(self):
        # The real Rogue failed receipt has unconditional Vanish/Stealth/Slice
        # and Dice, but no unconditional spell with positive native damage.
        source = [self.source(1856), self.source(1784),
                  self.source(11281, conditional=True)]
        witnesses = _native_positive_source_casts(source, self.native_response(11281))
        self.assertEqual([{"spellId": 11281}], witnesses)
        candidate = [self.source(1856), self.source(1784)]
        repaired = _ensure_native_damage_action(candidate, witnesses, random.Random(2))
        self.assertEqual(11281, repaired[0]["action"]["castSpell"]["spellId"]["spellId"])

    def test_existing_positive_cast_moves_to_front_without_duplication(self):
        witnesses = [{"spellId": 11713}]
        actions = [self.source(11689), self.source(11713)]
        repaired = _ensure_native_damage_action(actions, witnesses, random.Random(3))
        self.assertEqual([11713, 11689],
                         [a["action"]["castSpell"]["spellId"]["spellId"] for a in repaired])

    def test_no_paid_native_damage_receipt_does_not_invent_witness(self):
        source = [self.source(11689), self.source(11713, conditional=True)]
        zero = {"result": {"raidMetrics": {"parties": [{"players": [{
            "actions": [{"id": {"spellId": 11713},
                         "targets": [{"casts": 40, "damage": 0.0}]}]
        }]}]}}}
        self.assertEqual([], _native_positive_source_casts(source, zero))
        candidate = [self.source(11689), self.source(11689)]
        self.assertIs(candidate, _ensure_native_damage_action(
            candidate, [], random.Random(4)))


class NativeExecutionErrorReporting(unittest.TestCase):
    def test_missing_dps_average_preserves_raw_native_response(self):
        source = request()
        raw = {"result": {"raidMetrics": {"dps": {"aggregatorData": {"n": 0}}}}}

        def write_output(args, **kwargs):
            output = Path(args[args.index("--outfile") + 1])
            output.write_text(json.dumps(raw))
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        with patch.object(p73.subprocess, "run", side_effect=write_output):
            with self.assertRaises(p73.NativeScoreExtractionError) as raised:
                p73.run(
                    Path("native"), source, 40, 731, "balanced",
                    time.monotonic() + 5.0,
                )

        self.assertEqual(raw, raised.exception.raw_response)
        self.assertIn("result.raidMetrics.dps.avg", str(raised.exception))
        self.assertGreaterEqual(raised.exception.elapsed_s, 0.0)
        self.assertTrue(raised.exception.request_sha256)

    def test_failed_score_extraction_writes_request_and_raw_response_receipts(self):
        effective = native_payload(request(), 40, 731)
        key = fingerprint(effective)
        raw = {"result": {"raidMetrics": {"dps": {"aggregatorData": {"n": 0}}}}}
        exc = p73.NativeScoreExtractionError(
            "missing avg", raw_response=raw, elapsed_s=0.012,
            request_sha256=key,
        )

        with tempfile.TemporaryDirectory() as directory:
            outdir = Path(directory)
            receipt = _write_native_failure(outdir, key, effective, exc)
            request_path = outdir / ("failed_" + key + ".json")
            response_path = outdir / ("failed_" + key + ".response.json")

            self.assertEqual(effective, json.loads(request_path.read_text()))
            self.assertEqual(raw, json.loads(response_path.read_text()))
            self.assertEqual(fingerprint(raw), receipt["raw_response_sha256"])
            self.assertEqual(response_path.name, receipt["response_file"])
            self.assertNotIn("score", receipt)

    def test_failed_native_execution_preserves_returncode_stdout_and_stderr(self):
        completed = subprocess.CompletedProcess(
            args=["native"], returncode=7,
            stdout="native stdout detail",
            stderr="native stderr detail",
        )
        with patch.object(p73.subprocess, "run", return_value=completed) as run:
            with self.assertRaises(RuntimeError) as raised:
                p73.run(
                    Path("native"), {"simOptions": {}}, 40, 731, "balanced",
                    time.monotonic() + 5.0,
                )
        message = str(raised.exception)
        self.assertIn("returncode=7", message)
        self.assertIn("output_exists=False", message)
        self.assertIn("native stdout detail", message)
        self.assertIn("native stderr detail", message)
        self.assertIs(run.call_args.kwargs["stdout"], subprocess.PIPE)
        self.assertIs(run.call_args.kwargs["stderr"], subprocess.PIPE)


if __name__ == "__main__":
    unittest.main()
