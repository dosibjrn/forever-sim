#!/usr/bin/env python3
"""Two *distinct* gsim 2D mob kills on one source-Rust actor/ACK timeline.

This is a bounded production integration regression, not paid recovery,
a 100-mob run, or P4/P5/P6 acceptance. Damage and Warcraft actions originate
only in the pinned Rust engine; gsim applies them to real 2D world targets.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.game.runtime.go_native_world_damage_ack import GsimNativeDamageWorldApplier
from src.game.runtime.go_world_range_feed import GsimGoRangeFeed
from tools.wf_gsim_go_live_range_probe import diagnostic_gsim_world


def run(binary: Path, prepared: Path, *, mob_health: float = 1200.,
        corrupt_ack: bool = False) -> dict:
    """Execute two world kills; retain one Rust process, actor and ACK lineage."""
    if not 0 < mob_health <= 100_000:
        raise ValueError("RUST_TWO_WORLD_MOB_HEALTH_INVALID")
    request = json.loads(prepared.read_text())
    source_hash = request["request_sha256"]
    if not isinstance(source_hash, str) or len(source_hash) != 64:
        raise ValueError("RUST_TWO_WORLD_PREPARED_SOURCE_INVALID")
    # Real two-target gsim CombatRuntime; first m1, then m0. Never replace
    # the world or actor between targets. Only the selected world mob changes.
    world = diagnostic_gsim_world(
        target_spawn_yards=15., enemy_move_speed_yards_s=0.,
        target_health=mob_health, source_single_target=False,
    )
    feed = GsimGoRangeFeed(world, native_player_index=0)
    applier = GsimNativeDamageWorldApplier(world)
    targets = ("m1", "m0")
    iteration = 0
    previous_ack = ""
    last_clock_ns = -1
    kills = []
    events = 0
    ticks = 0
    native_report = None
    env = dict(os.environ, FOREVER_GSIM_WORLD_BRIDGE="1", WOWSIM_RNG_MODE="stochastic")
    proc = subprocess.Popen(
        [str(binary.resolve()), "native-world-pulls", "--infile",
         str(prepared.resolve()), "--targets", "2"],
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
                if index != iteration + 1 or index != 1 or len(kills) != 1:
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
            if tick["native_clock_ns"] != clock_ns or tick["sequence"] != ticks:
                raise AssertionError("RUST_TWO_WORLD_RANGE_FEED_MISMATCH")
            tick["iteration_index"] = iteration
            tick["previous_world_ack_id"] = previous_ack
            tick["next_world_boundary_ns"] = (
                clock_ns + 100_000_000 if world.queue or world._enemy_motion else None)
            proc.stdin.write(json.dumps(tick, sort_keys=True, allow_nan=False) + "\n")
            proc.stdin.flush()
            receipt = json.loads(proc.stdout.readline())
            if (receipt["type"] != "native_rust_world_receipt"
                    or receipt["iteration_index"] != iteration
                    or receipt["native_process_id"] != proc.pid):
                raise AssertionError("RUST_TWO_WORLD_RECEIPT_INVALID")
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
        if native_report is None or len(kills) != 2 or events < 2:
            raise AssertionError(("RUST_TWO_WORLD_KILLS_NOT_COMPLETED", native_report, kills, events))
        result = native_report["result"]
        if (native_report["source_sha256"] != source_hash
                or result["world_targets_killed"] != 2
                or not result["continuous_native_actor"]
                or not result["actual_2d_ack"]
                or result["paid_recovery"]
                or len(result["windows"]) != 2
                or result["windows"][1]["native_kill_ns"] <= result["windows"][0]["native_kill_ns"]
                or native_report["checkpoint_certified"]):
            raise AssertionError("RUST_TWO_WORLD_NATIVE_RESULT_INVALID")
        if [k["target_id"] for k in kills] != ["m1", "m0"]:
            raise AssertionError("RUST_TWO_WORLD_DISTINCT_TARGET_IDS_INVALID")
        return {
            "source_sha256": source_hash, "native_pid": proc.pid,
            "native_windows": result["windows"], "world_kills": kills,
            "native_damage_events": events, "world_ticks": ticks,
            "continuous_native_actor": True, "actual_2d_ack": True,
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
    args = parser.parse_args()
    valid = run(args.binary, args.prepared, mob_health=args.mob_health)
    print("RUST_TWO_REAL_GSIM_WORLD_KILLS", json.dumps(valid, sort_keys=True), flush=True)
    forged = run(args.binary, args.prepared, mob_health=args.mob_health, corrupt_ack=True)
    print("RUST_TWO_WORLD_FORGED_ACK_REJECTED", json.dumps(forged, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
