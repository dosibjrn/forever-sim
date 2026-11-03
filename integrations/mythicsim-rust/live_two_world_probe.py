#!/usr/bin/env python3
"""Drive two DISTINCT live gsim mobs through one selected native Rust Fight.

This is a production-boundary diagnostic, NOT P4/P5/P6 acceptance: it does
not yet charge paid travel/recovery or run 100 consecutive targets. The optional
explicit target-HP override is a *synthetic smoke control*, never source proof.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.game.runtime.go_native_world_damage_ack import GsimNativeDamageWorldApplier
from src.game.runtime.go_world_range_feed import GsimGoRangeFeed
from tools.wf_gsim_go_live_range_probe import diagnostic_gsim_world


def prepared_source_health(prepared: dict) -> float:
    health = prepared["target"]["stats"]["Health"]
    if type(health) not in (float, int) or not math.isfinite(health) or health <= 0:
        raise ValueError("TWO_WORLD_SOURCE_TARGET_HEALTH_INVALID")
    return float(health)


def run(binary: Path, prepared_path: Path, *,
        diagnostic_world_health: float | None = None, distance: float = 15.) -> dict:
    raw = prepared_path.read_bytes()
    prepared = json.loads(raw)
    if prepared.get("contract") != "forever-prepared":
        raise ValueError("TWO_WORLD_PREPARED_CONTRACT_INVALID")
    source_health = prepared_source_health(prepared)
    if diagnostic_world_health is not None:
        if (type(diagnostic_world_health) not in (float, int)
                or not math.isfinite(diagnostic_world_health)
                or diagnostic_world_health <= 0):
            raise ValueError("TWO_WORLD_DIAGNOSTIC_HEALTH_INVALID")
    target_health = (float(diagnostic_world_health)
                     if diagnostic_world_health is not None else source_health)
    world = diagnostic_gsim_world(
        target_spawn_yards=distance, enemy_move_speed_yards_s=0.,
        target_health=target_health, source_single_target=False,
    )
    feed = GsimGoRangeFeed(world, native_player_index=0)
    applier = GsimNativeDamageWorldApplier(world)
    source_sha = prepared["request_sha256"]
    if not isinstance(source_sha, str) or len(source_sha) != 64:
        raise ValueError("TWO_WORLD_SOURCE_HASH_MISSING")
    previous_ack_id = ""
    next_target = 0
    last_clock_ns = -1
    native_pid = None
    deaths = []
    damage_event_ids = []
    done_records = []
    world_kills = []
    env = dict(os.environ, FOREVER_GSIM_WORLD_BRIDGE="1")
    with subprocess.Popen(
        [str(binary.resolve()), "native-pulls", "--infile",
         str(prepared_path.resolve()), "--targets", "2"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1, env=env,
    ) as proc:
        try:
            for line in proc.stdout:
                native = json.loads(line)
                kind = native.get("type")
                if kind == "native_rust_world_iteration_done":
                    assert native["iteration_index"] == len(done_records)
                    assert native["native_process_id"] == proc.pid
                    assert native["native_request_sha256"] == source_sha
                    assert native["native_duration_ns"] > 0
                    assert world_kills[-1] == ("m1" if len(done_records) == 0 else "m0")
                    done_records.append(native)
                    continue
                if kind != "native_rust_world_boundary_request":
                    # Final native-pulls CLI JSON follows the two terminal receipts.
                    if kind is not None or native.get("engine") != "forever-engine":
                        raise AssertionError("TWO_WORLD_UNEXPECTED_NATIVE_OUTPUT")
                    result = native
                    break
                index = native["iteration_index"]
                if index not in (0, 1) or index < next_target:
                    raise AssertionError("TWO_WORLD_NATIVE_TARGET_INDEX_INVALID")
                clock_ns = native["native_clock_ns"]
                if (type(clock_ns) is not int or clock_ns % 1_000_000
                        or clock_ns <= last_clock_ns):
                    raise AssertionError("TWO_WORLD_NATIVE_CLOCK_NOT_MONOTONIC")
                if (native["native_request_sha256"] != source_sha
                        or native["native_process_id"] != proc.pid):
                    raise AssertionError("TWO_WORLD_NATIVE_IDENTITY_DRIFT")
                world.advance_to(clock_ns / 1e9)
                if index != next_target:
                    if (index != 1 or next_target != 0 or world.targets["m1"].alive
                            or len(done_records) != 1):
                        raise AssertionError("TWO_WORLD_PREMATURE_NATIVE_RETARGET")
                    world.engage_target("m0")
                    world.select_target("m0")
                    applier.begin_next_world_target("m0")
                    next_target = 1
                tick = feed.next_tick()
                if tick["sequence"] != native["sequence"]:
                    raise AssertionError("TWO_WORLD_NATIVE_SEQUENCE_RESET")
                tick.update(previous_world_ack_id=previous_ack_id,
                            iteration_index=index,
                            next_world_boundary_ns=(
                                clock_ns + 100_000_000
                                if world.queue or world._enemy_motion else None
                            ))
                proc.stdin.write(json.dumps(tick, sort_keys=True, allow_nan=False) + "\n")
                proc.stdin.flush()
                receipt = json.loads(proc.stdout.readline())
                if (receipt.get("type") != "native_rust_world_receipt"
                        or receipt["iteration_index"] != index
                        or receipt["native_process_id"] != proc.pid
                        or receipt["native_request_sha256"] != source_sha):
                    raise AssertionError("TWO_WORLD_NATIVE_RECEIPT_INVALID")
                feed.accept_range_receipt(receipt["native_range_receipt"])
                ack = applier.apply(tick, receipt)
                ack["iteration_index"] = index
                for event_id in ack["applied_event_ids"]:
                    if event_id in damage_event_ids:
                        raise AssertionError("TWO_WORLD_DUPLICATE_NATIVE_DAMAGE_EVENT")
                    damage_event_ids.append(event_id)
                previous_ack_id = ack["world_after_sha256"]
                if ack["world_target_health_after"] == 0:
                    killed = tick["selected_target_id"]
                    if killed not in world_kills:
                        world_kills.append(killed)
                        deaths.append({"id": killed, "clock_ns": clock_ns,
                                       "ack": previous_ack_id})
                proc.stdin.write(json.dumps(ack, sort_keys=True, allow_nan=False) + "\n")
                proc.stdin.flush()
                last_clock_ns = clock_ns
            else:
                raise AssertionError("TWO_WORLD_NATIVE_FINAL_REPORT_MISSING")
            proc.stdin.close()
            stderr = proc.stderr.read()
            status = proc.wait(timeout=20)
            assert status == 0, ("TWO_WORLD_NATIVE_FAILURE", stderr[-4000:])
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
    assert len(done_records) == 2 and world_kills == ["m1", "m0"], (
        "TWO_WORLD_KILLS_NOT_PROVEN", world_kills, len(done_records))
    assert result["result"]["scope"] == "TWO_REAL_GSIM_WORLD_KILLS_DIAGNOSTIC_NOT_GATE"
    assert result["result"]["continuous_actor"]
    assert result["result"]["actual_2d_ack"]
    assert result["result"]["paid_recovery"] is False
    assert len(result["result"]["windows"]) == 2
    assert len(damage_event_ids) >= 2 and deaths[1]["clock_ns"] > deaths[0]["clock_ns"]
    return {
        "native_pid": proc.pid, "source_request_sha256": source_sha,
        "prepared_raw_sha256": hashlib.sha256(raw).hexdigest(),
        "world_health": target_health,
        "synthetic_health_override": diagnostic_world_health is not None,
        "world_kills": world_kills, "deaths": deaths,
        "native_damage_event_count": len(damage_event_ids),
        "native_terminal_records": len(done_records),
        "paid_recovery": False, "checkpoint_certified": False,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--binary", required=True, type=Path)
    p.add_argument("--prepared", required=True, type=Path)
    p.add_argument("--diagnostic-world-health", type=float, default=None,
                   help="explicit synthetic 2D HP control; NEVER a source/gate proof")
    args = p.parse_args()
    actual = run(args.binary, args.prepared,
                 diagnostic_world_health=args.diagnostic_world_health)
    print("REAL_NATIVE_TWO_GSIM_WORLD_TARGETS", json.dumps(actual, sort_keys=True))


if __name__ == "__main__":
    main()
