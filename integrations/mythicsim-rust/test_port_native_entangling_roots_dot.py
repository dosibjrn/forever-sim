#!/usr/bin/env python3
"""Fail-closed and idempotent native Rust source-port guards; not gate acceptance."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]
sys.path.insert(0, str(PROJECT))
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
            dest = root / "src/core/fight.rs"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("// native fight module\n")
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
            bridge = (root / "src/core/fight/world_bridge.rs").read_text()
            self.assertIn("queue_control_event", bridge)
            self.assertIn('kind: "control".to_owned()', bridge)
            self.assertIn("native_roots_control_bridge_tests", bridge)
            self.assertIn("native_root_control_is_emitted_on_land_and_absent_on_miss",
                          (root / "src/core/fight.rs").read_text())


    def test_native_root_event_freezes_and_expires_in_real_gsim_2d_world(self):
        from tools.wf_gsim_go_live_range_probe import diagnostic_gsim_world
        from src.game.runtime.go_native_world_damage_ack import GsimNativeDamageWorldApplier
        from src.game.runtime.native_step_protocol import snapshot_gsim_world, state_hash

        runtime = diagnostic_gsim_world()
        runtime.advance_to(1.0)
        before_distance = runtime._enemy_distance("m1")
        self.assertAlmostEqual(before_distance, 15.0)

        world_hash = state_hash(snapshot_gsim_world(runtime))
        tick = {
            "sequence": 0,
            "clock_ms": 1000,
            "native_clock_ns": 1_000_000_000,
            "selected_target_id": "m1",
            "world_sha256": world_hash,
        }
        event = {
            "event_id": "native-effect-1",
            "kind": "control",
            "native_time_ns": 1_000_000_000,
            "damage": 0.0,
            "source_action_id": "SpellID:9853",
            "rank": 0,
            "landed": True,
            "crit": False,
            "periodic": False,
            "native_target_index": 0,
            "native_target_unit_index": 0,
            "native_target_label": "Target",
            "native_caster_type": "",
            "native_caster_unit_index": 0,
            "native_caster_label": "",
            "control_id": "root",
            "duration_ns": 27_000_000_000,
        }
        response = {
            "sequence": 0,
            "native_process_id": 123,
            "observed_input_world_sha256": world_hash,
            "native_damage_events": [event],
        }
        ack = GsimNativeDamageWorldApplier(runtime).apply(tick, response)
        self.assertEqual(ack["applied_event_ids"], ["native-effect-1"])
        self.assertEqual(ack["applied_native_damage"], 0.0)
        self.assertTrue(ack["applied_controls"][0]["applied"])
        self.assertAlmostEqual(runtime.targets["m1"].active_controls["root"], 28.0)
        self.assertNotEqual(ack["world_after_sha256"], world_hash)

        runtime.advance_to(27.9)
        self.assertAlmostEqual(runtime._enemy_distance("m1"), before_distance)
        self.assertNotIn("m1", runtime._melee_targets)
        runtime.advance_to(30.0)
        self.assertNotIn("root", runtime.targets["m1"].active_controls)
        self.assertIn("m1", runtime._melee_targets)

    def test_missing_native_anchor_is_not_silently_accepted(self):
        path = "src/classes/druid/agent.rs"
        initial = "\n".join(old for old, _, _ in port.AGENT_PATCHES)
        with self.assertRaisesRegex(ValueError, "SOURCE_DRIFT"):
            port.port_text(path, initial.replace("    InsectSwarm,", "    Unexpected,"))


if __name__ == "__main__":
    unittest.main()
