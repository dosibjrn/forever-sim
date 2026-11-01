"""#28 range-only gsim projection, not a native Go/PROCESS acceptance test."""
from __future__ import annotations

import math
import pytest

from src.game.runtime.go_world_range_feed import (
    GsimGoRangeFeed, GoWorldRangeError, _projection_from_snapshot,
)


def sample():
    return {"world_2d_source": "gsim.CombatRuntime", "clock_ms": 0,
            "player_xy_yards": [0., 0.], "selected_target_id": "m1",
            "enemies": {"m1": {"alive": True, "xy_yards": [20., 0.], "controls": {}}}}


def test_pure_projection_is_range_only_and_source_hash_bound():
    world = sample()
    projected = _projection_from_snapshot(world, sequence=0, native_player_index=0)
    assert projected["native_clock_ns"] == 0
    assert projected["distance_yards"] == 20
    assert projected["range_only"] and not projected["native_action_ack"]
    assert not projected["checkpoint_certified"]
    world["enemies"]["m1"]["xy_yards"] = [15., 0.]
    changed = _projection_from_snapshot(world, sequence=0, native_player_index=0)
    assert changed["distance_yards"] == 15
    assert changed["world_sha256"] != projected["world_sha256"]


@pytest.mark.parametrize("change", [
    lambda w: w.update(clock_ms=0.1),
    lambda w: w.update(player_xy_yards=[math.nan, 0]),
    lambda w: w["enemies"]["m1"].update(xy_yards=[math.inf, 0]),
    lambda w: w["enemies"]["m1"].update(alive=False),
    lambda w: w.update(world_2d_source="fake"),
    lambda w: w["enemies"]["m1"].pop("controls"),
])
def test_malformed_snapshot_rejected(change):
    w = sample()
    change(w)
    with pytest.raises(GoWorldRangeError):
        _projection_from_snapshot(w, sequence=0, native_player_index=0)


def _runtime():
    from src.game.model import ActorDefinition, ResourceDefinition
    from src.game.runtime import ActorState, CombatRuntime, TargetState
    actor = ActorState.from_ir(ActorDefinition('hero', 'player', base_stats={}),
        (ResourceDefinition('health', 'Health', 'hero', initial_amount=500, capacity=500),), ())
    runtime = CombatRuntime(actor=actor, target=TargetState.with_health('m0', 500),
        other_targets=(TargetState.with_health('m1', 500),),
        spatial_positions_yards={'m0': (0., 0.), 'm1': (20., 0.)},
        enemy_move_speed_yards_s=5., melee_radius_yards=5.)
    runtime.engage_target('m1')
    runtime.select_target('m1')
    return runtime


def receipt(tick):
    return {"sequence": tick["sequence"], "native_clock_ns": tick["native_clock_ns"],
            "player_index": tick["native_player_index"], "applied_yards": tick["distance_yards"],
            "native_encounter_damage": 0.0}


def test_real_gsim_moving_target_emits_two_serial_range_ticks():
    runtime = _runtime()
    feed = GsimGoRangeFeed(runtime, native_player_index=0)
    one = feed.next_tick()
    assert one["distance_yards"] == 20.
    assert one["world_target_health_before"] == 500.
    assert one["world_target_max_health"] == 500.
    with pytest.raises(GoWorldRangeError, match="PREVIOUS_NATIVE_RANGE_RECEIPT_MISSING"):
        feed.next_tick()
    ack = feed.accept_range_receipt(receipt(one))
    assert ack["native_spell_action_ack"] is False
    runtime.advance_to(1.0)
    two = feed.next_tick()
    assert two["sequence"] == 1 and two["clock_ms"] == 1000
    assert two["distance_yards"] == pytest.approx(15.)
    assert two["world_sha256"] != one["world_sha256"]
    assert feed.accept_range_receipt(receipt(two))["checkpoint_certified"] is False


def test_mismatched_receipts_and_live_world_mutation_fail_closed():
    runtime = _runtime()
    feed = GsimGoRangeFeed(runtime, native_player_index=0)
    tick = feed.next_tick()
    for wrong in (dict(receipt(tick), sequence=1),
                  dict(receipt(tick), native_clock_ns=1),
                  dict(receipt(tick), applied_yards=999),
                  dict(receipt(tick), native_encounter_damage=-1)):
        with pytest.raises(GoWorldRangeError):
            feed.accept_range_receipt(wrong)
    runtime.advance_to(0.5)
    with pytest.raises(GoWorldRangeError, match="WORLD_MUTATED_BEFORE_NATIVE_RECEIPT"):
        feed.accept_range_receipt(receipt(tick))


def test_fake_runtime_not_accepted_as_gsim():
    with pytest.raises(Exception, match="WORLD_CONTROLLER_NOT_GSIM"):
        GsimGoRangeFeed(sample(), native_player_index=0)



def test_partial_real_gsim_health_is_projected_before_first_native_action():
    runtime = _runtime()
    runtime.targets["m1"].health = 75.
    feed = GsimGoRangeFeed(runtime, native_player_index=0)
    tick = feed.next_tick()
    assert tick["world_target_health_before"] == 75.
    assert tick["world_target_max_health"] == 500.
    assert tick["selected_target_id"] == "m1"
