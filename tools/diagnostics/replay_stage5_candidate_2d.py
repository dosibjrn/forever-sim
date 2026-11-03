#!/usr/bin/env python3
"""Bounded live native↔gsim-2D replay of the Druid Balance Stage-5 candidates.

This is a diagnostic only: it does not certify source legality, P7, or an M1 gate.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
ENGINE_DIR = ROOT / "integrations/mythicsim-rust/engine"
PROBE_PATH = ROOT / "integrations/mythicsim-rust/live_world_probe.py"


def load_probe():
    spec = importlib.util.spec_from_file_location("work1_stage5_live_world_probe", PROBE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load live-world probe: {PROBE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def one_artifact_root(artifact_dir: Path) -> Path:
    matrices = list(artifact_dir.rglob("matrix.json"))
    if len(matrices) != 1:
        raise RuntimeError(f"expected exactly one matrix.json, found {len(matrices)}")
    return matrices[0].parent


def load_candidates(root: Path) -> tuple[dict[str, Any], list[tuple[str, Path]]]:
    profile_dir = root / "profiles/druid__balance"
    paths = [
        ("baseline", profile_dir / "baseline_effective_request.json"),
        ("best_balanced", profile_dir / "best_effective_request.json"),
    ]
    donor_paths = sorted((profile_dir / "generated_talent_donors").glob("*.effective_request.json"))
    if not donor_paths:
        raise RuntimeError("Stage-5 artifact contains no generated Druid Balance donor requests")
    paths.extend((f"generated_donor:{path.stem}", path) for path in donor_paths)
    for label, path in paths:
        if not path.is_file():
            raise RuntimeError(f"missing {label} request: {path}")
    matrix = json.loads((root / "matrix.json").read_text())
    row = next((item for item in matrix if item.get("profile_id") == "druid/balance"), None)
    if row is None:
        raise RuntimeError("matrix.json has no druid/balance row")
    return row, paths


def request_shape(path: Path) -> tuple[dict[str, Any], float]:
    request = json.loads(path.read_text())
    parties = request.get("raid", {}).get("parties", [])
    players = [player for party in parties for player in party.get("players", [])]
    targets = request.get("encounter", {}).get("targets", [])
    if len(players) != 1 or len(targets) != 1 or targets[0].get("level") != 63:
        raise RuntimeError(
            f"{path.name}: expected one player and one level-63 target; "
            f"players={len(players)} targets={[t.get('level') for t in targets]}"
        )
    player = players[0]
    if player.get("class") != "ClassDruid":
        raise RuntimeError(f"{path.name}: expected ClassDruid, got {player.get('class')!r}")
    distance = player.get("distanceFromTarget")
    if not isinstance(distance, (int, float)) or distance <= 0:
        raise RuntimeError(f"{path.name}: invalid distanceFromTarget={distance!r}")
    return player, float(distance)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    if args.iterations != 5:
        parser.error("this bounded diagnostic is intentionally fixed at 5 iterations")
    root = one_artifact_root(args.artifact_dir)
    provenance = json.loads((root / "provenance.json").read_text())
    if provenance.get("stage_seconds") != 5:
        raise RuntimeError(f"expected a 5-second Stage-5 artifact, got {provenance.get('stage_seconds')!r}")
    if provenance.get("candidate_rng_mode") != "balanced":
        raise RuntimeError(f"expected Balanced candidates, got {provenance.get('candidate_rng_mode')!r}")

    engine_sha = subprocess.check_output(
        ["git", "-C", str(ENGINE_DIR), "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
    ).strip()
    if provenance.get("engine_git_sha") != engine_sha:
        raise RuntimeError(
            f"artifact engine pin {provenance.get('engine_git_sha')} != checkout {engine_sha}"
        )

    matrix_row, candidates = load_candidates(root)
    print(
        "STAGE5_ARTIFACT",
        json.dumps(
            {
                "repo_git_sha": provenance.get("repo_git_sha"),
                "engine_git_sha": engine_sha,
                "stage_seconds": provenance.get("stage_seconds"),
                "candidate_rng_mode": provenance.get("candidate_rng_mode"),
                "holdout_status": provenance.get("holdout_status"),
                "process_p7_pass": provenance.get("process_p7_pass"),
                "druid_balance_native_paid_total": matrix_row.get("native_paid_total"),
                "druid_balance_three_axis_paid": matrix_row.get("three_axis_paid"),
                "druid_balance_baseline": matrix_row.get("baseline_balanced_score"),
                "druid_balance_best": matrix_row.get("best_balanced_screen"),
                "native_invalid": matrix_row.get("native_invalid"),
                "native_unsupported": matrix_row.get("native_unsupported"),
                "native_rejections": matrix_row.get("native_rejections"),
                "next_stage_eligible": matrix_row.get("next_stage_eligible"),
                "live_gsim_2d_rust_causality": matrix_row.get("live_gsim_2d_rust_causality"),
                "candidate_count": len(candidates),
            },
            sort_keys=True,
        ),
        flush=True,
    )

    prepared: list[tuple[str, Path, dict[str, Any], float, str]] = []
    for label, path in candidates:
        player, distance = request_shape(path)
        request_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        prepared.append((label, path, player, distance, request_sha))
        print(
            "CANDIDATE_SHAPE",
            json.dumps(
                {
                    "label": label,
                    "request": str(path.relative_to(root)),
                    "request_sha256": request_sha,
                    "talents": player.get("talentsString"),
                    "apl_action_count": len(player.get("rotation", {}).get("priorityList", [])),
                    "distance": distance,
                },
                sort_keys=True,
            ),
            flush=True,
        )

    if args.validate_only:
        print("STAGE5_CANDIDATE_SHAPES_VALID_DIAGNOSTIC_ONLY", flush=True)
        return 0
    if args.binary is None or not args.binary.is_file():
        raise RuntimeError("--binary must point to the compiled selected forever-engine")

    probe = load_probe()
    results = []
    for label, path, player, distance, request_sha in prepared:
        native = probe.native_source_control(args.binary, path, 5, rng_mode="balanced")
        live = probe.run(
            args.binary,
            path,
            distance=distance,
            iterations=5,
            rng_mode="balanced",
        )
        native_dps = float(native["native_dps"])
        live_native_dps = float(live["native_dps"])
        world_dps = float(live["world_mean_dps"])
        native_delta = abs(native_dps - live_native_dps)
        world_delta = abs(native_dps - world_dps)
        if live.get("iterations_done") != 5:
            raise RuntimeError(f"{label}: expected 5 live iterations, got {live.get('iterations_done')}")
        if live.get("native_damage_events", 0) <= 0 or live.get("native_world_ticks", 0) <= 0:
            raise RuntimeError(f"{label}: missing native damage events or world ticks: {live}")
        if native_delta >= 1e-5 or world_delta >= 1e-5:
            raise RuntimeError(
                f"{label}: native↔2D parity failed; native={native_dps} "
                f"live_native={live_native_dps} world={world_dps}"
            )
        result = {
            "label": label,
            "request_sha256": request_sha,
            "talents": player.get("talentsString"),
            "apl_action_count": len(player.get("rotation", {}).get("priorityList", [])),
            "iterations": 5,
            "rng_mode": "balanced",
            "native_source_control_dps": native_dps,
            "live_native_dps": live_native_dps,
            "live_2d_dps": world_dps,
            "native_delta": native_delta,
            "world_delta": world_delta,
            "native_damage_events": live.get("native_damage_events"),
            "native_world_ticks": live.get("native_world_ticks"),
            "source_request_raw_sha256": live.get("source_request_raw_sha256"),
            "checkpoint_certified": False,
            "p7_gate_pass": False,
        }
        results.append(result)
        print("WORK1_STAGE5_NATIVE_2D_CANDIDATE", json.dumps(result, sort_keys=True), flush=True)

    print(
        "WORK1_STAGE5_NATIVE_2D_DIAGNOSTIC_GREEN_NOT_P7_GATE",
        json.dumps(
            {
                "candidate_count": len(results),
                "all_native_2d_parity_checks_passed": True,
                "checkpoint_certified": False,
                "p7_gate_pass": False,
                "m1_write": False,
                "results": results,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
