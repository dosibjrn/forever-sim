#!/usr/bin/env python3
"""Exercise landed/missed Entangling Roots through selected Rust and gsim 2D.

The native Rust dot callback is the only source of the control event. The
recording adapter observes the actual event and the real CombatRuntime target
position before/while rooted/after expiry; no synthetic control is injected.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import tempfile

import live_world_probe


_APPLIERS = []


class _RecordingApplier(live_world_probe.GsimNativeDamageWorldApplier):
    def __init__(self, runtime):
        super().__init__(runtime)
        self.control_events = []
        self.samples = []
        _APPLIERS.append(self)

    def apply(self, tick, response):
        self.control_events.extend(response.get("native_control_events", []))
        ack = super().apply(tick, response)
        target_id = tick["selected_target_id"]
        x, y = self._runtime._enemy_position_at(target_id)
        self.samples.append({
            "clock_ns": tick["native_clock_ns"],
            "distance_yards": math.hypot(x, y),
            "root_expiry_s": self._runtime.targets[target_id].active_controls.get("root"),
        })
        return ack


live_world_probe.GsimNativeDamageWorldApplier = _RecordingApplier


def _request_with_roots(source_path: Path, seed: int, duration_s: float) -> dict:
    source = json.loads(source_path.read_text())
    players = [player for party in source["raid"]["parties"] for player in party["players"]]
    if len(players) != 1:
        raise ValueError("ROOTS_PROBE_EXPECTS_ONE_PLAYER")
    player = players[0]
    player["rotation"]["prepullActions"] = []
    player["rotation"]["priorityList"] = [{
        "action": {
            "castSpell": {"spellId": {"rank": 6, "spellId": 9853}},
            "condition": {
                "not": {
                    "val": {
                        "dotIsActive": {"spellId": {"rank": 6, "spellId": 9853}}
                    }
                }
            },
        }
    }]
    source["simOptions"]["iterations"] = 1
    source["simOptions"]["randomSeed"] = seed
    source["encounter"]["duration"] = duration_s
    source["encounter"]["durationVariation"] = 0
    return source


def _run(binary: Path, source_path: Path, seed: int, duration_s: float):
    request = _request_with_roots(source_path, seed, duration_s)
    with tempfile.TemporaryDirectory() as folder:
        request_path = Path(folder) / "roots-request.json"
        request_path.write_text(json.dumps(request, sort_keys=True))
        _APPLIERS.clear()
        result = live_world_probe.run(
            binary, request_path, distance=20.0, iterations=1,
            rng_mode="balanced", enemy_move_speed_yards_s=5.0,
        )
    if len(_APPLIERS) != 1:
        raise AssertionError(f"ROOTS_PROBE_EXPECTED_ONE_APPLIER_GOT_{len(_APPLIERS)}")
    return result, _APPLIERS[0]


def _assert_miss(applier, seed: int) -> dict:
    if applier.control_events:
        raise AssertionError(f"ROOTS_MISS_SEED_LANDED:{seed}")
    if len(applier.samples) < 2:
        raise AssertionError("ROOTS_MISS_PROBE_MISSING_WORLD_SAMPLES")
    start = applier.samples[0]["distance_yards"]
    end = applier.samples[-1]["distance_yards"]
    if end >= start - 5.0:
        raise AssertionError(f"ROOTS_MISS_DID_NOT_KEEP_MOVING:{start}:{end}")
    return {"seed": seed, "start_yards": start, "end_yards": end}


def _assert_land_and_expiry(applier, seed: int) -> dict:
    if len(applier.control_events) != 1:
        raise AssertionError(f"ROOTS_LAND_EXPECTED_ONE_CONTROL_EVENT:{seed}:{len(applier.control_events)}")
    event = applier.control_events[0]
    if (event.get("control_id") != "root" or event.get("landed") is not True
            or event.get("duration_ns") != 27_000_000_000
            or "9853" not in event.get("source_action_id", "")):
        raise AssertionError(f"ROOTS_NATIVE_EVENT_CONTRACT_INVALID:{event}")
    active = [sample for sample in applier.samples if sample["root_expiry_s"] is not None]
    if not active:
        raise AssertionError("ROOTS_CONTROL_NEVER_ACTIVE_IN_GSIM")
    expiry_s = active[0]["root_expiry_s"]
    first_active_ns = active[0]["clock_ns"]
    frozen = [
        sample["distance_yards"] for sample in applier.samples
        if first_active_ns <= sample["clock_ns"] < int(expiry_s * 1_000_000_000)
    ]
    after = [
        sample for sample in applier.samples
        if sample["clock_ns"] > int(expiry_s * 1_000_000_000)
    ]
    if not frozen or max(frozen) - min(frozen) > 0.05:
        raise AssertionError(f"ROOTS_DID_NOT_FREEZE_2D_TARGET:{frozen}")
    if not after or after[-1]["distance_yards"] >= frozen[-1] - 1.0:
        raise AssertionError(f"ROOTS_DID_NOT_RELEASE_TARGET_AFTER_EXPIRY:{after[-3:]}")
    return {
        "seed": seed,
        "native_time_ns": event["native_time_ns"],
        "duration_ns": event["duration_ns"],
        "expiry_s": expiry_s,
        "frozen_distance_yards": frozen[-1],
        "after_expiry_distance_yards": after[-1]["distance_yards"],
        "control_event_id": event["event_id"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()

    hit_seed = None
    miss_result = None
    # Fixed, deterministic balanced-mode seeds. Search only short 2s casts;
    # the single long run is reserved for the landed root's actual expiry.
    seeds = [1179706472, *range(1, 33)]
    for seed in seeds:
        _, applier = _run(args.binary, args.request, seed, 2.0)
        if applier.control_events and hit_seed is None:
            hit_seed = seed
        if not applier.control_events and miss_result is None:
            miss_result = _assert_miss(applier, seed)
        if hit_seed is not None and miss_result is not None:
            break
    if hit_seed is None or miss_result is None:
        raise AssertionError("ROOTS_PROBE_COULD_NOT_FIND_BOTH_LAND_AND_MISS")

    _, landed = _run(args.binary, args.request, hit_seed, 29.0)
    land_result = _assert_land_and_expiry(landed, hit_seed)
    print(json.dumps({
        "status": "PASS",
        "rng_mode": "balanced",
        "miss": miss_result,
        "land_and_expiry": land_result,
        "iterations": 1,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
