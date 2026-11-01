#!/usr/bin/env python3
"""One-shot real Rust same-class source-bounded gear probes for 28 L60 specs.

This is NOT a cold search, NOT a legal JOINT result, and NOT P7 evidence.
Each successful numeric score comes from the pinned native Rust binary only.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import random
import subprocess
import tempfile
import time
from collections import Counter
from pathlib import Path

from native_gear_adapter import NativeGearAdapter, GearRejected
from native_l60_matrix import (ROOT, HEAL, TANK, create_inventory, digest,
                               load_native_item_index, player)
from p73_talent_search_v2 import run


def classify_native_failure(message: str) -> str:
    """Keep Rust engine panics separate from fixture/metric/gear blockers."""
    if "balanced RNG: probability must be finite and in [0,1]" in message:
        return "RUST_BALANCED_RNG_PROBABILITY"
    if "raidMetrics" in message and ("dps" in message or "avg" in message):
        return "MISSING_NATIVE_DPS_METRIC"
    return "RUST_NATIVE_EXECUTION"



def replay_rng_modes(binary, request: dict, *, iterations: int, seed: int,
                     evaluator=None) -> dict:
    """Re-run the exact failing request in both native RNG modes.

    This is a *diagnostic* of the pinned Rust executable, not an optimizer
    candidate, a cold search, a paid score, or evidence of P7 promotion.
    The original failing request/seed is preserved across both replays.
    """
    native = evaluator if evaluator is not None else run
    original = copy.deepcopy(request)
    modes = {}
    for mode in ("balanced", "stochastic"):
        started = time.monotonic()
        try:
            score, _output, native_s, payload_sha = native(
                binary, copy.deepcopy(original), iterations, seed, mode,
                started + 10.0,
            )
            if not math.isfinite(score):
                modes[mode] = {"success": False, "category": "NONFINITE_NATIVE_METRIC",
                               "reason": "Native replay returned non-finite score"}
            else:
                modes[mode] = {"success": True, "diagnostic_score": score,
                               "native_duration_s": native_s,
                               "native_payload_sha256": payload_sha}
        except Exception as exc:
            modes[mode] = {"success": False,
                           "category": classify_native_failure(str(exc)),
                           "reason": str(exc)[-1100:]}
    if request != original:
        raise AssertionError("RNG replay mutated frozen native request")
    return {"accounting": "NOT_PAID_NOT_PROMOTABLE", "seed": seed,
            "iterations": iterations, **modes}


def capture_rng_backtrace(binary, request: dict, *, iterations: int, seed: int,
                          stderr_path: Path, runner=None) -> dict:
    """Capture a pinned Rust balanced-RNG panic stack for the *exact* failed input.

    This is an extra diagnostic subprocess, not a search candidate or score.
    Never replace the original request or classify a successful diagnostic
    process as an optimizer evaluation.
    """
    native_runner = runner if runner is not None else subprocess.run
    original = copy.deepcopy(request)
    payload = copy.deepcopy(request)
    payload["simOptions"]["iterations"] = iterations
    payload["simOptions"]["randomSeed"] = str(seed)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, WOWSIM_RNG_MODE="balanced", RUST_BACKTRACE="1")
    with tempfile.TemporaryDirectory() as tmp:
        request_path = Path(tmp) / "exact_failed_request.json"
        output_path = Path(tmp) / "native_output.json"
        request_path.write_text(json.dumps(payload, separators=(",", ":")))
        command = [str(binary), "sim", "--request", str(request_path),
                   "--outfile", str(output_path), "--gate"]
        try:
            completed = native_runner(command, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.PIPE, text=True,
                                      env=env, timeout=10.0)
            exit_code = completed.returncode
            stderr = completed.stderr or ""
            status = "COMPLETED"
        except subprocess.TimeoutExpired as exc:
            exit_code = None
            stderr = exc.stderr or ""
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            status = "TIMEOUT"
    stderr_path.write_text(stderr)
    if request != original:
        raise AssertionError("Native RNG backtrace changed original request")
    return {
        "accounting": "DIAGNOSTIC_NOT_PAID",
        "status": status,
        "exit_code": exit_code,
        "panic_reproduced": "balanced RNG: probability must be finite and in [0,1]" in stderr,
        "backtrace_present": "stack backtrace:" in stderr,
        "stderr_sha256": digest(stderr_path),
        "stderr_excerpt": stderr[-4096:],
        "native_payload_sha256": hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "iterations": iterations,
        "seed": seed,
    }


NEXT_FIX = {
    "SOURCE_BOUNDED_GEAR_POOL_EXHAUSTED": "Verify class equip/weapon rules and broaden native items.jsonl pools beyond observed fixtures.",
    "RUST_BALANCED_RNG_PROBABILITY": "Replay the attached exact mutated request and isolate the nonfinite/out-of-range probability in pinned Rust rng.rs:41.",
    "MISSING_NATIVE_DPS_METRIC": "Inspect native output and require a finite spec-compatible DPS metric before any paid result.",
    "RUST_NATIVE_EXECUTION": "Replay the attached exact native request and minimize the engine failure.",
    "OBJECTIVE_MISMATCH": "Implement and verify HPS/TPS native extractor with a comparable source fixture.",
    "SPEC_IDENTITY": "Find a verified Discipline request; do not equate Smite with Discipline.",
    "NO_NATIVE_REQUEST": "Locate a verified same-spec native source request.",
    "PARTIAL_GEAR_LEGALITY": "Verify source class/slot/hand/enchant restrictions and class talent tree before cold JOINT search.",
}


def group_gear_gaps(rows: list[dict]) -> dict[str, dict]:
    """Group exact blockers without double-counting an engine failure summary.

    Each failed native request appears once. A blocked profile without an
    exact request still contributes one summary entry to its blocker group.
    """
    groups: dict[str, dict] = {}
    for row in rows:
        failures = row.get("native_failures") or []
        if row.get("blocker") and not (
            row.get("status") == "BLOCKED_NATIVE_GEAR_EVALUATION" and failures
        ):
            category = row.get("blocker_category") or "UNCLASSIFIED"
            group = groups.setdefault(category, {
                "category": category, "profiles": [],
                "next_fix": NEXT_FIX.get(category, "Reproduce exact blocker"),
            })
            group["profiles"].append({
                "profile_id": row["profile_id"],
                "request_path": row.get("request_path"),
                "request_sha256": row.get("request_sha256"),
                "reason": row["blocker"],
            })
        for failure in failures:
            category = failure["category"]
            group = groups.setdefault(category, {
                "category": category, "profiles": [],
                "next_fix": NEXT_FIX.get(category, "Reproduce exact native request"),
            })
            group["profiles"].append({
                "profile_id": row["profile_id"],
                "request_path": failure["request_path"],
                "request_sha256": failure["request_sha256"],
                "reason": failure["reason"],
                "rng_replay": failure.get("rng_replay"),
                "rng_backtrace": failure.get("rng_backtrace"),
            })
    return groups


def probe_all(*, engine_src: Path, binary: Path, outdir: Path, seed: int, iterations: int, max_attempts: int = 3):
    records = create_inventory(ROOT / "config/validation/checkpoint_148.json", engine_src)
    index = load_native_item_index(engine_src)
    outdir.mkdir(parents=True, exist_ok=True)
    rows = []
    for idx, (inventory, reference) in enumerate(records):
        profile = inventory["profile_id"]
        cls = profile.split("/", 1)[0]
        row = {"profile_id": profile, "source_type": inventory["source_type"],
               "source_sha256": inventory["source_sha256"], "native_paid": 0,
               "status": "BLOCKED_NO_NATIVE_REQUEST", "native_score": None,
               "dimensions_searched": ["gear"], "dimensions_fixed": ["talents", "apl"],
               "legal_certification": "PARTIAL_GEAR_LEGALITY_SOURCE_BOUNDED",
               "cold_search": False, "independent_holdout": False, "blocker": None,
               "blocker_category": None, "native_attempts": 0, "native_failures": []}
        if reference is None:
            row["blocker"] = inventory["blocker"]
            row["blocker_category"] = "NO_NATIVE_REQUEST"
        elif profile == "priest/discipline":
            row.update(status="BLOCKED_SPEC_IDENTITY", blocker="Smite fixture not verified Discipline",
                       blocker_category="SPEC_IDENTITY")
        elif profile in HEAL or profile in TANK:
            row.update(status="BLOCKED_OBJECTIVE", blocker="HPS/TPS extractor not verified; do not score as DPS",
                       blocker_category="OBJECTIVE_MISMATCH")
        else:
            same_class = [req for inv, req in records if req is not None
                          and inv["profile_id"].split("/", 1)[0] == cls]
            try:
                adapter = NativeGearAdapter(cls, reference, same_class, index)
                row["source_bounded_mutable_positions"] = list(adapter.mutable_indices)
                attempted_swaps: set[tuple[int, int]] = set()
                rowdir = outdir / "profiles" / profile.replace("/", "__")
                rowdir.mkdir(parents=True, exist_ok=True)
                for attempt in range(max_attempts):
                    try:
                        candidate, swap = adapter.mutate_one(
                            random.Random(seed + idx + attempt),
                            excluded_swaps=attempted_swaps,
                        )
                    except GearRejected as exc:
                        if not row["native_failures"]:
                            row.update(status="BLOCKED_GEAR_POOL", blocker=str(exc),
                                       blocker_category="SOURCE_BOUNDED_GEAR_POOL_EXHAUSTED")
                        break
                    attempted_swaps.add((swap["source_slot_index"], swap["to_id"]))
                    assert player(candidate)["class"] == player(reference)["class"]
                    assert player(candidate)["talentsString"] == player(reference)["talentsString"]
                    assert player(candidate)["rotation"] == player(reference)["rotation"]
                    req_path = rowdir / f"gear_attempt_{attempt:03}.request.json"
                    req_path.write_text(json.dumps(candidate, indent=2) + "\n")
                    request_rel = str(req_path.relative_to(outdir))
                    request_sha = digest(req_path)
                    row["native_attempts"] += 1
                    start = time.monotonic()
                    try:
                        score, _output, native_s, payload_sha = run(
                            binary, candidate, iterations, seed + idx + attempt,
                            "balanced", start + 30.0)
                        if not math.isfinite(score):
                            raise ValueError("Non-finite native Rust DPS")
                    except Exception as exc:
                        failure = {
                            "request_path": request_rel,
                            "request_sha256": request_sha,
                            "swap": swap,
                            "category": classify_native_failure(str(exc)),
                            "reason": str(exc)[-1100:],
                        }
                        if failure["category"] == "RUST_BALANCED_RNG_PROBABILITY":
                            # Paired native replay uses the SAME request and seed.
                            # Scores here are diagnostic, never paid/promotable.
                            failure["rng_replay"] = replay_rng_modes(
                                binary, candidate, iterations=iterations,
                                seed=seed + idx + attempt,
                            )
                            # Preserve full Rust panic stack as an artifact;
                            # diagnostic runs are excluded from native_paid.
                            trace_path = rowdir / f"gear_attempt_{attempt:03}.balanced_backtrace.stderr.txt"
                            try:
                                trace = capture_rng_backtrace(
                                    binary, candidate, iterations=iterations,
                                    seed=seed + idx + attempt, stderr_path=trace_path)
                                trace["stderr_path"] = str(trace_path.relative_to(outdir))
                                failure["rng_backtrace"] = trace
                            except (OSError, subprocess.SubprocessError) as diagnostic_exc:
                                failure["rng_backtrace"] = {
                                    "accounting": "DIAGNOSTIC_NOT_PAID",
                                    "status": "CAPTURE_FAILED",
                                    "reason": str(diagnostic_exc)[-500:],
                                }
                        row["native_failures"].append(failure)
                        continue
                    row.update(status="NATIVE_GEAR_PROBE_PAID_PARTIAL_LEGALITY",
                               native_paid=1, native_score=score, native_duration_s=native_s,
                               native_payload_sha256=payload_sha,
                               request_path=request_rel, request_sha256=request_sha,
                               swap=swap,
                               blocker="Full equip legality, talent freedom and cold JOINT search not yet verified",
                               blocker_category="PARTIAL_GEAR_LEGALITY")
                    break
                if row["native_paid"] == 0 and row["native_failures"]:
                    first = row["native_failures"][0]
                    row.update(status="BLOCKED_NATIVE_GEAR_EVALUATION",
                               request_path=first["request_path"],
                               request_sha256=first["request_sha256"],
                               blocker=f"{len(row['native_failures'])} distinct native failures; first: {first['reason']}",
                               blocker_category=first["category"])
            except GearRejected as exc:
                row.update(status="BLOCKED_GEAR_POOL", blocker=str(exc),
                           blocker_category="SOURCE_BOUNDED_GEAR_POOL_EXHAUSTED")
        rows.append(row)
    result = {"scope": "NATIVE_GEAR_MUTATION_DIAGNOSTIC_NOT_JOINT_NOT_P7_PASS",
              "engine_binary_sha256": digest(binary),
              "engine_items_sha256": digest(engine_src / "data/items.jsonl"),
              "engine_enchants_sha256": digest(engine_src / "data/enchants.jsonl"),
              "seed": seed, "iterations": iterations, "rows": rows}
    (outdir / "gear_probe.json").write_text(json.dumps(result, indent=2) + "\n")
    groups = group_gear_gaps(rows)
    (outdir / "gear_gaps.json").write_text(json.dumps(
        {"scope": "NATIVE_GEAR_PROBE_ROOT_CAUSE_GAPS", "groups": list(groups.values())},
        indent=2) + "\n")

    counts = Counter(r["status"] for r in rows)
    classes = sorted({r["profile_id"].split("/")[0] for r in rows
                      if r["native_paid"] > 0})
    (outdir / "gear_probe.md").write_text(
        "# Native Rust same-class gear mutation diagnostic\n\n"
        "Not a cold search, full gear legality certification, JOINT, or P7 PASS.\n\n"
        f"Paid real native classes: {classes}; statuses: {dict(counts)}\n\n"
        "| Profile | Paid | Native DPS | Status | Exact blocker |\n|---|---:|---:|---|---|\n" +
        "\n".join(f"| {r['profile_id']} | {r['native_paid']} | {r['native_score']} | "
                  f"{r['status']} | {str(r['blocker']).replace('|', '/')[:130]} |" for r in rows) + "\n")
    print(json.dumps({"rows": len(rows), "paid_classes": classes,
                      "statuses": dict(counts)}, indent=2))
    if len(rows) != 28:
        raise AssertionError("Gear probe must preserve 28 canonical rows")
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine-src", required=True, type=Path)
    ap.add_argument("--binary", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--seed", type=int, default=2710)
    ap.add_argument("--iterations", type=int, default=10)
    ap.add_argument("--max-gear-attempts", type=int, default=3)
    a = ap.parse_args()
    if a.iterations < 1 or a.max_gear_attempts < 1 or not a.binary.is_file():
        ap.error("Need a real native binary and positive iterations")
    probe_all(engine_src=a.engine_src, binary=a.binary,
              outdir=a.out, seed=a.seed, iterations=a.iterations,
              max_attempts=a.max_gear_attempts)


if __name__ == "__main__":
    main()
