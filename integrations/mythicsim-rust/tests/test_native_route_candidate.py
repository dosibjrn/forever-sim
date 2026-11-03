"""Forever-owned regressions for the neutral native candidate boundary."""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.engine_client import native_candidate_client
from src.engine_client import native_route_candidate


def _request() -> dict:
    return {
        "simOptions": {
            "iterations": 3000,
            "randomSeed": "42",
            "debugFirstIteration": True,
        },
        "raid": {
            "parties": [
                {
                    "players": [
                        {
                            "class": "ClassDruid",
                            "talentsString": "0" * 60,
                            "rotation": {"type": "Simple", "priorityList": []},
                        }
                    ]
                }
            ]
        },
    }


def _world_report(target_count: int = 100) -> dict:
    windows = []
    kills = []
    for index in range(target_count):
        kill_ns = (index + 1) * 1_000_000_000
        windows.append({"index": index, "native_kill_ns": kill_ns})
        kills.append(
            {
                "target_id": f"mob-{index}",
                "world_kill_clock_ns": kill_ns,
                "ack_sha256": f"{index + 1:064x}",
            }
        )
    return {
        "world_targets_killed": target_count,
        "continuous_native_actor": True,
        "actual_2d_ack": True,
        "native_damage_events": target_count,
        "world_ticks": target_count,
        "native_gsim_moving_ticks": target_count - 1,
        "native_moving_receipts": target_count,
        "native_movement_cast_legal": True,
        "gsim_world_walk_steps": target_count - 1,
        "gsim_route_legs": [{} for _ in range(target_count - 1)],
        "gsim_route_paid_receipts": [{} for _ in range(target_count - 1)],
        "gsim_route_paid_movement_s": float(target_count - 1),
        "world_target_hp": 100.0,
        "native_windows": windows,
        "world_kills": kills,
        "world_elapsed_seconds": float(target_count * 2),
        "world_seconds_per_target_without_paid_recovery": 2.0,
        "world_per_target_elapsed_seconds_without_paid_recovery": [2.0] * target_count,
        "native_actor_mana_after_world_kills": [100.0 - index for index in range(target_count)],
        "native_actor_mana_delta_between_world_kills": [-1.0] * (target_count - 1),
        "minimum_native_actor_mana": 1.0,
        "minimum_native_actor_health": 400.0,
        "paid_recovery": False,
        "world_target_provenance": {
            "kind": "caller_supplied_diagnostic_hp",
            "verified_forever_mob": False,
        },
        "checkpoint_certified": False,
    }


class NativeCandidateClientTests(unittest.TestCase):
    def test_prepare_forwards_scenario_and_preserves_native_prepared_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "forever-engine"
            binary.write_bytes(b"test binary")
            request = _request()
            original = json.loads(json.dumps(request))
            scenario = "druid-l60-route-candidate"
            prepared_output = {
                "schema_version": 2,
                "contract": "forever-prepared",
                "scenario_id": scenario,
                "request_sha256": "a" * 64,
                "reference": {"engine_revision": "selected-rust-sha"},
                "player": {
                    "talents_string": request["raid"]["parties"][0]["players"][0]["talentsString"],
                    "talents": {"balance": {}, "feral": {}, "restoration": {}},
                },
            }

            def fake_run(command, **kwargs):
                self.assertEqual(command[1], "prepare")
                self.assertEqual(command[command.index("--scenario") + 1], scenario)
                submitted = json.loads(
                    Path(command[command.index("--request") + 1]).read_text()
                )
                self.assertFalse(submitted["simOptions"]["debugFirstIteration"])
                self.assertEqual(submitted["simOptions"]["iterations"], 3000)
                Path(command[command.index("--outfile") + 1]).write_text(
                    json.dumps(prepared_output)
                )
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch.object(native_candidate_client.subprocess, "run", side_effect=fake_run):
                result = native_candidate_client.prepare_native_request(
                    binary=binary,
                    request=request,
                    scenario=scenario,
                    deadline=time.monotonic() + 30,
                )

            self.assertEqual(result["status"], "PREPARED")
            self.assertEqual(result["engine_identity"], "selected-rust-sha")
            self.assertEqual(result["request_sha256"], "a" * 64)
            self.assertEqual(request, original)

    def test_native_prepare_unsupported_is_not_relabelled_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "forever-engine"
            binary.write_bytes(b"test binary")
            request = _request()
            scenario = "native-unsupported-candidate"
            refusal = {
                "prepared": False,
                "refusal": {
                    "code": "unsupported_mechanic",
                    "reason": "native mechanic coverage is unavailable",
                },
            }
            with patch.object(
                native_candidate_client.subprocess,
                "run",
                return_value=SimpleNamespace(
                    returncode=2,
                    stdout=json.dumps(refusal),
                    stderr="",
                ),
            ) as run:
                result = native_candidate_client.prepare_native_request(
                    binary=binary,
                    request=request,
                    scenario=scenario,
                    deadline=time.monotonic() + 30,
                )
            self.assertEqual(result["status"], "UNSUPPORTED")
            self.assertEqual(result["reason"], "native mechanic coverage is unavailable")
            self.assertEqual(run.call_args.args[0][run.call_args.args[0].index("--scenario") + 1], scenario)

    def test_prepare_rejects_prepared_scenario_identity_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "forever-engine"
            binary.write_bytes(b"test binary")
            request = _request()
            prepared_output = {
                "schema_version": 2,
                "contract": "forever-prepared",
                "scenario_id": "wrong-scenario",
                "request_sha256": "a" * 64,
                "reference": {"engine_revision": "selected-rust-sha"},
                "player": {
                    "talents_string": request["raid"]["parties"][0]["players"][0]["talentsString"],
                    "talents": {"balance": {}, "feral": {}, "restoration": {}},
                },
            }

            def fake_run(command, **kwargs):
                Path(command[command.index("--outfile") + 1]).write_text(
                    json.dumps(prepared_output)
                )
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch.object(native_candidate_client.subprocess, "run", side_effect=fake_run):
                result = native_candidate_client.prepare_native_request(
                    binary=binary,
                    request=request,
                    scenario="expected-scenario",
                    deadline=time.monotonic() + 30,
                )
            self.assertEqual(result["status"], "ERROR")
            self.assertEqual(result["reason"], "NATIVE_PREPARE_OUTPUT_CONTRACT_MISMATCH")

    def test_native_prepare_refusal_is_authoritative_and_never_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            engine_root = Path(directory) / "engine"
            binary = engine_root / "target" / "release" / "forever-engine"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"test binary")
            with (
                patch.object(
                    native_route_candidate,
                    "prepare_native_request",
                    return_value={"status": "INVALID", "stage": "prepare", "reason": "native refusal"},
                ),
                patch.object(native_route_candidate, "_simulate_prepared") as simulate,
                patch.object(native_route_candidate, "_run_world_bridge") as world,
            ):
                result = native_route_candidate.run_native_route_candidate(
                    binary=binary,
                    engine_root=engine_root,
                    request=_request(),
                    scenario="route-invalid-candidate",
                    mob_health=100.0,
                )
            self.assertEqual(result["status"], "INVALID")
            self.assertEqual(result["native_validation_status"], "INVALID")
            self.assertFalse(result["python_fallback"])
            self.assertFalse(result["checkpoint_certified"])
            simulate.assert_not_called()
            world.assert_not_called()

    def test_native_unsupported_execution_is_preserved_without_world_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            engine_root = Path(directory) / "engine"
            binary = engine_root / "target" / "release" / "forever-engine"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"test binary")
            prepared = {
                "status": "PREPARED",
                "engine_identity": "selected-rust-sha",
                "request_sha256": "a" * 64,
                "prepared_sha256": "b" * 64,
                "prepared": {"contract": "forever-prepared"},
            }
            with (
                patch.object(native_route_candidate, "prepare_native_request", return_value=prepared),
                patch.object(
                    native_route_candidate,
                    "_simulate_prepared",
                    return_value={"status": "UNSUPPORTED", "stage": "sim", "reason": "native coverage refusal"},
                ),
                patch.object(native_route_candidate, "_run_world_bridge") as world,
            ):
                result = native_route_candidate.run_native_route_candidate(
                    binary=binary,
                    engine_root=engine_root,
                    request=_request(),
                    scenario="route-unsupported-candidate",
                    mob_health=100.0,
                )
            self.assertEqual(result["status"], "UNSUPPORTED")
            self.assertEqual(result["native_validation_status"], "VALID")
            self.assertEqual(result["native_execution_status"], "UNSUPPORTED")
            self.assertFalse(result["python_fallback"])
            world.assert_not_called()

    def test_native_score_requires_exact_100_target_2d_ack_lineage(self):
        with tempfile.TemporaryDirectory() as directory:
            engine_root = Path(directory) / "engine"
            binary = engine_root / "target" / "release" / "forever-engine"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"test binary")
            request = _request()
            original = json.loads(json.dumps(request))
            prepared = {
                "status": "PREPARED",
                "engine_identity": "selected-rust-sha",
                "request_sha256": "a" * 64,
                "prepared_sha256": "b" * 64,
                "prepared": {"contract": "forever-prepared", "sim": {"iterations": 5}},
            }
            simulated = {
                "status": "EXECUTED",
                "dps": 1234.5,
                "iterations_done": 5,
                "report_sha256": "c" * 64,
            }
            world = _world_report(100)
            with (
                patch.object(native_route_candidate, "prepare_native_request", return_value=prepared) as prepare,
                patch.object(native_route_candidate, "_simulate_prepared", return_value=simulated) as simulate,
                patch.object(native_route_candidate, "_run_world_bridge", return_value=world) as bridge,
            ):
                result = native_route_candidate.run_native_route_candidate(
                    binary=binary,
                    engine_root=engine_root,
                    request=request,
                    scenario="druid-l60-route-candidate",
                    mob_health=100.0,
                    iterations=5,
                    seed=647003,
                    target_count=100,
                )

            self.assertEqual(result["status"], "SCORED")
            self.assertEqual(result["native_validation_status"], "VALID")
            self.assertEqual(result["native_execution_status"], "EXECUTED")
            self.assertEqual(result["native_score_dps"], 1234.5)
            self.assertEqual(result["iterations_done"], 5)
            self.assertEqual(result["world_execution"]["world_targets_killed"], 100)
            self.assertTrue(result["world_execution"]["actual_2d_ack"])
            self.assertTrue(result["world_execution"]["continuous_native_actor"])
            self.assertFalse(result["python_fallback"])
            self.assertFalse(result["cross_level_resource_carry_verified"])
            self.assertFalse(result["route_transition_supported"])
            self.assertFalse(result["checkpoint_certified"])
            self.assertEqual(request, original)

            submitted = prepare.call_args.kwargs["request"]
            self.assertEqual(submitted["simOptions"]["iterations"], 5)
            self.assertEqual(submitted["simOptions"]["randomSeed"], "647003")
            self.assertFalse(submitted["simOptions"]["debugFirstIteration"])
            self.assertEqual(simulate.call_args.kwargs["rng_mode"], native_route_candidate.NativeRngMode.BALANCED)
            self.assertEqual(bridge.call_args.kwargs["target_count"], 100)
            self.assertEqual(bridge.call_args.kwargs["mob_health"], 100.0)

    def test_missing_2d_ack_rejects_candidate_even_after_native_dps(self):
        with tempfile.TemporaryDirectory() as directory:
            engine_root = Path(directory) / "engine"
            binary = engine_root / "target" / "release" / "forever-engine"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"test binary")
            prepared = {
                "status": "PREPARED",
                "engine_identity": "selected-rust-sha",
                "request_sha256": "a" * 64,
                "prepared_sha256": "b" * 64,
                "prepared": {"contract": "forever-prepared"},
            }
            simulated = {"status": "EXECUTED", "dps": 1234.5, "iterations_done": 1}
            world = _world_report(100)
            world["actual_2d_ack"] = False
            with (
                patch.object(native_route_candidate, "prepare_native_request", return_value=prepared),
                patch.object(native_route_candidate, "_simulate_prepared", return_value=simulated),
                patch.object(native_route_candidate, "_run_world_bridge", return_value=world),
            ):
                result = native_route_candidate.run_native_route_candidate(
                    binary=binary,
                    engine_root=engine_root,
                    request=_request(),
                    scenario="route-no-2d-ack",
                    mob_health=100.0,
                )
            self.assertEqual(result["status"], "ERROR")
            self.assertEqual(result["stage"], "world")
            self.assertEqual(result["native_score_dps"], 1234.5)
            self.assertFalse(result["python_fallback"])
            self.assertFalse(result["checkpoint_certified"])

    def test_binary_outside_selected_engine_root_is_not_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            engine_root = Path(directory) / "engine"
            outside = Path(directory) / "unselected" / "forever-engine"
            outside.parent.mkdir()
            outside.write_bytes(b"test binary")
            with patch.object(native_route_candidate, "prepare_native_request") as prepare:
                result = native_route_candidate.run_native_route_candidate(
                    binary=outside,
                    engine_root=engine_root,
                    request=_request(),
                    scenario="route-unselected-engine",
                    mob_health=100.0,
                )
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["reason"], "NATIVE_BINARY_OUTSIDE_SELECTED_ENGINE_ROOT")
            prepare.assert_not_called()


class SelectedRustRouteCandidateIntegrationTests(unittest.TestCase):
    def test_druid_l60_candidate_scores_and_executes_100_2d_targets(self):
        binary_value = os.environ.get("FOREVER_ENGINE_BINARY")
        if not binary_value:
            self.skipTest("FOREVER_ENGINE_BINARY is not set")
        binary = Path(binary_value).resolve()
        engine_root = ROOT / "integrations" / "mythicsim-rust" / "engine"
        request_path = engine_root / "tests" / "classes" / "druid" / "prepare" / "balance.request.json"
        self.assertTrue(binary.is_file(), binary)
        self.assertTrue(request_path.is_file(), request_path)
        request = json.loads(request_path.read_text(encoding="utf-8"))

        result = native_route_candidate.run_native_route_candidate(
            binary=binary,
            engine_root=engine_root,
            request=request,
            scenario="work1-druid-l60-balance-native-route-candidate",
            mob_health=100.0,
            iterations=1,
            seed=647003,
            target_count=100,
            timeout_seconds=240,
        )

        self.assertEqual(result["status"], "SCORED", result)
        self.assertEqual(result["native_validation_status"], "VALID", result)
        self.assertEqual(result["native_execution_status"], "EXECUTED", result)
        self.assertTrue(math.isfinite(result["native_score_dps"]))
        self.assertGreater(result["native_score_dps"], 0)
        self.assertEqual(result["iterations_done"], 1)
        world = result["world_execution"]
        self.assertEqual(world["world_targets_killed"], 100)
        self.assertTrue(world["continuous_native_actor"])
        self.assertTrue(world["actual_2d_ack"])
        self.assertGreaterEqual(world["native_damage_events"], 100)
        self.assertGreaterEqual(world["world_ticks"], 100)
        self.assertGreater(world["native_gsim_moving_ticks"], 0)
        self.assertTrue(world["native_movement_cast_legal"])
        self.assertEqual(world["gsim_route_legs"], 99)
        self.assertEqual(world["gsim_route_paid_receipts"], 99)
        self.assertGreater(world["gsim_route_paid_movement_s"], 0)
        self.assertGreater(world["world_seconds_per_target_without_paid_recovery"], 0)
        self.assertAlmostEqual(
            world["world_seconds_per_target_without_paid_recovery"],
            world["world_elapsed_seconds"] / 100,
        )
        self.assertEqual(len(world["native_actor_mana_after_world_kills"]), 100)
        self.assertEqual(len(world["native_actor_mana_delta_between_world_kills"]), 99)
        self.assertGreater(world["minimum_native_actor_health"], 0)
        self.assertFalse(result["cross_level_resource_carry_verified"])
        self.assertFalse(result["route_transition_supported"])
        self.assertFalse(result["checkpoint_certified"])
        self.assertFalse(result["python_fallback"])
        self.assertFalse(world["paid_recovery"])
        self.assertEqual(world["world_target_hp"], 100.0)
        self.assertEqual(world["target_provenance"]["source_status"], "synthetic_diagnostic")
        self.assertGreater(world["world_seconds_per_target_without_paid_recovery"], 0)
        self.assertIsInstance(world["target_provenance"], dict)


if __name__ == "__main__":
    unittest.main(verbosity=2)
