"""Minimal M1 scoreboard: historical LIVE gate PASS stamps, never gate evidence.

Only wf_gate.py calls record_pass after the real production provider returns PASS.
This tool displays stored acceptance history; it never awards a new PASS.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs/planning/M1_PASSES.tsv"
GATES = tuple(f"P{n}" for n in range(1, 7)) + tuple(f"P7.{n}" for n in range(1, 6))
CLASSES = frozenset(("druid", "hunter", "mage", "paladin", "priest",
                     "rogue", "shaman", "warlock", "warrior"))
LEVELS = frozenset((20, 30, 40, 60))
FIELDS = ("class", "level", "spec", "gate", "passed_at_utc", "commit",
          "run_url", "compatibility_id")
TOTAL = 148 * len(GATES)  # 1628: historical PASSes, NOT 1628 test implementations


def _key(row):
    return tuple(row[k] for k in ("class", "level", "spec", "gate"))


def _rows(path=LEDGER):
    path = Path(path)
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError("M1 ledger schema mismatch")
        rows = {}
        for row in reader:
            if (row["class"] not in CLASSES or int(row["level"]) not in LEVELS
                    or not re.fullmatch(r"[a-z][a-z0-9_-]*", row["spec"])
                    or row["gate"] not in GATES or not row["passed_at_utc"]
                    or not re.fullmatch(r"[0-9a-f]{40}", row["commit"])):
                raise ValueError("Invalid M1 PASS row: " + str(_key(row)))
            rows[_key(row)] = row  # newest valid recording for this exact gate
    return rows


def _write(rows, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, delimiter="\t", fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows[k] for k in sorted(rows))
    temp.replace(path)


def record_pass(*, class_key, level, spec, gate, report, root=ROOT, path=LEDGER):
    """Called only after wf_gate._run_live_gate validates a real PASS."""
    if report.get("status") != "PASS" or report.get("reasons"):
        raise ValueError("Only an executed live PASS can be recorded")
    if class_key not in CLASSES or level not in LEVELS or gate not in GATES:
        raise ValueError("Not an M1 checkpoint/gate")
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", spec):
        raise ValueError("Invalid spec")
    sha = subprocess.check_output(
        ["git", "rev-parse", "--verify", "HEAD"], cwd=root, text=True
    ).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("No auditable git revision")
    run_id = os.getenv("GITHUB_RUN_ID", "")
    run_url = (f"{os.getenv('GITHUB_SERVER_URL', 'https://github.com')}/"
               f"{os.getenv('GITHUB_REPOSITORY', 'dosibjrn/forever-sim')}"
               f"/actions/runs/{run_id}") if run_id else ""
    proof = report.get("runtime_proof") or {}
    # Providers must emit the SAME source/ruleset/executor compatibility ID
    # before 11 gate stamps can certify a WHOLE checkpoint automatically.
    compatibility = report.get("compatibility_id") or proof.get("compatibility_id") or ""
    rows = _rows(path)
    row = dict(zip(FIELDS, (class_key, str(level), spec, gate,
                           datetime.now(timezone.utc).isoformat(), sha,
                           run_url, compatibility)))
    rows[_key(row)] = row
    _write(rows, path)


def scoreboard(path=LEDGER):
    rows = _rows(path)
    by_checkpoint = {}
    for row in rows.values():
        key = (row["class"], row["level"], row["spec"])
        by_checkpoint.setdefault(key, []).append(row)
    # OVERALL PLAN: one unrestricted plus four Druid profiles / three others
    # at each of the four levels. No new profile may inflate the 1,628 total.
    if len(by_checkpoint) > 148:
        raise ValueError("More than 148 distinct M1 checkpoint identities")
    for class_key in CLASSES:
        for level in LEVELS:
            specs = {spec for (c, lev, spec) in by_checkpoint
                     if c == class_key and int(lev) == level}
            if len(specs) > (5 if class_key == "druid" else 4):
                raise ValueError("Too many M1 profiles for a class/level")
    complete = [group for group in by_checkpoint.values()
                if {r["gate"] for r in group} == set(GATES)]
    compatible = sum(bool(group[0]["compatibility_id"]) and
                     len({r["compatibility_id"] for r in group}) == 1
                     for group in complete)
    return {"passed_gates": len(rows), "total_gates": TOTAL,
            "gate_percent": 100 * len(rows) / TOTAL,
            "complete_candidates": len(complete),
            "certified_checkpoints": compatible,
            "total_checkpoints": 148}


def main(argv=None):
    parser = argparse.ArgumentParser(description="M1 live-PASS scoreboard (no gate reruns)")
    parser.add_argument("--ledger", type=Path, default=LEDGER)
    parser.add_argument("--invalidate", nargs=4, metavar=("CLASS", "LEVEL", "SPEC", "GATE"),
                        help="Remove a materially invalidated historical PASS")
    args = parser.parse_args(argv)
    if args.invalidate:
        rows = _rows(args.ledger)
        del_key = tuple(args.invalidate)
        if del_key not in rows:
            parser.error("No such PASS to invalidate")
        del rows[del_key]
        _write(rows, args.ledger)
    result = scoreboard(args.ledger)
    print(f"M1: {result['passed_gates']}/{TOTAL} accepted gate runs "
          f"({result['gate_percent']:.2f}%)")
    print(f"Whole checkpoints: {result['certified_checkpoints']}/148; "
          f"11/11 gate candidates: {result['complete_candidates']}")
    print("Unlinked/mismatched compatibility IDs never certify a whole checkpoint.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
