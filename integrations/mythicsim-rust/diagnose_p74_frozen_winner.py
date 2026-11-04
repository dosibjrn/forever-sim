#!/usr/bin/env python3
"""Replay the exact failed P7.4 frozen gear winner for a cheap parity diagnostic.

This is a 25-fight no-record diagnostic, never a P7.4 gate or M1 receipt.
The winner is reconstructed from the trusted #41778065670 production report
and its canonical sorted-request hash is checked before either engine runs.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

EXPECTED_SORTED_WINNER_SHA256 = (
    "67069c454ae125cecd958cf8987ba9af467a52f0e04f57ee0e3c44bc3ee48e2b"
)
WINNER_GEAR = (
    (0, 16441, 8692),
    (1, 281281, 904),
    (2, 231659, 7882),
    (3, 277206, 1888),
    (4, 21351, 7648),
    (5, 272571, 7665),
    (6, 22501, 8491),
    (7, 240045, None),
    (8, 240071, 2589),
    (9, 240050, 7648),
    (10, 19147, None),
    (11, 234028, None),
    (12, 272438, None),
    (13, 19379, None),
    (14, 19884, 7662),
    (15, 208414, 33),
)
ITERATIONS = 25


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--binary", type=Path,
        default=ROOT / "integrations/mythicsim-rust/engine/target/debug/forever-engine",
    )
    args = parser.parse_args()
    if not args.binary.is_file():
        raise FileNotFoundError(f"SELECTED_RUST_BINARY_MISSING:{args.binary}")

    saved_request = ROOT / "docs/evidence/druid-l60-balance/p7.3/saved_728_request.json"
    candidate = json.loads(saved_request.read_text())
    items = candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"]
    if len(items) != len(WINNER_GEAR):
        raise AssertionError(
            f"P74_WINNER_GEAR_SLOT_COUNT:{len(items)}!={len(WINNER_GEAR)}"
        )
    for index, (item, (slot, item_id, enchant_id)) in enumerate(zip(items, WINNER_GEAR)):
        if slot != index:
            raise AssertionError("P74_WINNER_GEAR_SLOT_ORDER_DIVERGED")
        item["id"] = item_id
        item.pop("enchant", None)
        if enchant_id is not None:
            item["enchant"] = enchant_id

    sorted_sha = hashlib.sha256(
        json.dumps(candidate, sort_keys=True).encode()
    ).hexdigest()
    if sorted_sha != EXPECTED_SORTED_WINNER_SHA256:
        raise AssertionError(
            "P74_FROZEN_WINNER_RECONSTRUCTION_MISMATCH:"
            f"expected={EXPECTED_SORTED_WINNER_SHA256},actual={sorted_sha}"
        )

    probe = _load_module(
        ROOT / "integrations/mythicsim-rust/live_world_probe.py",
        "work1_p74_frozen_winner_probe",
    )
    gate = _load_module(
        ROOT / "tools/wf_gate_p7_1_live.py",
        "work1_p74_frozen_winner_gate_assertions",
    )
    player = candidate["raid"]["parties"][0]["players"][0]
    with tempfile.TemporaryDirectory(prefix="work1-p74-winner-") as folder:
        frozen_path = Path(folder) / "frozen-winner.json"
        frozen_path.write_text(json.dumps(candidate))
        raw_sha = hashlib.sha256(frozen_path.read_bytes()).hexdigest()
        native = probe.native_source_control(
            args.binary, frozen_path, ITERATIONS, rng_mode="stochastic"
        )
        live = probe.run(
            args.binary, frozen_path,
            distance=player["distanceFromTarget"],
            iterations=ITERATIONS, rng_mode="stochastic",
        )
        strict_mismatch = gate._source_native_world_parity(
            native, live, ITERATIONS, expected_raw_sha=raw_sha
        )
        # The P7.4 production comparison may ignore a standalone native-only
        # aggregate only when a real gsim lethal ACK ended at least one fight.
        # Coupled native↔world DPS and every per-fight damage/HP receipt remain strict.
        mismatch = gate._source_native_world_parity(
            native, live, ITERATIONS, expected_raw_sha=raw_sha,
            allow_world_lethal=True
        )
        evidence = {
            "diagnostic": "P7.4_EXACT_FROZEN_WINNER_25_FIGHT_NO_RECORD",
            "gate_pass": False,
            "m1_recorded": False,
            "winner_sorted_sha256": sorted_sha,
            "winner_raw_sha256": raw_sha,
            "iterations": ITERATIONS,
            "native_dps": native["native_dps"],
            "live_native_dps": live["native_dps"],
            "live_world_mean_dps": live["world_mean_dps"],
            "native_first_duration_s": native["first_duration_s"],
            "live_sampled_duration_s": live["sampled_duration_s"],
            "live_first_iteration_duration_s": live["per_iteration"][0]["duration_s"],
            "live_damage_events": live["native_damage_events"],
            "live_world_target_lethal_fights": live["world_target_lethal_fights"],
            "live_world_target_survived_fights": live["world_target_survived_fights"],
            "live_world_target_health_remaining_by_fight": [
                row["world_target_health_remaining"] for row in live["per_iteration"]
            ],
            "coupled_native_world_abs_delta": abs(
                live["native_dps"] - live["world_mean_dps"]),
            "live_world_boundaries": live["native_world_ticks"],
            "standalone_native_control_parity_failure": strict_mismatch,
            "native_source_control_comparable": live["world_target_lethal_fights"] == 0,
            "parity_failure": mismatch,
        }
        print(json.dumps(evidence, sort_keys=True), flush=True)
        if mismatch is not None:
            raise RuntimeError(f"P74_EXACT_WINNER_PARITY_DIAGNOSTIC_FAILED:{mismatch}")
        print(
            "P74_EXACT_WINNER_NATIVE_WORLD_LETHAL_AWARE_PARITY_DIAGNOSTIC_PASS_NOT_GATE",
            flush=True,
        )


if __name__ == "__main__":
    main()
