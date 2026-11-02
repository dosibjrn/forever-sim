#!/usr/bin/env python3
"""Versioned upstream candidate diagnostic; NOT an acceptance gate or PASS receipt.

Old WF633 exact SHA/DPS is replayed against old pinned engine BEFORE merging
upstream. A newer source engine is expected to alter mechanics legitimately;
never rewrite that historical reference or count this probe as P7 acceptance.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
REQ = ROOT / "docs/evidence/wf633/rust_request_reconstructed.json"
META = ROOT / "docs/evidence/wf633/WF633_VALIDATION.json"
WORLD_REQUEST = ROOT / "docs/evidence/druid-l60-balance/p7.3/saved_728_request.json"
PROBE = Path(__file__).with_name("live_world_probe.py")


def run(binary: Path) -> dict:
    meta = json.loads(META.read_text())
    raw = REQ.read_bytes()
    raw_sha = hashlib.sha256(raw).hexdigest()
    assert raw_sha == meta["request_sha256"], "HISTORICAL_SOURCE_REQUEST_MUTATED"
    assert meta["engine_revision"] == "666fe17a42682068a3c8497d88d5fa3732cbdfb9"
    assert WORLD_REQUEST.is_file(), "SAVED_SOURCE_WORLD_REQUEST_MISSING"
    assert binary.is_file(), "RUST_UPSTREAM_ENGINE_NOT_BUILT"

    spec = importlib.util.spec_from_file_location("rust_upstream_probe", PROBE)
    assert spec and spec.loader
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)

    # Native new-engine source replay uses the unchanged saved original request,
    # only replacing the iteration budget as accepted by PROCESS v2.14.
    native = probe.native_source_control(binary, WORLD_REQUEST, 1000, rng_mode="stochastic")
    assert math.isfinite(native["native_dps"]) and native["native_dps"] > 0
    baseline = float(meta["rust_dps"])
    delta = (native["native_dps"] / baseline) - 1.0

    comparisons = {}
    for mode in ("stochastic", "balanced"):
        direct = probe.native_source_control(binary, WORLD_REQUEST, 3, rng_mode=mode)
        world = probe.run(binary, WORLD_REQUEST, distance=15., iterations=3, rng_mode=mode)
        assert world["checkpoint_certified"] is False
        assert world["iterations_done"] == 3
        assert world["native_damage_events"] > 0 and world["native_world_ticks"] > 0
        assert abs(direct["native_dps"] - world["world_mean_dps"]) < 1e-5, (
            "UPDATED_RUST_NATIVE_2D_DPS_NOT_IDENTICAL", mode, direct, world)
        assert abs(world["native_dps"] - world["world_mean_dps"]) < 1e-5
        comparisons[mode] = {
            "source_native_dps_3": direct["native_dps"],
            "real_2d_world_dps_3": world["world_mean_dps"],
            "native_damage_events": world["native_damage_events"],
            "native_world_boundaries": world["native_world_ticks"],
        }

    # Classes must run through the SAME actual Rust ↔ 2D world ACK path.
    for spec_name, request, distance in (
        ("mage_fire", "fixtures/mage/prepared-v2/fire-reference.request.json", 20.),
        ("hunter_pet_prepull",
         "fixtures/mage/prepared-v2/all-values-beast-mastery-hunter-labeled.request.json", 12.),
    ):
        # Fixtures live in the cloned fork, not forever-sim.
        source = binary.parents[2] / request
        assert source.is_file(), ("UPDATED_RUST_SOURCE_FIXTURE_MISSING", str(source))
        try:
            world = probe.run(binary, source, distance=distance)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"UPSTREAM_NATIVE_PREPARE_REFUSED_OR_BROKEN {spec_name} "
                f"returncode={exc.returncode} "
                f"stdout={(exc.stdout or '')[-3000:]} "
                f"stderr={(exc.stderr or '')[-3000:]}"
            ) from exc
        assert world["native_damage_events"] > 0
        assert abs(world["native_dps"] - world["world_mean_dps"]) < 1e-5
        if spec_name == "hunter_pet_prepull":
            assert world["native_pet_damage_events"] > 0
            assert world["native_precombat_damage_events"] > 0
        comparisons[spec_name] = {
            "native_dps": world["native_dps"],
            "world_dps": world["world_mean_dps"],
            "native_damage_events": world["native_damage_events"],
        }

    data = {
        "kind": "UPSTREAM_ENGINE_COMPATIBILITY_DIAGNOSTIC_NOT_M1_OR_P7_PASS",
        "historical_baseline_engine_sha": meta["engine_revision"],
        "historical_baseline_dps": baseline,
        "historical_baseline_request_sha256": raw_sha,
        "new_engine_native_stochastic_1000_dps": native["native_dps"],
        "relative_delta_vs_historical": delta,
        "meaning": "Changed native result is reported, not overwritten or auto-certified.",
        "source_native_2d_comparisons": comparisons,
        "checkpoint_certified": False,
    }
    return data


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--engine", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    result = run(args.engine.resolve())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
