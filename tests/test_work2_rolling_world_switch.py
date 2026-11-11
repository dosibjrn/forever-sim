"""Source-shaped rolling 2D transport regressions, not a paid native overlap."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import runpy

import pytest

from src.game.model import ActorDefinition, ResourceDefinition
from src.game.runtime import ActorState, CombatRuntime, TargetState


ROOT = Path(__file__).resolve().parents[1]
_bridge = runpy.run_path(str(
    ROOT / "integrations/mythicsim-rust/live_two_world_pulls.py"))
admit = _bridge["_source_acked_rolling_switch"]
new_kills = _bridge["_new_source_acked_world_kills"]


def two_live_world():
    # Mirror the live runner: A starts in range; B is an initially idle mob
    # outside ambient aggro (the generic range probe puts m0 at player feet).
    player = ActorState.from_ir(
        ActorDefinition("hero", "player", base_stats={}),
        (ResourceDefinition("health", "Health", "hero",
                            initial_amount=500, capacity=500),), ())
    world = CombatRuntime(
        actor=player, target=TargetState.with_health("m0", 10_000_000),
        other_targets=(TargetState.with_health("m1", 10_000_000),),
        spatial_positions_yards={"m1": (12., 0.), "m0": (32., 0.)},
        enemy_move_speed_yards_s=0., melee_radius_yards=5.)
    world.engage_target("m1")
    world.select_target("m1")
    world.targets["m1"].health = world.targets["m1"].max_health * 0.45
    assert world.targets["m0"].alive
    return world


def source_switch(world):
    return {
        "from_native_target_index": 0, "to_native_target_index": 1,
        "prior_world_target_id": "m1",
        "prior_world_target_health": world.targets["m1"].health,
        "prior_world_target_max_health": world.targets["m1"].max_health,
        "prior_world_ack_id": "a" * 64,
        "source_ack_sequence": 1,
        "switch_native_clock_ns": 100_000_000,
        "health_fraction_at_most": 0.5,
    }


def accepted(world, source):
    return admit(
        source, world=world, old_id="m1", new_id="m0",
        previous_ack="a" * 64, source_sequence=1,
        last_clock_ns=100_000_000, boundary_clock_ns=200_000_000)


def test_source_acked_45_percent_b_acquisition_retains_two_live_world_ids():
    world = two_live_world()
    switch = source_switch(world)
    assert accepted(world, switch) == switch
    assert world.targets["m1"].alive and world.targets["m0"].alive
    # Source validation does not itself engage, select or move an enemy.
    assert world.target.id == "m1"


@pytest.mark.parametrize("key,value", [
    ("from_native_target_index", 1),
    ("to_native_target_index", 0),
    ("prior_world_target_id", "forged"),
    ("prior_world_ack_id", "b" * 64),
    ("source_ack_sequence", 0),
    ("switch_native_clock_ns", 99_000_000),
    ("switch_native_clock_ns", 201_000_000),
    ("health_fraction_at_most", 0.6),
    ("prior_world_target_health", -1),
    ("prior_world_target_max_health", 0),
])
def test_unacked_early_b_switch_fails_without_mutating_world(key, value):
    world = two_live_world()
    source = source_switch(world)
    source[key] = value
    before = (world.target.id, world.targets["m0"].alive,
              world.targets["m1"].health)
    with pytest.raises(AssertionError, match="RUST_WORLD_OVERLAP_SOURCE_SWITCH_UNACKED"):
        accepted(world, source)
    assert before == (world.target.id, world.targets["m0"].alive,
                      world.targets["m1"].health)


def test_above_half_hp_or_preengaged_b_cannot_be_authorized_by_python():
    world = two_live_world()
    world.targets["m1"].health = world.targets["m1"].max_health * 0.75
    with pytest.raises(AssertionError, match="SOURCE_SWITCH_UNACKED"):
        accepted(world, source_switch(world))
    world = two_live_world()
    world.engage_target("m0")
    with pytest.raises(AssertionError, match="SOURCE_SWITCH_UNACKED"):
        accepted(world, source_switch(world))


def test_selected_b_die_first_then_old_a_dot_kill_tracks_two_real_ids():
    world = two_live_world()
    world.engage_target("m0")
    world.select_target("m0")
    before = {name: world.targets[name].health for name in ("m1", "m0")}
    world.targets["m0"].apply_damage(before["m0"])
    ack_b = {
        "world_after_sha256": "b" * 64,
        "native_target_health_acks": [{
            "native_target_index": 1, "world_target_id": "m0",
            "world_target_health_before": before["m0"],
            "world_target_health_after": 0.0,
        }],
    }
    first = new_kills(world=world, before=before, ack=ack_b,
                      clock_ns=300_000_000, overlap=True)
    assert [row["target_id"] for row in first] == ["m0"]

    before = {name: world.targets[name].health for name in ("m1", "m0")}
    world.targets["m1"].apply_damage(before["m1"])
    ack_a = {
        "world_after_sha256": "c" * 64,
        "native_target_health_acks": [{
            "native_target_index": 0, "world_target_id": "m1",
            "world_target_health_before": before["m1"],
            "world_target_health_after": 0.0,
        }],
    }
    second = new_kills(world=world, before=before, ack=ack_a,
                       clock_ns=400_000_000, overlap=True)
    assert [row["target_id"] for row in first + second] == ["m0", "m1"]
    assert len({row["ack_sha256"] for row in first + second}) == 2


def test_indexless_or_wrong_world_lethal_cannot_be_recorded():
    world = two_live_world()
    before = {name: world.targets[name].health for name in ("m1", "m0")}
    world.targets["m1"].apply_damage(before["m1"])
    ack = {"world_after_sha256": "c" * 64,
           "native_target_health_acks": []}
    with pytest.raises(AssertionError, match="KILL_NOT_INDEX_ACKED"):
        new_kills(world=world, before=before, ack=ack,
                  clock_ns=500_000_000, overlap=True)
    forged = deepcopy(ack)
    forged["native_target_health_acks"] = [{
        "native_target_index": 0,
        "world_target_id": "m0",
        "world_target_health_before": before["m1"],
        "world_target_health_after": 0,
    }]
    with pytest.raises(AssertionError, match="KILL_NOT_INDEX_ACKED"):
        new_kills(world=world, before=before, ack=forged,
                  clock_ns=500_000_000, overlap=True)


def test_joint_world_kill_clocks_use_one_native_fight_not_two_serial_windows():
    measure = _bridge["_verified_joint_overlap_elapsed"]
    kills = [
        {"target_id": "m0", "world_kill_clock_ns": 2_000_000_000,
         "ack_sha256": "a" * 64},
        {"target_id": "m1", "world_kill_clock_ns": 3_000_000_000,
         "ack_sha256": "b" * 64},
    ]
    actual = measure([{"index": 0, "native_kill_ns": 3_000_000_000}], kills)
    assert actual["world_elapsed_seconds"] == 3
    assert actual["world_per_target_elapsed_seconds_without_paid_recovery"] == [2, 1]
    assert actual["world_kill_order"] == ["m0", "m1"]
    with pytest.raises(AssertionError, match="JOINT_WINDOW_INVALID"):
        measure([{"index": 0, "native_kill_ns": 3_000_000_000},
                 {"index": 1, "native_kill_ns": 4_000_000_000}], kills)
    with pytest.raises(AssertionError, match="KILL_CLOCK_INVALID"):
        measure([{"index": 0, "native_kill_ns": 3_000_000_000}],
                [kills[0], {**kills[1], "ack_sha256": "a" * 64}])
    with pytest.raises(AssertionError, match="KILL_CLOCK_INVALID"):
        measure([{"index": 0, "native_kill_ns": 2_500_000_000}], kills)


def test_joint_route_is_charged_from_source_switch_not_first_world_death():
    world = two_live_world()
    world.advance_to(0.1)
    walk = _bridge["_queue_world_walk"](
        world, "m0", speed_yards_s=7., approach_radius_yards=12.)
    assert walk["scheduled_yards"] > 0
    assert walk["start_s"] == pytest.approx(0.1)
    final_s = walk["arrival_s"] + 0.2
    world.advance_to(final_s)
    final_ns = round(final_s * 1_000_000_000)
    kills = [
        {"target_id": "m0", "world_kill_clock_ns": 1_000_000_000},
        {"target_id": "m1", "world_kill_clock_ns": final_ns},
    ]
    receipts, paid_s = _bridge["_paid_joint_overlap_route"](
        kills, [walk], world.trace,
        switch={"switch_native_clock_ns": 100_000_000})
    assert paid_s == pytest.approx(walk["arrival_s"] - 0.1)
    assert receipts[0]["observed_gsim_movement_steps"] == walk[
        "scheduled_movement_steps"]
    assert receipts[0]["start_reason"] == "source_acked_live_overlap_switch"
    with pytest.raises(AssertionError, match="SOURCE_CLOCK_INVALID"):
        _bridge["_paid_joint_overlap_route"](
            kills, [walk], world.trace,
            switch={"switch_native_clock_ns": 200_000_000})


def test_joint_source_apl_policy_does_not_pass_without_native_applied_echo():
    verify = _bridge["_verify_native_rolling_world_apl"]
    policy = {
        "pull_mode": "rolling", "switch_trigger": {
            "type": "current_target_hp_fraction_at_most", "fraction": 0.5},
        "max_live_targets": 2,
    }
    overlap = {
        "source_apl_selected_b": True,
        "both_world_targets_lethal_ack": True,
        "native_world_target_indices": [0, 1],
        "world_target_ids": ["m1", "m0"],
        "combined_native_fight_window": True,
    }
    kills = [{"target_id": "m0", "ack_sha256": "b" * 64},
             {"target_id": "m1", "ack_sha256": "c" * 64}]
    source = {"prior_world_target_id": "m1", "to_native_target_index": 1}
    args = dict(requested=policy, kills=kills, source_switch=source,
                old_target_dot_ticks=2, first_world_id="m1",
                second_world_id="m0")
    with pytest.raises(AssertionError, match="ROLLING_APL_NOT_PROVEN"):
        verify({"world_overlap": overlap}, **args)
    assert verify({"world_overlap": overlap, "applied_world_apl": policy},
                  **args)["old_target_dot_ticks_after_switch_acked"] == 2
    with pytest.raises(AssertionError, match="ROLLING_APL_NOT_PROVEN"):
        verify({"world_overlap": overlap, "applied_world_apl": policy},
               **{**args, "old_target_dot_ticks": 0})
