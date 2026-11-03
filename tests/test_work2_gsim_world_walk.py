"""Work2: gsim's real queued player movement is not a target teleport.

Unit-level scheduler regression only. Rust↔2D native effect integration must be
proven by the separate exact-source Actions diagnostic.
"""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from src.game.model import ActorDefinition, ResourceDefinition
from src.game.runtime import ActorState, CombatRuntime, TargetState


def _world_module():
    script = Path(__file__).resolve().parents[1] / "integrations/mythicsim-rust/live_two_world_pulls.py"
    spec = spec_from_file_location("work2_live_walk", script)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _walk_helper():
    return _world_module()._queue_world_walk


def _world():
    player = ActorState.from_ir(
        ActorDefinition("hero", "player", base_stats={}),
        (ResourceDefinition("health", "Health", "hero", initial_amount=500, capacity=500),), ())
    return CombatRuntime(
        actor=player,
        target=TargetState.with_health("m0", 1200),
        other_targets=(TargetState.with_health("m1", 1200),),
        spatial_positions_yards={"m0": (12., 0.), "m1": (32., 0.)},
        enemy_move_speed_yards_s=0., melee_radius_yards=5.)


def test_next_target_uses_real_world_movement_event_clock():
    world = _world()
    start_pos = world.player_position_yards
    leg = _walk_helper()(world, "m1", speed_yards_s=7.)
    assert leg["scheduled_yards"] == pytest.approx(20.)
    assert leg["arrival_s"] - leg["start_s"] == pytest.approx(20. / 7.)
    assert world.player_position_yards == start_pos  # never teleported
    assert world.enemy_positions_yards["m1"] == (32., 0.)
    world.advance_to(leg["arrival_s"])
    assert world.player_position_yards == pytest.approx((20., 0.))
    steps = [event for event in world.trace if event.kind == "SpatialPlayerMoveStep"]
    assert len(steps) == 10
    assert all(a.time_s < b.time_s for a, b in zip(steps, steps[1:]))


def test_in_range_walk_is_zero_cost_without_world_change():
    world = _world()
    leg = _walk_helper()(world, "m0", speed_yards_s=7.)
    assert leg["scheduled_yards"] == 0.
    assert leg["arrival_s"] == leg["start_s"]
    assert world.player_position_yards == (0., 0.)
    assert not any(event.kind == "SpatialPlayerMoveStep" for _, _, event in world.queue._heap)

def test_native_movement_projection_tracks_gsim_live_route_not_future_queue():
    world = _world()
    assert world._player_is_moving() is False
    leg = _walk_helper()(world, "m1", speed_yards_s=7.)
    assert world._player_is_moving() is True
    assert world.player_position_yards == (0., 0.)
    world.advance_to(leg["start_s"] + (leg["arrival_s"] - leg["start_s"]) / 2)
    assert world._player_is_moving() is True
    world.advance_to(leg["arrival_s"])
    assert world._player_is_moving() is False
    assert world.player_position_yards == pytest.approx((20., 0.))


@pytest.mark.parametrize("level, expected_hp", [
    (20, 484.), (30, 955.), (40, 1524.), (60, 3052.),
])
def test_world_targets_use_existing_documented_classic_leveling_hp(level, expected_hp):
    health, metadata = _world_module()._target_health_profile(None, level)
    assert health == expected_hp
    assert metadata["authority"] == "src.shared.leveling.objective.MOB_BASE_HP"
    assert "not_verified_forever" in metadata["source_status"]
    target = TargetState.with_health("source_target", health, **metadata)
    assert target.health == expected_hp
    assert target.metadata["level"] == level


@pytest.mark.parametrize("level", [True, False, 0, -1, 63, 100, "60", 60.0])
def test_world_source_hp_rejects_unsourced_or_non_integer_level(level):
    with pytest.raises(ValueError, match="RUST_WORLD_TARGET_LEVEL_UNSOURCED"):
        _world_module()._target_health_profile(None, level)


def test_explicit_synthetic_hp_is_not_mislabeled_as_sourced():
    helper = _world_module()._target_health_profile
    hp, metadata = helper(None, None)
    assert hp == 1200.
    assert metadata["source_status"] == "synthetic_diagnostic"
    hp, metadata = helper(1250., None)
    assert hp == 1250.
    assert metadata["source_status"] == "synthetic_diagnostic"
    with pytest.raises(ValueError, match="RUST_WORLD_TARGET_PROFILE_CONFLICT"):
        helper(1250., 60)
    for invalid in (0., -1., 100001., float("nan"), float("inf"), True):
        with pytest.raises(ValueError, match="RUST_MULTI_WORLD_MOB_HEALTH_INVALID"):
            helper(invalid, None)
