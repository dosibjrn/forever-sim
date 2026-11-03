#!/usr/bin/env python3
"""Selected-Rust Roots miss/land/expiry through the real gsim 2D world ACK.

This is a focused mechanics diagnostic, not a P1/P2 gate or checkpoint PASS.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import tempfile

from live_world_probe import run


def request_for(base: dict, seed: int, duration_s: float) -> dict:
    request = copy.deepcopy(base)
    player = request["raid"]["parties"][0]["players"][0]
    player["talentsString"] = "0000000"
    player["rotation"]["priorityList"] = [
        {
            "action": {
                "castSpell": {"spellId": {"spellId": 9853}},
                "condition": {"not": {"val": {
                    "dotIsActive": {"spellId": {"spellId": 9853}}
                }}},
            }
        },
        {"action": {"castSpell": {"spellId": {"spellId": 9912}}}},
    ]
    request["simOptions"]["iterations"] = 1
    request["simOptions"]["randomSeed"] = str(seed)
    request["encounter"]["duration"] = float(duration_s)
    request["encounter"]["durationVariation"] = 0.0
    return request


def run_one(binary: Path, base: dict, folder: Path, seed: int, duration_s: float) -> dict:
    request_path = folder / f"roots-{seed}-{duration_s:.1f}.json"
    request_path.write_text(json.dumps(request_for(base, seed, duration_s)))
    return run(
        binary, request_path, distance=15.0, iterations=1,
        enemy_move_speed_yards_s=5.0,
        # Fixed-seed non-search mechanics diagnostic only.
        rng_mode="stochastic",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    binary = args.binary.resolve()
    base = json.loads(args.request.read_text())
    if (len(base["raid"]["parties"]) != 1
            or len(base["raid"]["parties"][0]["players"]) != 1
            or len(base["encounter"]["targets"]) != 1
            or base["encounter"]["targets"][0]["level"] != 63):
        raise ValueError("ROOTS_CONTROL_FIXTURE_SHAPE_INVALID")

    miss = None
    land_seed = None
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        # A short first-cast window gives a clean miss/land sample before a
        # missed Roots cast can be retried by the APL.
        for seed in range(1, 65):
            result = run_one(binary, base, folder, seed, 1.6)
            sample = result["per_iteration"][0]
            attempts = [e for e in sample["native_control_events"]
                        if e["event_kind"] == "attempt"]
            if len(attempts) != 1:
                raise AssertionError(("ROOTS_FIRST_CAST_ATTEMPT_COUNT", seed, attempts))
            if attempts[0]["landed"] and land_seed is None:
                land_seed = seed
            if not attempts[0]["landed"] and miss is None:
                miss = (seed, sample)
            if land_seed is not None and miss is not None:
                break

        if miss is None or land_seed is None:
            raise AssertionError(("ROOTS_MISS_AND_LAND_SEEDS_NOT_FOUND", land_seed, miss))

        miss_seed, miss_sample = miss
        miss_events = miss_sample["native_control_events"]
        miss_attempt = next(e for e in miss_events if e["event_kind"] == "attempt")
        if miss_attempt["landed"] is not False:
            raise AssertionError("ROOTS_MISS_NEGATIVE_CONTROL_INVALID")
        if any(e["event_kind"] == "apply"
               and e["native_time_ns"] == miss_attempt["native_time_ns"]
               for e in miss_events):
            raise AssertionError("ROOTS_MISS_CREATED_CONTROL")
        miss_x = miss_sample["world_target_position_yards"][0]
        if not 5.0 < miss_x < 15.0:
            raise AssertionError(("ROOTS_MISS_WORLD_DID_NOT_KEEP_MOVING", miss_x))

        landed_result = run_one(binary, base, folder, land_seed, 29.1)
        landed = landed_result["per_iteration"][0]
        events = landed["native_control_events"]
        attempts = [e for e in events if e["event_kind"] == "attempt"]
        applies = [e for e in events if e["event_kind"] == "apply"]
        expires = [e for e in events if e["event_kind"] == "expire"]
        if not attempts or attempts[0]["landed"] is not True:
            raise AssertionError(("ROOTS_LAND_NOT_REPRODUCED", land_seed, attempts))
        if len(applies) != 1 or len(expires) != 1:
            raise AssertionError(("ROOTS_GAIN_EXPIRE_EVENT_COUNTS", applies, expires))
        applied, expired = applies[0], expires[0]
        if expired["native_time_ns"] != applied["expires_at_ns"]:
            raise AssertionError(("ROOTS_NATIVE_EXPIRY_TIME_MISMATCH", applied, expired))
        gain_x = applied["world_position_yards"][0]
        expiry_x = expired["world_position_yards"][0]
        final_x = landed["world_target_position_yards"][0]
        if not 5.0 < gain_x < 15.0:
            raise AssertionError(("ROOTS_GAIN_POSITION_INVALID", gain_x))
        if abs(gain_x - expiry_x) > 1e-6:
            raise AssertionError(("ROOTS_TARGET_MOVED_WHILE_ROOTED", gain_x, expiry_x))
        if final_x > 5.0 + 1e-6 or "root" in landed["world_target_controls"]:
            raise AssertionError(("ROOTS_TARGET_DID_NOT_RESUME_AFTER_EXPIRY", final_x,
                                  landed["world_target_controls"]))

    print("RUST_ROOTS_MISS_LAND_EXPIRE_GSIM_2D_CONTROL_PASS_NOT_GATE")
    print(json.dumps({
        "miss_seed": miss_seed,
        "land_seed": land_seed,
        "miss_position_yards": miss_x,
        "root_gain_position_yards": gain_x,
        "root_expiry_position_yards": expiry_x,
        "post_expiry_position_yards": final_x,
        "root_expiry_ns": applied["expires_at_ns"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
