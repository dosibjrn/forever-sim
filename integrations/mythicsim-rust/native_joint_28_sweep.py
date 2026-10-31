#!/usr/bin/env python3
"""28-row native Rust JOINT breadth using the ONE existing search_native kernel.

This runner reuses native_joint_two_class.execute; it does not introduce a new
optimizer or scorer. A whole-build donor talent and a source-bounded gear swap
are *partial* legality, not rank-wise 51-point or full equip certification.
Thus measured 5s rows cannot yet be promoted to 30s/300s or PROCESS P7 PASS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

from native_joint_two_class import execute
from native_l60_matrix import (
    HEAL, TANK, ROOT, create_inventory, load_native_item_index,
)

STAGES = (5, 30, 300)
SOURCE_GAP = "VERIFY_PER_RANK_TALENTS_AND_FULL_EQUIP_RULES"

def cold_stage_seed(base_seed: int, stage: int, profile_index: int) -> int:
    """Stable, independent 63-bit RNG stream per cold stage and profile.

    Stage 30/300 may inspect prior-stage eligibility but must never inherit
    its RNG trajectory or winner. Hashing a domain-separated tuple avoids
    accidental 5s-prefix reuse when all stages use the same CLI --seed.
    """
    if stage not in STAGES or profile_index < 0:
        raise ValueError("Invalid cold stage or profile index")
    key = f"native-l60-cold-v1:{base_seed}:{stage}:{profile_index}".encode("ascii")
    return (int.from_bytes(hashlib.sha256(key).digest()[:8], "big")
            & ((1 << 63) - 1)) or 1



def preflight(profile: str, source: dict, request: dict | None, stage: int,
              previous: dict | None = None, *,
              current_provenance: dict | None = None) -> tuple[str, str] | None:
    """Fail closed before any native invocation; stage promotion is not a score race."""
    if request is None:
        return ("BLOCKED_SOURCE", str(source.get("blocker") or "No exact source request"))
    if profile == "priest/discipline":
        return ("BLOCKED_SPEC_IDENTITY",
                "Smite Priest fixture does not establish a Discipline spec identity")
    if profile in HEAL or profile in TANK:
        unit = "HPS" if profile in HEAL else "TPS"
        return ("BLOCKED_OBJECTIVE", unit + " objective/extractor and compatible source not verified")
    if stage != 5:
        if previous is None:
            return ("BLOCKED_PRIOR_STAGE", "Missing completed prior-stage exact profile row")
        if not previous.get("full_source_legality_certified", False) or (
            previous.get("status") != "FULL_SOURCE_NATIVE_JOINT"
        ):
            return ("BLOCKED_FULL_SOURCE_LEGALITY",
                    "Previous stage is source-bounded, not rank-wise 51-point and full equip legal")
        expected_stage = {30: 5, 300: 30}[stage]
        if (previous.get("profile_id") != profile
                or previous.get("stage_seconds") != expected_stage):
            return ("BLOCKED_PRIOR_STAGE",
                    f"Expected the exact {expected_stage}s prior row for {profile}")
        if (not source.get("source_sha256")
                or previous.get("source_sha256") != source["source_sha256"]):
            return ("BLOCKED_SOURCE_PROVENANCE",
                    "Current native source SHA256 differs from the prior cold stage")
        # An absent current engine manifest is NOT permission to promote.
        if current_provenance is None:
            return ("BLOCKED_ENGINE_PROVENANCE",
                    "Current Rust binary and DB SHA256 manifest missing")
        # A prior 5s/30s result is not comparable after swapping the
        # Rust executable or ANY pinned native DB. Missing hashes fail
        # closed, even if the same fixture and spec name are supplied.
        db_names = ("items", "enchants", "spells")
        previous_db = previous.get("native_db_sha256")
        current_db = current_provenance.get("native_db_sha256")
        if (not previous.get("native_binary_sha256")
                or not current_provenance.get("native_binary_sha256")
                or previous["native_binary_sha256"]
                != current_provenance["native_binary_sha256"]
                or not isinstance(previous_db, dict)
                or not isinstance(current_db, dict)
                or any(not previous_db.get(name)
                       or not current_db.get(name)
                       or previous_db[name] != current_db[name]
                       for name in db_names)):
            return ("BLOCKED_ENGINE_PROVENANCE",
                    "Prior stage Rust binary or pinned native DB SHA256 "
                    "does not match current stage")
        if (previous.get("native_paid", 0) < 1
                or not previous.get("replay_matches")
                or previous.get("native_errors", 0) != 0):
            return ("BLOCKED_PRIOR_STAGE",
                    "Prior stage lacks paid, independently replayed error-free native evidence")
    return None


def build_matrix(inventory: list[tuple[dict, dict | None]], *, stage: int, run,
                 prior_rows: dict[str, dict] | None = None,
                 native_provenance: dict | None = None) -> list[dict]:
    """Preserve canonical 28 rows. Only injected production run() can pay Rust."""
    if stage not in STAGES:
        raise ValueError("Invalid stage")
    keys = [r["profile_id"] for r, _ in inventory]
    if len(keys) != 28 or len(set(keys)) != 28:
        raise ValueError("Expected 28 unique canonical L60 fixed profiles")
    rows = []
    for inv, request in inventory:
        profile = inv["profile_id"]
        previous = (prior_rows or {}).get(profile)
        block = preflight(profile, inv, request, stage, previous,
                          current_provenance=native_provenance)
        base = {
            "profile_id": profile,
            "stage_seconds": stage,
            "source_sha256": inv.get("source_sha256"),
            "source_path": inv.get("source_path"),
            "source_type": inv.get("source_type"),
            "source_talent_points": inv.get("source_talent_points"),
            "source_talent_points_missing_to_51": inv.get("source_talent_points_missing_to_51"),
            "source_talent_status": inv.get("source_talent_status"),
            "same_class_51_point_donor_builds": inv.get("same_class_51_point_donor_builds"),
            "source_talent_validation_scope": inv.get("source_talent_validation_scope"),
            "objective": "HPS" if profile in HEAL else ("TPS" if profile in TANK else "DPS"),
            "native_paid": 0,
            "three_axis_paid": 0,
            "full_source_legality_certified": False,
            "process_gate_pass": False,
            "promotable": False,
        }
        if block:
            base["status"], base["blocker"] = block
            base["promotion_blocker"] = block[0]
            rows.append(base)
            continue
        try:
            measured = run(profile)
        except (TimeoutError, subprocess.SubprocessError) as exc:
            # Native CLI startup/process/timeout failures are row-local, not
            # grounds to abandon the other 27 source fixtures. Never assign
            # paid candidates or a simulated score to a failed native call.
            # Other OSError failures (missing executable, artifact I/O) and
            # programming errors must fail CI, not masquerade as row blockers.
            base["status"] = "BLOCKED_NATIVE_EXECUTION"
            base["blocker"] = f"{type(exc).__name__}: {str(exc)[:500]}"
            base["promotion_blocker"] = "BLOCKED_NATIVE_EXECUTION"
            rows.append(base)
            continue
        if measured.get("process_gate_pass") or measured.get("full_source_legality_certified"):
            # This source-bounded adapter cannot certify full legal gear/talents.
            raise ValueError("Unverified full-source legality or P7 certification")
        # Never let an adapter's measured result replace canonical inventory
        # identity, stage or source provenance. Otherwise a valid Rust score
        # could be silently attributed to another fixture in the stage ledger.
        for key in ("profile_id", "stage_seconds", "source_sha256",
                    "source_path", "source_type", "objective",
                    "source_talent_points", "source_talent_points_missing_to_51",
                    "source_talent_status", "same_class_51_point_donor_builds",
                    "source_talent_validation_scope"):
            if key in measured and measured[key] != base[key]:
                raise ValueError(f"Measured native row changed canonical {key}: {profile}")
        # Scorer provenance is supplied by the orchestration layer, never
        # accepted as a free-form assertion from a per-spec adapter.
        for key in ("native_binary_sha256", "native_db_sha256"):
            if key in measured and (
                native_provenance is None or measured[key] != native_provenance.get(key)
            ):
                raise ValueError(f"Measured native row changed pinned {key}: {profile}")
        # A per-profile adapter is not the authority for certification.
        # The source-bounded runner can report only a bounded native JOINT
        # diagnostic or an explicit BLOCKED row. Reject forged RAN/full-legal
        # statuses even if their Boolean certification fields are false.
        status = measured.get("status")
        partial = "SOURCE_BOUNDED_NATIVE_JOINT_PARTIAL_LEGALITY"
        if status != partial and not (
            isinstance(status, str) and status.startswith("BLOCKED_")
        ):
            raise ValueError(f"Unsupported native result status for {profile}: {status!r}")
        paid = measured.get("native_paid", 0)
        three_axis = measured.get("three_axis_paid", 0)
        if (type(paid) is not int or type(three_axis) is not int
                or paid < 0 or three_axis < 0 or three_axis > paid):
            raise ValueError(f"Inconsistent paid native counts for {profile}")
        # An explicitly failed frozen Rust source baseline cannot be hidden
        # behind a paid/replayed JOINT search result. The production adapter
        # labels it BLOCKED_NATIVE_BASELINE; reject contradictory adapters.
        if status == partial and measured.get("baseline_status") not in (
            None, "RAN_NATIVE"
        ):
            raise ValueError(f"JOINT success with failed native source baseline: {profile}")
        if status == partial and measured.get("baseline_status") == "RAN_NATIVE" and (
            measured.get("baseline_native_paid") != 1
        ):
            raise ValueError(f"JOINT success without paid native source baseline: {profile}")
        if status == partial and (
            three_axis < 1 or measured.get("replay_matches") is not True
        ):
            raise ValueError(
                f"Source-bounded JOINT row lacks paid three-axis replay: {profile}"
            )
        base.update(measured)
        base["full_source_legality_certified"] = False
        base["process_gate_pass"] = False
        base["promotable"] = False
        base["promotion_blocker"] = (
            "BLOCKED_NATIVE_BASELINE" if status == "BLOCKED_NATIVE_BASELINE"
            else "BLOCKED_FULL_SOURCE_LEGALITY"
        )
        base["score_scope"] = "BALANCED_NATIVE_SCREEN_ONLY_NOT_HOLDOUT"
        rows.append(base)
    return rows


def _cause(row: dict) -> str:
    status = row["status"]
    if status == "SOURCE_BOUNDED_NATIVE_JOINT_PARTIAL_LEGALITY":
        return SOURCE_GAP
    if status == "BLOCKED_FULL_SOURCE_LEGALITY":
        return SOURCE_GAP
    if status.startswith("BLOCKED_OBJECTIVE"):
        return "VERIFY_NATIVE_HPS_TPS_OBJECTIVE"
    if status == "BLOCKED_SPEC_IDENTITY":
        return "VERIFY_DISCIPLINE_FIXTURE_IDENTITY"
    if status == "BLOCKED_SOURCE_LEGALITY":
        detail = str(row.get("blocker") or "")
        if detail.startswith("BLOCKED_GEAR_POOL:"):
            return "SOURCE_GEAR_POOL_MISSING"
        if detail.startswith("BLOCKED_TALENTS:"):
            return "SOURCE_TALENT_DONORS_MISSING"
        if "talent allocation" in detail or "talent encoding" in detail:
            return "SOURCE_TALENT_ENCODING_INVALID"
        return "INVESTIGATE_SOURCE_LEGALITY"
    if status == "BLOCKED_NO_PAID_THREE_AXIS_JOINT":
        return "VERIFY_SOURCE_GEAR_TALENTS_APL"
    if status == "BLOCKED_SOURCE":
        return "PROVIDE_EXACT_NATIVE_REQUEST"
    if status == "BLOCKED_PRIOR_STAGE":
        return "PROVIDE_PRIOR_STAGE_PAID_REPLAY"
    if status == "BLOCKED_SOURCE_PROVENANCE":
        return "RESTORE_EXACT_SOURCE_SHA_FOR_STAGE_CHAIN"
    if status == "BLOCKED_ENGINE_PROVENANCE":
        return "RESTORE_EXACT_NATIVE_ENGINE_AND_DB_SHA_FOR_STAGE_CHAIN"
    if status == "BLOCKED_NATIVE_BASELINE":
        return "REPLAY_FROZEN_NATIVE_SOURCE_BASELINE"
    if status == "BLOCKED_NATIVE_REPLAY_MISMATCH":
        return "REPRODUCE_EXACT_NATIVE_WINNER"
    if status == "BLOCKED_NATIVE_EXECUTION":
        return "REPLAY_FAILED_NATIVE_PROFILE_REQUEST"
    return "INVESTIGATE_" + status


def gap_summary(rows: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        cause = _cause(row)
        groups.setdefault(cause, []).append({
            "profile_id": row["profile_id"],
            "status": row["status"],
            "blocker": row.get("blocker") or row.get("promotion_blocker"),
            "source_talent_points": row.get("source_talent_points"),
            "source_talent_points_missing_to_51": row.get("source_talent_points_missing_to_51"),
            "source_talent_status": row.get("source_talent_status"),
            "same_class_51_point_donor_builds": row.get("same_class_51_point_donor_builds"),
            "source_talent_validation_scope": row.get("source_talent_validation_scope"),
        })
    return [{"cause": cause, "count": len(entries), "rows": entries}
            for cause, entries in sorted(groups.items(), key=lambda kv: -len(kv[1]))]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_report(out: Path, rows: list[dict], *, stage: int, binary: Path,
                engine_src: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    db = {name: _sha(engine_src / "data" / (name + ".jsonl"))
          for name in ("items", "enchants", "spells")}
    provenance = {"stage_seconds": stage, "binary_sha256": _sha(binary),
                  "native_db_sha256": db,
                  "source_scope": "PINNED_NATIVE_SOURCE_BOUNDED_PARTIAL_LEGALITY",
                  "process_p7_pass": False}
    for row in rows:
        row["native_binary_sha256"] = provenance["binary_sha256"]
        row["native_db_sha256"] = db
    (out / "matrix.json").write_text(json.dumps(rows, indent=2) + "\n")
    (out / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    (out / "gaps.json").write_text(json.dumps(gap_summary(rows), indent=2) + "\n")
    lines = ["# Native Rust L60 source-bounded JOINT " + str(stage) + "s",
             "", "Not full legal JOINT, not stochastic holdout, not PROCESS P7.",
             "", "| Profile | Status | Source points | Same-class 51pt donors | Paid | 3-axis paid | Native source baseline | Balanced screen | Delta vs baseline | Gap |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for r in rows:
        def esc(value):
            return str(value if value is not None else "—").replace("|", "\\|").replace("\n", " ")
        lines.append("| " + " | ".join(map(esc, (
            r["profile_id"], r["status"], r.get("source_talent_points"),
            r.get("same_class_51_point_donor_builds"),
            r["native_paid"], r["three_axis_paid"],
            r.get("baseline_balanced_native", r.get("baseline_status")),
            r.get("best_balanced_screen"), r.get("best_vs_source_baseline"),
            r.get("blocker") or r.get("promotion_blocker"),
        ))) + " |")
    (out / "matrix.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--engine-src", required=True, type=Path)
    ap.add_argument("--binary", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--stage", required=True, type=int, choices=STAGES)
    ap.add_argument("--prior", type=Path, help="Prior stage matrix.json for 30/300s")
    ap.add_argument("--iterations", type=int, default=40)
    ap.add_argument("--seed", type=int, default=731)
    args = ap.parse_args()
    if not args.binary.is_file():
        ap.error("Pinned native Rust executable missing")
    if args.iterations < 1:
        ap.error("iterations must be positive")
    if args.stage != 5 and args.prior is None:
        ap.error("30/300s requires prior stage matrix.json")
    inventory = create_inventory(ROOT / "config/validation/checkpoint_148.json",
                                 args.engine_src)
    native_items = load_native_item_index(args.engine_src)
    previous = ({r["profile_id"]: r for r in json.loads(args.prior.read_text())}
                if args.prior else None)

    def pay_native(profile: str) -> dict:
        index = next(i for i, (r, _) in enumerate(inventory)
                     if r["profile_id"] == profile)
        seed = cold_stage_seed(args.seed, args.stage, index)
        measured = execute(
            profile, inventory, native_items,
            binary=args.binary, engine_src=args.engine_src,
            seconds=float(args.stage), iterations=args.iterations,
            seed=seed,
            outdir=args.out / "profiles" / profile.replace("/", "__"),
        )
        # Persist the cold-start seed even for a native BLOCKED result.
        # This is provenance, never a substitute for paid Rust evidence.
        measured["cold_search_seed"] = seed
        return measured

    native_provenance = {
        "native_binary_sha256": _sha(args.binary),
        "native_db_sha256": {
            name: _sha(args.engine_src / "data" / (name + ".jsonl"))
            for name in ("items", "enchants", "spells")
        },
    }
    rows = build_matrix(inventory, stage=args.stage, run=pay_native,
                        prior_rows=previous, native_provenance=native_provenance)
    save_report(args.out, rows, stage=args.stage, binary=args.binary,
                engine_src=args.engine_src)
    print(json.dumps({"stage_seconds": args.stage, "profiles": len(rows),
                      "statuses": dict(Counter(r["status"] for r in rows)),
                      "native_paid": sum(r["native_paid"] for r in rows),
                      "three_axis_paid": sum(r["three_axis_paid"] for r in rows),
                      "promotable": sum(bool(r["promotable"]) for r in rows)},
                     sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
