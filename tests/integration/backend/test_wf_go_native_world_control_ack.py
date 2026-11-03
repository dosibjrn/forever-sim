from __future__ import annotations

import math

import pytest

from src.game.runtime.go_native_world_damage_ack import (
    GsimNativeDamageWorldApplier,
    NativeDamageWorldApplicationError,
)
from src.game.runtime.native_step_protocol import snapshot_gsim_world, state_hash
from tools.wf_gsim_go_live_range_probe import diagnostic_gsim_world


def _world_and_tick():
    world = diagnostic_gsim_world(
        target_spawn_yards=20.0,
        enemy_move_speed_yards_s=5.0,
        target_health=1000.0,
        source_single_target=True,
        source_in_front_of_target=True,
    )
    world.advance_to(2.0)
    snapshot = snapshot_gsim_world(world)
    digest = state_hash(snapshot)
    tick = {
        "sequence": 0,
        "clock_ms": snapshot["clock_ms"],
        "native_clock_ns": snapshot["clock_ms"] * 1_000_000,
        "selected_target_id": snapshot["selected_target_id"],
        "world_sha256": digest,
    }
    return world, tick, digest


def _root_event(*, landed: bool = True, duration_ns: int = 3_000_000_000):
    return {
        "event_id": "native-control-1",
        "native_time_ns": 2_000_000_000,
        "duration_ns": duration_ns,
        "control_id": "root",
        "source_action_id": "SpellID:9853",
        "rank": 0,
        "landed": landed,
        "native_target_index": 0,
        "native_target_unit_index": 0,
        "native_target_label": "native-target",
    }


def _distance(world, target_id: str) -> float:
    x, y = world._enemy_position_at(target_id)
    return math.hypot(x, y)


def test_landed_native_roots_control_freezes_real_2d_target_until_native_expiry():
    world, tick, digest = _world_and_tick()
    target_id = tick["selected_target_id"]
    position_at_apply = _distance(world, target_id)
    assert position_at_apply < 20.0

    applier = GsimNativeDamageWorldApplier(world)
    ack = applier.apply(tick, {
        "sequence": 0,
        "native_process_id": 77,
        "observed_input_world_sha256": digest,
        "native_damage_events": [],
        "native_control_events": [_root_event()],
    })

    assert ack["applied_control_event_ids"] == ["native-control-1"]
    assert ack["applied_control_events"][0]["applied"] is True
    assert world.targets[target_id].active_controls["root"] == pytest.approx(5.0)

    world.advance_to(4.0)
    assert _distance(world, target_id) == pytest.approx(position_at_apply, abs=1e-6)

    world.advance_to(5.0)
    assert "root" not in world.targets[target_id].active_controls
    world.advance_to(6.0)
    assert _distance(world, target_id) < position_at_apply - 1.0


def test_absent_native_roots_control_leaves_2d_approach_running():
    world, tick, digest = _world_and_tick()
    target_id = tick["selected_target_id"]
    position_at_tick = _distance(world, target_id)

    applier = GsimNativeDamageWorldApplier(world)
    ack = applier.apply(tick, {
        "sequence": 0,
        "native_process_id": 78,
        "observed_input_world_sha256": digest,
        "native_damage_events": [],
        "native_control_events": [],
    })

    assert ack["applied_control_event_ids"] == []
    world.advance_to(3.0)
    assert _distance(world, target_id) < position_at_tick


def test_unlanded_native_roots_control_is_rejected_before_world_mutation():
    world, tick, digest = _world_and_tick()
    target_id = tick["selected_target_id"]
    before = state_hash(snapshot_gsim_world(world))

    applier = GsimNativeDamageWorldApplier(world)
    with pytest.raises(NativeDamageWorldApplicationError, match="NOT_LANDED_ROOT"):
        applier.apply(tick, {
            "sequence": 0,
            "native_process_id": 79,
            "observed_input_world_sha256": digest,
            "native_damage_events": [],
            "native_control_events": [_root_event(landed=False)],
        })

    assert state_hash(snapshot_gsim_world(world)) == before
    assert "root" not in world.targets[target_id].active_controls
