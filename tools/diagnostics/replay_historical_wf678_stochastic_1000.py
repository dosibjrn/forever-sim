#!/usr/bin/env python3
"""No-record 1,000-fight Stochastic replay of historical WF678 axes on current Rust + gsim 2D.

This is a diagnostic of historical-candidate transferability, not a P7 gate,
optimizer seed, candidate-selection step, or M1 acceptance receipt.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.wf_gate_coverage import P7_FINAL_STOCHASTIC_ITERATIONS


def load_module(path: Path, name: str):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load diagnostic module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def player(request: dict) -> dict:
    return request["raid"]["parties"][0]["players"][0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    args = parser.parse_args()

    iterations = P7_FINAL_STOCHASTIC_ITERATIONS
    binary = args.binary.resolve()
    if not binary.is_file():
        raise FileNotFoundError(binary)

    helper = load_module(
        ROOT / "tools/diagnostics/replay_historical_wf678_winner.py",
        "work1_historical_wf678_replay_helpers",
    )
    selected_engine = helper.git_selected_engine()
    reference = json.loads(helper.REFERENCE.read_text())
    axes = json.loads(helper.AXES.read_text())

    candidate = copy.deepcopy(reference)
    target = player(candidate)
    target["equipment"] = copy.deepcopy(axes["equipment"])
    target["talentsString"] = axes["talentsString"]
    target["rotation"] = copy.deepcopy(axes["rotation"])
    candidate["simOptions"]["iterations"] = iterations
    seed = str(candidate["simOptions"]["randomSeed"])
    if not seed:
        raise ValueError("CURRENT_BALANCE_REFERENCE_RANDOM_SEED_MISSING")

    assert candidate["encounter"]["duration"] == 120
    assert candidate["encounter"]["targets"][0]["level"] == 63

    axes_payload = {
        "equipment": axes["equipment"],
        "talentsString": axes["talentsString"],
        "rotation": axes["rotation"],
    }
    axes_sha = sha256(json.dumps(
        axes_payload, sort_keys=True, separators=(",", ":")
    ).encode())

    print("HISTORICAL_WF678_SOURCE", axes["historical_source"])
    print("HISTORICAL_WF678_NATIVE_ONLY_HOLDOUT_DPS", axes["historical_holdout_dps"])
    print("HISTORICAL_WF678_NATIVE_ONLY_HOLDOUT_ITERATIONS",
          axes["historical_holdout_iterations"])
    print("CURRENT_SELECTED_RUST_PIN", selected_engine)
    print("CURRENT_SAVED_BALANCE_REFERENCE_SHA256",
          helper.file_sha256(helper.REFERENCE))
    print("HISTORICAL_AXES_SHA256", axes_sha)
    print("CURRENT_SOURCE_CATALOGUE_SHA256",
          helper.file_sha256(helper.CATALOGUE))
    print("CURRENT_RUST_ITEMS_SHA256", helper.file_sha256(helper.RUST_ITEMS))
    print("CURRENT_RUST_ENCHANTS_SHA256", helper.file_sha256(helper.RUST_ENCHANTS))
    print("CURRENT_NATIVE_BINARY_SHA256", helper.file_sha256(binary))
    print("CURRENT_SCENARIO", json.dumps({
        "duration": candidate["encounter"]["duration"],
        "target_level": candidate["encounter"]["targets"][0]["level"],
        "distance": target.get("distanceFromTarget"),
        "iterations": iterations,
        "random_seed": seed,
        "rng_mode": "stochastic",
    }, sort_keys=True))

    integration = helper.INTEGRATION
    sys.path.insert(0, str(integration))
    source = helper.load_module(
        integration / "p75_unrestricted_search.py",
        "work1_historical_wf678_current_source",
    )
    try:
        ranks = source.parse(target["talentsString"])
        if not source.validate(ranks, moonkin=False, insect=False):
            print("HISTORICAL_WF678_1000_STATUS=BLOCKED_CURRENT_TALENT_LEGALITY")
            print("HISTORICAL_WF678_TALENTS", target["talentsString"])
            return 0
    except Exception as exc:
        print("HISTORICAL_WF678_1000_STATUS=BLOCKED_CURRENT_TALENT_LEGALITY")
        print("HISTORICAL_WF678_TALENT_ERROR", type(exc).__name__, str(exc))
        return 0

    validator = source.GearValidator(
        helper.CATALOGUE, helper.RUST_ITEMS, helper.RUST_ENCHANTS, reference
    )
    try:
        try:
            audit = source.validate_candidate_gear(
                validator, reference, target["equipment"]["items"]
            )
        except source.RejectedGear as exc:
            print("HISTORICAL_WF678_CURRENT_SOURCE_LEGALITY=REJECTED")
            print("HISTORICAL_WF678_REJECTION", json.dumps({
                "category": exc.category,
                "slot": exc.slot,
                "item_id": exc.item_id,
                "message": str(exc),
            }, sort_keys=True))
            print("HISTORICAL_WF678_1000_STATUS=BLOCKED_CURRENT_SOURCE_LEGALITY")
            return 0
    finally:
        validator.close()

    print("HISTORICAL_WF678_CURRENT_SOURCE_LEGALITY=ACCEPTED")
    print("HISTORICAL_WF678_CURRENT_GEAR_AUDIT", json.dumps(audit, sort_keys=True))

    probe = helper.load_module(
        integration / "live_world_probe.py",
        "work1_historical_wf678_current_native_2d_probe",
    )
    with tempfile.TemporaryDirectory(prefix="forever-wf678-1000-") as tmp:
        request_path = Path(tmp) / "historical-wf678-current-scenario.json"
        request_path.write_text(json.dumps(candidate))
        request_sha = sha256(request_path.read_bytes())

        # This replay is evaluation only: the historical axes never enter the
        # optimizer, a Balanced score, parent pool, rerank, or winner selection.
        native = probe.native_source_control(
            binary, request_path, iterations, rng_mode="stochastic"
        )
        live = probe.run(
            binary,
            request_path,
            distance=float(target.get("distanceFromTarget", 15.0)),
            iterations=iterations,
            rng_mode="stochastic",
        )

    native_dps = float(native["native_dps"])
    world_dps = float(live["world_mean_dps"])
    parity_delta = abs(native_dps - world_dps)
    if (live.get("iterations_done") != iterations
            or live.get("native_damage_events", 0) <= 0
            or live.get("native_world_ticks", 0) <= 0
            or parity_delta >= 1e-5):
        raise AssertionError(
            "HISTORICAL_WF678_1000_NATIVE_2D_PARITY_OR_EXECUTION_FAILED:"
            f"native={native}:world={live}"
        )

    result = {
        "status": "EXECUTED_DIAGNOSTIC_NOT_GATE",
        "mode": "stochastic",
        "iterations": iterations,
        "random_seed": seed,
        "selected_rust_pin": selected_engine,
        "request_raw_sha256": request_sha,
        "historical_axes_sha256": axes_sha,
        "historical_native_only_holdout_dps": axes["historical_holdout_dps"],
        "native_dps": native_dps,
        "world_mean_dps": world_dps,
        "parity_delta": parity_delta,
        "native_damage_events": int(live["native_damage_events"]),
        "native_world_ticks": int(live["native_world_ticks"]),
        "iterations_done": int(live["iterations_done"]),
    }
    print("HISTORICAL_WF678_1000_STOCHASTIC_NATIVE_2D_RESULT",
          json.dumps(result, sort_keys=True), flush=True)
    print("NO_P7_VERDICT_NO_M1_WRITE_NO_OPTIMIZER_SEED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
