"""Prepare ephemeral P7.5 prior receipts from actual accepted M1 Actions runs.

No ledger writes or synthetic DPS. GitHub's authenticated M1 workflow retrieves
the *original* registered run logs, never a reference build or an optimizer
screen score. The official recorder supplies a pre-run TSV snapshot so a P7.5
target in a multi-gate batch cannot mistake its own in-progress P7.1-P7.4 run
for a completed accepted prior. P7.5 uses the original officially recorded receipts as immutable historical
observations. Never search for or request newer reruns of accepted M1 gates.
A prior can be excluded from the current P7.5 numerical comparison when its
engine/source/scenario differs; that does not invalidate its historical PASS.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import re
import subprocess

_PRIORS = ("P7.1", "P7.2", "P7.3", "P7.4")
_WORKFLOW = "M1 - Merge-owned batch live gate recorder"


def _approved_rows(root: Path, class_key: str, level: int, spec: str, *,
                   ledger_path: Path | None = None):
    # The M1 workflow snapshots this file before its target loop. Reading that
    # immutable snapshot prevents a later P7.5 target from treating an earlier
    # gate in the same still-running batch as a completed trusted M1 run.
    source = ledger_path or (root / "docs/planning/M1_PASSES.tsv")
    with source.open(newline="") as handle:
        rows = csv.DictReader(handle, delimiter="\t")
        return {
            row["gate"]: row
            for row in rows
            if (row.get("class") == class_key
                and row.get("level") == str(level)
                and row.get("spec") == spec
                and row.get("gate") in _PRIORS
                and row.get("status") == "PASS"
                and row.get("passed_at_utc"))
        }


def _registered_run_id(run_url: str, repository: str) -> int:
    # Never fetch an arbitrary URL supplied through TSV or an Actions log.
    pattern = rf"https://github\.com/{re.escape(repository)}/actions/runs/([1-9][0-9]*)"
    match = re.fullmatch(pattern, run_url or "")
    if match is None:
        raise ValueError("P75_PRIOR_NOT_REGISTERED_CANONICAL_ACTIONS_URL")
    return int(match.group(1))


def _parse_accepted_gate_line(log: str, *, class_key: str,
                              level: int, spec: str, gate: str) -> dict:
    """Only accept the terminal single-line JSON emitted by real wf_gate CLI.

    GitHub CLI prefixes each job log line with a job/step/time; walk JSON
    start positions rather than assuming a timestamp or formatting style.
    Reject missing/ambiguous/mismatched terminal reports, not just missing
    score fields. The existing P7.5 comparator validates native proof and DPS.
    """
    matches = []
    for line in log.splitlines():
        for marker in ('{"class":', '{"class" :'):
            start = line.find(marker)
            if start < 0:
                continue
            try:
                entry = json.loads(line[start:].strip())
            except (ValueError, TypeError):
                continue
            if not isinstance(entry, dict):
                continue
            if not (entry.get("class") == class_key
                    and entry.get("level") == level
                    and entry.get("spec") == spec
                    and entry.get("gate") == gate
                    and entry.get("status") == "PASS"):
                continue
            results = entry.get("results")
            if (isinstance(results, list) and len(results) == 1
                    and isinstance(results[0], dict)
                    and results[0].get("gate") == gate
                    and results[0].get("status") == "PASS"):
                matches.append(results[0])
            break
    if not matches:
        raise ValueError("P75_ACCEPTED_M1_PRODUCTION_GATE_JSON_NOT_IN_RUN_LOG")
    # The CLI prints its complete result and the workflow prints the stored
    # --out report again. Both must agree; no cherry-picked success among
    # contradictory records from one approved run.
    first = matches[0]
    if any(report != first for report in matches[1:]):
        raise ValueError("P75_CONFLICTING_M1_GATE_REPORTS_IN_RUN_LOG")
    return first


def _read_approved_run(repository: str, run_id: int) -> str:
    """Use authenticated gh CLI only for the original accepted workflow run."""
    command = ["gh", "run", "view", str(run_id), "--repo", repository]
    metadata = subprocess.run(command + ["--json", "workflowName,conclusion,event"],
                              capture_output=True, text=True, check=True,
                              timeout=90)
    info = json.loads(metadata.stdout)
    if (info.get("workflowName") != _WORKFLOW
            or info.get("conclusion") != "success"
            or info.get("event") not in ("workflow_dispatch", "issue_comment")):
        raise ValueError("P75_PRIOR_NOT_SUCCESSFUL_TRUSTED_M1_RUN")
    log = subprocess.run(command + ["--log"], capture_output=True, text=True,
                         check=True, timeout=180)
    return log.stdout


def collect_accepted_receipts(root: Path, repository: str, class_key: str,
                              level: int, spec: str, *, read_run=_read_approved_run,
                              ledger_path: Path | None = None):
    rows = _approved_rows(root, class_key, level, spec,
                          ledger_path=ledger_path)
    if not rows:
        raise ValueError("P75_NO_REGISTERED_ACCEPTED_PRIOR")
    receipts = []
    for gate in _PRIORS:
        if gate not in rows:
            continue  # PARTIAL / untested is never counted as accepted
        run_url = rows[gate].get("run_url", "")
        run_id = _registered_run_id(run_url, repository)
        report = _parse_accepted_gate_line(
            read_run(repository, run_id), class_key=class_key,
            level=level, spec=spec, gate=gate)
        receipts.append({"gate": gate, "run_url": run_url, "report": report})

    # Only the registered original official PASS is returned. A newer engine
    # does not authorize rerunning, replacing or revalidating accepted gates.
    return {"receipts": receipts}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True,
                        help="Exact GITHUB_REPOSITORY owner/name")
    parser.add_argument("--class", dest="class_key", required=True)
    parser.add_argument("--level", required=True, type=int)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--ledger", type=Path, default=None,
        help=("Optional immutable pre-run M1_PASSES.tsv snapshot. The official "
              "M1 workflow passes this so a P7.5 target cannot read its own "
              "in-progress batch as an accepted prior."),
    )
    args = parser.parse_args()
    if not os.environ.get("GH_TOKEN"):
        parser.error("GH_TOKEN needed to read accepted Actions logs")
    root = Path(__file__).resolve().parents[1]
    try:
        receipts = collect_accepted_receipts(
            root, args.repository, args.class_key, args.level, args.spec,
            ledger_path=args.ledger)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError,
            json.JSONDecodeError) as exc:
        parser.error(f"Cannot supply genuine accepted prior receipts: {exc}")
    # Private ephemeral runner file only: not a new artifact or M1 ledger.
    args.out.write_text(json.dumps(receipts, separators=(",", ":")) + "\n")
    print(f"P7.5: loaded {len(receipts['receipts'])} registered accepted M1 prior receipts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
