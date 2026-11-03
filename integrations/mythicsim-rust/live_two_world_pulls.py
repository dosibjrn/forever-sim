#!/usr/bin/env python3
"""Multiple *distinct* gsim 2D mob kills on one source-Rust actor/ACK timeline.

This is a bounded production integration regression, not paid recovery,
a 100-mob run, or P4/P5/P6 acceptance. Damage and Warcraft actions originate
only in the pinned Rust engine; gsim applies them to real 2D world targets.
"""
from __future__ import annotations

import argparse
import json
from math import hypot
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.game.runtime.go_native_world_damage_ack import GsimNativeDamageWorldApplier
from src.game.runtime.go_world_range_feed import GsimGoRangeFeed
from src.game.model import ActorDefinition, ResourceDefinition
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.shared.leveling.spaced_pulls import SpacedPullLayout


def _queue_world_walk(world: CombatRuntime, target_id: str, *,
                      speed_yards_s: float) -> dict:
    """Use gsim's live 2D movement scheduler, never teleport a target/player.

    A world walk is not native cast-while-moving legality, source-native
    recovery, incoming damage, or a full paid 100-mob evaluator.
    """
    start = world.player_position_yards
    target = world.enemy_positions_yards[target_id]
    dx, dy = target[0] - start[0], target[1] - start[1]
    distance = hypot(dx, dy)
    # Stop outside melee, well inside the native Balance spell's range.
    # This is a diagnostic approach position, not fabricated spell range.
    approach_radius_yards = 12.0
    if distance <= approach_radius_yards:
        return {"target_id": target_id, "scheduled_yards": 0.0,
                "start_s": world.actor.current_time_s,
                "arrival_s": world.actor.current_time_s}
    destination = (target[0] - approach_radius_yards * dx / distance,
                   target[1] - approach_radius_yards * dy / distance)
    start_s = float(world.actor.current_time_s)
    arrival_s = world.begin_player_move(destination, speed_yards_s=speed_yards_s)
    if arrival_s <= start_s or world.player_position_yards != start:
        raise AssertionError("RUST_TWO_WORLD_ROUTE_TELEPORTED_OR_UNCHARGED")
    return {"target_id": target_id,
            "scheduled_yards": distance - approach_radius_yards,
            "start_s": start_s, "arrival_s": arrival_s}


def run(binary: Path, prepared: Path, *, mob_health: float = 1200.,
        target_count: int = 2, corrupt_ack: bool = False) -> dict:
    """Execute N world kills; retain one Rust process, actor and ACK lineage."""
    if not 0 < mob_health <= 100_000:
        raise ValueError("RUST_MULTI_WORLD_MOB_HEALTH_INVALID")
    if type(target_count) is not int or not 2 <= target_count <= 100:
        raise ValueError("RUST_MULTI_WORLD_TARGET_COUNT_INVALID")
    request = json.loads(prepared.read_text())
    source_hash = request["request_sha256"]
    if not isinstance(source_hash, str) or len(source_hash) != 64:
        raise ValueError("RUST_TWO_WORLD_PREPARED_SOURCE_INVALID")
    # One actual 2D world for the entire target sequence. This is the
    # existing native combat/world ACK diagnostic, not paid travel/recovery.
    # Keep the real 20-yard grid. Start near the FIRST mob, not the
    # centroid of a growing field (which falsely strands the first pull
    # in a 100-target scenario). Subsequent range is earned by actual gsim
    # player route events on the same world clock; no target teleport.
    targets = ("m1", "m0") + tuple(f"m{i}" for i in range(2, target_count))
    route = SpacedPullLayout(mob_count=target_count)
    points = route.positions_yards
    positions = {target_id: (x + 12.0 - points[0][0], y - points[0][1])
                 for target_id, (x, y) in zip(targets, points)}
    actor = ActorState.from_ir(
        ActorDefinition("hero", "player", base_stats={}),
        (ResourceDefinition("health", "Health", "hero",
                            initial_amount=500, capacity=500),), ())
    world = CombatRuntime(
        actor=actor, target=TargetState.with_health("m0", mob_health),
        other_targets=tuple(TargetState.with_health(t, mob_health)
                            for t in targets if t != "m0"),
        spatial_positions_yards=positions,
        enemy_move_speed_yards_s=0., melee_radius_yards=5.,
    )
    for target_id, (x, y) in positions.items():
        world.targets[target_id].metadata["facing_xy_yards"] = (-x, -y)
    world.engage_target(targets[0])
    world.select_target(targets[0])
    feed = GsimGoRangeFeed(world, native_player_index=0)
    applier = GsimNativeDamageWorldApplier(world)
    iteration = 0
    previous_ack = ""
    last_clock_ns = -1
    kills = []
    walks = []
    events = 0
    ticks = 0
    native_report = None
    env = dict(os.environ, FOREVER_GSIM_WORLD_BRIDGE="1", WOWSIM_RNG_MODE="stochastic")
    proc = subprocess.Popen(
        [str(binary.resolve()), "native-world-pulls", "--infile",
         str(prepared.resolve()), "--targets", str(target_count)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1, env=env,
    )
    try:
        for line in proc.stdout:
            native = json.loads(line)
            if native.get("type") != "native_rust_world_boundary_request":
                if native.get("engine") == "forever-engine":
                    if native_report is not None:
                        raise AssertionError("RUST_TWO_WORLD_DUPLICATE_REPORT")
                    native_report = native
                    continue
                raise AssertionError(("RUST_TWO_WORLD_UNEXPECTED_OUTPUT", native))
            index = native["iteration_index"]
            if index != iteration:
                if index != iteration + 1 or len(kills) != index or index >= target_count:
                    raise AssertionError("RUST_TWO_WORLD_TARGET_INDEX_SKIP")
                if world.targets[targets[iteration]].alive:
                    raise AssertionError("RUST_TWO_WORLD_NEXT_TARGET_BEFORE_LETHAL")
                iteration = index
                # Same CombatRuntime, same gsim actor, same feed and applier.
                world.engage_target(targets[iteration])
                world.select_target(targets[iteration])
                applier.begin_next_world_target(targets[iteration])
            clock_ns = native["native_clock_ns"]
            if (clock_ns <= last_clock_ns or clock_ns % 1_000_000
                    or native["sequence"] != ticks
                    or native["native_request_sha256"] != source_hash
                    or native["native_process_id"] != proc.pid):
                raise AssertionError("RUST_TWO_WORLD_CLOCK_SOURCE_OR_SEQUENCE_INVALID")
            world.advance_to(clock_ns / 1e9)
            tick = feed.next_tick()
            # Source of truth: gsim live 2D route, not queued-step inference
            # or a native movement guess. Rust applies its own cast legality.
            tick["gsim_player_moving"] = bool(world._player_is_moving())
            if tick["native_clock_ns"] != clock_ns or tick["sequence"] != ticks:
                raise AssertionError("RUST_TWO_WORLD_RANGE_FEED_MISMATCH")
            tick["iteration_index"] = iteration
            tick["previous_world_ack_id"] = previous_ack
            tick["next_world_boundary_ns"] = (
                clock_ns + 100_000_000 if world.queue or world._enemy_motion else None)
            proc.stdin.write(json.dumps(tick, sort_keys=True, allow_nan=False) + "\n")
            proc.stdin.flush()
            receipt_line = proc.stdout.readline()
            if not receipt_line:
                raise AssertionError(("RUST_TWO_WORLD_NATIVE_EXIT_BEFORE_RECEIPT",
                                      proc.stderr.read()[-4000:]))
            receipt = json.loads(receipt_line)
            if (receipt["type"] != "native_rust_world_receipt"
                    or receipt["iteration_index"] != iteration
                    or receipt["native_process_id"] != proc.pid):
                raise AssertionError("RUST_TWO_WORLD_RECEIPT_INVALID")
            if receipt["native_range_receipt"].get("gsim_player_moving") is not tick["gsim_player_moving"]:
                raise AssertionError("RUST_TWO_WORLD_MOVING_RECEIPT_MISMATCH")
            feed.accept_range_receipt(receipt["native_range_receipt"])
            ack = applier.apply(tick, receipt)
            ack["iteration_index"] = iteration
            events += len(ack["applied_event_ids"])
            if corrupt_ack and events:
                ack["applied_event_ids"] = []
            proc.stdin.write(json.dumps(ack, sort_keys=True, allow_nan=False) + "\n")
            proc.stdin.flush()
            previous_ack = ack["world_after_sha256"]
            last_clock_ns = clock_ns
            ticks += 1
            if not world.targets[targets[iteration]].alive:
                if len(kills) != iteration:
                    raise AssertionError("RUST_TWO_WORLD_DUPLICATE_KILL")
                if ack["world_target_health_after"] != 0:
                    raise AssertionError("RUST_TWO_WORLD_KILL_NOT_ACKED")
                kills.append({"target_id": targets[iteration],
                              "world_kill_clock_ns": clock_ns,
                              "ack_sha256": previous_ack})
                if not corrupt_ack and iteration + 1 < target_count:
                    # The lethal world ACK has already been transmitted.
                    # Queue real gsim SpatialPlayerMoveStep events before the
                    # next source-Rust boundary. Rust sees the ensuing range
                    # and native actor timeline; no movement is free.
                    walks.append(_queue_world_walk(
                        world, targets[iteration + 1],
                        speed_yards_s=route.movement_speed_yards_s))
            if corrupt_ack and events:
                break
        proc.stdin.close()
        stderr = proc.stderr.read()
        status = proc.wait(timeout=20)
        if corrupt_ack:
            if not events or status == 0 or "RUST_WORLD_DAMAGE_ACK_EVENTS_MISMATCH" not in stderr:
                raise AssertionError(("RUST_TWO_WORLD_FORGED_ACK_NOT_REJECTED", status, stderr[-2000:]))
            return {"forged_ack_rejected": True, "native_events": events}
        if status != 0:
            raise AssertionError(("RUST_TWO_WORLD_NATIVE_FAILED", status, stderr[-3000:]))
        if native_report is None or len(kills) != target_count or events < target_count:
            raise AssertionError(("RUST_TWO_WORLD_KILLS_NOT_COMPLETED", native_report, kills, events))
        result = native_report["result"]
        if (native_report["source_sha256"] != source_hash
                or result["world_targets_killed"] != target_count
                or not result["continuous_native_actor"]
                or not result["actual_2d_ack"]
                or result["paid_recovery"]
                or len(result["windows"]) != target_count
                or any(b["native_kill_ns"] <= a["native_kill_ns"]
                       for a, b in zip(result["windows"], result["windows"][1:]))
                or native_report["checkpoint_certified"]):
            raise AssertionError("RUST_TWO_WORLD_NATIVE_RESULT_INVALID")
        if [k["target_id"] for k in kills] != list(targets):
            raise AssertionError("RUST_TWO_WORLD_DISTINCT_TARGET_IDS_INVALID")
        return {
            "source_sha256": source_hash, "native_pid": proc.pid,
            "native_windows": result["windows"], "world_kills": kills,
            "native_damage_events": events, "world_ticks": ticks,
            "continuous_native_actor": True, "actual_2d_ack": True,
            "world_targets_killed": target_count,
            "gsim_world_walk_steps": sum(
                event.kind == "SpatialPlayerMoveStep" for event in world.trace),
            "gsim_route_legs": walks,
            "paid_recovery": False, "checkpoint_certified": False,
        }
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--mob-health", type=float, default=1200.)
    parser.add_argument("--targets", type=int, default=2)
    args = parser.parse_args()
    valid = run(args.binary, args.prepared, mob_health=args.mob_health,
                target_count=args.targets)
    print("RUST_TWO_REAL_GSIM_WORLD_KILLS", json.dumps(valid, sort_keys=True), flush=True)
    forged = run(args.binary, args.prepared, mob_health=args.mob_health,
                 target_count=args.targets, corrupt_ack=True)
    print("RUST_TWO_WORLD_FORGED_ACK_REJECTED", json.dumps(forged, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
