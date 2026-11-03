#!/usr/bin/env python3
"""Fail-closed and idempotent native Rust source-port guards; not gate acceptance."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

from src.game.runtime.go_native_world_damage_ack import (
    GsimNativeDamageWorldApplier, NativeDamageWorldApplicationError,
)
from src.game.runtime.native_step_protocol import snapshot_gsim_world, state_hash
from tools.wf_gsim_go_live_range_probe import diagnostic_gsim_world

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "native_roots_dot", ROOT / "port_native_entangling_roots_dot.py")
port = importlib.util.module_from_spec(spec)
spec.loader.exec_module(port)


class NativeRootsDotPortTest(unittest.TestCase):
    def test_all_source_anchors_apply_once_and_are_idempotent(self):
        patches = {
            "src/classes/druid/prepare/balance.rs": port.PREP_PATCHES,
            "src/classes/druid/agent.rs": port.AGENT_PATCHES,
            "src/classes/druid/prepared/coverage.rs": port.COVERAGE_PATCHES,
            "src/contracts/prepared_v2.rs": port.CONTRACT_PATCHES,
            "src/classes/druid/prepare/export.rs": port.EXPORT_PATCHES,
            "src/core/fight/world_bridge.rs": port.WORLD_BRIDGE_PATCHES,
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path, rules in patches.items():
                dest = root / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text("\n".join(old for old, _, _ in rules))
            dest = root / "tests/classes/druid/prepare.rs"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("// native test suite\n")
            self.assertEqual(port.main(["port", tmp]), 0)
            first = {p: (root / p).read_bytes() for p in port.PATHS}
            self.assertEqual(port.main(["port", tmp]), 0)
            self.assertEqual(first, {p: (root / p).read_bytes() for p in port.PATHS})
            self.assertIn("0.25 * f64::from", (root / list(patches)[0]).read_text())
            self.assertIn("EntanglingRoots {}", (root / "src/contracts/prepared_v2.rs").read_text())
            self.assertIn('"kind": "entangling_roots"', (root / "src/classes/druid/prepare/export.rs").read_text())
            self.assertIn('"entangling_roots",', (root / "src/classes/druid/prepared/coverage.rs").read_text())

    def _tick_response(self, runtime, sequence, *, root_expiry_ns, root_changed_at_ns):
        world = snapshot_gsim_world(runtime)
        clock_ms = world["clock_ms"]
        tick = {
            "sequence": sequence,
            "native_clock_ns": clock_ms * 1_000_000,
            "clock_ms": clock_ms,
            "selected_target_id": world["selected_target_id"],
            "world_sha256": state_hash(world),
        }
        response = {
            "sequence": sequence,
            "native_process_id": 7001,
            "observed_input_world_sha256": tick["world_sha256"],
            "native_damage_events": [],
            "native_range_receipt": {
                "native_rooted_until_ns": root_expiry_ns,
                "native_root_control_changed_at_ns": root_changed_at_ns,
            },
        }
        return tick, response

    def test_native_root_control_freezes_then_releases_real_moving_target(self):
        runtime = diagnostic_gsim_world(
            target_spawn_yards=20., enemy_move_speed_yards_s=5.,
            target_health=1_000_000., source_single_target=True,
        )
        runtime.advance_to(1.0)
        moving_position = runtime.enemy_positions_yards["m1"][0]
        self.assertLess(moving_position, 20.)

        applier = GsimNativeDamageWorldApplier(runtime)
        tick, response = self._tick_response(
            runtime, 0, root_expiry_ns=3_000_000_000,
            root_changed_at_ns=1_000_000_000,
        )
        ack = applier.apply(tick, response)
        self.assertTrue(ack["world_target_rooted"])
        self.assertEqual(ack["native_rooted_until_ns"], 3_000_000_000)
        rooted_position = runtime.enemy_positions_yards["m1"][0]

        runtime.advance_to(2.0)
        self.assertAlmostEqual(runtime.enemy_positions_yards["m1"][0], rooted_position, delta=1e-6)
        tick, response = self._tick_response(
            runtime, 1, root_expiry_ns=3_000_000_000,
            root_changed_at_ns=None,
        )
        self.assertTrue(applier.apply(tick, response)["world_target_rooted"])

        # gsim's scheduled ControlExpired event runs at the native dot expiry.
        runtime.advance_to(3.0)
        tick, response = self._tick_response(
            runtime, 2, root_expiry_ns=None,
            root_changed_at_ns=3_000_000_000,
        )
        expiry_ack = applier.apply(tick, response)
        self.assertFalse(expiry_ack["world_target_rooted"])
        runtime.advance_to(4.0)
        self.assertLess(runtime.enemy_positions_yards["m1"][0], rooted_position)

    def test_missed_roots_negative_control_does_not_stop_target_motion(self):
        runtime = diagnostic_gsim_world(
            target_spawn_yards=20., enemy_move_speed_yards_s=5.,
            target_health=1_000_000., source_single_target=True,
        )
        runtime.advance_to(1.0)
        before = runtime.enemy_positions_yards["m1"][0]
        applier = GsimNativeDamageWorldApplier(runtime)
        tick, response = self._tick_response(
            runtime, 0, root_expiry_ns=None, root_changed_at_ns=None,
        )
        ack = applier.apply(tick, response)
        self.assertFalse(ack["world_target_rooted"])
        runtime.advance_to(2.0)
        self.assertLess(runtime.enemy_positions_yards["m1"][0], before)

    def test_early_native_root_clear_fails_closed_until_break_rules_are_sourced(self):
        runtime = diagnostic_gsim_world(
            target_spawn_yards=20., enemy_move_speed_yards_s=5.,
            target_health=1_000_000., source_single_target=True,
        )
        runtime.advance_to(1.0)
        applier = GsimNativeDamageWorldApplier(runtime)
        tick, response = self._tick_response(
            runtime, 0, root_expiry_ns=3_000_000_000,
            root_changed_at_ns=1_000_000_000,
        )
        applier.apply(tick, response)
        runtime.advance_to(2.0)
        tick, response = self._tick_response(
            runtime, 1, root_expiry_ns=None,
            root_changed_at_ns=2_000_000_000,
        )
        with self.assertRaisesRegex(
                NativeDamageWorldApplicationError,
                "WORLD_ROOT_CONTROL_EARLY_CLEAR_UNSUPPORTED"):
            applier.apply(tick, response)

    def test_missing_native_anchor_is_not_silently_accepted(self):
        path = "src/classes/druid/agent.rs"
        initial = "\n".join(old for old, _, _ in port.AGENT_PATCHES)
        with self.assertRaisesRegex(ValueError, "SOURCE_DRIFT"):
            port.port_text(path, initial.replace("    InsectSwarm,", "    Unexpected,"))


if __name__ == "__main__":
    unittest.main()
