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


def request_for(base: dict) -> dict:
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
    request["simOptions"]["iterations"] = 32
    request["simOptions"]["randomSeed"] = "42"
    request["encounter"]["duration"] = 29.1
    request["encounter"]["durationVariation"] = 0.0
    return request


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

    with tempfile.TemporaryDirectory() as tmp:
        request_path = Path(tmp) / "roots-control.json"
        request_path.write_text(json.dumps(request_for(base)))
        result = run(
            binary, request_path, distance=15.0, iterations=32,
            enemy_move_speed_yards_s=5.0,
            # Fixed-seed non-search mechanics diagnostic only.
            rng_mode="stochastic",
        )

    missed = []
    landed = []
    for sample in result["per_iteration"]:
        events = sample["native_control_events"]
        attempts = [e for e in events if e["event_kind"] == "attempt"]
        if not attempts:
            raise AssertionError(("ROOTS_FIRST_CAST_ATTEMPT_MISSING", sample))
        first = attempts[0]
        if first["landed"] is False:
            if any(e["event_kind"] == "apply"
                   and e["native_time_ns"] == first["native_time_ns"]
                   for e in events):
                raise AssertionError(("ROOTS_MISS_CREATED_CONTROL", sample))
            missed.append(sample)
        elif first["landed"] is True:
            applies = [e for e in events if e["event_kind"] == "apply"]
            expires = [e for e in events if e["event_kind"] == "expire"]
            if len(applies) == 1 and len(expires) == 1:
                landed.append((sample, applies[0], expires[0]))

    if not missed or not landed:
        raise AssertionError(("ROOTS_MISS_AND_LAND_NOT_BOTH_OBSERVED", len(missed), len(landed)))

    sample, applied, expired = landed[0]
    if expired["native_time_ns"] != applied["expires_at_ns"]:
        raise AssertionError(("ROOTS_NATIVE_EXPIRY_TIME_MISMATCH", applied, expired))
    gain_x = applied["world_position_yards"][0]
    expiry_x = expired["world_position_yards"][0]
    final_x = sample["world_target_position_yards"][0]
    if not 5.0 < gain_x < 15.0:
        raise AssertionError(("ROOTS_GAIN_POSITION_INVALID", gain_x))
    if abs(gain_x - expiry_x) > 1e-6:
        raise AssertionError(("ROOTS_TARGET_MOVED_WHILE_ROOTED", gain_x, expiry_x))
    if final_x > 5.0 + 1e-6 or "root" in sample["world_target_controls"]:
        raise AssertionError(("ROOTS_TARGET_DID_NOT_RESUME_AFTER_EXPIRY", final_x,
                              sample["world_target_controls"]))

    print("RUST_ROOTS_MISS_LAND_EXPIRE_GSIM_2D_CONTROL_PASS_NOT_GATE")
    print(json.dumps({
        "iterations": len(result["per_iteration"]),
        "missed_first_casts": len(missed),
        "landed_first_casts": len(landed),
        "root_gain_position_yards": gain_x,
        "root_expiry_position_yards": expiry_x,
        "post_expiry_position_yards": final_x,
        "root_expiry_ns": applied["expires_at_ns"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
