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
import math
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
        iterations: int = 1, periodic_world_poll: bool = False,
        facing_switch_at_s: float | None = None) -> dict:
    raw = request.read_bytes()
    source = json.loads(raw)
    players = [p for party in source["raid"]["parties"] for p in party["players"]]
    assert len(players) == 1 and len(source["encounter"]["targets"]) == 1
    assert source["encounter"]["targets"][0]["level"] == 63
    if not 1 <= iterations <= source["simOptions"]["iterations"]:
        raise ValueError("RUST_WORLD_ITERATIONS_OUT_OF_SOURCE_RANGE")
    if facing_switch_at_s is not None and (
            not math.isfinite(facing_switch_at_s) or facing_switch_at_s <= 0 or iterations != 1):
        raise ValueError("RUST_WORLD_FACING_SWITCH_INVALID")
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
    pet_damage_events = 0
    precombat_damage_events = 0
    applied_damage = 0.
    applied_damage_compensation = 0.
    last_tick = -1
    iteration = -1
    samples = []
    iteration_damage = 0.
    total_ticks = 0
    facing_switch_clock_ns = None
    source_action_events_before = {}
    source_action_events_after = {}
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
                    assert abs(native["native_total_damage"] - iteration_damage) < 1e-4, ("NATIVE_WORLD_DAMAGE_EVENTS_UNACCOUNTED", native["native_total_damage"], iteration_damage, event_count, pet_damage_events)
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
                if (facing_switch_at_s is not None and facing_switch_clock_ns is None
                        and clock_ns >= round(facing_switch_at_s * 1e9)):
                    # The real 2D world, not a patched source request, turns
                    # its stationary target before the next native decision.
                    # Target starts at +distance, hero at origin: heading -X
                    # puts the hero in front, whereas +X means behind.
                    world.targets["m1"].metadata["facing_xy_yards"] = (-1., 0.)
                    facing_switch_clock_ns = clock_ns
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
                action_counter = (source_action_events_after
                    if facing_switch_clock_ns is not None
                    else source_action_events_before)
                for event in receipt["native_damage_events"]:
                    if event["native_caster_type"] == "pet":
                        pet_damage_events += 1
                    if event["native_time_ns"] < 0:
                        precombat_damage_events += 1
                    action = event["source_action_id"]
                    action_counter[action] = action_counter.get(action, 0) + 1
                ack["iteration_index"] = iteration
                event_count += len(ack["applied_event_ids"])
                # Millions of positive source-native events must not lose
                # bookkeeping precision through naive global float addition.
                # Compensated accumulation is independent of per-fight totals.
                delta = ack["applied_native_damage"]
                adjusted = delta - applied_damage_compensation
                updated = applied_damage + adjusted
                applied_damage_compensation = (updated - applied_damage) - adjusted
                applied_damage = updated
                iteration_damage += delta
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
            assert math.isclose(
                math.fsum(s["world_applied_damage"] for s in samples),
                applied_damage, rel_tol=1e-12, abs_tol=1e-4,
            ), ("LIVE_WORLD_DAMAGE_ACCOUNTING_DIVERGENCE",
                math.fsum(s["world_applied_damage"] for s in samples), applied_damage)
            return {"native_dps": native_dps, "sampled_duration_s": duration,
                    "world_mean_dps": world_mean_dps, "iterations_done": iterations,
                    "world_applied_damage": applied_damage, "native_damage_events": event_count,
                    "native_pet_damage_events": pet_damage_events,
                    "native_precombat_damage_events": precombat_damage_events,
                    "native_world_ticks": total_ticks,
                    "world_health_remaining": world.targets["m1"].health,
                    "per_iteration": samples,
                    "source_request_proto_sha256": request_sha,
                    "source_request_raw_sha256": raw_sha,
                    "facing_switch_clock_ns": facing_switch_clock_ns,
                    "source_action_events_before": source_action_events_before,
                    "source_action_events_after": source_action_events_after,
                    "checkpoint_certified": False}
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)

def native_source_control(binary: Path, request: Path, iterations: int) -> dict:
    """Independent real Rust source engine with only iteration count reduced.

    Keeps saved gear, talents, rotation, encounter and RNG seed unchanged.
    The world path receives the ORIGINAL request and same first N fights.
    """
    source = json.loads(request.read_text())
    assert 1 <= iterations <= source["simOptions"]["iterations"]
    source["simOptions"]["iterations"] = iterations
    with tempfile.TemporaryDirectory() as folder:
        reduced = Path(folder) / "native_source_control.json"
        output = Path(folder) / "native_result.json"
        reduced.write_text(json.dumps(source, sort_keys=True))
        completed = subprocess.run(
            [str(binary.resolve()), "sim", "--request", str(reduced),
             "--outfile", str(output), "--gate"],
            capture_output=True, text=True, timeout=120,
            env={k: v for k, v in os.environ.items()
                 if k not in ("FOREVER_GSIM_WORLD_BRIDGE", "FOREVER_GSIM_WORLD_ITERATIONS")},
        )
        assert completed.returncode == 0, (
            "NATIVE_SOURCE_CONTROL_FAILED", completed.stderr[-2000:])
        result = json.loads(output.read_text())
        assert result["identity"]["engine"] == "forever-engine"
        measured = result["result"]
        assert measured["iterationsDone"] == iterations
        return {"native_dps": measured["raidMetrics"]["dps"].get("avg", 0.),
                "first_duration_s": measured["firstIterationDuration"],
                "iterations": iterations}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--request", type=Path, required=True)
    p.add_argument("--reference-iterations", type=int, default=0,
                   help="on-demand native-vs-live stochastic reference run; 0=quick causal regression")
    args = p.parse_args()
    if args.reference_iterations:
        source = json.loads(args.request.read_text())
        player = source["raid"]["parties"][0]["players"][0]
        assert player["class"] == "ClassDruid" and "balanceDruid" in player
        assert len(source["encounter"]["targets"]) == 1
        assert source["encounter"]["targets"][0]["level"] == 63
        assert args.reference_iterations <= source["simOptions"]["iterations"]
        baseline = native_source_control(args.binary, args.request, args.reference_iterations)
        coupled = run(args.binary, args.request,
                      distance=player["distanceFromTarget"],
                      iterations=args.reference_iterations)
        assert coupled["iterations_done"] == baseline["iterations"]
        assert abs(coupled["native_dps"] - baseline["native_dps"]) < 1e-6, (
            "LIVE_RUST_SOURCE_DPS_DIVERGENCE", coupled["native_dps"], baseline["native_dps"])
        assert abs(coupled["sampled_duration_s"] - baseline["first_duration_s"]) < 1e-9
        # This is the original saved MythicSim reference, not an optimizer
        # candidate; source-native-vs-live parity alone is not a gate PASS.
        if args.reference_iterations == source["simOptions"]["iterations"]:
            witness = json.loads((ROOT / "docs/evidence/wf633/WF633_VALIDATION.json").read_text())
            assert coupled["native_dps"] >= witness["reference_dps"], (
                "LIVE_RUST_BELOW_SAVED_REFERENCE", coupled["native_dps"], witness["reference_dps"])
        print("REAL_RUST_LIVE_SOURCE_STOCHASTIC", json.dumps({
            "iterations": coupled["iterations_done"],
            "native_dps": baseline["native_dps"],
            "live_native_dps": coupled["native_dps"],
            "world_dps": coupled["world_mean_dps"],
            "world_ticks": coupled["native_world_ticks"],
            "source_sha256": coupled["source_request_raw_sha256"],
            "world_damage_events": coupled["native_damage_events"],
            "saved_reference_threshold_checked":
                args.reference_iterations == source["simOptions"]["iterations"],
            "checkpoint_certified": False,
        }, sort_keys=True), flush=True)
        return
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
    control = native_source_control(args.binary, args.request, 3)
    print("REAL_RUST_THREE_FIGHT_NATIVE_SOURCE_CONTROL", json.dumps(control, sort_keys=True), flush=True)
    assert abs(multi["native_dps"] - control["native_dps"]) < 1e-6, (
        "STATIC_WORLD_CHANGED_SOURCE_NATIVE_DPS", multi["native_dps"], control["native_dps"])
    assert abs(multi["sampled_duration_s"] - control["first_duration_s"]) < 1e-9, (
        "STATIC_WORLD_CHANGED_SOURCE_DURATION", multi["sampled_duration_s"], control["first_duration_s"])
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
