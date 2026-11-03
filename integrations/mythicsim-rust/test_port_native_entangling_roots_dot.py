#!/usr/bin/env python3
"""Fail-closed and idempotent native Rust source-port guards; not gate acceptance."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.game.model import ActorDefinition, ResourceDefinition
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.game.runtime.go_native_world_damage_ack import (
    GsimNativeDamageWorldApplier,
    NativeDamageWorldApplicationError,
)
from src.game.runtime.native_step_protocol import snapshot_gsim_world, state_hash

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "native_roots_dot", ROOT / "port_native_entangling_roots_dot.py")
port = importlib.util.module_from_spec(spec)
spec.loader.exec_module(port)


class NativeRootsDotPortTest(unittest.TestCase):
    def test_all_source_anchors_apply_once_and_are_idempotent(self):
        patches = {
            "src/core/fight.rs": port.FIGHT_PATCHES,
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
            self.assertIn("0.25 * f64::from", (root / "src/classes/druid/prepare/balance.rs").read_text())
            self.assertIn("EntanglingRoots {}", (root / "src/contracts/prepared_v2.rs").read_text())
            self.assertIn('"kind": "entangling_roots"', (root / "src/classes/druid/prepare/export.rs").read_text())
            self.assertIn('"entangling_roots",', (root / "src/classes/druid/prepared/coverage.rs").read_text())
            agent = (root / "src/classes/druid/agent.rs").read_text()
            bridge = (root / "src/core/fight/world_bridge.rs").read_text()
            fight = (root / "src/core/fight.rs").read_text()
            self.assertIn("pub(crate) rank: i32", fight)
            self.assertIn("rank: exported.rank", fight)
            self.assertIn("world_bridge::record_control", agent)
            self.assertIn("mod forever_roots_native_control_tests", agent)
            self.assertIn("crate::RngMode::Balanced", agent)
            self.assertIn('control_id: Some("root".to_owned())', bridge)
            self.assertIn('"native_control_events": control_events', bridge)
            self.assertIn('ack["acknowledged_control_event_ids"]', bridge)
            self.assertIn("RUST_WORLD_CONTROL_ACK_EVENTS_MISMATCH", bridge)

    def test_missing_native_anchor_is_not_silently_accepted(self):
        path = "src/classes/druid/agent.rs"
        initial = "\n".join(old for old, _, _ in port.AGENT_PATCHES)
        with self.assertRaisesRegex(ValueError, "SOURCE_DRIFT"):
            port.port_text(path, initial.replace("    InsectSwarm,", "    Unexpected,"))


    @staticmethod
    def _moving_world():
        actor = ActorState.from_ir(
            ActorDefinition("hero", "player", base_stats={}),
            (ResourceDefinition("health", "Health", "hero",
                                initial_amount=500, capacity=500),), ())
        positions = {"m0": (20.0, 0.0), "m1": (20.0, 5.0)}
        world = CombatRuntime(
            actor=actor,
            target=TargetState.with_health("m0", 1000.0),
            other_targets=(TargetState.with_health("m1", 1000.0),),
            spatial_positions_yards=positions,
            enemy_move_speed_yards_s=7.0,
            melee_radius_yards=5.0,
        )
        for target_id, (x, y) in positions.items():
            world.targets[target_id].metadata["facing_xy_yards"] = (-x, -y)
        world.engage_target("m0")
        world.select_target("m0")
        return world

    @staticmethod
    def _control_event(duration_ns=1_000_000_000):
        return {
            "event_id": "native-effect-1",
            "effect_kind": "control",
            "control_id": "root",
            "duration_ns": duration_ns,
            "break_semantics_status": "unimplemented",
            "native_time_ns": 100_000_000,
            "damage": 0.0,
            "source_action_id": "SpellID: 9853",
            "rank": 6,
            "landed": True,
            "crit": False,
            "periodic": False,
            "native_target_index": 0,
            "native_target_unit_index": 0,
            "native_target_label": "Target 1",
            "native_caster_type": "",
            "native_caster_unit_index": 0,
            "native_caster_label": "",
        }

    def test_native_root_control_freezes_and_resumes_real_2d_enemy_motion(self):
        world = self._moving_world()
        world.advance_to(0.1)
        frozen_position = world._enemy_position_at("m0")
        snapshot = snapshot_gsim_world(world)
        digest = state_hash(snapshot)
        tick = {
            "sequence": 0,
            "native_clock_ns": 100_000_000,
            "clock_ms": 100,
            "world_sha256": digest,
            "selected_target_id": "m0",
        }
        response = {
            "sequence": 0,
            "native_process_id": 12345,
            "observed_input_world_sha256": digest,
            "native_damage_events": [],
            "native_control_events": [self._control_event()],
        }
        applier = GsimNativeDamageWorldApplier(world)
        ack = applier.apply(tick, response)
        self.assertEqual(ack["applied_event_ids"], ["native-effect-1"])
        self.assertEqual(ack["acknowledged_control_event_ids"], ["native-effect-1"])
        self.assertEqual(ack["applied_control_event_ids"], ["native-effect-1"])
        self.assertNotEqual(ack["world_before_sha256"], ack["world_after_sha256"])
        self.assertEqual(ack["root_break_semantics"], "unimplemented")
        self.assertIn("root", world.targets["m0"].active_controls)

        world.advance_to(0.6)
        while_rooted = world._enemy_position_at("m0")
        self.assertAlmostEqual(while_rooted[0], frozen_position[0], places=6)
        self.assertAlmostEqual(while_rooted[1], frozen_position[1], places=6)

        world.advance_to(1.1)
        world.advance_to(1.6)
        after_expiry = world._enemy_position_at("m0")
        self.assertLess(after_expiry[0], while_rooted[0],
                        "enemy movement must resume when the native root duration expires")

    def test_invalid_native_root_rank_is_rejected_before_world_mutation(self):
        world = self._moving_world()
        world.advance_to(0.1)
        digest = state_hash(snapshot_gsim_world(world))
        tick = {
            "sequence": 0,
            "native_clock_ns": 100_000_000,
            "clock_ms": 100,
            "world_sha256": digest,
            "selected_target_id": "m0",
        }
        event = self._control_event()
        event["rank"] = 0
        response = {
            "sequence": 0,
            "native_process_id": 12345,
            "observed_input_world_sha256": digest,
            "native_damage_events": [],
            "native_control_events": [event],
        }
        with self.assertRaisesRegex(
                NativeDamageWorldApplicationError,
                "WORLD_DAMAGE_ACK_CONTROL_EVENT_INVALID"):
            GsimNativeDamageWorldApplier(world).apply(tick, response)
        self.assertNotIn("root", world.targets["m0"].active_controls)
        self.assertEqual(state_hash(snapshot_gsim_world(world)), digest)


    def test_invalid_native_root_control_is_rejected_before_world_mutation(self):
        world = self._moving_world()
        world.advance_to(0.1)
        digest = state_hash(snapshot_gsim_world(world))
        tick = {
            "sequence": 0,
            "native_clock_ns": 100_000_000,
            "clock_ms": 100,
            "world_sha256": digest,
            "selected_target_id": "m0",
        }
        response = {
            "sequence": 0,
            "native_process_id": 12345,
            "observed_input_world_sha256": digest,
            "native_damage_events": [],
            "native_control_events": [self._control_event(duration_ns=0)],
        }
        with self.assertRaisesRegex(
                NativeDamageWorldApplicationError,
                "WORLD_DAMAGE_ACK_CONTROL_EVENT_INVALID"):
            GsimNativeDamageWorldApplier(world).apply(tick, response)
        self.assertNotIn("root", world.targets["m0"].active_controls)
        self.assertEqual(state_hash(snapshot_gsim_world(world)), digest)


    def test_pre_pull_root_expired_before_first_world_ack_is_consumed_not_extended(self):
        world = self._moving_world()
        digest = state_hash(snapshot_gsim_world(world))
        tick = {
            "sequence": 0,
            "native_clock_ns": 0,
            "clock_ms": 0,
            "world_sha256": digest,
            "selected_target_id": "m0",
        }
        event = self._control_event(duration_ns=27_000_000_000)
        event["native_time_ns"] = -30_000_000_000
        response = {
            "sequence": 0,
            "native_process_id": 12345,
            "observed_input_world_sha256": digest,
            "native_damage_events": [],
            "native_control_events": [event],
        }
        ack = GsimNativeDamageWorldApplier(world).apply(tick, response)
        self.assertEqual(ack["acknowledged_control_event_ids"], ["native-effect-1"])
        self.assertEqual(ack["applied_control_event_ids"], [])
        self.assertEqual(
            ack["acknowledged_control_events"][0]["world_application_status"],
            "expired_before_world_ack",
        )
        self.assertNotIn("root", world.targets["m0"].active_controls)
        self.assertEqual(ack["world_before_sha256"], ack["world_after_sha256"])


if __name__ == "__main__":
    unittest.main()
