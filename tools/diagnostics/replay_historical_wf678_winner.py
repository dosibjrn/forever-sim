#!/usr/bin/env python3
"""No-record diagnostic: replay historical WF678 winner axes on current selected Rust + gsim 2D.

This deliberately does NOT seed or alter the optimizer, write M1, or claim P7
acceptance. It overlays only the historical winner's gear/talents/APL onto the
current saved Balance scenario, checks today's source/Rust legality, then runs
a tiny explicit Balanced and Stochastic native+2D parity smoke.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
INTEGRATION = ROOT / "integrations/mythicsim-rust"
ENGINE_ROOT = INTEGRATION / "engine"
EXPECTED_ENGINE = "deb366e986dbc156e2242ddac3ac8c4ac854c107"
REFERENCE = ROOT / "docs/evidence/druid-l60-balance/p7.3/saved_728_request.json"
AXES = ROOT / "docs/evidence/druid-l60-balance/p7.5/historical_wf678_winner_axes.json"
CATALOGUE = ROOT / "data/forever/catalogue/items_2026-09-29.sqlite"
RUST_ITEMS = ENGINE_ROOT / "data/items.jsonl"
RUST_ENCHANTS = ENGINE_ROOT / "data/enchants.jsonl"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load diagnostic module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def git_selected_engine() -> str:
    entry = subprocess.check_output(
        ["git", "ls-tree", "HEAD", "integrations/mythicsim-rust/engine"],
        cwd=ROOT, text=True,
    ).strip().split()
    if len(entry) < 3 or entry[1] != "commit":
        raise RuntimeError("SELECTED_RUST_GITLINK_MISSING")
    actual = subprocess.check_output(
        ["git", "-C", str(ENGINE_ROOT), "rev-parse", "HEAD"], text=True,
    ).strip()
    if entry[2] != actual:
        raise RuntimeError(f"SELECTED_RUST_GITLINK_MISMATCH:{entry[2]}!={actual}")
    if actual != EXPECTED_ENGINE:
        raise RuntimeError(f"UNEXPECTED_SELECTED_RUST_PIN:{actual}")
    return actual


def player(request: dict) -> dict:
    return request["raid"]["parties"][0]["players"][0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.iterations <= 20:
        parser.error("--iterations must be within [1, 20] for a bounded diagnostic")

    binary = args.binary.resolve()
    if not binary.is_file():
        raise FileNotFoundError(binary)
    selected_engine = git_selected_engine()
    reference = json.loads(REFERENCE.read_text())
    axes = json.loads(AXES.read_text())
    candidate = copy.deepcopy(reference)
    target = player(candidate)
    target["equipment"] = copy.deepcopy(axes["equipment"])
    target["talentsString"] = axes["talentsString"]
    target["rotation"] = copy.deepcopy(axes["rotation"])
    candidate["simOptions"]["iterations"] = args.iterations

    # The old run and current gate use the same 120s / level-63 encounter and
    # the same raid/party buffs. The reference raw request hash did change;
    # this is a cross-version axes replay, not a claim of byte-identical replay.
    assert candidate["encounter"]["duration"] == 120
    assert candidate["encounter"]["targets"][0]["level"] == 63
    print("HISTORICAL_WF678_SOURCE", axes["historical_source"])
    print("HISTORICAL_WF678_HOLDOUT_DPS", axes["historical_holdout_dps"])
    print("HISTORICAL_WF678_HOLDOUT_ITERATIONS", axes["historical_holdout_iterations"])
    print("HISTORICAL_REFERENCE_SHA256", axes["historical_reference_sha256"])
    print("CURRENT_SAVED_BALANCE_REFERENCE_SHA256", file_sha256(REFERENCE))
    print("HISTORICAL_SOURCE_CATALOGUE_SHA256", axes["historical_source_catalogue_sha256"])
    print("CURRENT_SOURCE_CATALOGUE_SHA256", file_sha256(CATALOGUE))
    print("HISTORICAL_RUST_ITEMS_SHA256", axes["historical_rust_items_sha256"])
    print("CURRENT_RUST_ITEMS_SHA256", file_sha256(RUST_ITEMS))
    print("HISTORICAL_RUST_ENCHANTS_SHA256", axes["historical_rust_enchants_sha256"])
    print("CURRENT_RUST_ENCHANTS_SHA256", file_sha256(RUST_ENCHANTS))
    print("HISTORICAL_NATIVE_BINARY_SHA256", axes["historical_native_binary_sha256"])
    print("CURRENT_NATIVE_BINARY_SHA256", file_sha256(binary))
    print("CURRENT_SELECTED_RUST_PIN", selected_engine)
    print("CURRENT_SCENARIO", json.dumps({
        "duration": candidate["encounter"]["duration"],
        "durationVariation": candidate["encounter"].get("durationVariation"),
        "targetLevel": candidate["encounter"]["targets"][0]["level"],
        "distance": target.get("distanceFromTarget"),
    }, sort_keys=True))

    sys.path.insert(0, str(INTEGRATION))
    source = load_module(INTEGRATION / "p75_unrestricted_search.py",
                         "historical_wf678_current_source")
    try:
        ranks = source.parse(target["talentsString"])
        if not source.validate(ranks, moonkin=False, insect=False):
            print("HISTORICAL_WF678_REPLAY_STATUS=BLOCKED_CURRENT_TALENT_LEGALITY")
            print("HISTORICAL_WF678_TALENTS", target["talentsString"])
            return 0
    except Exception as exc:
        print("HISTORICAL_WF678_REPLAY_STATUS=BLOCKED_CURRENT_TALENT_LEGALITY")
        print("HISTORICAL_WF678_TALENT_ERROR", type(exc).__name__, str(exc))
        return 0

    validator = source.GearValidator(CATALOGUE, RUST_ITEMS, RUST_ENCHANTS, reference)
    try:
        try:
            audit = source.validate_candidate_gear(
                validator, reference, target["equipment"]["items"])
        except source.RejectedGear as exc:
            print("HISTORICAL_WF678_CURRENT_SOURCE_LEGALITY=REJECTED")
            print("HISTORICAL_WF678_REJECTION", json.dumps({
                "category": exc.category, "slot": exc.slot,
                "item_id": exc.item_id, "message": str(exc),
            }, sort_keys=True))
            print("HISTORICAL_WF678_REPLAY_STATUS=BLOCKED_CURRENT_SOURCE_LEGALITY")
            return 0
    finally:
        validator.close()
    print("HISTORICAL_WF678_CURRENT_SOURCE_LEGALITY=ACCEPTED")
    print("HISTORICAL_WF678_CURRENT_GEAR_AUDIT", json.dumps(audit, sort_keys=True))

    probe = load_module(INTEGRATION / "live_world_probe.py",
                        "historical_wf678_current_native_2d_probe")
    outputs = {}
    with tempfile.TemporaryDirectory(prefix="forever-wf678-replay-") as tmp:
        request_path = Path(tmp) / "historical-wf678-current-scenario.json"
        request_path.write_text(json.dumps(candidate))
        for mode in ("balanced", "stochastic"):
            native = probe.native_source_control(
                binary, request_path, args.iterations, rng_mode=mode)
            live = probe.run(
                binary, request_path,
                distance=float(target.get("distanceFromTarget", 15.0)),
                iterations=args.iterations, rng_mode=mode)
            native_dps = float(native["native_dps"])
            world_dps = float(live["world_mean_dps"])
            parity_delta = abs(native_dps - world_dps)
            if (live.get("iterations_done") != args.iterations
                    or live.get("native_damage_events", 0) <= 0
                    or live.get("native_world_ticks", 0) <= 0
                    or parity_delta >= 1e-5):
                raise AssertionError(
                    f"HISTORICAL_WF678_NATIVE_2D_PARITY_OR_EXECUTION_FAILED:{mode}:"
                    f"{native}:{live}")
            outputs[mode] = native_dps
            print("HISTORICAL_WF678_CURRENT_PIN_REPLAY", json.dumps({
                "mode": mode, "iterations": args.iterations,
                "native_dps": native_dps, "world_mean_dps": world_dps,
                "parity_delta": parity_delta,
                "native_damage_events": live["native_damage_events"],
                "native_world_ticks": live["native_world_ticks"],
            }, sort_keys=True), flush=True)
    if abs(outputs["balanced"] - outputs["stochastic"]) <= 0.01:
        raise AssertionError(
            f"SELECTED_RUST_IGNORED_EXPLICIT_RNG_MODE:{outputs}")
    print("HISTORICAL_WF678_REPLAY_STATUS=EXECUTED_CURRENT_PIN_NATIVE_2D_DIAGNOSTIC_NOT_GATE")
    print("HISTORICAL_WF678_BALANCED_NATIVE_2D_DPS", outputs["balanced"])
    print("HISTORICAL_WF678_STOCHASTIC_NATIVE_2D_DPS", outputs["stochastic"])
    print("NO_P7_VERDICT_NO_M1_WRITE_NO_OPTIMIZER_SEED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
