#!/usr/bin/env python3
"""Exercise the thin P2 adapter against the exact selected Rust submodule."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from unittest.mock import patch
from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from src.engine_client.native_p2_rank_probe import (  # noqa: E402
    NativeP2ProbeError,
    NativeRngMode,
    _simulate_prepared,
    encode_native_druid_talents,
    prepare_native_request,
    parse_native_druid_layout,
    run_native_prepare_pair,
)

ENGINE_ROOT = Path(os.environ.get(
    "FOREVER_ENGINE_ROOT", str(Path(__file__).resolve().parents[1] / "engine")
))


class NativeP2PrepareAdapterTest(unittest.TestCase):
    def test_layout_uses_selected_rust_forever_trees_order(self):
        layout = parse_native_druid_layout(ENGINE_ROOT)
        self.assertEqual(layout["feral"][10]["field"], "predatory_strikes")
        self.assertEqual(layout["balance"][15]["field"], "moonkin_form")
        self.assertNotIn("max_rank", layout["balance"][15])

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
        # The public pair result intentionally keeps compact receipts under
        # before/after and exposes full prepared states under these private
        # diagnostic keys. Do not assume the compact receipt nests PreparedV2.
        self.assertEqual(result["before"]["status"], "PREPARED")
        self.assertEqual(result["after"]["status"], "PREPARED")
        self.assertTrue(result["before"]["prepared_sha256"])
        self.assertTrue(result["after"]["prepared_sha256"])
        before_prepared = result["_before_prepared"]
        after_prepared = result["_after_prepared"]
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


    def test_wire_encoder_does_not_reject_native_owned_talent_rank(self):
        # Check only that the adapter can serialize a single-digit rank;
        # MythicSim alone decides whether that rank is game-legal.
        encoded = encode_native_druid_talents({"moonkin_form": 2}, ENGINE_ROOT)
        self.assertEqual(encoded.split("-")[0][-1], "2")

    def test_prepare_adapter_preserves_structured_native_refusal_category(self):
        # These are synthetic *native response envelopes*. Do not retest
        # MythicSim's Warcraft legality, e.g. a specific talent rank cap.
        fixture = ENGINE_ROOT / "tests/classes/druid/prepare/balance.request.json"
        request = json.loads(fixture.read_text(encoding="utf-8"))
        cases = (
            ("talents", "INVALID"),
            ("request", "INVALID"),
            ("rotation_unsupported", "UNSUPPORTED"),
            ("prepare_fault", "ERROR"),
        )
        # prepare_native_request checks that the binary path exists before
        # invoking subprocess.run; a temporary file keeps this a boundary-only
        # test without requiring or validating a real MythicSim executable.
        with tempfile.TemporaryDirectory(prefix="native-p2-mock-") as directory:
            binary = Path(directory) / "forever-engine"
            binary.touch()
            for native_code, expected in cases:
                with self.subTest(native_code=native_code):
                    native_refusal = {
                        "prepared": False,
                        "refusal": {
                            "code": native_code,
                            "reason": "native-owned reason",
                        },
                    }
                    with patch(
                        "src.engine_client.native_p2_rank_probe.subprocess.run",
                        return_value=subprocess.CompletedProcess(
                            args=["forever-engine", "prepare"],
                            returncode=3,
                            stdout=json.dumps(native_refusal),
                            stderr="",
                        ),
                    ):
                        result = prepare_native_request(
                            binary=binary,
                            request=request,
                            scenario="native-refusal-wire-contract",
                            deadline=time.monotonic() + 60,
                        )
                    self.assertEqual(result["status"], expected, result)
                    self.assertEqual(result["refusal"]["code"], native_code)
                    self.assertEqual(result["reason"], "native-owned reason")

    def _simulate_with_cli_result(self, returncode, report):
        with patch(
            "src.engine_client.native_p2_rank_probe.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=["forever-engine", "sim"], returncode=returncode,
                stdout=json.dumps(report), stderr="",
            ),
        ):
            return _simulate_prepared(
                binary_path=Path("/selected/engine/target/debug/forever-engine"),
                prepared={"sim": {"iterations": 1, "seed": 647003}},
                rng_mode=NativeRngMode.BALANCED,
                iterations=1,
                seed=647003,
                deadline=time.monotonic() + 60,
            )

    def test_sim_unsupported_requires_native_refusal_exit_and_complete_coverage(self):
        report = {
            "scenario_id": "native-p2-test",
            "supported": False,
            "reasons": ["rotation_unsupported: test fixture"],
            "refusals": [{"code": "rotation_unsupported", "reason": "test fixture"}],
        }
        result = self._simulate_with_cli_result(3, report)
        self.assertEqual(result["status"], "UNSUPPORTED", result)
        self.assertEqual(result["coverage"], report)

    def test_sim_does_not_infer_unsupported_from_malformed_or_wrong_exit(self):
        explicit_refusal = {
            "scenario_id": "native-p2-test",
            "supported": False,
            "reasons": ["rotation_unsupported: test fixture"],
            "refusals": [{"code": "rotation_unsupported", "reason": "test fixture"}],
        }
        cases = (
            (1, explicit_refusal),  # process fault, not the Rust gate-refusal exit
            (3, {  # refusal exit with a contradictory supported result
                "scenario_id": "native-p2-test", "supported": True,
                "reasons": [], "refusals": [],
            }),
            (3, {  # incomplete coverage envelope
                "scenario_id": "native-p2-test", "supported": False,
                "reasons": ["rotation_unsupported: test fixture"],
            }),
        )
        for returncode, report in cases:
            with self.subTest(returncode=returncode, report=report):
                result = self._simulate_with_cli_result(returncode, report)
                self.assertEqual(result["status"], "ERROR", result)
                self.assertEqual(
                    result["reason"], "NATIVE_SIM_FAILED_WITHOUT_STRUCTURED_COVERAGE"
                )

    def test_rank_pair_rejects_changes_outside_the_target_rank_before_execution(self):
        before = {
            "ferocity": 5,
            "feral_swiftness": 2,
            "feral_instinct": 3,
            "thick_hide": 5,
        }
        # The candidate changes the target rank and an unrelated talent rank.
        after = {
            **before,
            "feral_swiftness": 3,
            "predatory_strikes": 1,
        }
        with self.assertRaisesRegex(
            NativeP2ProbeError, "NATIVE_P2_PAIR_CHANGES_MORE_THAN_TARGET"
        ):
            run_native_prepare_pair(
                binary=Path("/not-built/forever-engine"),
                engine_root=ENGINE_ROOT,
                scenario="cat",
                before_selection=before,
                after_selection=after,
                target_talent_id="predatory_strikes",
                target_rank=1,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
