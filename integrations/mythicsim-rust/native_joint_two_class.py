#!/usr/bin/env python3
"""Source-bounded two-class REAL Rust JOINT smoke using the shared gsim search.

This is an integration proof, not a PROCESS P7.5 PASS: talent choices are
verified *whole 51-point source builds*, NOT an exhaustive per-rank tree;
gear options are source-observed native DB items, NOT full equip-law parity.
The class-neutral native_matrix.search_native remains the only search loop.
No mocked scorer is permitted here.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import random
import subprocess
import time
from pathlib import Path

from apl_mutation import mutate_apl
from native_gear_adapter import GearRejected, NativeGearAdapter
from native_joint_composition import CandidateAxis, JointCandidateAdapter, search_joint
from native_l60_matrix import (
    ROOT, create_inventory, digest, fingerprint, legal_apl_only_request,
    load_native_item_index, player,
)
from p73_talent_search_v2 import run
from native_source_donors import load_source_donor_fixtures


def _write_native_failure(outdir: Path, request_sha256: str,
                          effective_request: dict, exc: Exception) -> dict:
    """Persist failed request plus any native response without inventing a score."""
    request_path = outdir / ("failed_" + request_sha256 + ".json")
    request_path.write_text(json.dumps(effective_request, indent=2) + "\n")
    record = {
        "effective_request_sha256": request_sha256,
        "error": str(exc)[-1200:],
    }
    raw = getattr(exc, "raw_response", None)
    if isinstance(raw, dict):
        response_path = outdir / ("failed_" + request_sha256 + ".response.json")
        response_path.write_text(json.dumps(raw, indent=2) + "\n")
        record["raw_response_sha256"] = fingerprint(raw)
        record["response_file"] = response_path.name
        elapsed = getattr(exc, "elapsed_s", None)
        if isinstance(elapsed, (int, float)) and math.isfinite(float(elapsed)):
            record["native_duration_s"] = float(elapsed)
    return record


def talent_points(talents: str) -> int:
    """Count points in source-native two- or three-tree encodings.

    The pinned Rust fixtures include two-tree 51-point strings (Assassination
    Rogue and Holy Priest). Preserve the exact source bytes for native scoring:
    accepting their encoding does NOT synthesize a missing tree or certify
    per-rank talent legality.
    """
    if not isinstance(talents, str) or talents.count("-") not in (1, 2):
        raise ValueError("Not a two- or three-tree source talent allocation")
    trees = talents.split("-")
    if any(any(c not in "0123456789" for c in t) for t in trees):
        raise ValueError("Invalid talent encoding")
    return sum(int(c) for t in trees for c in t)


def _is_full_51_source_build(talents: object) -> bool:
    try:
        return talent_points(talents) == 51
    except (TypeError, ValueError):
        return False


def native_payload(candidate: dict, iterations: int, seed: int) -> dict:
    payload = copy.deepcopy(candidate)
    payload["simOptions"]["iterations"] = iterations
    payload["simOptions"]["randomSeed"] = str(seed)
    return payload


def native_score_request(
    binary: Path,
    candidate: dict,
    iterations: int,
    seed: int,
    rng_mode: str,
    deadline: float,
    *,
    runner=run,
) -> tuple[dict, dict]:
    """Score one exact request with an explicit optimizer RNG mode.

    This joint-search lane is selection, not holdout: every baseline,
    candidate and exact replay must use the typed balanced backend. Stochastic
    evaluation is reserved for a separate frozen finalist holdout.
    """
    if rng_mode != "balanced":
        raise ValueError("JOINT_OPTIMIZER_REQUIRES_EXPLICIT_BALANCED_RNG")
    effective = native_payload(candidate, iterations, seed)
    expected_sha = fingerprint(effective)
    score, raw, elapsed, scored_sha = runner(
        binary, candidate, iterations, seed, rng_mode, deadline
    )
    if scored_sha != expected_sha:
        raise RuntimeError("Native payload/score provenance mismatch")
    if not math.isfinite(float(score)):
        raise RuntimeError("Native evaluator returned a non-finite score")
    return {
        "effective_request_sha256": expected_sha,
        "score": float(score),
        "rng_mode": rng_mode,
        "iterations": iterations,
        "seed": seed,
        "native_duration_s": elapsed,
        "raw_response_sha256": fingerprint(raw),
    }, raw


def source_bounded_adapter(
    class_key: str, reference: dict, same_class: list[dict],
    items: dict[int, dict], *, donor_fixtures: list[dict] | None = None,
) -> tuple[JointCandidateAdapter, dict]:
    """Use exact pinned same-class source requests; the scheduler is unchanged."""
    original = player(reference)
    extra_same_class = [
        fixture for fixture in (donor_fixtures or [])
        if fixture.get("class_name") == original.get("class")
        and isinstance(fixture.get("request"), dict)
    ]
    donor_requests = [fixture["request"] for fixture in extra_same_class]
    source_requests = same_class + donor_requests
    gear = NativeGearAdapter(class_key, reference, source_requests, items)
    if not gear.mutable_indices:
        raise ValueError("BLOCKED_GEAR_POOL: no source-bounded legal alternate item")

    base_gear = copy.deepcopy(original["equipment"]["items"])
    base_apl = copy.deepcopy(original["rotation"]["priorityList"])
    source_talents = set()
    talents = set()
    for request in source_requests:
        try:
            source_player = player(request)
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        if source_player.get("class") != original["class"]:
            continue
        source_talent = source_player.get("talentsString")
        if isinstance(source_talent, str):
            source_talents.add(source_talent)
        if _is_full_51_source_build(source_talent):
            talents.add(source_talent)
    talents = sorted(talents)
    if original["talentsString"] not in source_talents or len(talents) < 2:
        raise ValueError(
            "BLOCKED_TALENTS: need a source-observed baseline and two "
            "independent full 51-point same-class source builds"
        )
    alternate = [t for t in talents if t != original["talentsString"]]

    gear_donor_fixtures_scanned = [
        {
            "source_path": fixture["source_path"],
            "source_sha256": fixture["source_sha256"],
            "item_count": fixture["item_count"],
        }
        for fixture in extra_same_class
        if fixture.get("item_count") == len(base_gear)
    ]
    talent_donor_fixtures = [
        {
            "source_path": fixture["source_path"],
            "source_sha256": fixture["source_sha256"],
            "talents_sha256": fingerprint(
                player(fixture["request"]).get("talentsString")
            ),
        }
        for fixture in extra_same_class
        if _is_full_51_source_build(
            player(fixture["request"]).get("talentsString")
        )
    ]

    def make_gear(rng):
        request, _audit = gear.mutate_one(rng)
        return copy.deepcopy(player(request)["equipment"]["items"])

    def mutate_gear(current, rng):
        request = copy.deepcopy(reference)
        player(request)["equipment"]["items"] = copy.deepcopy(current)
        try:
            updated, _audit = gear.mutate_from(request, rng)
        except GearRejected:
            return make_gear(rng)
        return copy.deepcopy(player(updated)["equipment"]["items"])

    def gear_legal(value):
        request = copy.deepcopy(reference)
        player(request)["equipment"]["items"] = copy.deepcopy(value)
        try:
            gear.validate(request)
            return True
        except (GearRejected, KeyError, ValueError, TypeError):
            return False

    def cold_talent(rng):
        return rng.choice(alternate)

    def mutate_talent(current, rng):
        choices = [t for t in talents if t != current]
        return rng.choice(choices)

    def talent_legal(value):
        # The exact source reference is a legal starting anchor even when it
        # spends fewer than 51 points. Every mutated/cold talent candidate
        # must still be one of the pinned full 51-point source builds.
        return (value == original["talentsString"]
                or (value in talents and _is_full_51_source_build(value)))

    def cold_apl(rng):
        for _ in range(8):
            actions = mutate_apl(None, base_apl, rng, cold=True)
            if actions != base_apl:
                return actions
        raise ValueError("BLOCKED_APL: no different source-corpus action generated")

    def mutate_apl_axis(current, rng):
        return mutate_apl(current, base_apl, rng)

    def apl_legal(value):
        request = copy.deepcopy(reference)
        player(request)["rotation"]["priorityList"] = copy.deepcopy(value)
        return legal_apl_only_request(reference, request)

    def joint_legal(candidate):
        # Cross-axis source guard: separately validate the gear *as used* in
        # this candidate. Native scoring remains necessary for combat semantics.
        return (player(candidate)["class"] == original["class"]
                and gear_legal(player(candidate)["equipment"]["items"])
                and talent_legal(player(candidate)["talentsString"])
                and apl_legal(player(candidate)["rotation"]["priorityList"]))

    result = JointCandidateAdapter(
        reference,
        gear=CandidateAxis(make_gear, mutate_gear, gear_legal),
        talents=CandidateAxis(cold_talent, mutate_talent, talent_legal),
        apl=CandidateAxis(cold_apl, mutate_apl_axis, apl_legal),
        joint_legal=joint_legal,
    )
    return result, {
        "gear_mutable_slots": list(gear.mutable_indices),
        "talent_builds": talents,
        "source_donor_fixture_count": len(extra_same_class),
        "gear_donor_fixtures_scanned": gear_donor_fixtures_scanned,
        "talent_donor_fixtures": talent_donor_fixtures,
        "talent_validation": "SOURCE_OBSERVED_BASELINE_PLUS_51_POINT_WHOLE_BUILDS_NOT_RANKWISE",
        "gear_validation": "PINNED_SAME_CLASS_SLOT_NATIVE_DB_PARTIAL_EQUIP_RULES",
        "apl_validation": "SOURCE_CAST_IDENTITIES_AND_OPAQUE_ACTION_CORPUS",
    }


def axis_delta(reference: dict, candidate: dict) -> dict[str, bool]:
    r, p = player(reference), player(candidate)
    return {
        "gear": p["equipment"]["items"] != r["equipment"]["items"],
        "talents": p["talentsString"] != r["talentsString"],
        "apl": p["rotation"]["priorityList"] != r["rotation"]["priorityList"],
    }


def execute(profile_id: str, inventory: list, native_items: dict, *,
            binary: Path, engine_src: Path, seconds: float, iterations: int,
            seed: int, outdir: Path,
            donor_fixtures: list[dict] | None = None) -> dict:
    row = {
        "profile_id": profile_id, "status": "BLOCKED_SOURCE",
        "dimensions_requested": ["gear", "talents", "apl"],
        "native_paid": 0, "baseline_paid": 0, "native_paid_total": 0,
        "baseline_balanced_score": None,
        "baseline_effective_request_sha256": None,
        "baseline_native_duration_s": None,
        "baseline_rng_mode": None,
        "baseline_iterations": None,
        "baseline_seed": None,
        "baseline_response_sha256": None,
        "three_axis_paid": 0, "process_gate_pass": False,
        "source_scope": "SMOKE_FIXTURE_OR_PINNED_REFERENCE",
        "full_source_legality_certified": False,
        "live_gsim_2d_rust_causality": False,
    }
    source = next(((inv, req) for inv, req in inventory
                   if inv["profile_id"] == profile_id), None)
    if source is None:
        row["blocker"] = "Profile absent from canonical inventory"
        return row
    inv, reference = source
    row["source_sha256"] = inv["source_sha256"]
    row["source_type"] = inv["source_type"]
    row["source_path"] = inv["source_path"]
    if reference is None:
        row["blocker"] = inv["blocker"]
        return row

    cls = profile_id.split("/", 1)[0]
    same_class = [req for entry, req in inventory if req is not None
                  and entry["profile_id"].split("/", 1)[0] == cls]
    try:
        adapter, scope = source_bounded_adapter(
            cls, reference, same_class, native_items,
            donor_fixtures=donor_fixtures,
        )
    except Exception as exc:
        row["status"] = "BLOCKED_SOURCE_LEGALITY"
        row["blocker"] = str(exc)[:500]
        return row
    row.update(scope)
    outdir.mkdir(parents=True, exist_ok=True)
    paid_dir = outdir / "paid"
    paid_dir.mkdir(exist_ok=True)
    (outdir / "source_request.json").write_text(json.dumps(reference, indent=2) + "\n")

    paid = []
    native_failures = []
    baseline_effective = native_payload(reference, iterations, seed)
    try:
        baseline_record, baseline_raw = native_score_request(
            binary, reference, iterations, seed, "balanced",
            time.monotonic() + 30.0,
        )
    except Exception as exc:
        row["status"] = "BLOCKED_NATIVE_BASELINE"
        row["blocker"] = "Balanced native reference baseline failed: " + str(exc)[-700:]
        failure = _write_native_failure(
            outdir, fingerprint(baseline_effective), baseline_effective, exc
        )
        row["native_failures"] = [{"stage": "baseline", **failure}]
        return row
    row["baseline_paid"] = 1
    row["baseline_balanced_score"] = baseline_record["score"]
    row["baseline_effective_request_sha256"] = baseline_record["effective_request_sha256"]
    row["baseline_native_duration_s"] = baseline_record["native_duration_s"]
    row["baseline_rng_mode"] = baseline_record["rng_mode"]
    row["baseline_iterations"] = baseline_record["iterations"]
    row["baseline_seed"] = baseline_record["seed"]
    row["baseline_response_sha256"] = baseline_record["raw_response_sha256"]
    (outdir / "baseline_effective_request.json").write_text(
        json.dumps(baseline_effective, indent=2) + "\n"
    )
    (outdir / "baseline_response.json").write_text(
        json.dumps(baseline_raw, indent=2) + "\n"
    )
    deadline = time.monotonic() + seconds
    # One evaluator; no home-made DPS, Go scorer or fake score can enter report.
    def evaluate(candidate, *, iterations, seed, rng_mode):
        effective = native_payload(candidate, iterations, seed)
        key = fingerprint(effective)
        if not adapter.legal(candidate):
            raise ValueError("JOINT_LEGALITY_REJECTED_BEFORE_NATIVE")
        try:
            native_record, raw = native_score_request(
                binary, candidate, iterations, seed, rng_mode, deadline
            )
            score = native_record["score"]
            elapsed = native_record["native_duration_s"]
            scored_sha = native_record["effective_request_sha256"]
        except (TimeoutError, subprocess.TimeoutExpired):
            raise
        except Exception as exc:
            if len(native_failures) < 12:
                native_failures.append({
                    "stage": "candidate",
                    **_write_native_failure(outdir, key, effective, exc),
                })
            raise
        if key != scored_sha or not math.isfinite(score):
            raise RuntimeError("Native payload/score provenance mismatch")
        delta = axis_delta(reference, candidate)
        if not any(delta.values()):
            raise ValueError("Reference-identical search not counted as 3-axis discovery")
        (paid_dir / (key + ".json")).write_text(json.dumps(effective, indent=2) + "\n")
        (paid_dir / (key + ".response.json")).write_text(
            json.dumps(raw, indent=2) + "\n"
        )
        paid.append({
            "effective_request_sha256": key,
            "score": score, "rng_mode": rng_mode,
            "iterations": iterations, "seed": seed,
            "native_duration_s": elapsed,
            "raw_response_sha256": native_record["raw_response_sha256"],
            "delta_from_reference": delta,
            "item_ids": [x.get("id", 0) for x in player(candidate)["equipment"]["items"]],
            "talents": player(candidate)["talentsString"],
            "apl_sha256": fingerprint(player(candidate)["rotation"]["priorityList"]),
            "source_bounded_legality": True,
            "full_source_legality_certified": False,
        })
        return score

    result = search_joint(
        profile_id=profile_id, adapter=adapter, evaluate=evaluate,
        seconds=seconds, iterations=iterations, seed=seed)
    row["search_status"] = result["status"]
    row["native_paid"] = len(paid)
    row["native_paid_total"] = row["baseline_paid"] + row["native_paid"]
    row["paid_unique"] = result["paid_candidates"]
    row["native_errors"] = result["engine_errors"]
    row["legal_rejections"] = result["legal_rejections"]
    row["search_elapsed_s"] = result["elapsed_s"]
    row["three_axis_paid"] = sum(all(e["delta_from_reference"].values()) for e in paid)
    row["best_balanced_screen"] = result["best_score"]
    row["source_bounded_joint"] = row["three_axis_paid"] > 0
    row["status"] = (
        "SOURCE_BOUNDED_NATIVE_JOINT_PARTIAL_LEGALITY"
        if row["source_bounded_joint"] else "BLOCKED_NO_PAID_THREE_AXIS_JOINT"
    )
    row["blocker"] = None if row["source_bounded_joint"] else (
        "No legal source-bounded Rust paid candidate changed gear, talents, and APL")
    row["native_failures"] = native_failures

    (outdir / "paid_trace.json").write_text(json.dumps(paid, indent=2) + "\n")
    if result["best_candidate"] is not None:
        winner = native_payload(result["best_candidate"], iterations, seed)
        row["best_effective_request_sha256"] = fingerprint(winner)
        (outdir / "best_effective_request.json").write_text(json.dumps(winner, indent=2) + "\n")
        # Independent exact-byte native replay with the same seed and RNG mode.
        try:
            replay_record, replay_raw = native_score_request(
                binary, result["best_candidate"], iterations, seed,
                "balanced", time.monotonic() + 30.0,
            )
            replay = replay_record["score"]
            replay_sha = replay_record["effective_request_sha256"]
            row["replay_score"] = replay
            row["replay_rng_mode"] = replay_record["rng_mode"]
            row["replay_response_sha256"] = replay_record["raw_response_sha256"]
            row["replay_effective_sha256"] = replay_sha
            (outdir / "best_replay_response.json").write_text(
                json.dumps(replay_raw, indent=2) + "\n"
            )
            row["replay_matches"] = (
                replay_sha == row["best_effective_request_sha256"]
                and math.isclose(replay, row["best_balanced_screen"], rel_tol=1e-10))
        except Exception as exc:
            row["replay_matches"] = False
            row["replay_error"] = str(exc)[-800:]
        if not row["replay_matches"]:
            row["status"] = "BLOCKED_NATIVE_REPLAY_MISMATCH"
            row["blocker"] = "Frozen effective scorer payload did not reproduce"
    else:
        row["replay_matches"] = False

    (outdir / "report.json").write_text(json.dumps(row, indent=2) + "\n")
    return row


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--engine-src", type=Path, required=True)
    ap.add_argument("--binary", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--profile", action="append", required=True)
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--iterations", type=int, default=40)
    ap.add_argument("--seed", type=int, default=731)
    args = ap.parse_args()
    if not (0 < args.seconds <= 300) or not math.isfinite(args.seconds):
        ap.error("Finite 0 < seconds <= 300 required")
    if args.iterations < 1:
        ap.error("Positive iterations required")
    if len({x.split("/", 1)[0] for x in args.profile}) < 2:
        ap.error("Real native two-class proof requires two different classes")
    if not args.binary.is_file():
        ap.error("Real pinned native Rust binary missing")
    registry = ROOT / "config/validation/checkpoint_148.json"
    inventory = create_inventory(registry, args.engine_src)
    items = load_native_item_index(args.engine_src)
    donor_inventory = load_source_donor_fixtures(args.engine_src)
    donor_fixtures = donor_inventory["fixtures"]
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for idx, profile in enumerate(args.profile):
        outdir = args.out / profile.replace("/", "__")
        row = execute(
            profile, inventory, items,
            binary=args.binary, engine_src=args.engine_src,
            seconds=args.seconds, iterations=args.iterations,
            seed=args.seed + idx, outdir=outdir,
            donor_fixtures=donor_fixtures)
        rows.append(row)
        print(json.dumps({"profile":profile, "status":row["status"],
                          "paid":row["native_paid"],
                          "three_axis_paid":row["three_axis_paid"],
                          "source_donor_fixture_count":row.get("source_donor_fixture_count", 0),
                          "replay_matches":row.get("replay_matches")}), flush=True)
    (args.out / "joint_matrix.json").write_text(json.dumps(rows, indent=2) + "\n")
    # CI must fail if either class did NOT actually score and replay a
    # three-axis-mutated legal source-bounded candidate on the real Rust.
    if not all(r["status"] == "SOURCE_BOUNDED_NATIVE_JOINT_PARTIAL_LEGALITY"
               and r.get("replay_matches") and r["native_paid"] >= 1
               for r in rows):
        raise SystemExit("BLOCKED: No completed two-class Rust JOINT proof; see artifacts")


if __name__ == "__main__":
    main()
