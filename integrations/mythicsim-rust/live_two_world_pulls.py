#!/usr/bin/env python3
"""Multiple *distinct* gsim 2D mob kills on one source-Rust actor/ACK timeline.

This is a native↔2D ACK integration, not by itself a P4/P5/P6 acceptance.
Explicit recovery policy is executed on the retained Rust actor and clock. Damage and Warcraft actions originate
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
from src.game.runtime.native_step_protocol import snapshot_gsim_world
from src.game.runtime.go_world_range_feed import GsimGoRangeFeed
from src.game.model import ActorDefinition, ResourceDefinition
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.scenarios.spaced_pulls import SpacedPullLayout
from src.scenarios.leveling_targets import MOB_BASE_HP, representative_hp


class NativeWorldChainFailure(AssertionError):
    """A failed native/world run with observed, ACKed progress.

    This is a transport result, not a completed 100-target objective.
    Keep observed kills as data instead of forcing callers to parse stderr.
    """

    def __init__(self, reason: str, exit_code: int, detail: str,
                 killed: int, native_damage_events: int,
                 native_source_damage_effects_by_caster: dict | None = None,
                 *, native_refusal_code: str | None = None):
        # Preserve the authoritative Rust NDJSON refusal code for callers.
        # The historical five-element exception tuple stays unchanged.
        self.code = native_refusal_code
        self.reason = detail
        self.exit_code = exit_code
        self.killed = killed
        self.native_damage_events = native_damage_events
        # These are actually world-ACKed Rust effects, not inferred casts.
        # Preserve them when a hostile retained actor dies partway through.
        self.native_source_damage_effects_by_caster = {
            caster: dict(actions) for caster, actions in
            (native_source_damage_effects_by_caster or {}).items()
        }
        # Keep the existing five-element refusal tuple intact for callers.
        super().__init__((reason, exit_code, detail, killed, native_damage_events))


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


def _verified_joint_overlap_elapsed(windows: list[dict],
                                    world_kills: list[dict]) -> dict:
    """One retained native Fight; two independently ACKed 2D kill clocks.

    Source reports one joint window and must not be split into fabricated
    serial per-target resource windows. World kill deltas are real ACK clocks.
    """
    if (len(windows) != 1 or len(world_kills) != 2
            or windows[0].get("index") != 0):
        raise AssertionError("RUST_WORLD_OVERLAP_JOINT_WINDOW_INVALID")
    native_end_ns = windows[0].get("native_kill_ns")
    first = world_kills[0].get("world_kill_clock_ns")
    last = world_kills[1].get("world_kill_clock_ns")
    if (any(type(ns) is not int for ns in (native_end_ns, first, last))
            or not 0 < first < last <= native_end_ns
            or world_kills[0].get("target_id") == world_kills[1].get("target_id")
            or not all(isinstance(k.get("ack_sha256"), str)
                       and len(k["ack_sha256"]) == 64 for k in world_kills)
            or world_kills[0]["ack_sha256"] == world_kills[1]["ack_sha256"]):
        raise AssertionError("RUST_WORLD_OVERLAP_WORLD_KILL_CLOCK_INVALID")
    return {
        "world_elapsed_seconds": last / 1e9,
        "world_seconds_per_target_without_paid_recovery": last / 2e9,
        "world_per_target_elapsed_seconds_without_paid_recovery":
            [first / 1e9, (last - first) / 1e9],
        "native_joint_window_end_ns": native_end_ns,
        "world_kill_order": [k["target_id"] for k in world_kills],
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
            raise AssertionError(
                "RUST_MULTI_WORLD_NATIVE_ACTOR_NOT_ALIVE"
                f":index={index}:actor_health={health!r}")
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


def _native_paid_recovery_receipts(windows: list[dict], kills: list[dict],
                                   *, decisions: bool = False) -> dict:
    """Classify ACK-clock recovery from verified source-Rust receipts.

    Fixed passive rest needs actual native ticks. Decisions can instead pay
    for real food/water before the next mana tick, OR for a clock-advanced
    travel-only gap where Rust decided no refill was needed. Vendor receipts
    must already have passed _native_food_water_receipts clock validation.
    Older pins without native receipts remain explicitly unobserved.
    """
    if not windows or len(windows) != len(kills):
        raise AssertionError("RUST_WORLD_PAID_RECOVERY_TARGET_COUNT_INVALID")
    present = [
        isinstance(window, dict)
        and "native_passive_recovery_ns" in window
        and "native_passive_recovery_ticks" in window
        for window in windows
    ]
    if not any(present):
        return {
            "native_passive_recovery_observed": False,
            "native_passive_recovery_ns_by_target": None,
            "native_passive_recovery_ticks_by_target": None,
            "paid_recovery": False,
        }
    if not all(present):
        raise AssertionError("RUST_WORLD_PAID_RECOVERY_RECEIPT_INCOMPLETE")
    elapsed, ticks_by_target = [], []
    for index, window in enumerate(windows):
        ns = window["native_passive_recovery_ns"]
        ticks = window["native_passive_recovery_ticks"]
        if type(ns) is not int or ns < 0 or type(ticks) is not int or ticks < 0:
            raise AssertionError("RUST_WORLD_PAID_RECOVERY_RECEIPT_INVALID")
        if index == 0:
            if ns != 0 or ticks != 0:
                raise AssertionError("RUST_WORLD_FIRST_TARGET_HAS_UNPAID_RECOVERY")
        else:
            between_kills_ns = (
                kills[index]["world_kill_clock_ns"]
                - kills[index - 1]["world_kill_clock_ns"]
            )
            if ns > between_kills_ns or (ns == 0 and ticks > 0):
                raise AssertionError("RUST_WORLD_PAID_RECOVERY_CLOCK_INVALID")
        elapsed.append(ns)
        ticks_by_target.append(ticks)
    return {
        "native_passive_recovery_observed": True,
        "native_passive_recovery_ns_by_target": elapsed,
        "native_passive_recovery_ticks_by_target": ticks_by_target,
        "paid_recovery": all(
            ns > 0 and (
                ticks > 0 or (
                    decisions and (
                        windows[index]["food_seconds"] > 0
                        or windows[index]["water_seconds"] > 0
                        # The selected Rust native_world_recovery_paid also
                        # counts charged travel-only gaps when Decisions
                        # explicitly decides no refill is needed. That is
                        # clock-paid movement, not a free simulated regen tick.
                        or windows[index].get("decisions_full_recovery") is False
                    )
                )
            )
            for index, (ns, ticks) in enumerate(zip(elapsed, ticks_by_target))
            if index > 0
        ),
    }


def _native_food_water_receipts(windows: list[dict], *, required: bool) -> dict:
    """Forward native Decisions consumption, never synthesize food/water in Python."""
    keys = ("food_seconds", "water_seconds", "food_health_gain",
            "water_mana_gain", "decisions_full_recovery")
    present = [isinstance(w, dict) and all(key in w for key in keys)
               for w in windows]
    if not all(present):
        if required or any(present) or any(
                isinstance(w, dict) and any(key in w for key in keys)
                for w in windows):
            raise AssertionError("RUST_WORLD_NATIVE_FOOD_WATER_RECEIPT_INCOMPLETE")
        return {"native_food_water_observed": False}
    rows = []
    for index, window in enumerate(windows):
        values = [window[key] for key in keys[:4]]
        if (any(type(value) not in (float, int) or not isfinite(value)
                or value < 0 for value in values)
                or type(window["decisions_full_recovery"]) is not bool):
            raise AssertionError("RUST_WORLD_NATIVE_FOOD_WATER_RECEIPT_INVALID")
        food_s, water_s, food_hp, water_mana = values
        recovery_s = window.get("native_passive_recovery_ns")
        if (type(recovery_s) is not int or recovery_s < 0
                or food_s > recovery_s / 1e9 + 1e-6
                or water_s > recovery_s / 1e9 + 1e-6
                or (food_hp > 0 and food_s == 0)
                or (water_mana > 0 and water_s == 0)
                or (index == 0 and any(values))):
            raise AssertionError("RUST_WORLD_NATIVE_FOOD_WATER_CLOCK_INVALID")
        rows.append({key: window[key] for key in keys})
    return {
        "native_food_water_observed": True,
        "native_food_water_by_target": rows,
        "native_food_seconds_total": sum(row["food_seconds"] for row in rows),
        "native_water_seconds_total": sum(row["water_seconds"] for row in rows),
        "native_food_health_gain_total": sum(row["food_health_gain"] for row in rows),
        "native_water_mana_gain_total": sum(row["water_mana_gain"] for row in rows),
    }


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


def _paid_joint_overlap_route(kills: list[dict], walks: list[dict],
                              trace: list, *, switch: dict) -> tuple[list[dict], float]:
    """Account only executed gsim movement after the source A->B switch.

    Unlike serial travel, the movement does NOT start after A's lethal ACK.
    The joint fight may kill B before A; the horizon is their last world death.
    """
    if len(kills) != 2 or len(walks) != 1 or not isinstance(switch, dict):
        raise AssertionError("RUST_WORLD_OVERLAP_ROUTE_RECEIPT_COUNT_INVALID")
    leg = walks[0]
    start_ns = switch.get("switch_native_clock_ns")
    final_ns = kills[-1].get("world_kill_clock_ns")
    start = leg.get("start_s")
    arrival = leg.get("arrival_s")
    yards = leg.get("scheduled_yards")
    steps = leg.get("scheduled_movement_steps")
    queued_positions = leg.get("scheduled_step_positions")
    generation = leg.get("movement_generation")
    if (type(start_ns) is not int or type(final_ns) is not int
            or not 0 <= start_ns < final_ns
            or any(type(v) not in (float, int) or not isfinite(v)
                   for v in (start, arrival, yards))
            or abs(start - start_ns / 1e9) > 1e-6
            or arrival < start or yards < 0
            or type(steps) is not int or steps < 0
            or not isinstance(queued_positions, list)
            or len(queued_positions) != steps
            or (yards > 0 and (type(generation) is not int or steps == 0))
            or (yards == 0 and (generation is not None or steps != 0
                                or start != arrival))):
        raise AssertionError("RUST_WORLD_OVERLAP_ROUTE_SOURCE_CLOCK_INVALID")
    final_s = final_ns / 1e9
    executed = [event for event in trace
                if yards > 0 and event.kind == "SpatialPlayerMoveStep"
                and event.payload.get("move_generation") == generation
                and start < event.time_s <= final_s + 1e-9]
    if (len(executed) > steps
            or any(tuple(event.payload.get("xy", ())) != tuple(expected)
                   for event, expected in zip(executed, queued_positions))
            or any(b.time_s <= a.time_s for a, b in zip(executed, executed[1:]))
            or (final_s >= arrival and len(executed) != steps)):
        raise AssertionError("RUST_WORLD_OVERLAP_ROUTE_GSIM_STEPS_INVALID")
    paid_s = min(final_s - start, arrival - start) if yards > 0 else 0.0
    return ([{
        "target_id": leg["target_id"],
        "source_switch_clock_ns": start_ns,
        "final_world_kill_clock_ns": final_ns,
        "actual_paid_world_movement_s": paid_s,
        "observed_gsim_movement_steps": len(executed),
        "scheduled_arrival_s": arrival,
        "arrival_reached_before_kill": final_s >= arrival,
        "start_reason": "source_acked_live_overlap_switch",
    }], paid_s)


def _native_recovery_cli_args(recovery_policy: str | None,
                              recovery_seconds: int | None,
                              health_threshold: float,
                              mana_threshold: float) -> tuple[str | None, list[str]]:
    """Serialize the documented Rust recovery CLI; no Python game recovery."""
    requested_mode = recovery_policy or ("fixed" if recovery_seconds is not None else None)
    if requested_mode not in (None, "fixed", "decisions"):
        raise ValueError("RUST_WORLD_RECOVERY_POLICY_INVALID")
    native_recovery_args = []
    if requested_mode == "fixed":
        seconds = 12 if recovery_seconds is None else recovery_seconds
        if type(seconds) is not int or not 1 <= seconds <= 120:
            raise ValueError("RUST_WORLD_RECOVERY_SECONDS_INVALID")
        native_recovery_args = ["--recovery-seconds", str(seconds)]
    elif requested_mode == "decisions":
        if recovery_seconds is not None:
            raise ValueError("RUST_WORLD_RECOVERY_POLICY_CONFLICT")
        if (any(type(value) not in (int, float) or not isfinite(value)
                or not 0 <= value <= 1
                for value in (health_threshold, mana_threshold))):
            raise ValueError("RUST_WORLD_DECISIONS_THRESHOLDS_INVALID")
        native_recovery_args = [
            "--recovery-policy", "decisions",
            "--health-threshold", str(health_threshold),
            "--mana-threshold", str(mana_threshold),
        ]
    return requested_mode, native_recovery_args


def _persistent_api_evaluate_request(*, targets: int, rng_mode: str,
                                     health_threshold: float,
                                     mana_threshold: float,
                                     world_apl: dict | None = None) -> dict:
    """Forward only source-native Decisions rest inputs to the Rust API.

    Rust's native evaluate schema uses a nested between_pulls policy.
    The returned native thresholds MUST independently acknowledge any changed
    request before Forever considers its paid time a policy measurement.
    """
    request = {
        "op": "evaluate", "targets": targets,
        "rng_mode": rng_mode, "recover_at_end": True,
    }
    if (health_threshold, mana_threshold) != (1.0, 1.0):
        request["between_pulls"] = {
            "health_fraction": health_threshold,
            "mana_fraction": mana_threshold,
        }
    if world_apl is not None:
        # Send the requested World-APL to Rust; never pretend that merely
        # including a request means the native world actually executed it.
        request["world_apl"] = world_apl
    return request


def _verify_native_recovery_thresholds(result: dict, *,
                                       health_threshold: float,
                                       mana_threshold: float) -> None:
    """Never score Rust's unchanged full-rest policy as a 30% World-APL."""
    applied = result.get("thresholds")
    if (not isinstance(applied, dict)
            or applied.get("health_fraction") != health_threshold
            or applied.get("mana_fraction") != mana_threshold):
        raise AssertionError(
            "RUST_WORLD_NATIVE_RECOVERY_THRESHOLDS_NOT_APPLIED:"
            f" requested=({health_threshold},{mana_threshold})"
            f" observed={applied!r}")


def _verify_native_rolling_world_apl(
        result: dict, *, requested: dict, kills: list[dict],
        source_switch: dict, old_target_dot_ticks: int,
        first_world_id: str, second_world_id: str) -> dict:
    """Require native two-live-target telemetry plus real distinct world ACKs.

    The current serial Rust scheduler cannot supply this evidence. An
    unrecognized/ignored World-APL field therefore fails closed instead of
    recycling the successful serial paid world as an overlap measurement.
    """
    applied = result.get("applied_world_apl")
    overlap = result.get("world_overlap")
    kill_ids = [row["target_id"] for row in kills]
    kill_acks = [row["ack_sha256"] for row in kills]
    # Rust #55 currently proves the joint source Fight but does not yet
    # return applied_world_apl. Keep this exact policy echo mandatory:
    # an ignored API request cannot become a paid optimizer observation.
    if (applied != requested or not isinstance(overlap, dict)
            or overlap.get("source_apl_selected_b") is not True
            or overlap.get("both_world_targets_lethal_ack") is not True
            or overlap.get("native_world_target_indices") != [0, 1]
            or overlap.get("world_target_ids") != [first_world_id, second_world_id]
            or overlap.get("combined_native_fight_window") is not True
            or source_switch.get("prior_world_target_id") != first_world_id
            or source_switch.get("to_native_target_index") != 1
            or type(old_target_dot_ticks) is not int
            or old_target_dot_ticks < 1
            or len(kill_ids) != 2 or set(kill_ids) != {first_world_id, second_world_id}
            or len(set(kill_acks)) != 2
            or any(not isinstance(ack, str) or len(ack) != 64 for ack in kill_acks)):
        raise AssertionError(
            "RUST_WORLD_NATIVE_ROLLING_APL_NOT_PROVEN:"
            f" applied={applied!r} overlap={overlap!r}"
            f" kills={kill_ids!r} old_dot_ticks={old_target_dot_ticks}")
    return {
        **overlap,
        "native_target_to_world_id": {"0": first_world_id, "1": second_world_id},
        "max_concurrent_alive_targets": 2,
        "simultaneously_alive_world_target_ids": [first_world_id, second_world_id],
        "old_target_dot_ticks_after_switch_acked": old_target_dot_ticks,
    }


def accumulate_acked_native_source_effects(
        counts: dict, native_receipt: dict, world_ack: dict) -> None:
    """Forward only Rust damage effects that the 2D world actually ACKed.

    This is a transport/accounting observation, not a Warcraft source audit,
    individual spell cast count, or P4 unlock acceptance verdict.
    """
    applied = set(world_ack["applied_event_ids"])
    for effect in native_receipt["native_damage_events"]:
        if effect["event_id"] not in applied:
            continue
        # Preserve source-native identities and caster types verbatim. In
        # particular, pet effects must not count as player spell effects.
        action_id = effect.get("source_action_id")
        caster = effect.get("native_caster_type")
        if isinstance(action_id, str) and action_id and isinstance(caster, str):
            actions = counts.setdefault(caster, {})
            actions[action_id] = actions.get(action_id, 0) + 1


def _source_acked_rolling_switch(source: dict, *, world: CombatRuntime,
                                 old_id: str, new_id: str, previous_ack: str,
                                 source_sequence: int, last_clock_ns: int,
                                 boundary_clock_ns: int) -> dict:
    """Only Rust's earlier, hash-bound live A health ACK can admit B."""
    if not isinstance(source, dict):
        raise AssertionError("RUST_WORLD_OVERLAP_SOURCE_SWITCH_MISSING")
    old, new = world.targets[old_id], world.targets[new_id]
    health = source.get("prior_world_target_health")
    maximum = source.get("prior_world_target_max_health")
    switch_ns = source.get("switch_native_clock_ns")
    # Source-ACK refusal keeps the observed 2D identities available for
    # diagnosing a real nonlethal switch without certifying a fabricated one.
    enemy_state = snapshot_gsim_world(world)["enemies"]
    if (type(source.get("from_native_target_index")) is not int
            or source["from_native_target_index"] != 0
            or type(source.get("to_native_target_index")) is not int
            or source["to_native_target_index"] != 1
            or source.get("prior_world_target_id") != old_id
            or source.get("prior_world_ack_id") != previous_ack
            or not isinstance(previous_ack, str) or len(previous_ack) != 64
            or type(source.get("source_ack_sequence")) is not int
            or source["source_ack_sequence"] != source_sequence
            or type(switch_ns) is not int
            or not last_clock_ns <= switch_ns <= boundary_clock_ns
            or type(health) not in (int, float)
            or type(maximum) not in (int, float)
            or not isfinite(health) or not isfinite(maximum)
            or maximum <= 0 or health <= 0 or health > maximum
            or abs(float(health) - float(old.health)) > 1e-6
            or abs(float(maximum) - float(old.max_health)) > 1e-6
            or source.get("health_fraction_at_most") != 0.5
            or health / maximum > 0.5
            or not old.alive or not new.alive
            or not enemy_state[old_id]["engaged"]
            or enemy_state[new_id]["engaged"]):
        raise AssertionError(
            "RUST_WORLD_OVERLAP_SOURCE_SWITCH_UNACKED:"
            f" old_engaged={enemy_state[old_id]['engaged']}"
            f" new_engaged={enemy_state[new_id]['engaged']}"
            f" old_alive={old.alive} new_alive={new.alive}"
            f" source_hp_fraction={health / maximum if type(health) in (int, float) and type(maximum) in (int, float) and maximum else None}"
            f" world_hp_fraction={old.health / old.max_health}")
    return dict(source)


def _new_source_acked_world_kills(*, world: CombatRuntime,
                                  before: dict[str, float],
                                  ack: dict, clock_ns: int,
                                  overlap: bool,
                                  native_target_ids: tuple[str, str] | None = None) -> list[dict]:
    """Record actual 2D kills using the explicit native slot/world ID binding."""
    rows = ack.get("native_target_health_acks") if overlap else None
    # In a joint Fight slot 0 is original A and slot 1 is acquired B.
    # Do not derive those bindings from snapshot dictionary insertion order.
    if overlap:
        if (not isinstance(native_target_ids, tuple)
                or len(native_target_ids) != 2
                or any(not isinstance(value, str) or not value
                       for value in native_target_ids)
                or len(set(native_target_ids)) != 2
                or set(native_target_ids) != set(before)):
            raise AssertionError("RUST_TWO_WORLD_KILL_SLOT_MAP_INVALID")
        slot_by_id = {world_id: index
                      for index, world_id in enumerate(native_target_ids)}
    deaths = []
    for target_id, previous_hp in before.items():
        after_hp = float(world.targets[target_id].health)
        if previous_hp <= 0 or after_hp != 0:
            continue
        if overlap:
            matched = [row for row in (rows if isinstance(rows, list) else [])
                       if isinstance(row, dict)
                       and type(row.get("native_target_index")) is int
                       and row["native_target_index"] == slot_by_id[target_id]
                       and row.get("world_target_id") == target_id
                       and row.get("world_target_health_before") == previous_hp
                       and row.get("world_target_health_after") == 0]
            if len(matched) != 1:
                raise AssertionError("RUST_TWO_WORLD_KILL_NOT_INDEX_ACKED")
        elif (ack.get("world_target_health_before") != previous_hp
              or ack.get("world_target_health_after") != 0):
            raise AssertionError("RUST_TWO_WORLD_KILL_NOT_ACKED")
        deaths.append({"target_id": target_id, "world_kill_clock_ns": clock_ns,
                       "ack_sha256": ack["world_after_sha256"]})
    return deaths


def run(binary: Path, prepared: Path, *, mob_health: float | None = None,
        target_count: int = 2, corrupt_ack: bool = False,
        require_native_moving: bool = False,
        classic_mob_level: int | None = None,
        require_native_health_damage: bool = False,
        require_native_zero_health_damage: bool = False,
        rng_mode: str = "stochastic",
        recovery_policy: str | None = None,
        recovery_seconds: int | None = None,
        health_threshold: float = 0.5,
        mana_threshold: float = 0.1,
        world_apl: dict | None = None,
        api_process: subprocess.Popen | None = None,
        prepared_payload: dict | None = None) -> dict:
    """Execute N world kills; retain one Rust process, actor and ACK lineage.

    No policy means the existing native default. Explicit fixed/Decisions
    requests use only the Rust CLI; Python never grants resource recovery.
    """
    if rng_mode not in ("balanced", "stochastic"):
        raise ValueError("RUST_MULTI_WORLD_RNG_MODE_INVALID")
    if require_native_health_damage and require_native_zero_health_damage:
        raise ValueError("RUST_WORLD_CONFLICTING_NATIVE_HEALTH_CONTROLS")
    requested_mode, native_recovery_args = _native_recovery_cli_args(
        recovery_policy, recovery_seconds, health_threshold, mana_threshold)
    seconds = 12 if recovery_seconds is None else recovery_seconds
    mob_health, target_metadata = _target_health_profile(mob_health, classic_mob_level)
    if type(target_count) is not int or not 2 <= target_count <= 100:
        raise ValueError("RUST_MULTI_WORLD_TARGET_COUNT_INVALID")
    request = (prepared_payload if prepared_payload is not None
               else json.loads(prepared.read_text()))
    if world_apl is not None and (
            api_process is None or world_apl != {
                "pull_mode": "rolling",
                "switch_trigger": {
                    "type": "current_target_hp_fraction_at_most",
                    "fraction": 0.5,
                },
                "max_live_targets": 2,
            }):
        raise ValueError("RUST_WORLD_APL_NATIVE_API_OR_POLICY_UNSUPPORTED")
    if api_process is not None and (not isinstance(request, dict)
                                    or api_process.poll() is not None):
        raise ValueError("NATIVE_API_SESSION_OR_PREPARED_ACTOR_INVALID")
    # PreparedV2 has a native "target" attack actor, not an "enemy" key.
    # Never pre-veto its real source-health probe using a Python shape guess.
    # The actual native per-window damage receipt must still be observed and
    # strictly positive when require_native_health_damage is requested.
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
    rolling_switch = None
    old_target_dot_ticks_after_switch = 0
    events = 0
    # Source-action IDs are emitted by the selected Rust combat boundary.
    # Retain only damage events actually applied/ACKed by the 2D world;
    # these are observed effects, NOT an inferred spell-cast count.
    native_source_damage_effects_by_caster = {}
    ticks = 0
    native_moving_ticks = 0
    native_moving_receipts = 0
    native_report = None
    env = dict(os.environ, FOREVER_GSIM_WORLD_BRIDGE="1")
    proc = api_process or subprocess.Popen(
        [str(binary.resolve()), "native-world-pulls", "--infile",
         str(prepared.resolve()), "--targets", str(target_count),
         "--rng-mode", rng_mode, *native_recovery_args],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1, env=env,
    )
    if api_process is not None:
        if requested_mode != "decisions":
            raise ValueError("NATIVE_API_REQUIRES_DECISIONS_RECOVERY")
        proc.stdin.write(json.dumps(_persistent_api_evaluate_request(
            targets=target_count, rng_mode=rng_mode,
            health_threshold=health_threshold, mana_threshold=mana_threshold,
            world_apl=world_apl,
        ), sort_keys=True) + "\n")
        proc.stdin.flush()
    try:
        for line in proc.stdout:
            native = json.loads(line)
            if api_process is not None and "ok" in native:
                if native.get("ok") is not True:
                    # Rust sends both a structured refusal and legacy human
                    # error string. Never discard the native code at this
                    # world/ACK boundary (previously every result was None).
                    refusal = native.get("refusal")
                    native_code = (refusal.get("code")
                                   if isinstance(refusal, dict) else None)
                    native_reason = (refusal.get("reason")
                                     if isinstance(refusal, dict) else None)
                    raise NativeWorldChainFailure(
                        "RUST_NATIVE_API_EVALUATE_REFUSED", -1,
                        str(native_reason if isinstance(native_reason, str)
                            else native.get("error"))[-3000:],
                        len(kills), events,
                        native_source_damage_effects_by_caster,
                        native_refusal_code=native_code
                            if isinstance(native_code, str) else None)
                native_report = native.get("result")
                break
            if native.get("type") != "native_rust_world_boundary_request":
                if native.get("engine") == "forever-engine":
                    if native_report is not None:
                        raise AssertionError("RUST_TWO_WORLD_DUPLICATE_REPORT")
                    native_report = native
                    continue
                raise AssertionError(("RUST_TWO_WORLD_UNEXPECTED_OUTPUT", native))
            index = native["iteration_index"]
            clock_ns = native["native_clock_ns"]
            source_switch = native.get("source_apl_world_switch")
            if index != iteration:
                if index != iteration + 1 or index >= target_count:
                    raise AssertionError("RUST_TWO_WORLD_TARGET_INDEX_SKIP")
                if world_apl is not None:
                    if (target_count != 2 or iteration != 0 or index != 1
                            or rolling_switch is not None or kills):
                        raise AssertionError("RUST_WORLD_OVERLAP_THIRD_OR_EARLY_SWITCH")
                    rolling_switch = _source_acked_rolling_switch(
                        source_switch, world=world, old_id=targets[0],
                        new_id=targets[1], previous_ack=previous_ack,
                        source_sequence=ticks, last_clock_ns=last_clock_ns,
                        boundary_clock_ns=clock_ns)
                    iteration = index
                    # The source APL may switch after the prior world tick.
                    # Charge that elapsed source-clock gap in the real world
                    # before engaging B or scheduling any movement.
                    switch_ns = rolling_switch["switch_native_clock_ns"]
                    if switch_ns % 1_000_000:
                        raise AssertionError(
                            "RUST_WORLD_OVERLAP_SOURCE_SWITCH_MS_UNSUPPORTED")
                    world.advance_to(switch_ns / 1e9)
                    world.engage_target(targets[iteration])
                    world.select_target(targets[iteration])
                    applier.begin_overlapping_world_target(targets[iteration])
                    # Queue a real, charged gsim walk at the source-ACKed
                    # switch, while A is still alive (not after A's kill).
                    walks.append(_queue_world_walk(
                        world, targets[iteration],
                        speed_yards_s=route.movement_speed_yards_s,
                        approach_radius_yards=approach_radius_yards))
                else:
                    if len(kills) != index:
                        raise AssertionError("RUST_TWO_WORLD_TARGET_INDEX_SKIP")
                    if world.targets[targets[iteration]].alive:
                        raise AssertionError("RUST_TWO_WORLD_NEXT_TARGET_BEFORE_LETHAL")
                    if source_switch is not None:
                        raise AssertionError("RUST_WORLD_UNREQUESTED_SOURCE_OVERLAP")
                    iteration = index
                    world.engage_target(targets[iteration])
                    world.select_target(targets[iteration])
                    applier.begin_next_world_target(targets[iteration])
            elif (source_switch is not None
                  and (rolling_switch is None or source_switch != rolling_switch)):
                raise AssertionError("RUST_WORLD_UNACKED_OR_MUTATED_SOURCE_SWITCH")
            elif rolling_switch is not None and source_switch != rolling_switch:
                raise AssertionError("RUST_WORLD_OVERLAP_SWITCH_ANCESTRY_LOST")
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
            before_health = {target_id: float(world.targets[target_id].health)
                             for target_id in targets}
            ack = applier.apply(tick, receipt)
            ack["iteration_index"] = iteration
            events += len(ack["applied_event_ids"])
            if corrupt_ack and events:
                ack["applied_event_ids"] = []
            accumulate_acked_native_source_effects(
                native_source_damage_effects_by_caster, receipt, ack)
            if (rolling_switch is not None
                    and before_health[targets[0]] > world.targets[targets[0]].health):
                # The old A really lost 2D HP in this ACK. Only then count
                # source-periodic effects on A; a dead-target overkill event
                # must never become evidence of a live post-switch DoT tick.
                applied = set(ack["applied_event_ids"])
                old_target_dot_ticks_after_switch += sum(
                    effect.get("native_target_index") == 0
                    and effect.get("periodic") is True
                    and effect.get("event_id") in applied
                    and effect.get("damage", 0) > 0
                    for effect in ack["applied_events"])
            newly_dead = _new_source_acked_world_kills(
                world=world, before=before_health, ack=ack,
                clock_ns=clock_ns, overlap=rolling_switch is not None,
                native_target_ids=targets[:2] if rolling_switch is not None else None)
            for death in newly_dead:
                if death["target_id"] in {k["target_id"] for k in kills}:
                    raise AssertionError("RUST_TWO_WORLD_DUPLICATE_KILL")
                kills.append(death)
            proc.stdin.write(json.dumps(ack, sort_keys=True, allow_nan=False) + "\n")
            proc.stdin.flush()
            previous_ack = ack["world_after_sha256"]
            last_clock_ns = clock_ns
            ticks += 1
            if (newly_dead and rolling_switch is None and not corrupt_ack
                    and iteration + 1 < target_count):
                # Legacy serial route is still permitted only after lethal.
                walks.append(_queue_world_walk(
                    world, targets[iteration + 1],
                    speed_yards_s=route.movement_speed_yards_s,
                    approach_radius_yards=approach_radius_yards))
            if corrupt_ack and events:
                break
        if api_process is None:
            proc.stdin.close()
            stderr = proc.stderr.read()
            status = proc.wait(timeout=20)
        else:
            # The persistent API process is reused for the next candidate.
            # Its stdout is terminated by an API response, not by process EOF.
            stderr, status = "", 0
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
            raise NativeWorldChainFailure("RUST_TWO_WORLD_NATIVE_FAILED", status,
                                          stderr[-3000:], len(kills), events,
                                          native_source_damage_effects_by_caster)
        if native_report is None or len(kills) != target_count or events < target_count:
            raise NativeWorldChainFailure("RUST_TWO_WORLD_KILLS_NOT_COMPLETED",
                                          status, str(native_report)[-3000:],
                                          len(kills), events,
                                          native_source_damage_effects_by_caster)
        result = native_report["result"]
        if (api_process is not None and requested_mode == "decisions"
                and (health_threshold, mana_threshold) != (1.0, 1.0)):
            _verify_native_recovery_thresholds(
                result, health_threshold=health_threshold,
                mana_threshold=mana_threshold)
        if (native_report["source_sha256"] != source_hash
                or result["world_targets_killed"] != target_count
                or not result["continuous_native_actor"]
                or not result["actual_2d_ack"]
                or type(result.get("paid_recovery")) is not bool
                or len(result["windows"]) != (1 if rolling_switch is not None else target_count)
                or any(b["native_kill_ns"] <= a["native_kill_ns"]
                       for a, b in zip(result["windows"], result["windows"][1:]))
                or native_report["checkpoint_certified"]):
            raise AssertionError("RUST_TWO_WORLD_NATIVE_RESULT_INVALID")
        if (len({k["target_id"] for k in kills}) != target_count
                or set(k["target_id"] for k in kills) != set(targets)
                or (rolling_switch is None
                    and [k["target_id"] for k in kills] != list(targets))):
            raise AssertionError("RUST_TWO_WORLD_DISTINCT_TARGET_IDS_INVALID")
        if world_apl is not None and rolling_switch is None:
            raise AssertionError("RUST_WORLD_ROLLING_SOURCE_SWITCH_NOT_OBSERVED")
        if rolling_switch is not None and (
                not isinstance(result.get("world_overlap"), dict)
                or result["windows"][0].get("index") != 0
                or result["windows"][0].get("native_kill_ns", 0)
                   < kills[-1]["world_kill_clock_ns"]):
            raise AssertionError("RUST_WORLD_OVERLAP_JOINT_WINDOW_NOT_PROVEN")
        native_world_overlap = (
            _verify_native_rolling_world_apl(
                result, requested=world_apl, kills=kills,
                source_switch=rolling_switch,
                old_target_dot_ticks=old_target_dot_ticks_after_switch,
                first_world_id=targets[0], second_world_id=targets[1])
            if world_apl is not None else None
        )
        # Rust is the health authority; no invented gsim player damage.
        # A completed native-damage world kill must not hide a dead actor.
        native_window_count = 1 if rolling_switch is not None else target_count
        elapsed = (_verified_joint_overlap_elapsed(result["windows"], kills)
                   if rolling_switch is not None
                   else _verified_world_elapsed(result["windows"], kills))
        min_native_health = _native_survival_min_health(
            result["windows"], native_window_count)
        native_mana = _native_mana_continuity(
            result["windows"], native_window_count)
        if rolling_switch is not None:
            # One joint native Fight ends after BOTH lethal world ACKs. Do not
            # present its terminal mana/regen as two independent kill states.
            native_mana["native_actor_mana_after_joint_overlap_fight"] = (
                native_mana.pop("native_actor_mana_after_world_kills")[0])
            native_mana.pop("native_actor_mana_delta_between_world_kills")
            for old, new in (
                ("native_combat_mana_regen_actual_gain_by_target",
                 "native_combat_mana_regen_actual_gain_by_joint_fight"),
                ("native_combat_mana_regen_events_by_target",
                 "native_combat_mana_regen_events_by_joint_fight"),
            ):
                if old in native_mana:
                    native_mana[new] = native_mana.pop(old)[0]
        food_water = _native_food_water_receipts(
            result["windows"], required=requested_mode == "decisions")
        recovery = _native_paid_recovery_receipts(
            result["windows"], ([kills[-1]] if rolling_switch is not None else kills),
            decisions=requested_mode == "decisions")
        if requested_mode == "fixed":
            # The earlier pinned fixed-duration Rust bridge did not yet emit
            # recovery_mode, but it DID echo the exact applied duration.
            if result.get("recovery_mode") not in (None, "fixed_passive"):
                raise AssertionError("RUST_WORLD_NATIVE_RECOVERY_POLICY_NOT_APPLIED")
            if result.get("recovery_seconds_per_gap") != seconds:
                raise AssertionError("RUST_WORLD_NATIVE_RECOVERY_DURATION_NOT_APPLIED")
        elif requested_mode == "decisions":
            if result.get("recovery_mode") != "decisions_food_water":
                raise AssertionError("RUST_WORLD_NATIVE_RECOVERY_POLICY_NOT_APPLIED")
        if result["paid_recovery"] is not recovery["paid_recovery"]:
            raise AssertionError("RUST_WORLD_NATIVE_PAID_RECOVERY_FLAG_MISMATCH")
        # Fixed rest promises a charged gap after every kill.  Decisions is
        # conditional: a healthy actor can legitimately skip any particular
        # gap. The native per-target ns/tick/food receipts still account for
        # every gap; zero rest is not an unpaid *requested* rest. Keep the
        # existing native paid_recovery flag as-is instead of rewriting it.
        native_recovery_clock_accounted = (
            recovery["paid_recovery"] if requested_mode != "decisions"
            else (recovery["native_passive_recovery_observed"]
                  and food_water["native_food_water_observed"]))
        native_health_damage = _native_health_damage_summary(
            result["windows"], require_positive=require_native_health_damage,
            require_zero=require_native_zero_health_damage)
        if require_native_moving and walks and native_moving_ticks == 0:
            raise AssertionError("RUST_TWO_WORLD_SOURCE_NEVER_OBSERVED_REAL_GSIM_MOVEMENT")
        route_receipts, paid_world_movement_s = (
            _paid_joint_overlap_route(
                kills, walks, world.trace, switch=rolling_switch)
            if rolling_switch is not None
            else _paid_world_route_receipts(kills, walks, world.trace))
        return {
            "source_sha256": source_hash, "native_pid": proc.pid,
            "world_target_hp": mob_health,
            "world_target_provenance": target_metadata,
            "native_windows": result["windows"], "world_kills": kills,
            "minimum_native_actor_health": min_native_health,
            "native_actor_resource_observation_scope": (
                "joint_fight_end_only" if rolling_switch is not None
                else "each_serial_world_kill"),
            **native_mana,
            **recovery,
            **food_water,
            "native_recovery_clock_accounted": native_recovery_clock_accounted,
            "native_recovery_mode": result.get("recovery_mode"),
            # Forward only an actual selected-Rust post-final-kill refill receipt.
            # Older pins omit it: missing is not full-resource recovery.
            "native_terminal_recovery": result.get("terminal_recovery"),
            "native_recovery_seconds_per_gap": result.get("recovery_seconds_per_gap"),
            "native_recovery_thresholds": result.get("thresholds"),
            "native_world_apl": result.get("applied_world_apl"),
            "native_world_overlap": native_world_overlap,
            "native_world_overlap_verified": native_world_overlap is not None,
            "native_passive_recovery_elapsed_seconds": (
                sum(recovery["native_passive_recovery_ns_by_target"]) / 1e9
                if recovery["native_passive_recovery_observed"] else None),
            # Only a native-confirmed paid recovery grants this elapsed
            # objective. The existing diagnostic clock field remains intact.
            "world_seconds_per_target_paid_recovery": (
                elapsed["world_elapsed_seconds"] / target_count
                if native_recovery_clock_accounted else None),
            "world_per_target_elapsed_seconds_paid_recovery": (
                elapsed["world_per_target_elapsed_seconds_without_paid_recovery"]
                if native_recovery_clock_accounted else None),
            "native_health_damage": native_health_damage,
            "native_damage_events": events,
            "native_source_damage_effects_by_caster": native_source_damage_effects_by_caster,
            "world_ticks": ticks,
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
            "checkpoint_certified": False,
        }
    finally:
        if api_process is None and proc.poll() is None:
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
