#!/usr/bin/env python3
"""No-record diagnostic: ablate historical WF678 axes against the failed P7.5 winner.

This deliberately does NOT seed or alter the optimizer, write M1, or claim P7
acceptance. It uses the historical winner only as a controlled diagnostic
reference. Each case is independently source-validated and paid through the
current selected Rust + gsim 2D path with explicit Balanced RNG.
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
EXPECTED_REFERENCE_RAW_SHA256 = "e99b06e5aa891a941ac077643a4209ab8582c810b678df4ec2d47ac48c6c646a"
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


def json_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


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


def compose_candidate(reference: dict, base_build: dict, historical_axes: dict,
                      selected_axes: tuple[str, ...], iterations: int) -> dict:
    """Overlay only named historical axes on a supplied baseline build."""
    allowed = {"gear", "talents", "apl"}
    unknown = set(selected_axes) - allowed
    if unknown:
        raise ValueError(f"Unknown historical axes: {sorted(unknown)}")
    required = ("equipment", "talentsString", "rotation")
    if any(key not in base_build for key in required):
        raise ValueError("Baseline build is missing one or more optimization axes")
    candidate = copy.deepcopy(reference)
    target = player(candidate)
    for key in required:
        target[key] = copy.deepcopy(base_build[key])
    if "gear" in selected_axes:
        target["equipment"] = copy.deepcopy(historical_axes["equipment"])
    if "talents" in selected_axes:
        target["talentsString"] = historical_axes["talentsString"]
    if "apl" in selected_axes:
        target["rotation"] = copy.deepcopy(historical_axes["rotation"])
    candidate["simOptions"]["iterations"] = iterations
    return candidate


def validate_build_axes(source, validator, reference: dict, build: dict,
                        label: str) -> dict:
    target = build
    try:
        ranks = source.parse(target["talentsString"])
        if not source.validate(ranks, moonkin=False, insect=False):
            raise RuntimeError(f"{label}_TALENTS_REJECTED")
    except Exception as exc:
        raise RuntimeError(
            f"{label}_TALENT_LEGALITY:{type(exc).__name__}:{exc}") from exc
    try:
        audit = source.validate_candidate_gear(
            validator, reference, target["equipment"]["items"])
    except source.RejectedGear as exc:
        raise RuntimeError(
            f"{label}_GEAR_REJECTED:{exc.category}:{exc.slot}:{exc.item_id}:{exc}") from exc
    return audit


def run_case(probe, binary: Path, candidate: dict, iterations: int,
             mode: str, temp_dir: Path, case_name: str) -> dict:
    target = player(candidate)
    request_path = temp_dir / f"{case_name}-{mode}.json"
    request_path.write_text(json.dumps(candidate, ensure_ascii=False))
    native = probe.native_source_control(
        binary, request_path, iterations, rng_mode=mode)
    live = probe.run(
        binary, request_path,
        distance=float(target.get("distanceFromTarget", 15.0)),
        iterations=iterations, rng_mode=mode)
    native_dps = float(native["native_dps"])
    world_dps = float(live["world_mean_dps"])
    parity_delta = abs(native_dps - world_dps)
    if (live.get("iterations_done") != iterations
            or live.get("native_damage_events", 0) <= 0
            or live.get("native_world_ticks", 0) <= 0
            or parity_delta >= 1e-5):
        raise AssertionError(
            f"AXIS_ABLATION_NATIVE_2D_PARITY_OR_EXECUTION_FAILED:{case_name}:{mode}:"
            f"{native}:{live}")
    return {
        "case": case_name,
        "mode": mode,
        "iterations": iterations,
        "native_dps": native_dps,
        "world_mean_dps": world_dps,
        "parity_delta": parity_delta,
        "native_damage_events": live["native_damage_events"],
        "native_world_ticks": live["native_world_ticks"],
        "equipment_sha256": json_sha256(target["equipment"]),
        "talents_sha256": hashlib.sha256(
            target["talentsString"].encode("utf-8")).hexdigest(),
        "rotation_sha256": json_sha256(target["rotation"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--search-report", type=Path,
                        help="Exact no-record P7.5 CLI report containing frozen_source_build")
    args = parser.parse_args()
    if not 1 <= args.iterations <= 20:
        parser.error("--iterations must be within [1, 20] for a bounded diagnostic")

    binary = args.binary.resolve()
    if not binary.is_file():
        raise FileNotFoundError(binary)
    selected_engine = git_selected_engine()
    reference = json.loads(REFERENCE.read_text())
    axes = json.loads(AXES.read_text())

    # A failed P7.5 artifact is a diagnostic baseline only, never an optimizer
    # seed. Fail closed if its source request or selected Rust pin has drifted.
    search_record = None
    if args.search_report:
        report = json.loads(args.search_report.read_text())
        rows = report.get("results")
        if not isinstance(rows, list):
            raise RuntimeError("P75_SEARCH_REPORT_HAS_NO_RESULTS")
        search_record = next((row for row in rows if row.get("gate") == "P7.5"), None)
        if not isinstance(search_record, dict):
            raise RuntimeError("P75_SEARCH_REPORT_RECORD_MISSING")
        if search_record.get("status") != "FAIL":
            raise RuntimeError("P75_SEARCH_REPORT_IS_NOT_THE_EXPECTED_FAILED_DIAGNOSTIC")
        if search_record.get("native_source_revision") != selected_engine:
            raise RuntimeError("P75_SEARCH_REPORT_RUST_PIN_MISMATCH")
        if search_record.get("source_request_raw_sha256") != EXPECTED_REFERENCE_RAW_SHA256:
            raise RuntimeError("P75_SEARCH_REPORT_SOURCE_REQUEST_MISMATCH")
        search_build = search_record.get("frozen_source_build")
        if not isinstance(search_build, dict):
            raise RuntimeError("P75_SEARCH_REPORT_FROZEN_BUILD_MISSING")
        baseline_label = "failed_p75_search_winner"
        print("P75_SEARCH_REPORT_STATUS", search_record["status"])
        print("P75_SEARCH_REPORT_SOURCE_SHA256", search_record["source_request_raw_sha256"])
        print("P75_SEARCH_REPORT_FROZEN_STOCHASTIC_DPS",
              search_record.get("frozen_stochastic_world_dps"))
        print("P75_SEARCH_REPORT_REQUIRED_DPS", search_record.get("final_required_dps"))
    else:
        search_build = player(reference)
        baseline_label = "saved_reference"

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
    print("AXIS_ABLATION_BASELINE", baseline_label)
    print("CURRENT_SCENARIO", json.dumps({
        "duration": reference["encounter"]["duration"],
        "durationVariation": reference["encounter"].get("durationVariation"),
        "targetLevel": reference["encounter"]["targets"][0]["level"],
        "distance": player(reference).get("distanceFromTarget"),
    }, sort_keys=True))

    sys.path.insert(0, str(INTEGRATION))
    source = load_module(INTEGRATION / "p75_unrestricted_search.py",
                         "historical_wf678_current_source")
    validator = source.GearValidator(CATALOGUE, RUST_ITEMS, RUST_ENCHANTS, reference)
    try:
        historical_audit = validate_build_axes(
            source, validator, reference, axes, "HISTORICAL_WF678")
        baseline_audit = validate_build_axes(
            source, validator, reference, search_build, baseline_label.upper())
    finally:
        validator.close()
    print("HISTORICAL_WF678_CURRENT_SOURCE_LEGALITY=ACCEPTED")
    print("HISTORICAL_WF678_CURRENT_GEAR_AUDIT", json.dumps(historical_audit, sort_keys=True))
    print("AXIS_ABLATION_BASELINE_CURRENT_SOURCE_LEGALITY=ACCEPTED")
    print("AXIS_ABLATION_BASELINE_GEAR_AUDIT", json.dumps(baseline_audit, sort_keys=True))

    probe = load_module(INTEGRATION / "live_world_probe.py",
                        "historical_wf678_current_native_2d_probe")
    case_specs = (
        ("baseline", ()),
        ("historical_gear_only", ("gear",)),
        ("historical_talents_only", ("talents",)),
        ("historical_apl_only", ("apl",)),
        ("historical_gear_talents", ("gear", "talents")),
        ("historical_gear_apl", ("gear", "apl")),
        ("historical_talents_apl", ("talents", "apl")),
        ("historical_all_axes", ("gear", "talents", "apl")),
    )
    outputs = {}
    with tempfile.TemporaryDirectory(prefix="forever-wf678-axis-ablation-") as tmp:
        temp_dir = Path(tmp)
        for case_name, selected_axes in case_specs:
            candidate = compose_candidate(
                reference, search_build, axes, selected_axes, args.iterations)
            balanced = run_case(
                probe, binary, candidate, args.iterations,
                "balanced", temp_dir, case_name)
            outputs[case_name] = balanced
            print("P75_AXIS_ABLATION_RESULT",
                  json.dumps(balanced, sort_keys=True), flush=True)
            if case_name == "historical_all_axes":
                stochastic = run_case(
                    probe, binary, candidate, args.iterations,
                    "stochastic", temp_dir, case_name)
                outputs["historical_all_axes_stochastic"] = stochastic
                print("P75_AXIS_ABLATION_RESULT",
                      json.dumps(stochastic, sort_keys=True), flush=True)

    summary = {name: round(row["native_dps"], 4)
               for name, row in outputs.items()}
    print("P75_AXIS_ABLATION_SUMMARY", json.dumps(summary, sort_keys=True))
    print("P75_AXIS_ABLATION_STATUS=EXECUTED_CURRENT_PIN_NATIVE_2D_DIAGNOSTIC_NOT_GATE")
    print("NO_P7_VERDICT_NO_M1_WRITE_NO_OPTIMIZER_SEED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
