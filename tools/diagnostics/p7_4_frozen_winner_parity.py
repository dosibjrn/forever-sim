#!/usr/bin/env python3
"""No-record replay of the exact P7.4 frozen winner from Actions run 41778065670.

This is a bounded parity diagnostic, not a P7 gate or M1 recorder. It keeps
the saved request's fixed axes and replaces only the 16 item/enchant choices
reported by the terminal cold-search result.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_WINNER_SHA256 = "67069c454ae125cecd958cf8987ba9af467a52f0e04f57ee0e3c44bc3ee48e2b"
EXPECTED_BASE_RAW_SHA256 = "e99b06e5aa891a941ac077643a4209ab8582c810b678df4ec2d47ac48c6c646a"
DIAGNOSTIC_PHASE = "baseline-before-native-iteration-override"
ITERATION_GEAR = [
    (16441, 8692), (281281, 904), (231659, 7882), (277206, 1888),
    (21351, 7648), (272571, 7665), (22501, 8491), (240045, None),
    (240071, 2589), (240050, 7648), (19147, None), (234028, None),
    (272438, None), (19379, None), (19884, 7662), (208414, 33),
]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def frozen_winner_request(base_path):
    base_raw_sha = hashlib.sha256(base_path.read_bytes()).hexdigest()
    if base_raw_sha != EXPECTED_BASE_RAW_SHA256:
        raise AssertionError(f"FROZEN_P74_BASE_REQUEST_MISMATCH:{base_raw_sha}")
    base = json.loads(base_path.read_text())
    candidate = copy.deepcopy(base)
    items = candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"]
    if len(items) != len(ITERATION_GEAR):
        raise AssertionError(f"FROZEN_P74_GEAR_SLOT_COUNT:{len(items)}")
    # The P7.4 report numbers slots by equipment.items array position.
    for item, (item_id, enchant_id) in zip(items, ITERATION_GEAR):
        item["id"] = item_id
        item.pop("enchant", None)
        if enchant_id is not None:
            item["enchant"] = enchant_id
    preflight = load_module(
        "p74_frozen_preflight",
        ROOT / "integrations/mythicsim-rust/p74_preflight.py",
    )
    preflight.preflight(base, candidate)
    digest = hashlib.sha256(json.dumps(candidate, sort_keys=True).encode()).hexdigest()
    if digest != EXPECTED_WINNER_SHA256:
        raise AssertionError(
            f"FROZEN_P74_WINNER_RECONSTRUCTION_MISMATCH:{digest}")
    return candidate, preflight


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--base-request", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--assert-parity", action="store_true")
    args = parser.parse_args()
    if args.iterations < 1 or args.iterations > 1000:
        parser.error("--iterations must be in 1..1000")

    probe = load_module(
        "p74_frozen_live_probe",
        ROOT / "integrations/mythicsim-rust/live_world_probe.py",
    )
    candidate, preflight = frozen_winner_request(args.base_request)
    with tempfile.TemporaryDirectory(prefix="p74-frozen-parity-") as folder:
        request = Path(folder) / "frozen-winner.json"
        request.write_text(json.dumps(candidate))
        raw_sha = hashlib.sha256(request.read_bytes()).hexdigest()
        native = probe.native_source_control(
            args.binary, request, args.iterations, rng_mode="stochastic")
        live = probe.run(
            args.binary, request,
            distance=preflight.player(candidate)["distanceFromTarget"],
            iterations=args.iterations, rng_mode="stochastic",
        )
        first_world_duration = live["per_iteration"][0]["duration_s"]
        report = {
            "gate": "P7.4",
            "diagnostic_phase": DIAGNOSTIC_PHASE,
            "mode": "stochastic",
            "iterations": args.iterations,
            "cold_winner_request_sha256": EXPECTED_WINNER_SHA256,
            "base_request_raw_sha256": EXPECTED_BASE_RAW_SHA256,
            "frozen_request_raw_sha256": raw_sha,
            "native": native,
            "live_native_dps": live["native_dps"],
            "live_world_mean_dps": live["world_mean_dps"],
            "live_sampled_duration_s": live["sampled_duration_s"],
            "live_first_iteration_duration_s": first_world_duration,
            "live_source_request_proto_sha256": live["source_request_proto_sha256"],
            "live_source_request_raw_sha256": live["source_request_raw_sha256"],
            "deltas": {
                "native_vs_live_dps": native["native_dps"] - live["native_dps"],
                "native_vs_world_mean_dps": native["native_dps"] - live["world_mean_dps"],
                "native_vs_live_first_duration_s": native["first_duration_s"] - live["sampled_duration_s"],
                "native_vs_first_world_iteration_duration_s": native["first_duration_s"] - first_world_duration,
                "native_vs_live_request_proto_sha256_equal": (
                    native["source_request_proto_sha256"] == live["source_request_proto_sha256"]),
                "native_vs_live_request_raw_sha256_equal": (
                    native["source_request_raw_sha256"] == live["source_request_raw_sha256"]),
            },
        }
        print(json.dumps(report, sort_keys=True, indent=2), flush=True)
        assert native["iterations"] == args.iterations
        assert live["iterations_done"] == args.iterations
        if args.assert_parity:
            assert native["source_request_proto_sha256"] == live["source_request_proto_sha256"], report
            assert native["source_request_raw_sha256"] == live["source_request_raw_sha256"], report
            assert abs(native["native_dps"] - live["native_dps"]) < 1e-6, report
            assert abs(native["native_dps"] - live["world_mean_dps"]) < 1e-5, report
            assert abs(native["first_duration_s"] - live["sampled_duration_s"]) < 1e-9, report
            assert abs(native["first_duration_s"] - first_world_duration) < 1e-9, report


if __name__ == "__main__":
    main()
