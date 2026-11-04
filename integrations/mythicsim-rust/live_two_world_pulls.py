#!/usr/bin/env python3
"""Multiple *distinct* gsim 2D mob kills on one source-Rust actor/ACK timeline.

This is a bounded production integration regression, not paid recovery,
a 100-mob run, or P4/P5/P6 acceptance. Damage and Warcraft actions originate
only in the pinned Rust engine; gsim applies them to real 2D world targets.
"""
from __future__ import annotations

import argparse
import json
from math import hypot, isfinite
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
from src.scenarios.spaced_pulls import SpacedPullLayout
from src.scenarios.leveling_targets import MOB_BASE_HP, representative_hp


def _source_approach_radius(request: dict) -> float:
    """Use the selected source-prepared melee reach for diagnostic 2D placement.

    The gsim world controller does not define Warcraft attack range. A melee
    source build cannot start at the ranged diagnostic's 12-yard separation.
    The 90% fraction stays strictly within the sourced max range.
    """
    melee = request.get("melee", {})
    if melee.get("auto_swing_melee") is not True:
        return 12.0
    reach = melee.get("main_hand", {}).get("max_range")
    if type(reach) not in (int, float) or not isfinite(reach) or reach <= 0:
        raise ValueError("RUST_WORLD_SOURCE_MELEE_RANGE_INVALID")
    return min(12.0, 0.9 * float(reach))


def _verified_world_elapsed(windows: list[dict], world_kills: list[dict]) -> dict:
    """Measure time only from actual source-native kills ACKed by gsim 2D.

    This is shared-clock combat+travel time, NOT a completed paid
    recovery/100-mob leveling objective. Never infer cost from target count,
    prepared duration or independent native one-shot fights.
    """
    if not windows or len(windows) != len(world_kills):
        raise AssertionError("RUST_WORLD_ELAPSED_TARGET_COUNT_MISMATCH")
    last_ns = -1
    previous_kill_ns = 0
    elapsed_per_target_s = []
    for index, (native, world) in enumerate(zip(windows, world_kills)):
        native_ns = native.get("native_kill_ns")
        world_ns = world.get("world_kill_clock_ns")
        if (type(native_ns) is not int or type(world_ns) is not int
                or native.get("index") != index
                or native_ns <= last_ns or native_ns <= 0
                or native_ns != world_ns):
            raise AssertionError("RUST_WORLD_KILL_CLOCK_NOT_CAUSAL")
        elapsed_per_target_s.append((native_ns - previous_kill_ns) / 1_000_000_000)
        previous_kill_ns = native_ns
        last_ns = native_ns
    elapsed = last_ns / 1_000_000_000
    return {
        "world_elapsed_seconds": elapsed,
        "world_seconds_per_target_without_paid_recovery": elapsed / len(windows),
        "world_per_target_elapsed_seconds_without_paid_recovery": elapsed_per_target_s,
    }


def _queue_world_walk(world: CombatRuntime, target_id: str, *,
                      speed_yards_s: float,
                      approach_radius_yards: float = 12.0) -> dict:
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
    if distance <= approach_radius_yards:
        return {"target_id": target_id, "scheduled_yards": 0.0,
                "start_s": world.actor.current_time_s,
                "arrival_s": world.actor.current_time_s,
                "movement_generation": None, "scheduled_movement_steps": 0,
                "scheduled_step_positions": []}
    destination = (target[0] - approach_radius_yards * dx / distance,
                   target[1] - approach_radius_yards * dy / distance)
    start_s = float(world.actor.current_time_s)
    arrival_s = world.begin_player_move(destination, speed_yards_s=speed_yards_s)
    if arrival_s <= start_s or world.player_position_yards != start:
        raise AssertionError("RUST_TWO_WORLD_ROUTE_TELEPORTED_OR_UNCHARGED")
    # Bind the receipt to the *real* queued gsim movement generation. A single
    # unrelated/stale step must never certify a completed route as paid.
    generation = world._player_move_generation
    queued_steps = sorted(
        (event for _, _, event in world.queue._heap
         if event.kind == "SpatialPlayerMoveStep"
         and event.payload.get("move_generation") == generation),
        key=lambda event: event.time_s)
    if not queued_steps:
        raise AssertionError("RUST_WORLD_ROUTE_NO_QUEUED_GSIM_STEPS")
    return {"target_id": target_id,
            "scheduled_yards": distance - approach_radius_yards,
            "start_s": start_s, "arrival_s": arrival_s,
            "movement_generation": generation,
            "scheduled_movement_steps": len(queued_steps),
            # Pin the queued *2D path*, not only its length. A repeated or
            # reordered real step cannot stand in for an unexecuted waypoint.
            "scheduled_step_positions": [tuple(step.payload["xy"]) for step in queued_steps]}


def _target_health_profile(mob_health: float | None, classic_mob_level: int | None) -> tuple[float, dict]:
    """Source-labeled ordinary leveling target or explicit synthetic diagnostic.

    CMaNGOS is a documented Classic proxy, not verified Forever creature data.
    Never silently clamp a missing level to another level's target health.
    """
    if classic_mob_level is not None:
        if mob_health is not None:
            raise ValueError("RUST_WORLD_TARGET_PROFILE_CONFLICT")
        if type(classic_mob_level) is not int or classic_mob_level not in MOB_BASE_HP:
            raise ValueError("RUST_WORLD_TARGET_LEVEL_UNSOURCED")
        return representative_hp(classic_mob_level), {
            "source_status": "classic_reference_proxy_not_verified_forever",
            "source_basis": "CMaNGOS warrior BaseHealthExp0 ordinary melee reference",
            "authority": "src.scenarios.leveling_targets.MOB_BASE_HP",
            "level": classic_mob_level,
        }
    if mob_health is None:
        mob_health = 1200.0
    if isinstance(mob_health, bool) or not 0 < float(mob_health) <= 100_000:
        raise ValueError("RUST_MULTI_WORLD_MOB_HEALTH_INVALID")
    return float(mob_health), {
        "source_status": "synthetic_diagnostic",
        "source_basis": "explicit world-only HP fixture",
    }


def _native_survival_min_health(windows: list[dict], target_count: int) -> float:
    """Require actual selected-Rust player survival after EVERY acknowledged kill.

    The native actor owns health, enemy attacks, healing and regeneration. A
    real gsim world kill does not imply that its native player survived it.
    This only validates Rust's existing per-target receipt; it does not
    manufacture incoming damage or award a paid leveling gate.
    """
    if (type(target_count) is not int or not isinstance(windows, list)
            or len(windows) != target_count):
        raise AssertionError("RUST_MULTI_WORLD_NATIVE_SURVIVAL_WINDOWS_INVALID")
    health_values = []
    for index, window in enumerate(windows):
        if (not isinstance(window, dict) or type(window.get("index")) is not int
                or window["index"] != index):
            raise AssertionError("RUST_MULTI_WORLD_NATIVE_SURVIVAL_WINDOWS_INVALID")
        health = window.get("actor_health")
        if (type(health) not in (int, float) or not isfinite(health)
                or health <= 0):
            raise AssertionError("RUST_MULTI_WORLD_NATIVE_ACTOR_NOT_ALIVE")
        health_values.append(float(health))
    return min(health_values)

def _native_mana_continuity(windows: list[dict], target_count: int) -> dict:
    """Require real source-Rust mana states for every ACKed world kill.

    The sampled mana changes include actual casting costs, mana regeneration
    and other native resource effects. These are *not* proof of source-native
    timed between-pull recovery, and must never be treated as a mana-regen
    receipt or an independently paid 100-mob objective.
    """
    if (type(target_count) is not int or target_count <= 0
            or not isinstance(windows, list) or len(windows) != target_count):
        raise AssertionError("RUST_MULTI_WORLD_NATIVE_MANA_WINDOWS_INVALID")
    after_kill = []
    for index, window in enumerate(windows):
        if (not isinstance(window, dict) or type(window.get("index")) is not int
                or window["index"] != index):
            raise AssertionError("RUST_MULTI_WORLD_NATIVE_MANA_WINDOWS_INVALID")
        mana = window.get("actor_mana")
        if (type(mana) not in (int, float) or not isfinite(mana)
                or mana < 0):
            raise AssertionError("RUST_MULTI_WORLD_NATIVE_MANA_INVALID")
        after_kill.append(float(mana))
    # The selected Rust fork reports actual native mana-tick gains per kill.
    # Keep these separate from paid between-pull rest: combat regeneration is
    # not proof that the actor recovered while travelling or drinking.
    presence = [
        (("native_combat_mana_regen_actual_gain" in window),
         ("native_combat_mana_regen_events" in window))
        for window in windows
    ]
    if all(not gain and not events for gain, events in presence):
        regen_gains = regen_events = None  # Older native pin: unobserved.
    else:
        if not all(gain and events for gain, events in presence):
            raise AssertionError("RUST_MULTI_WORLD_NATIVE_REGEN_RECEIPT_INCOMPLETE")
        regen_gains, regen_events = [], []
        for window in windows:
            gain = window["native_combat_mana_regen_actual_gain"]
            events = window["native_combat_mana_regen_events"]
            if (type(gain) not in (int, float) or not isfinite(gain)
                    or gain < 0 or type(events) is not int or events < 0
                    or (gain > 0 and events == 0)):
                raise AssertionError("RUST_MULTI_WORLD_NATIVE_REGEN_RECEIPT_INVALID")
            regen_gains.append(float(gain))
            regen_events.append(events)
    receipt = {
        "native_actor_mana_after_world_kills": after_kill,
        "native_actor_mana_delta_between_world_kills": [
            current - previous for previous, current
            in zip(after_kill, after_kill[1:])
        ],
        "minimum_native_actor_mana": min(after_kill),
    }
    # Preserve the established response shape for an older selected engine.
    # Missing native regeneration is not a fabricated zero-gain observation.
    if regen_gains is not None:
        receipt.update({
            "native_combat_mana_regen_observed": True,
            "native_combat_mana_regen_actual_gain_by_target": regen_gains,
            "native_combat_mana_regen_events_by_target": regen_events,
        })
    return receipt


def _native_health_damage_summary(windows: list[dict], *,
                                  require_positive: bool,
                                  require_zero: bool = False) -> dict:
    """Carry actual per-target Rust damage-taken resource receipts into 2D results.

    The source Rust engine owns incoming attacks and health changes. Missing
    receipts from an older selected fork remain explicitly unobserved; never
    substitute player-HP deltas, gsim actor HP or synthetic damage.
    """
    if not isinstance(windows, list) or not windows:
        raise AssertionError("RUST_WORLD_NATIVE_HEALTH_DAMAGE_RECEIPT_INVALID")
    presence = [
        (isinstance(w, dict) and "native_health_damage_taken" in w,
         isinstance(w, dict) and "native_health_damage_events" in w)
        for w in windows
    ]
    if all(not amount and not events for amount, events in presence):
        if require_positive or require_zero:
            raise AssertionError("RUST_WORLD_NATIVE_HEALTH_DAMAGE_PORT_NOT_SELECTED")
        return {"observed": False, "damage_taken": None, "damage_events": None}
    if not all(amount and events for amount, events in presence):
        raise AssertionError("RUST_WORLD_NATIVE_HEALTH_DAMAGE_RECEIPT_INVALID")
    damage_total = 0.0
    event_total = 0
    for window in windows:
        amount = window["native_health_damage_taken"]
        events = window["native_health_damage_events"]
        if (type(amount) not in (int, float) or not isfinite(amount)
                or amount < 0 or type(events) is not int or events < 0
                or (amount > 0 and events == 0)):
            raise AssertionError("RUST_WORLD_NATIVE_HEALTH_DAMAGE_RECEIPT_INVALID")
        damage_total += float(amount)
        event_total += events
    if require_positive and damage_total <= 0:
        raise AssertionError("RUST_WORLD_NATIVE_ATTACK_NOT_OBSERVED")
    if require_zero and (damage_total != 0 or event_total != 0):
        raise AssertionError("RUST_WORLD_UNEXPECTED_NATIVE_HEALTH_DAMAGE")
    return {"observed": True, "damage_taken": damage_total,
            "damage_events": event_total}



def _paid_world_route_receipts(kills: list[dict], walks: list[dict],
                               trace: list) -> tuple[list[dict], float]:
    """Measure actually elapsed gsim movement time before subsequent world kills.

    A scheduled route is only a plan. The native/2D shared clock, real gsim
    movement steps and lethal ACK bound the portion actually paid by the actor.
    This is movement accounting, NOT native health/mana recovery or a gate PASS.
    """
    if len(kills) != len(walks) + 1:
        raise AssertionError("RUST_WORLD_ROUTE_KILL_LEG_COUNT_MISMATCH")
    receipts = []
    total_paid_s = 0.0
    for index, leg in enumerate(walks):
        prior_ns = kills[index].get("world_kill_clock_ns")
        next_ns = kills[index + 1].get("world_kill_clock_ns")
        if type(prior_ns) is not int or type(next_ns) is not int or next_ns <= prior_ns:
            raise AssertionError("RUST_WORLD_ROUTE_LETHAL_CLOCK_INVALID")
        first_s, next_s = prior_ns / 1e9, next_ns / 1e9
        start_s, arrival_s = leg.get("start_s"), leg.get("arrival_s")
        yards = leg.get("scheduled_yards")
        if (any(type(v) not in (int, float) or not isfinite(v)
                for v in (start_s, arrival_s, yards))
                or yards < 0 or arrival_s < start_s
                or abs(start_s - first_s) > 1e-6):
            raise AssertionError("RUST_WORLD_ROUTE_SCHEDULE_INVALID")
        # A mob can die before its scheduled arrival (e.g. a legal instant
        # cast on the move). Do not credit the as-yet-unexecuted route tail.
        through_s = min(next_s, float(arrival_s))
        paid_s = max(0.0, through_s - start_s) if yards > 0 else 0.0
        generation = leg.get("movement_generation")
        scheduled_steps = leg.get("scheduled_movement_steps")
        planned_positions = leg.get("scheduled_step_positions")
        if (not isinstance(planned_positions, list)
                or len(planned_positions) != scheduled_steps):
            raise AssertionError("RUST_WORLD_ROUTE_QUEUED_PATH_MISSING")
        if (type(scheduled_steps) is not int
                or (yards > 0 and (type(generation) is not int
                                    or scheduled_steps <= 0))
                or (yards == 0 and (generation is not None
                                    or scheduled_steps != 0))):
            raise AssertionError("RUST_WORLD_ROUTE_STEP_SCHEDULE_INVALID")
        executed_steps = [
            event for event in trace
            if yards > 0 and event.kind == "SpatialPlayerMoveStep"
            and event.payload.get("move_generation") == generation
            and start_s < event.time_s <= next_s + 1e-9
        ]
        steps = len(executed_steps)
        if yards == 0 and arrival_s != start_s:
            raise AssertionError("RUST_WORLD_ROUTE_ZERO_DISTANCE_CLOCK_INVALID")
        if steps > scheduled_steps:
            raise AssertionError("RUST_WORLD_ROUTE_DUPLICATE_GSIM_STEPS")
        if (any(not isinstance(event.payload.get("xy"), (tuple, list))
                or tuple(event.payload["xy"]) != tuple(expected)
                for event, expected in zip(executed_steps, planned_positions))
                or any(next_step.time_s <= step.time_s
                       for step, next_step in zip(executed_steps, executed_steps[1:]))):
            raise AssertionError("RUST_WORLD_ROUTE_STEPS_NOT_QUEUED_PATH")
        if yards > 0 and next_s >= arrival_s:
            # The real lethal ACK clock alone does not prove arrival. Every
            # scheduled 2D movement step of this leg must have actually run.
            if steps == 0:
                raise AssertionError("RUST_WORLD_ROUTE_COMPLETE_WITHOUT_GSIM_STEPS")
            if steps != scheduled_steps:
                raise AssertionError("RUST_WORLD_ROUTE_INCOMPLETE_GSIM_STEPS")
        receipts.append({
            "target_id": leg["target_id"],
            "prior_kill_clock_ns": prior_ns,
            "next_kill_clock_ns": next_ns,
            "actual_paid_world_movement_s": paid_s,
            "observed_gsim_movement_steps": steps,
            "scheduled_arrival_s": arrival_s,
            "arrival_reached_before_kill": next_s >= arrival_s,
        })
        total_paid_s += paid_s
    return receipts, total_paid_s


def run(binary: Path, prepared: Path, *, mob_health: float | None = None,
        target_count: int = 2, corrupt_ack: bool = False,
        require_native_moving: bool = False,
        classic_mob_level: int | None = None,
        require_native_health_damage: bool = False,
        require_native_zero_health_damage: bool = False,
        rng_mode: str = "stochastic") -> dict:
    """Execute N world kills; retain one Rust process, actor and ACK lineage."""
    if rng_mode not in ("balanced", "stochastic"):
        raise ValueError("RUST_MULTI_WORLD_RNG_MODE_INVALID")
    if require_native_health_damage and require_native_zero_health_damage:
        raise ValueError("RUST_WORLD_CONFLICTING_NATIVE_HEALTH_CONTROLS")
    mob_health, target_metadata = _target_health_profile(mob_health, classic_mob_level)
    if type(target_count) is not int or not 2 <= target_count <= 100:
        raise ValueError("RUST_MULTI_WORLD_TARGET_COUNT_INVALID")
    request = json.loads(prepared.read_text())
    if require_native_health_damage and (not isinstance(request.get("enemy"), dict)
            or request.get("target", {}).get("auto_swing_melee") is not True):
        raise ValueError("RUST_WORLD_NATIVE_ATTACK_SOURCE_MISSING")
    source_hash = request["request_sha256"]
    if not isinstance(source_hash, str) or len(source_hash) != 64:
        raise ValueError("RUST_TWO_WORLD_PREPARED_SOURCE_INVALID")
    approach_radius_yards = _source_approach_radius(request)
    # One actual 2D world for the entire target sequence. This is the
    # existing native combat/world ACK diagnostic, not paid travel/recovery.
    # Keep the real 20-yard grid. Start near the FIRST mob, not the
    # centroid of a growing field (which falsely strands the first pull
    # in a 100-target scenario). Subsequent range is earned by actual gsim
    # player route events on the same world clock; no target teleport.
    targets = ("m1", "m0") + tuple(f"m{i}" for i in range(2, target_count))
    route = SpacedPullLayout(mob_count=target_count)
    points = route.positions_yards
    positions = {target_id: (x + approach_radius_yards - points[0][0], y - points[0][1])
                 for target_id, (x, y) in zip(targets, points)}
    actor = ActorState.from_ir(
        ActorDefinition("hero", "player", base_stats={}),
        (ResourceDefinition("health", "Health", "hero",
                            initial_amount=500, capacity=500),), ())
    world = CombatRuntime(
        actor=actor, target=TargetState.with_health("m0", mob_health, **target_metadata),
        other_targets=tuple(TargetState.with_health(t, mob_health, **target_metadata)
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
    native_moving_ticks = 0
    native_moving_receipts = 0
    native_report = None
    env = dict(os.environ, FOREVER_GSIM_WORLD_BRIDGE="1")
    proc = subprocess.Popen(
        [str(binary.resolve()), "native-world-pulls", "--infile",
         str(prepared.resolve()), "--targets", str(target_count),
         "--rng-mode", rng_mode],
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
            # The selected public fork may not yet contain the reviewed native
            # movement-ingress port. Keep the old diagnostic usable on that
            # exact pin; never report native movement-cast legality unless the
            # real Rust receipt independently acknowledges every moving tick.
            observed_moving = receipt["native_range_receipt"].get("gsim_player_moving")
            if observed_moving is None:
                if require_native_moving:
                    raise AssertionError("RUST_TWO_WORLD_NATIVE_MOVEMENT_PORT_NOT_SELECTED")
            elif type(observed_moving) is not bool or observed_moving is not tick["gsim_player_moving"]:
                raise AssertionError("RUST_TWO_WORLD_MOVING_RECEIPT_MISMATCH")
            else:
                native_moving_receipts += 1
                if observed_moving:
                    native_moving_ticks += 1
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
                        speed_yards_s=route.movement_speed_yards_s,
                        approach_radius_yards=approach_radius_yards))
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
            # The selected Rust actor can run dry before target 100.  The
            # native process exits nonzero, but each preceding lethal ACK was
            # already applied by this same gsim world.  Forward that observed
            # count and native event count to the real gate candidate scorer;
            # a failed session still cannot become a completed world screen.
            raise AssertionError(("RUST_TWO_WORLD_NATIVE_FAILED", status,
                                  stderr[-3000:], len(kills), events))
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
        # Rust is the health authority; no invented gsim player damage.
        # A completed native-damage world kill must not hide a dead actor.
        elapsed = _verified_world_elapsed(result["windows"], kills)
        min_native_health = _native_survival_min_health(
            result["windows"], target_count)
        native_mana = _native_mana_continuity(
            result["windows"], target_count)
        native_health_damage = _native_health_damage_summary(
            result["windows"], require_positive=require_native_health_damage,
            require_zero=require_native_zero_health_damage)
        if require_native_moving and walks and native_moving_ticks == 0:
            raise AssertionError("RUST_TWO_WORLD_SOURCE_NEVER_OBSERVED_REAL_GSIM_MOVEMENT")
        route_receipts, paid_world_movement_s = _paid_world_route_receipts(
            kills, walks, world.trace)
        return {
            "source_sha256": source_hash, "native_pid": proc.pid,
            "world_target_hp": mob_health,
            "world_target_provenance": target_metadata,
            "native_windows": result["windows"], "world_kills": kills,
            "minimum_native_actor_health": min_native_health,
            **native_mana,
            "native_health_damage": native_health_damage,
            "native_damage_events": events, "world_ticks": ticks,
            "native_gsim_moving_ticks": native_moving_ticks,
            "native_moving_receipts": native_moving_receipts,
            "native_movement_cast_legal": native_moving_receipts == ticks,
            "continuous_native_actor": True, "actual_2d_ack": True,
            "world_targets_killed": target_count,
            **elapsed,
            "gsim_world_walk_steps": sum(
                event.kind == "SpatialPlayerMoveStep" for event in world.trace),
            "gsim_route_legs": walks,
            "gsim_route_paid_receipts": route_receipts,
            "gsim_route_paid_movement_s": paid_world_movement_s,
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
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--mob-health", type=float, default=None)
    target.add_argument("--classic-mob-level", type=int, default=None,
                        help="CMaNGOS ordinary-mob reference HP (Classic proxy, not Forever-verified)")
    parser.add_argument("--targets", type=int, default=2)
    parser.add_argument("--require-native-moving", action="store_true")
    health_controls = parser.add_mutually_exclusive_group()
    health_controls.add_argument("--require-native-health-damage", action="store_true",
                                 help="require source enemy swings and positive Rust player damage")
    health_controls.add_argument("--require-native-zero-health-damage", action="store_true",
                                 help="require selected Rust receipts with zero incoming damage")
    args = parser.parse_args()
    valid = run(args.binary, args.prepared, mob_health=args.mob_health,
                target_count=args.targets, require_native_moving=args.require_native_moving,
                classic_mob_level=args.classic_mob_level,
                require_native_health_damage=args.require_native_health_damage,
                require_native_zero_health_damage=args.require_native_zero_health_damage)
    print("RUST_TWO_REAL_GSIM_WORLD_KILLS", json.dumps(valid, sort_keys=True), flush=True)
    forged = run(args.binary, args.prepared, mob_health=args.mob_health,
                 target_count=args.targets, corrupt_ack=True,
                 classic_mob_level=args.classic_mob_level)
    print("RUST_TWO_WORLD_FORGED_ACK_REJECTED", json.dumps(forged, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
