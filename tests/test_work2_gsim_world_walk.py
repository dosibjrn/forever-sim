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
    assert metadata["authority"] == "src.scenarios.leveling_targets.MOB_BASE_HP"
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


def test_source_melee_attack_range_controls_real_world_approach():
    module = _world_module()
    source = {"melee": {"auto_swing_melee": True,
                        "main_hand": {"max_range": 5.0}}}
    assert module._source_approach_radius(source) == pytest.approx(4.5)
    assert module._source_approach_radius(
        {"melee": {"auto_swing_melee": False}}) == 12.
    world = _world()
    leg = module._queue_world_walk(
        world, "m1", speed_yards_s=7., approach_radius_yards=4.5)
    assert leg["scheduled_yards"] == pytest.approx(27.5)
    world.advance_to(leg["arrival_s"])
    assert world.player_position_yards == pytest.approx((27.5, 0.))
    assert world.enemy_positions_yards["m1"] == (32., 0.)


@pytest.mark.parametrize("range_yards", [0, -1, True, "5", float("nan"), float("inf")])
def test_source_melee_attack_range_rejects_invalid_input(range_yards):
    with pytest.raises(ValueError, match="RUST_WORLD_SOURCE_MELEE_RANGE_INVALID"):
        _world_module()._source_approach_radius(
            {"melee": {"auto_swing_melee": True,
                       "main_hand": {"max_range": range_yards}}})


def test_native_incoming_health_damage_is_sourced_from_each_rust_window():
    validate = _world_module()._native_health_damage_summary
    windows = [
        {"index": 0, "native_health_damage_taken": 0.0,
         "native_health_damage_events": 0},
        {"index": 1, "native_health_damage_taken": 241.5,
         "native_health_damage_events": 2},
    ]
    assert validate(windows, require_positive=True) == {
        "observed": True, "damage_taken": 241.5, "damage_events": 2,
    }
    assert validate(windows, require_positive=False)["damage_taken"] == 241.5


def test_native_incoming_health_damage_zero_is_not_a_positive_attack():
    validate = _world_module()._native_health_damage_summary
    windows = [
        {"index": 0, "native_health_damage_taken": 0.0,
         "native_health_damage_events": 0},
    ]
    assert validate(windows, require_positive=False)["observed"] is True
    with pytest.raises(AssertionError, match="RUST_WORLD_NATIVE_ATTACK_NOT_OBSERVED"):
        validate(windows, require_positive=True)


def test_native_incoming_health_damage_absent_is_never_fabricated():
    validate = _world_module()._native_health_damage_summary
    windows = [{"index": 0, "actor_health": 2893.}]
    assert validate(windows, require_positive=False) == {
        "observed": False, "damage_taken": None, "damage_events": None,
    }
    with pytest.raises(AssertionError, match="RUST_WORLD_NATIVE_HEALTH_DAMAGE_PORT_NOT_SELECTED"):
        validate(windows, require_positive=True)


@pytest.mark.parametrize("amount,events", [
    (-1., 1), (float("nan"), 1), (float("inf"), 1),
    (True, 1), ("1", 1), (1., -1), (1., 1.5),
    (1., True), (1., 0),
])
def test_native_incoming_damage_rejects_corrupt_rust_receipts(amount, events):
    validate = _world_module()._native_health_damage_summary
    with pytest.raises(AssertionError, match="RUST_WORLD_NATIVE_HEALTH_DAMAGE_RECEIPT_INVALID"):
        validate([{"index": 0, "native_health_damage_taken": amount,
                   "native_health_damage_events": events}], require_positive=False)


def test_native_incoming_damage_rejects_partial_window_provenance():
    validate = _world_module()._native_health_damage_summary
    with pytest.raises(AssertionError, match="RUST_WORLD_NATIVE_HEALTH_DAMAGE_RECEIPT_INVALID"):
        validate([{"index": 0, "native_health_damage_taken": 5.,
                   "native_health_damage_events": 1},
                  {"index": 1, "actor_health": 100.}], require_positive=False)


def test_native_health_receipt_proves_real_actor_survived_each_distinct_mob():
    validate = _world_module()._native_survival_min_health
    windows = [
        {"index": 0, "actor_health": 500.0, "actor_mana": 4900.},
        {"index": 1, "actor_health": 421.5, "actor_mana": 4500.},
    ]
    assert validate(windows, 2) == pytest.approx(421.5)


@pytest.mark.parametrize("health", [0, -1.0, None, "500", True, float("nan"), float("inf")])
def test_native_lethal_world_kill_cannot_mask_dead_or_unobserved_player(health):
    validate = _world_module()._native_survival_min_health
    windows = [{"index": 0, "actor_health": 500.},
               {"index": 1, "actor_health": health}]
    with pytest.raises(AssertionError, match="RUST_MULTI_WORLD_NATIVE_ACTOR_NOT_ALIVE"):
        validate(windows, 2)


def test_native_survival_failure_names_first_dead_window_and_real_health():
    validate = _world_module()._native_survival_min_health
    windows = [
        {"index": 0, "actor_health": 500.0},
        {"index": 1, "actor_health": 120.0},
        {"index": 2, "actor_health": 0.0},
        {"index": 3, "actor_health": -50.0},
    ]
    with pytest.raises(AssertionError, match=(
            r"RUST_MULTI_WORLD_NATIVE_ACTOR_NOT_ALIVE:index=2:actor_health=0[.]0")):
        validate(windows, 4)


def test_native_survival_refuses_skipped_or_missing_target_receipts():
    validate = _world_module()._native_survival_min_health
    for windows, count in (
        ([{"index": 0, "actor_health": 500.}], 2),
        ([{"index": 1, "actor_health": 500.},
          {"index": 1, "actor_health": 500.}], 2),
        ([{"index": True, "actor_health": 500.},
          {"index": 1, "actor_health": 500.}], 2),
    ):
        with pytest.raises(AssertionError, match="RUST_MULTI_WORLD_NATIVE_SURVIVAL_WINDOWS_INVALID"):
            validate(windows, count)


def test_paid_world_route_receipt_uses_actual_2d_step_clock_not_scheduled_distance():
    module = _world_module()
    world = _world()
    leg = module._queue_world_walk(world, "m1", speed_yards_s=7.)
    # A full real gsim route must count as paid clock time, not a teleport.
    world.advance_to(leg["arrival_s"])
    next_clock_ns = round((leg["arrival_s"] + 1.) * 1e9)
    receipts, paid = module._paid_world_route_receipts(
        [{"world_kill_clock_ns": 0}, {"world_kill_clock_ns": next_clock_ns}],
        [leg], world.trace)
    assert paid == pytest.approx(20. / 7.)
    assert receipts[0]["actual_paid_world_movement_s"] == pytest.approx(paid)
    assert receipts[0]["observed_gsim_movement_steps"] == 10
    assert receipts[0]["arrival_reached_before_kill"] is True


def test_paid_world_route_does_not_count_unexecuted_walk_after_next_kill():
    module = _world_module()
    world = _world()
    leg = module._queue_world_walk(world, "m1", speed_yards_s=7.)
    # A real instant attack can kill while moving; the remaining planned
    # route must NOT be billed as elapsed simulation time.
    world.advance_to(1.)
    receipts, paid = module._paid_world_route_receipts(
        [{"world_kill_clock_ns": 0}, {"world_kill_clock_ns": 1_000_000_000}],
        [leg], world.trace)
    assert paid == pytest.approx(1.)
    assert receipts[0]["observed_gsim_movement_steps"] < 10
    assert receipts[0]["arrival_reached_before_kill"] is False


@pytest.mark.parametrize("kills,leg_override,expected", [
    ([{"world_kill_clock_ns": 1}, {"world_kill_clock_ns": 1}], {},
     "RUST_WORLD_ROUTE_LETHAL_CLOCK_INVALID"),
    ([{"world_kill_clock_ns": 0}, {"world_kill_clock_ns": 2_000_000_000}],
     {"start_s": 0.5}, "RUST_WORLD_ROUTE_SCHEDULE_INVALID"),
    ([{"world_kill_clock_ns": 0}, {"world_kill_clock_ns": 2_000_000_000}],
     {"arrival_s": -1.}, "RUST_WORLD_ROUTE_SCHEDULE_INVALID"),
])
def test_paid_world_route_rejects_inconsistent_real_kill_clock(
        kills, leg_override, expected):
    module = _world_module()
    world = _world()
    leg = module._queue_world_walk(world, "m1", speed_yards_s=7.)
    with pytest.raises(AssertionError, match=expected):
        module._paid_world_route_receipts(
            kills, [{**leg, **leg_override}], world.trace)



def test_completed_world_route_rejects_only_partially_executed_2d_steps():
    module = _world_module()
    world = _world()
    leg = module._queue_world_walk(world, "m1", speed_yards_s=7.)
    assert leg["scheduled_movement_steps"] == 10
    # A real first gsim step exists, but the remaining 9 are not executed.
    # The late native kill clock must not turn that partial walk into a paid
    # *completed* route. The old implementation accepted any nonzero step count.
    world.advance_to(leg["start_s"] + 2. / 7.)
    assert len([e for e in world.trace if e.kind == "SpatialPlayerMoveStep"]) == 1
    with pytest.raises(AssertionError, match="RUST_WORLD_ROUTE_INCOMPLETE_GSIM_STEPS"):
        module._paid_world_route_receipts(
            [{"world_kill_clock_ns": 0},
             {"world_kill_clock_ns": round((leg["arrival_s"] + 1.) * 1e9)}],
            [leg], world.trace)


def test_completed_world_route_rejects_steps_from_a_different_generation():
    module = _world_module()
    world = _world()
    leg = module._queue_world_walk(world, "m1", speed_yards_s=7.)
    world.advance_to(leg["start_s"] + 2. / 7.)
    other_route_steps = world.trace.copy()
    # A real gsim event from another route does not finish this leg.
    for event in other_route_steps:
        event.payload["move_generation"] += 100
    with pytest.raises(AssertionError, match="RUST_WORLD_ROUTE_COMPLETE_WITHOUT_GSIM_STEPS"):
        module._paid_world_route_receipts(
            [{"world_kill_clock_ns": 0},
             {"world_kill_clock_ns": round((leg["arrival_s"] + 1.) * 1e9)}],
            [leg], other_route_steps)



def test_completed_world_route_rejects_replayed_real_step_as_missing_waypoint():
    module = _world_module()
    world = _world()
    leg = module._queue_world_walk(world, "m1", speed_yards_s=7.)
    world.advance_to(leg["arrival_s"])
    steps = [event for event in world.trace
             if event.kind == "SpatialPlayerMoveStep"]
    assert len(steps) == leg["scheduled_movement_steps"] == 10

    # The old count-only receipt treated these ten trace entries as a
    # completed walk even though the final gsim waypoint never happened.
    # Every event itself came from the real 2D runtime, not a fake point.
    corrupted_trace = world.trace.copy()
    last_step_index = max(i for i, event in enumerate(corrupted_trace)
                          if event.kind == "SpatialPlayerMoveStep")
    corrupted_trace[last_step_index] = steps[0]
    kills = [{"world_kill_clock_ns": 0},
             {"world_kill_clock_ns": round((leg["arrival_s"] + 1.) * 1e9)}]
    with pytest.raises(AssertionError, match="RUST_WORLD_ROUTE_STEPS_NOT_QUEUED_PATH"):
        module._paid_world_route_receipts(kills, [leg], corrupted_trace)


def test_world_route_receipt_requires_real_queued_waypoint_provenance():
    module = _world_module()
    world = _world()
    leg = module._queue_world_walk(world, "m1", speed_yards_s=7.)
    world.advance_to(leg["arrival_s"])
    leg.pop("scheduled_step_positions")
    with pytest.raises(AssertionError, match="RUST_WORLD_ROUTE_QUEUED_PATH_MISSING"):
        module._paid_world_route_receipts(
            [{"world_kill_clock_ns": 0},
             {"world_kill_clock_ns": round((leg["arrival_s"] + 1.) * 1e9)}],
            [leg], world.trace)


def test_world_elapsed_reports_each_real_native_acked_target_delta():
    verify = _world_module()._verified_world_elapsed
    measured = verify(
        [{"index": 0, "native_kill_ns": 1_000_000_000},
         {"index": 1, "native_kill_ns": 3_500_000_000},
         {"index": 2, "native_kill_ns": 4_000_000_000}],
        [{"world_kill_clock_ns": 1_000_000_000},
         {"world_kill_clock_ns": 3_500_000_000},
         {"world_kill_clock_ns": 4_000_000_000}])
    assert measured["world_elapsed_seconds"] == pytest.approx(4.)
    assert measured["world_seconds_per_target_without_paid_recovery"] == pytest.approx(4./3.)
    assert measured["world_per_target_elapsed_seconds_without_paid_recovery"] == pytest.approx(
        [1., 2.5, 0.5])


def test_completed_world_route_cannot_claim_paid_2d_walk_without_steps():
    module = _world_module()
    world = _world()
    leg = module._queue_world_walk(world, "m1", speed_yards_s=7.)
    # A scheduled route and subsequent native lethal timestamp are not
    # sufficient; this negative control has not advanced the gsim 2D world.
    assert leg["scheduled_yards"] > 0.
    with pytest.raises(AssertionError, match="RUST_WORLD_ROUTE_COMPLETE_WITHOUT_GSIM_STEPS"):
        module._paid_world_route_receipts(
            [{"world_kill_clock_ns": 0},
             {"world_kill_clock_ns": round((leg["arrival_s"] + 1.) * 1e9)}],
            [leg], world.trace)
