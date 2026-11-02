#!/usr/bin/env python3
"""Live gsim CombatRuntime ↔ pinned source-Rust Fight event loop.

Uses real native spell-result events, world-applied target HP, verified ACKs,
and world-derived 2D range/facing before the next Rust scheduler decision.
This is a bounded multi-fight vertical diagnostic, NOT P7.1.3 or 1/148.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.game.runtime.go_native_world_damage_ack import GsimNativeDamageWorldApplier
from src.game.runtime.go_world_range_feed import GsimGoRangeFeed
from tools.wf_gsim_go_live_range_probe import (
    diagnostic_gsim_world, source_target_health_from_request,
)

def run(binary: Path, request: Path, *, distance: float, forge_ack: bool = False,
        iterations: int = 1, periodic_world_poll: bool = False) -> dict:
    raw = request.read_bytes()
    source = json.loads(raw)
    players = [p for party in source["raid"]["parties"] for p in party["players"]]
    assert len(players) == 1 and source["encounter"]["targets"][0]["level"] == 63
    assert players[0]["class"] == "ClassDruid"
    if not 1 <= iterations <= source["simOptions"]["iterations"]:
        raise ValueError("RUST_WORLD_ITERATIONS_OUT_OF_SOURCE_RANGE")
    def new_world():
        world = diagnostic_gsim_world(
            target_spawn_yards=distance, enemy_move_speed_yards_s=0.,
            target_health=source_target_health_from_request(raw), source_single_target=True,
            source_in_front_of_target=players[0].get("inFrontOfTarget", False),
        )
        return world, GsimGoRangeFeed(world, native_player_index=0), GsimNativeDamageWorldApplier(world)
    world = feed = applier = None
    raw_sha = hashlib.sha256(raw).hexdigest()
    # Rust's prepared request identity is SHA256 of deterministic protobuf
    # wire encoding, NOT the raw JSON byte hash. Ask the genuine source engine.
    with tempfile.TemporaryDirectory() as prep_dir:
        prepared_file = Path(prep_dir) / "prepared.json"
        subprocess.run([str(binary.resolve()), "prepare", "--request",
                        str(request.resolve()), "--outfile", str(prepared_file)],
                       check=True, capture_output=True, text=True)
        request_sha = json.loads(prepared_file.read_text())["request_sha256"]
    previous_ack_id = ""
    event_count = 0
    applied_damage = 0.
    last_tick = -1
    iteration = -1
    samples = []
    iteration_damage = 0.
    total_ticks = 0
    with tempfile.TemporaryDirectory() as folder:
        output = Path(folder) / "result.json"
        env = dict(os.environ, FOREVER_GSIM_WORLD_BRIDGE="1",
                   FOREVER_GSIM_WORLD_ITERATIONS=str(iterations))
        proc = subprocess.Popen(
            [str(binary.resolve()), "sim", "--request", str(request.resolve()),
             "--outfile", str(output), "--gate"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, env=env,
        )
        try:
            for line in proc.stdout:
                native = json.loads(line)
                if native.get("type") == "native_rust_world_iteration_done":
                    assert native["iteration_index"] == iteration == len(samples)
                    assert native["native_process_id"] == proc.pid
                    assert native["native_request_sha256"] == request_sha
                    assert native["native_duration_ns"] > 0
                    assert abs(native["native_total_damage"] - iteration_damage) < 1e-4
                    samples.append({
                        "iteration_index": iteration,
                        "duration_s": native["native_duration_ns"] / 1e9,
                        "world_applied_damage": iteration_damage,
                        "world_dps": iteration_damage / (native["native_duration_ns"] / 1e9),
                    })
                    continue
                if native.get("type") != "native_rust_world_boundary_request":
                    raise AssertionError(f"UNEXPECTED_RUST_OUTPUT {native}")
                if native["iteration_index"] != iteration:
                    assert native["iteration_index"] == iteration + 1 == len(samples)
                    assert native["sequence"] == 0
                    iteration = native["iteration_index"]
                    world, feed, applier = new_world()
                    previous_ack_id = ""
                    last_tick = -1
                    iteration_damage = 0.
                clock_ns = native["native_clock_ns"]
                if clock_ns % 1_000_000 or clock_ns <= last_tick:
                    raise AssertionError("RUST_CLOCK_NOT_GSIM_MILLISECOND_MONOTONIC")
                if native["native_request_sha256"] != request_sha:
                    raise AssertionError(f"RUST_SOURCE_HASH_MISMATCH {native['native_request_sha256']} {request_sha}")
                if native["native_process_id"] != proc.pid:
                    raise AssertionError("RUST_NATIVE_PID_MISMATCH")
                world.advance_to(clock_ns / 1e9)
                tick = feed.next_tick()
                assert tick["sequence"] == native["sequence"]
                assert tick["native_clock_ns"] == clock_ns
                tick["previous_world_ack_id"] = previous_ack_id
                tick["iteration_index"] = iteration
                # Only the actual gsim world may schedule independent world
                # updates. If no world event/motion is pending, the next native
                # scheduler action is the earliest causally relevant boundary.
                # Periodic mode is the unchanged 100ms comparison control.
                tick["next_world_boundary_ns"] = (
                    clock_ns + 100_000_000
                    if periodic_world_poll or world.queue or world._enemy_motion
                    else None
                )
                proc.stdin.write(json.dumps(tick, sort_keys=True, allow_nan=False) + "\n")
                proc.stdin.flush()
                receipt = json.loads(proc.stdout.readline())
                assert receipt["type"] == "native_rust_world_receipt"
                assert receipt["iteration_index"] == iteration
                assert receipt["native_request_sha256"] == request_sha
                assert receipt["native_process_id"] == proc.pid
                feed.accept_range_receipt(receipt["native_range_receipt"])
                ack = applier.apply(tick, receipt)
                ack["iteration_index"] = iteration
                event_count += len(ack["applied_event_ids"])
                applied_damage += ack["applied_native_damage"]
                iteration_damage += ack["applied_native_damage"]
                previous_ack_id = ack["world_after_sha256"]
                if forge_ack and event_count:
                    ack["applied_event_ids"] = []
                proc.stdin.write(json.dumps(ack, sort_keys=True, allow_nan=False) + "\n")
                proc.stdin.flush()
                last_tick = clock_ns
                total_ticks += 1
                if forge_ack and event_count:
                    break
            proc.stdin.close()
            stderr = proc.stderr.read()
            status = proc.wait(timeout=20)
            if forge_ack:
                assert event_count > 0 and status != 0 and "RUST_WORLD_DAMAGE_ACK_EVENTS_MISMATCH" in stderr, stderr[-3000:]
                return {"forged_ack_rejected": True, "native_damage_events": event_count}
            assert status == 0, f"RUST_NATIVE_WORLD_EXIT_{status}: {stderr[-4000:]}"
            result = json.loads(output.read_text())
            # The genuine Rust protobuf-JSON report omits avg entirely for a
            # zero-damage fight (80yd out of range); that is 0 DPS, not an error.
            native_dps = result["result"]["raidMetrics"]["dps"].get("avg", 0.0)
            duration = result["result"]["firstIterationDuration"]
            assert result["result"]["iterationsDone"] == iterations
            assert len(samples) == iterations
            assert event_count > 0 or distance > 60
            assert native_dps >= 0 and duration > 0
            world_mean_dps = sum(s["world_dps"] for s in samples) / iterations
            assert abs(native_dps - world_mean_dps) < 1e-5, (
                "NATIVE_WORLD_STOCHASTIC_DPS_MISMATCH", native_dps, world_mean_dps)
            assert abs(sum(s["world_applied_damage"] for s in samples) - applied_damage) < 1e-4
            return {"native_dps": native_dps, "sampled_duration_s": duration,
                    "world_mean_dps": world_mean_dps, "iterations_done": iterations,
                    "world_applied_damage": applied_damage, "native_damage_events": event_count,
                    "native_world_ticks": total_ticks,
                    "world_health_remaining": world.targets["m1"].health,
                    "per_iteration": samples,
                    "source_request_proto_sha256": request_sha,
                    "source_request_raw_sha256": raw_sha,
                    "checkpoint_certified": False}
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--request", type=Path, required=True)
    args = p.parse_args()
    near = run(args.binary, args.request, distance=15.)
    print("REAL_RUST_NEAR_WORLD", json.dumps(near, sort_keys=True), flush=True)
    far = run(args.binary, args.request, distance=80.)
    print("REAL_RUST_FAR_WORLD", json.dumps(far, sort_keys=True), flush=True)
    assert near["native_dps"] > far["native_dps"], (near, far)
    assert near["native_damage_events"] > far["native_damage_events"]
    forged = run(args.binary, args.request, distance=15., forge_ack=True)
    multi = run(args.binary, args.request, distance=15., iterations=3)
    assert multi["iterations_done"] == len(multi["per_iteration"]) == 3
    assert multi["native_world_ticks"] > near["native_world_ticks"]
    assert multi["native_damage_events"] > near["native_damage_events"]
    # RED against the old bridge: ignoring the real gsim next-world deadline
    # forces 100ms polling even for the static, event-free reference encounter.
    periodic = run(args.binary, args.request, distance=15., iterations=3,
                   periodic_world_poll=True)
    assert abs(multi["native_dps"] - periodic["native_dps"]) < 1e-6, (
        "EVENT_DRIVEN_NATIVE_DPS_CHANGED", multi["native_dps"], periodic["native_dps"])
    assert abs(multi["world_applied_damage"] - periodic["world_applied_damage"]) < 1e-4
    assert multi["native_damage_events"] == periodic["native_damage_events"]
    assert multi["native_world_ticks"] < periodic["native_world_ticks"], (
        "STATIC_WORLD_STILL_POLLED_EVERY_100MS",
        multi["native_world_ticks"], periodic["native_world_ticks"])
    print("REAL_RUST_EVENT_BOUNDARY_VS_PERIODIC", json.dumps({
        "event_ticks": multi["native_world_ticks"],
        "periodic_ticks": periodic["native_world_ticks"],
        "event_dps": multi["native_dps"],
        "periodic_dps": periodic["native_dps"],
    }, sort_keys=True), flush=True)
    print("REAL_RUST_THREE_INDEPENDENT_SOURCE_FIGHTS", json.dumps(multi, sort_keys=True), flush=True)
    print(json.dumps({"near": near, "far": far, "forged": forged, "multi": multi,
                      "verdict": "REAL_RUST_GSIM_RANGE_DAMAGE_ACK_CAUSAL_DIAGNOSTIC_NOT_P7"},
                     sort_keys=True))

if __name__ == "__main__":
    main()
