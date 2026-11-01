#!/usr/bin/env python3
"""Cold native Rust gear-only L60 diagnostic; NEVER JOINT or PROCESS P7 PASS.

Gear pools are restricted to observed same-class, same-position source fixtures
and the pinned Rust item database. Talent/APL and all non-gear request fields
remain frozen. Native paid scores are produced only by the actual Rust binary.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import random
import subprocess
import time
from collections import Counter
from pathlib import Path

from native_gear_adapter import GearRejected, NativeGearAdapter
from native_gear_probe import classify_native_failure
from native_l60_matrix import (
    HEAL, TANK, ROOT, create_inventory, digest, fingerprint,
    load_native_item_index, player,
)
from native_matrix import search_native
from p73_talent_search_v2 import run


def cold_gear_kernel(adapter, reference, *, evaluate, seconds, iterations,
                     seed, clock=time.monotonic):
    """Pure adapter-driven search, injectable evaluator for unit tests only.

    No source winner or reference score is seeded into the search kernel.
    Every candidate is a distinct source-bounded gear mutation; talent and
    APL remain fixed. A mock evaluator is never a published native result.
    """
    paid_trace = []
    native_failures = []  # bounded exact Rust inputs; NEVER counted as paid

    def effective_native_request(candidate, iterations, seed):
        # p73_talent_search_v2.run applies exactly these two overrides.
        # Preserve the actual scored input, not only the optimizer proposal.
        payload = copy.deepcopy(candidate)
        payload["simOptions"]["iterations"] = iterations
        payload["simOptions"]["randomSeed"] = str(seed)
        return payload

    def propose(rng):
        candidate, _audit = adapter.mutate_one(rng)
        return candidate

    def mutate(candidate, rng):
        try:
            candidate, _audit = adapter.mutate_from(candidate, rng)
        except GearRejected:
            return propose(rng)
        return candidate

    def legal(candidate):
        try:
            adapter.validate(candidate)
            return player(candidate)["equipment"]["items"] != player(reference)["equipment"]["items"]
        except (GearRejected, KeyError, TypeError, IndexError):
            return False

    def paid(candidate, *, iterations, seed, rng_mode):
        try:
            value, payload_sha = evaluate(
                candidate, iterations=iterations, seed=seed, rng_mode=rng_mode
            )
            value = float(value)
            if not math.isfinite(value):
                raise ValueError("NONFINITE_NATIVE_GEAR_METRIC")
        except (TimeoutError, subprocess.TimeoutExpired):
            raise  # strict budget exhaustion is not an engine failure
        except Exception as exc:
            if len(native_failures) < 3:
                # p73_talent_search_v2.run rewrites these two fields before
                # executing Rust. Store that EXACT effective native request,
                # not the unmodified optimizer proposal.
                payload = effective_native_request(candidate, iterations, seed)
                native_failures.append({
                    "candidate": payload,
                    "candidate_sha256": fingerprint(payload),
                    "category": classify_native_failure(str(exc)),
                    "error": str(exc)[-1100:],
                    "iterations": iterations,
                    "seed": seed,
                    "rng_mode": rng_mode,
                    "accounting": "FAILED_NATIVE_NOT_PAID",
                })
            raise
        paid_trace.append({
            "candidate_sha256": fingerprint(candidate),
            "effective_request_sha256": fingerprint(
                effective_native_request(candidate, iterations, seed)),
            "native_payload_sha256": payload_sha,
            "score": value,
            "rng_mode": rng_mode,
        })
        return value

    result = search_native(
        profile_id=adapter.class_key + "/gear-only",
        reference=reference, propose=propose, mutate=mutate, legal=legal,
        evaluate=paid, seconds=seconds, iterations=iterations,
        seed=seed, clock=clock,
    )
    assert result["paid_candidates"] == len(paid_trace)
    result["native_failures"] = native_failures
    # search_native keeps the first highest-scoring paid candidate. Preserve
    # its exact Rust seed/iteration overrides for independent replay.
    result["best_native_request"] = None
    result["best_native_payload_sha256"] = None
    if result["best_candidate"] is not None:
        winning_trace = max(paid_trace, key=lambda entry: entry["score"])
        result["best_native_request"] = effective_native_request(
            result["best_candidate"], iterations, seed)
        result["best_native_payload_sha256"] = winning_trace["native_payload_sha256"]
        assert winning_trace["score"] == result["best_score"]
        assert winning_trace["candidate_sha256"] == fingerprint(result["best_candidate"])
    return result, paid_trace


def sweep(*, engine_src: Path, binary: Path, outdir: Path,
          seconds: float, iterations: int, seed: int):
    if not binary.is_file() or not (engine_src / "data/items.jsonl").is_file():
        raise ValueError("A real native Rust binary and pinned items DB are required")
    if seconds <= 0 or iterations < 1:
        raise ValueError("Positive per-profile budget and iterations required")
    records = create_inventory(ROOT / "config/validation/checkpoint_148.json", engine_src)
    items = load_native_item_index(engine_src)
    outdir.mkdir(parents=True, exist_ok=True)
    rows = []
    for idx, (inventory, reference) in enumerate(records):
        profile = inventory["profile_id"]
        cls = profile.split("/", 1)[0]
        row = {
            "profile_id": profile, "source_type": inventory["source_type"],
            "source_sha256": inventory["source_sha256"],
            "status": "BLOCKED_NO_NATIVE_REQUEST", "blocker": inventory["blocker"],
            "native_paid": 0, "baseline": None, "best": None,
            "dimensions_searched": ["gear"], "dimensions_fixed": ["talents", "apl"],
            "legal_certification": "PARTIAL_GEAR_LEGALITY_SOURCE_BOUNDED",
            "cold_search": True, "promotable": False, "independent_holdout": False,
            "native_errors": 0, "elapsed_search_s": 0.0,
            "native_failures": [], "native_error_categories": {},
        }
        if reference is None:
            pass
        elif profile == "priest/discipline":
            row.update(status="BLOCKED_SPEC_IDENTITY",
                       blocker="Smite source is not verified Discipline")
        elif profile in HEAL or profile in TANK:
            row.update(status="BLOCKED_OBJECTIVE",
                       blocker="Native HPS/TPS objective not verified; DPS is not comparable")
        else:
            same_class = [req for inv, req in records if req is not None
                          and inv["profile_id"].split("/", 1)[0] == cls]
            rowdir = outdir / "profiles" / profile.replace("/", "__")
            rowdir.mkdir(parents=True, exist_ok=True)
            try:
                adapter = NativeGearAdapter(cls, reference, same_class, items)
                row["mutable_positions"] = list(adapter.mutable_indices)
                if not adapter.mutable_indices:
                    raise GearRejected("NO_SOURCE_BOUNDED_ALTERNATIVE",
                                       "No verified same-class fixture gear swap")
                (rowdir / "source_request.json").write_text(json.dumps(reference, indent=2) + "\n")
                base_seed = int(reference["simOptions"].get("randomSeed", "42"))
                baseline, _output, native_s, payload_sha = run(
                    binary, reference, iterations, base_seed, "stochastic",
                    time.monotonic() + 30.0)
                if not math.isfinite(baseline):
                    raise ValueError("NONFINITE_NATIVE_BASELINE")
                row.update(baseline=baseline, baseline_duration_s=native_s,
                           baseline_payload_sha256=payload_sha,
                           baseline_rng_mode="stochastic",
                           search_rng_mode="balanced",
                           metric_comparison="NOT_COMPARABLE_DIFFERENT_RNG_MODE")
                deadline = time.monotonic() + seconds

                def native_eval(candidate, *, iterations, seed, rng_mode):
                    score, _output, _elapsed, payload = run(
                        binary, candidate, iterations, seed, rng_mode, deadline)
                    return score, payload

                result, trace = cold_gear_kernel(
                    adapter, reference, evaluate=native_eval,
                    seconds=seconds, iterations=iterations, seed=seed + idx)
                failure_summaries = []
                for failure_index, failure in enumerate(result["native_failures"]):
                    payload = failure["candidate"]
                    path = rowdir / f"native_failure_{failure_index:03}.request.json"
                    path.write_text(json.dumps(payload, indent=2) + "\n")
                    summary = {k: v for k, v in failure.items() if k != "candidate"}
                    summary["request_path"] = str(path.relative_to(outdir))
                    summary["request_sha256"] = digest(path)
                    failure_summaries.append(summary)
                row["native_failures"] = failure_summaries
                row["native_error_categories"] = dict(Counter(
                    f["category"] for f in failure_summaries))
                row.update(native_paid=result["paid_candidates"],
                           native_errors=result["engine_errors"],
                           rejected_legal=result["legal_rejections"],
                           elapsed_search_s=result["elapsed_s"],
                           best=result["best_score"],
                           native_status=result["status"])
                (rowdir / "paid_trace.json").write_text(json.dumps(trace, indent=2) + "\n")
                if result["best_candidate"] is not None:
                    best_path = rowdir / "best_request.json"
                    best_path.write_text(json.dumps(result["best_candidate"], indent=2) + "\n")
                    row["best_request_sha256"] = digest(best_path)
                    row["best_request_path"] = str(best_path.relative_to(outdir))
                    scored = result["best_native_request"]
                    scored_sha = fingerprint(scored)
                    if scored_sha != result["best_native_payload_sha256"]:
                        raise AssertionError("PAID_NATIVE_PAYLOAD_SHA_MISMATCH")
                    scored_path = rowdir / "best_scored_native_request.json"
                    scored_path.write_text(json.dumps(scored, indent=2) + "\n")
                    row["best_scored_native_request_path"] = str(
                        scored_path.relative_to(outdir))
                    row["best_scored_native_request_file_sha256"] = digest(scored_path)
                    row["best_native_payload_sha256"] = scored_sha
                    row["best_native_rng_mode"] = "balanced"
                if result["status"] == "RAN":
                    row.update(status="NATIVE_GEAR_COLD_PAID_PARTIAL_LEGALITY",
                               blocker="Talent/APL fixed; full gear restrictions unverified")
                elif result["status"] == "RAN_WITH_ENGINE_ERRORS":
                    row.update(status="NATIVE_GEAR_COLD_ERRORS_PARTIAL_LEGALITY",
                               blocker="Native candidate errors and incomplete equip legality")
                else:
                    row.update(status=result["status"], blocker=result["status"])
            except GearRejected as exc:
                row.update(status="BLOCKED_GEAR_POOL", blocker=str(exc))
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                row.update(status="BLOCKED_NATIVE_BASELINE",
                           blocker=str(exc)[-900:])
        rows.append(row)
    if len(rows) != 28 or len({r["profile_id"] for r in rows}) != 28:
        raise AssertionError("Must report all 28 canonical profiles exactly once")
    report = {
        "scope": "NATIVE_COLD_GEAR_ONLY_PARTIAL_LEGALITY_NOT_JOINT_NOT_P7_PASS",
        "binary_sha256": digest(binary),
        "items_sha256": digest(engine_src / "data/items.jsonl"),
        "enchants_sha256": digest(engine_src / "data/enchants.jsonl"),
        "spells_sha256": digest(engine_src / "data/spells.jsonl"),
        "budget_per_profile_s": seconds, "iterations": iterations, "seed": seed,
        "rows": rows,
    }
    (outdir / "gear_cold.json").write_text(json.dumps(report, indent=2) + "\n")
    counts = dict(Counter(row["status"] for row in rows))
    lines = [
        "# Native Rust cold gear-only L60 sweep", "",
        "**Partial legality; NOT JOINT, not 30/300s promotion, not P7 PASS.**", "",
        "| Profile | Paid | Baseline (stochastic) | Best (balanced) | Status | Blocker |",
        "|---|---:|---:|---:|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['profile_id']} | {row['native_paid']} | {row['baseline']} | "
            f"{row['best']} | {row['status']} | "
            f"{str(row['blocker']).replace('|', '/')[:100]} |"
        )
    lines.extend(["", "Status counts: " + str(counts)])
    (outdir / "gear_cold.md").write_text("\n".join(lines) + "\n")
    gaps = [{
        "profile_id": row["profile_id"], "category": row["status"],
        "reason": row["blocker"],
        "native_error_categories": row.get("native_error_categories", {}),
        "native_failures": row.get("native_failures", []),
        "next_fix": ("Verify class talent tree and full equip rules"
                     if row["native_paid"] else "Resolve the recorded source/objective/native blocker"),
    } for row in rows if row["blocker"]]
    (outdir / "gaps.json").write_text(json.dumps(gaps, indent=2) + "\n")
    print(json.dumps({"rows": len(rows), "paid_classes": sorted({
        row["profile_id"].split("/")[0] for row in rows if row["native_paid"] > 0
    }), "statuses": counts}, indent=2))
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine-src", required=True, type=Path)
    ap.add_argument("--binary", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--budget", type=float, default=5.0)
    ap.add_argument("--iterations", type=int, default=10)
    ap.add_argument("--seed", type=int, default=2710)
    a = ap.parse_args()
    sweep(engine_src=a.engine_src, binary=a.binary, outdir=a.out,
          seconds=a.budget, iterations=a.iterations, seed=a.seed)


if __name__ == "__main__":
    main()
