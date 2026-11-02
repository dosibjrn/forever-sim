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


@pytest.mark.parametrize("distance,melee", [(15., False), (3., True)])
def test_stationary_source_target_keeps_real_2d_position(distance, melee):
    from src.game.model import ActorDefinition, ResourceDefinition
    from src.game.runtime import ActorState, CombatRuntime, TargetState
    actor = ActorState.from_ir(ActorDefinition('hero', 'player', base_stats={}),
        (ResourceDefinition('health', 'Health', 'hero', initial_amount=500, capacity=500),), ())
    runtime = CombatRuntime(actor=actor, target=TargetState.with_health('m0', 500),
        other_targets=(TargetState.with_health('m1', 500),),
        spatial_positions_yards={'m0': (0., 0.), 'm1': (distance, 0.)},
        enemy_move_speed_yards_s=0., melee_radius_yards=5.)
    runtime.engage_target('m1')
    runtime.select_target('m1')
    assert ('m1' in runtime._melee_targets) is melee
    feed = GsimGoRangeFeed(runtime, native_player_index=0)
    for idx in range(3):
        runtime.advance_to(idx * 1.0)
        tick = feed.next_tick()
        assert tick["distance_yards"] == distance
        assert tick["clock_ms"] == idx * 1000
        feed.accept_range_receipt(receipt(tick))
    assert runtime.enemy_positions_yards['m1'] == (distance, 0.)


def test_negative_enemy_speed_still_rejected():
    from src.game.model import ActorDefinition, ResourceDefinition
    from src.game.runtime import ActorState, CombatRuntime, TargetState
    actor = ActorState.from_ir(ActorDefinition('hero', 'player', base_stats={}),
        (ResourceDefinition('health', 'Health', 'hero', initial_amount=500, capacity=500),), ())
    with pytest.raises(ValueError, match="invalid enemy movement speed"):
        CombatRuntime(actor=actor, target=TargetState.with_health('m0', 500),
            other_targets=(TargetState.with_health('m1', 500),),
            spatial_positions_yards={'m0': (0., 0.), 'm1': (15., 0.)},
            enemy_move_speed_yards_s=-1., melee_radius_yards=5.)


def test_saved_druid_source_target_health_drives_real_gsim_target():
    """Source Go stats.Health is index 32, not the old 10m-HP probe default."""
    import json
    from pathlib import Path
    from tools.wf_gsim_go_live_range_probe import (
        diagnostic_gsim_world, source_target_health_from_request,
    )
    request = Path("docs/evidence/druid-l60-balance/p7.3/frozen_winner_request.json")
    source = json.loads(request.read_text())
    health = source_target_health_from_request(request.read_bytes())
    assert health == source["encounter"]["targets"][0]["stats"][32] == 127393
    runtime = diagnostic_gsim_world(
        target_spawn_yards=15., enemy_move_speed_yards_s=0., target_health=health)
    tick = GsimGoRangeFeed(runtime, native_player_index=0).next_tick()
    assert tick["world_target_max_health"] == health
    assert tick["world_target_health_before"] == health
    assert tick["distance_yards"] == 15.


@pytest.mark.parametrize("mutation", [
    lambda x: x["encounter"]["targets"][0]["stats"].__setitem__(32, 0),
    lambda x: x["encounter"]["targets"][0]["stats"].__setitem__(32, float("nan")),
    lambda x: x["encounter"]["targets"][0].update(level=62),
    lambda x: x["encounter"].update(targets=[]),
    lambda x: x["encounter"]["targets"][0].update(stats=[]),
])
def test_source_target_health_fails_closed_on_invalid_reference(mutation):
    import json
    from pathlib import Path
    from tools.wf_gsim_go_live_range_probe import source_target_health_from_request
    request = Path("docs/evidence/druid-l60-balance/p7.3/frozen_winner_request.json")
    source = json.loads(request.read_text())
    mutation(source)
    with pytest.raises(ValueError, match="SOURCE_"):
        source_target_health_from_request(json.dumps(source).encode())


def test_source_dps_world_has_exactly_one_real_spatial_target():
    """The saved single-target MythicSim encounter must not gain a phantom mob."""
    from src.game.runtime.native_step_protocol import snapshot_gsim_world
    from tools.wf_gsim_go_live_range_probe import diagnostic_gsim_world
    runtime = diagnostic_gsim_world(target_spawn_yards=15.,
        enemy_move_speed_yards_s=0., target_health=127393.,
        source_single_target=True)
    world = snapshot_gsim_world(runtime)
    assert set(runtime.targets) == set(world["enemies"]) == {"m1"}
    assert runtime.multi_target and runtime.spatial_context["simultaneous_2d"]
    assert world["selected_target_id"] == "m1"
    assert world["enemies"]["m1"]["engaged"]
    assert world["enemies"]["m1"]["xy_yards"] == [15., 0.]
    assert runtime.scheduled_incoming_attacks == {}
    feed = GsimGoRangeFeed(runtime, native_player_index=0)
    for idx in range(3):
        runtime.advance_to(float(idx))
        tick = feed.next_tick()
        assert tick["distance_yards"] == 15.
        assert tick["world_target_max_health"] == 127393.
        feed.accept_range_receipt(receipt(tick))


def test_single_target_spatial_mode_uses_real_approach_and_range():
    from tools.wf_gsim_go_live_range_probe import diagnostic_gsim_world
    runtime = diagnostic_gsim_world(target_spawn_yards=20.,
        enemy_move_speed_yards_s=5., target_health=500.,
        source_single_target=True)
    feed = GsimGoRangeFeed(runtime, native_player_index=0)
    before = feed.next_tick()
    assert before["distance_yards"] == 20.
    feed.accept_range_receipt(receipt(before))
    runtime.advance_to(1.)
    after = feed.next_tick()
    assert after["distance_yards"] == pytest.approx(15.)
    assert after["world_sha256"] != before["world_sha256"]
    feed.accept_range_receipt(receipt(after))


def test_legacy_two_target_diagnostic_remains_spatial():
    from tools.wf_gsim_go_live_range_probe import diagnostic_gsim_world
    runtime = diagnostic_gsim_world(target_spawn_yards=15.,
        enemy_move_speed_yards_s=0.)
    assert set(runtime.targets) == {"m0", "m1"}
    assert runtime.multi_target


def test_source_single_target_rejects_unmatched_spatial_positions():
    from src.game.model import ActorDefinition, ResourceDefinition
    from src.game.runtime import ActorState, CombatRuntime, TargetState
    actor = ActorState.from_ir(ActorDefinition('hero', 'player', base_stats={}),
        (ResourceDefinition('health', 'Health', 'hero', initial_amount=500, capacity=500),), ())
    with pytest.raises(ValueError, match="2D pack requires positions"):
        CombatRuntime(actor=actor, target=TargetState.with_health('m1', 500),
            spatial_positions_yards={'m0': (0., 0.)})


def test_native_sampled_encounter_end_schedules_last_real_world_boundary():
    """A 120 +/- 15s source encounter must not drop its last ~56ms of combat."""
    from tools.wf_gsim_go_live_range_probe import _terminal_world_tick_ms
    # Pinned source Druid request's observed sampled end (real native Go CI).
    end_ns = 111_956_100_244
    assert _terminal_world_tick_ms(end_ns, 111_900) == 111_956
    assert _terminal_world_tick_ms(end_ns, 111_956) is None
    # Exact-millisecond encounter ends still require the last valid <end tick.
    assert _terminal_world_tick_ms(120_000_000_000, 119_900) == 119_999
