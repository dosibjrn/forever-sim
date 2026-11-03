#!/usr/bin/env python3
"""28-row native Rust JOINT diagnostic using the ONE existing search_native kernel.

This runner reuses native_joint_two_class.execute; it does not introduce a new
optimizer or scorer. Python bounds proposals to the declared candidate domain;
MythicSim Rust alone decides whether a submitted request is valid or supported.
The 5s matrix is a diagnostic, not a stochastic holdout or PROCESS P7 result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

from native_joint_two_class import execute, objective_for_profile
from native_executor import objective_metric_path
from native_source_donors import load_source_donor_fixtures
from native_l60_matrix import (
    ROOT, create_inventory, current_client_talent_donor_fixtures,
)

STAGES = (5, 30, 300)

def preflight(profile: str, source: dict, request: dict | None, stage: int,
              previous: dict | None = None) -> tuple[str, str] | None:
    """Fail closed before any native invocation; stage promotion is not a score race."""
    if request is None:
        return ("BLOCKED_SOURCE", str(source.get("blocker") or "No exact source request"))
    if stage != 5:
        if previous is None:
            return ("BLOCKED_PRIOR_STAGE", "Missing completed prior-stage exact profile row")
        if (previous.get("three_axis_paid", 0) < 1
                or not previous.get("replay_matches")
                or previous.get("native_errors", 0) != 0):
            return ("BLOCKED_PRIOR_STAGE",
                    "Prior stage lacks a three-axis native-paid candidate with exact replay and zero execution errors")
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
        objective = objective_for_profile(profile)
        base = {
            "profile_id": profile,
            "stage_seconds": stage,
            "objective": objective,
            "native_metric_path": objective_metric_path(objective),
            "source_sha256": inv.get("source_sha256"),
            "source_fixture_sha256": inv.get("source_fixture_sha256", inv.get("source_sha256")),
            "effective_source_request_fingerprint": inv.get("effective_source_request_fingerprint"),
            "source_path": inv.get("source_path"),
            "source_type": inv.get("source_type"),
            "talent_override": inv.get("talent_override"),
            "native_paid": 0,
            "baseline_paid": 0,
            "native_paid_total": 0,
            "native_donor_probe_attempts": 0,
            "native_donor_probe_paid": 0,
            "native_donor_probe_positive_builds": 0,
            "baseline_balanced_score": None,
            "three_axis_paid": 0,
            "native_errors": 0,
            "native_unscored": 0,
            "native_refusals": 0,
            "native_invalid": 0,
            "native_unsupported": 0,
        }
        if block:
            base["status"], base["blocker"] = block
            rows.append(base)
            continue
        measured = run(profile)
        base.update(measured)
        base.setdefault("baseline_paid", 0)
        base.setdefault("native_paid_total",
                        base.get("native_paid", 0) + base.get("baseline_paid", 0))
        # Strip obsolete proof/gate fields from older measured rows as well.
        for obsolete in (
            "full_source_legality_certified", "process_gate_pass",
            "promotable", "promotion_blocker", "live_gsim_2d_rust_causality",
        ):
            base.pop(obsolete, None)
        base["score_scope"] = "BALANCED_NATIVE_SCREEN_ONLY_NOT_HOLDOUT"
        rows.append(base)
    return rows


def _cause(row: dict) -> str | None:
    status = row["status"]
    if status == "NATIVE_JOINT_PAID" and row.get("replay_matches"):
        return None
    if status == "BLOCKED_SPEC_IDENTITY":
        return "VERIFY_DISCIPLINE_FIXTURE_IDENTITY"
    if status == "BLOCKED_CANDIDATE_DOMAIN":
        detail = str(row.get("blocker") or "")
        if detail.startswith("BLOCKED_GEAR_POOL:"):
            return "SOURCE_GEAR_POOL_MISSING"
        if detail.startswith("BLOCKED_TALENTS:"):
            return "SOURCE_TALENT_DONORS_MISSING"
        if detail.startswith("BLOCKED_NATIVE_HPS_WITNESS:"):
            return "SOURCE_HPS_DONOR_WITNESSES_MISSING"
        if detail.startswith("BLOCKED_NATIVE_TPS_WITNESS:"):
            return "SOURCE_TPS_DONOR_WITNESSES_MISSING"
        return "INVESTIGATE_CANDIDATE_DOMAIN"
    if status == "BLOCKED_NATIVE_REFUSALS":
        return "NATIVE_CANDIDATE_REFUSALS"
    if status == "BLOCKED_NATIVE_UNSCORED":
        return "NATIVE_SCORE_UNAVAILABLE"
    if status in {"BLOCKED_NATIVE_EXECUTION_ERROR", "NATIVE_JOINT_PAID_WITH_EXECUTION_ERRORS"}:
        return "NATIVE_EXECUTION_ERRORS"
    if status == "BLOCKED_NO_NATIVE_ACCEPTED_THREE_AXIS_CANDIDATE":
        if row.get("native_refusals", 0):
            return "NATIVE_CANDIDATE_REFUSALS"
        if row.get("native_errors", 0):
            return "NATIVE_EXECUTION_ERRORS"
        if row.get("native_unscored", 0):
            return "NATIVE_SCORE_UNAVAILABLE"
        return "NO_NATIVE_ACCEPTED_THREE_AXIS_CANDIDATE"
    if status == "BLOCKED_SOURCE":
        return "PROVIDE_EXACT_NATIVE_REQUEST"
    if status == "BLOCKED_PRIOR_STAGE":
        return "PROVIDE_PRIOR_STAGE_NATIVE_PAID_REPLAY"
    if status == "BLOCKED_NATIVE_REPLAY_MISMATCH":
        return "REPRODUCE_EXACT_NATIVE_WINNER"
    return "INVESTIGATE_" + status


def gap_summary(rows: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        cause = _cause(row)
        if cause is None:
            continue
        groups.setdefault(cause, []).append({
            "profile_id": row["profile_id"],
            "status": row["status"],
            "blocker": row.get("blocker") or row.get("search_status") or row["status"],
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
        "source_scope": "PINNED_NATIVE_CANDIDATE_DOMAIN",
        "source_talent_overrides": [
            {"profile_id": row["profile_id"], **row["talent_override"]}
            for row in rows if row.get("talent_override")
        ],
    }
    if donor_inventory is not None:
        donor_manifest = [
            {
                "source_path": item["source_path"],
                "source_sha256": item["source_sha256"],
                "class_name": item["class_name"],
                "item_count": item["item_count"],
                "source_type": item.get("source_type", "PINNED_SOURCE_FIXTURE"),
                "talent_source_repository": item.get("talent_source_repository"),
                "talent_source_pull_request": item.get("talent_source_pull_request"),
                "talent_source_commit": item.get("talent_source_commit"),
                "talent_source_path": item.get("talent_source_path"),
                "talent_source_blob_sha": item.get("talent_source_blob_sha"),
                "talent_preset_name": item.get("talent_preset_name"),
                "composed_over_profile": item.get("composed_over_profile"),
            }
            for item in donor_inventory.get("fixtures", [])
        ]
        manifest_bytes = json.dumps(
            donor_manifest, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        provenance["source_donor_corpus"] = {
            "directories": donor_inventory.get("directories", []),
            "loaded_count": len(donor_manifest),
            "pinned_engine_fixture_count": donor_inventory.get("pinned_engine_fixture_count", len(donor_manifest)),
            "current_client_preset_donor_count": len(donor_inventory.get("current_client_preset_donors", [])),
            "current_client_preset_donors": donor_inventory.get("current_client_preset_donors", []),
            "skipped_count": len(donor_inventory.get("skipped", [])),
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "skipped_sources": donor_inventory.get("skipped", []),
        }
    for row in rows:
        row.setdefault("baseline_paid", 0)
        row.setdefault("native_unscored", 0)
        row.setdefault("native_paid_total",
                       row.get("native_paid", 0) + row.get("baseline_paid", 0))
        row["repo_git_sha"] = repo_sha
        row["engine_git_sha"] = engine_sha
        row["native_binary_sha256"] = provenance["binary_sha256"]
        row["native_db_sha256"] = db
    (out / "matrix.json").write_text(json.dumps(rows, indent=2) + "\n")
    (out / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    (out / "gaps.json").write_text(json.dumps(gap_summary(rows), indent=2) + "\n")
    lines = ["# Native Rust L60 JOINT " + str(stage) + "s diagnostic",
             "", "Balanced native screen only; no stochastic holdout or PROCESS P7 claim.",
             "", "| Profile | Objective | Status | Baseline balanced | Best balanced | Search paid | Baseline paid | 3-axis paid | Unscored | Outcome / blocker |",
             "|---|---|---|---:|---:|---:|---:|---:|---:|---|"]
    for r in rows:
        def esc(value):
            return str(value if value is not None else "—").replace("|", "\\|").replace("\n", " ")
        lines.append("| " + " | ".join(map(esc, (
            r["profile_id"], r.get("objective", "DPS"), r["status"],
            r.get("baseline_balanced_score"), r.get("best_balanced_screen"),
            r["native_paid"], r.get("baseline_paid", 0),
            r["three_axis_paid"], r.get("native_unscored", 0),
            r.get("blocker") or r.get("search_status") or r["status"],
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
    donor_inventory = load_source_donor_fixtures(args.engine_src)
    donor_inventory["pinned_engine_fixture_count"] = len(donor_inventory["fixtures"])
    preset_donors = current_client_talent_donor_fixtures(inventory)
    donor_inventory["current_client_preset_donors"] = [
        {
            key: donor[key]
            for key in (
                "source_path", "source_sha256", "talent_preset_name",
                "talent_string", "composed_over_profile",
                "talent_source_commit", "talent_source_blob_sha",
                "talent_source_url",
            )
        }
        for donor in preset_donors
    ]
    donor_inventory["fixtures"] = donor_inventory["fixtures"] + preset_donors
    donor_fixtures = donor_inventory["fixtures"]
    previous = ({r["profile_id"]: r for r in json.loads(args.prior.read_text())}
                if args.prior else None)

    def pay_native(profile: str) -> dict:
        return execute(
            profile, inventory,
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
                      "native_refusals": sum(r.get("native_refusals", 0) for r in rows),
                      "native_invalid": sum(r.get("native_invalid", 0) for r in rows),
                      "native_unsupported": sum(r.get("native_unsupported", 0) for r in rows),
                      "native_errors": sum(r.get("native_errors", 0) for r in rows),
                      "native_unscored": sum(r.get("native_unscored", 0) for r in rows),
                      "source_donor_fixtures": len(donor_fixtures),
                      "current_client_preset_donors": len(preset_donors)},
                     sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
