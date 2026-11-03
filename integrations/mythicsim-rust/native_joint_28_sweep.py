#!/usr/bin/env python3
"""28-row native Rust JOINT breadth using the ONE existing search_native kernel.

This runner reuses native_joint_two_class.execute; it does not introduce a new
optimizer or scorer. The source-observed candidate pool is not exhaustive;
MythicSim Rust decides whether each paid candidate is valid or unsupported.
A native-paid, three-axis candidate with exact replay can advance the optimizer
screen from 5s to 30s to 300s; this never implies PROCESS P7 acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

from native_joint_two_class import execute
from native_source_donors import load_source_donor_fixtures
from native_l60_matrix import (
    HEAL, TANK, ROOT, create_inventory, load_native_item_index,
)

STAGES = (5, 30, 300)


def _native_stage_ready(row: dict) -> bool:
    """A prior screen advances only on a paid 3-axis native candidate + exact replay."""
    try:
        return (
            int(row.get("native_paid", 0)) >= 1
            and int(row.get("three_axis_paid", 0)) >= 1
            and bool(row.get("replay_matches"))
            and int(row.get("native_errors", 0)) == 0
        )
    except (TypeError, ValueError):
        return False


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
        if not _native_stage_ready(previous):
            return ("BLOCKED_PRIOR_STAGE",
                    "Prior stage lacks a native-paid three-axis candidate with exact replay and no execution errors")
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
            "source_fixture_sha256": inv.get("source_fixture_sha256", inv.get("source_sha256")),
            "effective_source_request_fingerprint": inv.get("effective_source_request_fingerprint"),
            "source_path": inv.get("source_path"),
            "source_type": inv.get("source_type"),
            "talent_override": inv.get("talent_override"),
            "objective": "HPS" if profile in HEAL else ("TPS" if profile in TANK else "DPS"),
            "native_paid": 0,
            "baseline_paid": 0,
            "native_paid_total": 0,
            "baseline_balanced_score": None,
            "three_axis_paid": 0,
            "process_gate_pass": False,
            "promotable": False,
            "next_stage_eligible": False,
        }
        if block:
            base["status"], base["blocker"] = block
            base["promotion_blocker"] = block[0]
            rows.append(base)
            continue
        measured = run(profile)
        if measured.get("process_gate_pass"):
            raise ValueError("A diagnostic JOINT screen cannot claim PROCESS P7 acceptance")
        base.update(measured)
        base.setdefault("baseline_paid", 0)
        base.setdefault("native_paid_total",
                        base.get("native_paid", 0) + base.get("baseline_paid", 0))
        base["process_gate_pass"] = False
        base["promotable"] = False
        base["next_stage_eligible"] = stage in (5, 30) and _native_stage_ready(base)
        if stage == 300:
            base["promotion_blocker"] = "FINAL_STAGE_NOT_PROCESS_P7_ACCEPTANCE"
        elif base["next_stage_eligible"]:
            base["promotion_blocker"] = None
        else:
            base["promotion_blocker"] = "BLOCKED_NO_NATIVE_PAID_THREE_AXIS_REPLAY"
        base["score_scope"] = "BALANCED_NATIVE_SCREEN_ONLY_NOT_HOLDOUT"
        rows.append(base)
    return rows


def _cause(row: dict) -> str:
    status = row["status"]
    if status == "NATIVE_JOINT_SOURCE_BOUNDED_SCREEN":
        return "NATIVE_JOINT_PAID_SCREEN_ONLY"
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
        if row.get("native_invalid", 0) or row.get("native_unsupported", 0):
            return "NATIVE_REJECTED_ALL_CANDIDATES"
        return "NO_NATIVE_PAID_THREE_AXIS_CANDIDATE"
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


def _git_sha(path: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _git_diff_sha(path: Path) -> str | None:
    try:
        diff = subprocess.check_output(
            ["git", "-C", str(path), "diff", "--binary"],
            stderr=subprocess.DEVNULL,
        )
        return hashlib.sha256(diff).hexdigest()
    except (OSError, subprocess.CalledProcessError):
        return None


def save_report(out: Path, rows: list[dict], *, stage: int, binary: Path,
                engine_src: Path,
                donor_inventory: dict | None = None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    db = {name: _sha(engine_src / "data" / (name + ".jsonl"))
          for name in ("items", "enchants", "spells")}
    repo_sha = _git_sha(ROOT)
    engine_sha = _git_sha(engine_src)
    port_path = ROOT / "integrations/mythicsim-rust/port_native_typed_rng.py"
    provenance = {
        "stage_seconds": stage,
        "repo_git_sha": repo_sha,
        "engine_git_sha": engine_sha,
        "engine_worktree_diff_sha256": _git_diff_sha(engine_src),
        "typed_rng_port_sha256": _sha(port_path) if port_path.is_file() else None,
        "binary_sha256": _sha(binary),
        "native_db_sha256": db,
        "candidate_rng_mode": "balanced",
        "holdout_rng_mode": "stochastic",
        "holdout_status": "NOT_RUN_STAGE_5",
        "source_scope": "PINNED_SOURCE_OBSERVED_CANDIDATE_POOL_NATIVE_OUTCOME_SCREEN",
        "source_talent_overrides": [
            {"profile_id": row["profile_id"], **row["talent_override"]}
            for row in rows if row.get("talent_override")
        ],
        "process_p7_pass": False,
    }
    if donor_inventory is not None:
        donor_manifest = [
            {
                "source_path": item["source_path"],
                "source_sha256": item["source_sha256"],
                "class_name": item["class_name"],
                "item_count": item["item_count"],
            }
            for item in donor_inventory.get("fixtures", [])
        ]
        manifest_bytes = json.dumps(
            donor_manifest, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        provenance["source_donor_corpus"] = {
            "directories": donor_inventory.get("directories", []),
            "loaded_count": len(donor_manifest),
            "skipped_count": len(donor_inventory.get("skipped", [])),
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "skipped_sources": donor_inventory.get("skipped", []),
        }
    for row in rows:
        row.setdefault("baseline_paid", 0)
        row.setdefault("native_paid_total",
                       row.get("native_paid", 0) + row.get("baseline_paid", 0))
        row["repo_git_sha"] = repo_sha
        row["engine_git_sha"] = engine_sha
        row["native_binary_sha256"] = provenance["binary_sha256"]
        row["native_db_sha256"] = db
    (out / "matrix.json").write_text(json.dumps(rows, indent=2) + "\n")
    (out / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    (out / "gaps.json").write_text(json.dumps(gap_summary(rows), indent=2) + "\n")
    lines = ["# Native Rust L60 JOINT screen " + str(stage) + "s",
             "", "Source-observed candidate pool; MythicSim decides candidate validity. Not exhaustive search, stochastic holdout, or PROCESS P7.",
             "", "| Profile | Status | Baseline balanced | Best balanced | Search paid | Baseline paid | 3-axis paid | Gap |",
             "|---|---|---:|---:|---:|---:|---:|---|"]
    for r in rows:
        def esc(value):
            return str(value if value is not None else "—").replace("|", "\\|").replace("\n", " ")
        lines.append("| " + " | ".join(map(esc, (
            r["profile_id"], r["status"], r.get("baseline_balanced_score"),
            r.get("best_balanced_screen"), r["native_paid"], r.get("baseline_paid", 0),
            r["three_axis_paid"], r.get("blocker") or r.get("promotion_blocker"),
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
    donor_inventory = load_source_donor_fixtures(args.engine_src)
    donor_fixtures = donor_inventory["fixtures"]
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
            donor_fixtures=donor_fixtures,
        )

    rows = build_matrix(inventory, stage=args.stage, run=pay_native,
                        prior_rows=previous)
    save_report(args.out, rows, stage=args.stage, binary=args.binary,
                engine_src=args.engine_src, donor_inventory=donor_inventory)
    print(json.dumps({"stage_seconds": args.stage, "profiles": len(rows),
                      "statuses": dict(Counter(r["status"] for r in rows)),
                      "baseline_paid": sum(r.get("baseline_paid", 0) for r in rows),
                      "search_native_paid": sum(r["native_paid"] for r in rows),
                      "native_paid_total": sum(r.get("native_paid_total", r["native_paid"]) for r in rows),
                      "three_axis_paid": sum(r["three_axis_paid"] for r in rows),
                      "source_donor_fixtures": len(donor_fixtures),
                      "promotable": sum(bool(r["promotable"]) for r in rows)},
                     sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
