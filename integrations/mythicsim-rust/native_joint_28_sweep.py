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
from collections import Counter
from pathlib import Path

from native_joint_two_class import execute
from native_l60_matrix import (
    HEAL, TANK, ROOT, create_inventory, load_native_item_index,
)

STAGES = (5, 30, 300)
SOURCE_GAP = "VERIFY_PER_RANK_TALENTS_AND_FULL_EQUIP_RULES"


def preflight(profile: str, source: dict, request: dict | None, stage: int,
              previous: dict | None = None) -> tuple[str, str] | None:
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
        if (previous.get("native_paid", 0) < 1
                or not previous.get("replay_matches")
                or previous.get("native_errors", 0) != 0):
            return ("BLOCKED_PRIOR_STAGE",
                    "Prior stage lacks paid, independently replayed error-free native evidence")
    return None


def build_matrix(inventory: list[tuple[dict, dict | None]], *, stage: int, run,
                 prior_rows: dict[str, dict] | None = None) -> list[dict]:
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
        block = preflight(profile, inv, request, stage, previous)
        base = {
            "profile_id": profile,
            "stage_seconds": stage,
            "source_sha256": inv.get("source_sha256"),
            "source_path": inv.get("source_path"),
            "source_type": inv.get("source_type"),
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
        measured = run(profile)
        if measured.get("process_gate_pass") or measured.get("full_source_legality_certified"):
            # This source-bounded adapter cannot certify full legal gear/talents.
            raise ValueError("Unverified full-source legality or P7 certification")
        base.update(measured)
        base["full_source_legality_certified"] = False
        base["process_gate_pass"] = False
        base["promotable"] = False
        base["promotion_blocker"] = "BLOCKED_FULL_SOURCE_LEGALITY"
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
    if status == "BLOCKED_NATIVE_REPLAY_MISMATCH":
        return "REPRODUCE_EXACT_NATIVE_WINNER"
    return "INVESTIGATE_" + status


def gap_summary(rows: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        cause = _cause(row)
        groups.setdefault(cause, []).append({
            "profile_id": row["profile_id"],
            "status": row["status"],
            "blocker": row.get("blocker") or row.get("promotion_blocker"),
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
             "", "| Profile | Status | Paid | 3-axis paid | Balanced screen | Gap |",
             "|---|---|---:|---:|---:|---|"]
    for r in rows:
        def esc(value):
            return str(value if value is not None else "—").replace("|", "\\|").replace("\n", " ")
        lines.append("| " + " | ".join(map(esc, (
            r["profile_id"], r["status"], r["native_paid"], r["three_axis_paid"],
            r.get("best_balanced_screen"), r.get("blocker") or r.get("promotion_blocker"),
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
        return execute(
            profile, inventory, native_items,
            binary=args.binary, engine_src=args.engine_src,
            seconds=float(args.stage), iterations=args.iterations,
            seed=args.seed + next(i for i, (r, _) in enumerate(inventory)
                                  if r["profile_id"] == profile),
            outdir=args.out / "profiles" / profile.replace("/", "__"),
        )

    rows = build_matrix(inventory, stage=args.stage, run=pay_native,
                        prior_rows=previous)
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
