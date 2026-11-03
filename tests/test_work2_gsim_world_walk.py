"""Work2: gsim's real queued player movement is not a target teleport.

Unit-level scheduler regression only. Rust↔2D native effect integration must be
proven by the separate exact-source Actions diagnostic.
"""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from src.game.model import ActorDefinition, ResourceDefinition
from src.game.runtime import ActorState, CombatRuntime, TargetState


def _walk_helper():
    script = Path(__file__).resolve().parents[1] / "integrations/mythicsim-rust/live_two_world_pulls.py"
    spec = spec_from_file_location("work2_live_walk", script)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._queue_world_walk


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
