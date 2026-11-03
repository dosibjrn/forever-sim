from __future__ import annotations

import pytest

from src.game.runtime.go_world_range_feed import GsimGoRangeFeed
from src.game.runtime.native_roots_world_ack import GsimNativeRootsWorldApplier
from tools.wf_gsim_go_live_range_probe import diagnostic_gsim_world


def _range_receipt(tick):
    receipt = {
        "sequence": tick["sequence"],
        "native_clock_ns": tick["native_clock_ns"],
        "player_index": 0,
        "applied_yards": tick["distance_yards"],
        "native_encounter_damage": 0.0,
        "facing_applied": tick["facing_applied"],
    }
    if tick["facing_applied"]:
        receipt["in_front_of_target"] = tick["in_front_of_target"]
    return receipt


def _native_receipt(tick, events):
    return {
        "sequence": tick["sequence"],
        "native_process_id": 123,
        "observed_input_world_sha256": tick["world_sha256"],
        "native_damage_events": [],
        "native_control_events": events,
    }


def _event(ordinal, kind, *, landed=None, expiry=None, time_ns=0):
    return {
        "event_id": f"native-control-{ordinal}",
        "event_kind": kind,
        "native_time_ns": time_ns,
        "control_id": "root",
        "landed": landed,
        "expires_at_ns": expiry,
        "source_action_id": "spell:9853",
        "source_rank_spell_id": 9853,
        "native_target_index": 0,
        "native_target_unit_index": 0,
        "native_target_label": "Target",
    }


def _world():
    runtime = diagnostic_gsim_world(
        target_spawn_yards=15.0,
        enemy_move_speed_yards_s=5.0,
        target_health=100_000.0,
        source_single_target=True,
    )
    return runtime, GsimGoRangeFeed(runtime, native_player_index=0), GsimNativeRootsWorldApplier(runtime)


def test_native_root_control_freezes_real_2d_motion_and_releases_at_source_expiry():
    runtime, feed, applier = _world()

    # The initial boundary is ACKed before the native cast resolves. The
    # landed attempt then needs a second, same-clock causal ACK.
    first = feed.next_tick()
    feed.accept_range_receipt(_range_receipt(first))
    ack0 = applier.apply(first, _native_receipt(first, []))
    assert ack0["applied_control_event_ids"] == []

    same_clock = feed.next_tick(allow_same_clock=True)
    assert same_clock["clock_ms"] == first["clock_ms"] == 0
    feed.accept_range_receipt(_range_receipt(same_clock))
    events = [_event(1, "attempt", landed=True), _event(2, "apply", landed=True, expiry=3_000_000_000)]
    ack1 = applier.apply(same_clock, _native_receipt(same_clock, events))
    assert ack1["applied_control_event_ids"] == ["native-control-1", "native-control-2"]
    assert runtime.targets["m1"].active_controls["root"] == pytest.approx(3.0)

    runtime.advance_to(1.0)
    assert runtime._enemy_position_at("m1")[0] == pytest.approx(15.0)

    # The Rust source expiry is delivered at 3s. The target is still frozen
    # at that exact world boundary; movement resumes only after the ACK.
    runtime.advance_to(3.0)
    expiry_tick = feed.next_tick()
    feed.accept_range_receipt(_range_receipt(expiry_tick))
    ack2 = applier.apply(
        expiry_tick,
        _native_receipt(expiry_tick, [_event(3, "expire", time_ns=3_000_000_000)]),
    )
    assert ack2["applied_control_event_ids"] == ["native-control-3"]
    assert "root" not in runtime.targets["m1"].active_controls
    runtime.advance_to(4.0)
    assert runtime._enemy_position_at("m1")[0] == pytest.approx(10.0)


def test_native_root_miss_is_acknowledged_without_suppressing_2d_motion():
    runtime, feed, applier = _world()
    first = feed.next_tick()
    feed.accept_range_receipt(_range_receipt(first))
    applier.apply(first, _native_receipt(first, []))

    same_clock = feed.next_tick(allow_same_clock=True)
    feed.accept_range_receipt(_range_receipt(same_clock))
    ack = applier.apply(
        same_clock,
        _native_receipt(same_clock, [_event(1, "attempt", landed=False)]),
    )
    assert ack["applied_control_event_ids"] == ["native-control-1"]
    assert "root" not in runtime.targets["m1"].active_controls

    runtime.advance_to(1.0)
    assert runtime._enemy_position_at("m1")[0] == pytest.approx(10.0)
