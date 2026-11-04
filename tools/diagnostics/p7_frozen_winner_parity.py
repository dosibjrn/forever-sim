#!/usr/bin/env python3
"""No-record reproduction of the exact frozen P7.4 winner from Actions #41778065670.

The script compares the current native-source control and live-world execution
on the same first N stochastic fights. It also isolates request iteration-count
normalization and the finite source target-health boundary. It never runs a
cold search, changes the saved source fixture, records M1, or claims a gate.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.wf_gate_p7_1_live import _source_native_world_parity
from tools.wf_gsim_go_live_range_probe import source_target_health_from_request

SOURCE_REQUEST = ROOT / "docs/evidence/druid-l60-balance/p7.3/saved_728_request.json"
SOURCE_RAW_SHA256 = "e99b06e5aa891a941ac077643a4209ab8582c810b678df4ec2d47ac48c6c646a"
COLD_WINNER_SORTED_SHA256 = "67069c454ae125cecd958cf8987ba9af467a52f0e04f57ee0e3c44bc3ee48e2b"

# Exact full loadout printed by the terminal production receipt #41778065670.
COLD_WINNER_GEAR = [
    (16441, 8692), (281281, 904), (231659, 7882), (277206, 1888),
    (21351, 7648), (272571, 7665), (22501, 8491), (240045, None),
    (240071, 2589), (240050, 7648), (19147, None), (234028, None),
    (272438, None), (19379, None), (19884, 7662), (208414, 33),
]


def load_probe():
    path = ROOT / "integrations/mythicsim-rust/live_world_probe.py"
    spec = importlib.util.spec_from_file_location("p74_frozen_winner_probe", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("P74_PROBE_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def frozen_winner_request() -> dict:
    raw = SOURCE_REQUEST.read_bytes()
    source_sha = hashlib.sha256(raw).hexdigest()
    if source_sha != SOURCE_RAW_SHA256:
        raise RuntimeError(f"P74_SOURCE_REQUEST_CHANGED:{source_sha}")
    request = json.loads(raw)
    items = request["raid"]["parties"][0]["players"][0]["equipment"]["items"]
    if len(items) != len(COLD_WINNER_GEAR):
        raise RuntimeError(f"P74_FROZEN_WINNER_SLOT_COUNT:{len(items)}")
    for item, (item_id, enchant_id) in zip(items, COLD_WINNER_GEAR):
        item["id"] = item_id
        item.pop("enchant", None)
        if enchant_id is not None:
            item["enchant"] = enchant_id
    actual = hashlib.sha256(
        json.dumps(request, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if actual != COLD_WINNER_SORTED_SHA256:
        raise RuntimeError(
            f"P74_FROZEN_WINNER_RECONSTRUCTION_MISMATCH:{actual}"
        )
    return request


def run_pair(probe, binary: Path, request: dict, *, iterations: int,
             label: str) -> dict:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="p74-frozen-winner-") as folder:
        path = Path(folder) / "frozen-winner.json"
        path.write_text(json.dumps(request), encoding="utf-8")
        raw_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        distance = float(
            request["raid"]["parties"][0]["players"][0]["distanceFromTarget"]
        )
        native = probe.native_source_control(
            binary, path, iterations, rng_mode="stochastic"
        )
        world = probe.run(
            binary, path, distance=distance, iterations=iterations,
            rng_mode="stochastic",
        )
        mismatch = _source_native_world_parity(
            native, world, iterations, expected_raw_sha=raw_sha
        )
        lethal_aware_mismatch = _source_native_world_parity(
            native, world, iterations, expected_raw_sha=raw_sha,
            allow_world_lethal=True,
        )
        samples = world.get("per_iteration", [])
        return {
            "label": label,
            "request_iterations": request["simOptions"]["iterations"],
            "requested_iterations": iterations,
            "request_raw_sha256": raw_sha,
            "execution_request_raw_sha256": hashlib.sha256(
                json.dumps(
                    {**request, "simOptions": {
                        **request["simOptions"], "iterations": iterations
                    }},
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest(),
            "source_target_health": source_target_health_from_request(
                path.read_bytes()
            ),
            "native_control": native,
            "world": {
                key: world[key] for key in (
                    "native_dps", "world_mean_dps", "sampled_duration_s",
                    "world_health_remaining", "iterations_done",
                    "native_damage_events", "native_world_ticks",
                    "native_precombat_damage_events", "source_request_proto_sha256",
                )
            },
            "world_duration_min_s": min(
                (row["duration_s"] for row in samples), default=None
            ),
            "world_duration_max_s": max(
                (row["duration_s"] for row in samples), default=None
            ),
            "world_dps_min": min(
                (row["world_dps"] for row in samples), default=None
            ),
            "world_dps_max": max(
                (row["world_dps"] for row in samples), default=None
            ),
            "parity_failure": mismatch,
            "parity_failure_allowing_world_lethal": lethal_aware_mismatch,
            "world_target_lethal_fights": world.get("world_target_lethal_fights", 0),
            "world_target_survived_fights": world.get("world_target_survived_fights", 0),
            "world_target_health_remaining_by_fight": [
                row.get("world_target_health_remaining") for row in samples
            ],
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=25)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if type(args.iterations) is not int or not 1 <= args.iterations <= 100:
        parser.error("--iterations must be between 1 and 100")

    binary = args.binary.resolve()
    if not binary.is_file():
        parser.error(f"selected Rust engine binary is missing: {binary}")
    probe = load_probe()
    winner = frozen_winner_request()
    saved_health = source_target_health_from_request(
        SOURCE_REQUEST.read_bytes()
    )

    original_iterations = copy.deepcopy(winner)
    normalized_iterations = copy.deepcopy(winner)
    normalized_iterations["simOptions"]["iterations"] = args.iterations
    high_health = copy.deepcopy(winner)
    high_health["encounter"]["targets"][0]["stats"][32] = 10_000_000

    results = [
        run_pair(
            probe, binary, original_iterations, iterations=args.iterations,
            label="saved_target_original_request_iterations",
        ),
        run_pair(
            probe, binary, normalized_iterations, iterations=args.iterations,
            label="saved_target_normalized_request_iterations",
        ),
        run_pair(
            probe, binary, high_health, iterations=args.iterations,
            label="diagnostic_high_target_health_original_iterations",
        ),
    ]
    report = {
        "diagnostic": "P7_4_FROZEN_WINNER_NATIVE_WORLD_PARITY",
        "checkpoint_certified": False,
        "m1_recorded": False,
        "gate_verdict": None,
        "source_request_raw_sha256": SOURCE_RAW_SHA256,
        "cold_winner_request_sorted_sha256": COLD_WINNER_SORTED_SHA256,
        "iterations_per_pair": args.iterations,
        "saved_target_health": saved_health,
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print("P7_4_FROZEN_WINNER_PARITY_DIAGNOSTIC", json.dumps(
        report, sort_keys=True, allow_nan=False
    ), flush=True)


if __name__ == "__main__":
    main()
