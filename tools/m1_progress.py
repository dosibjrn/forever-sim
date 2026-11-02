"""Minimal M1 scoreboard: historical LIVE gate PASS stamps, never gate evidence.

Only wf_gate.py calls record_pass after the real production provider returns PASS.
This tool displays stored acceptance history; it never awards a new PASS.
"""
from __future__ import annotations

import argparse
import csv
import math
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
# Also support the documented direct invocation: python tools/m1_progress.py
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.wf_gate_coverage import (measured_live_coverage,
                                    measured_p7_dps_proximity, pareto_effort_fraction)
LEDGER = ROOT / "docs/planning/M1_PASSES.tsv"
GATES = tuple(f"P{n}" for n in range(1, 7)) + tuple(f"P7.{n}" for n in range(1, 6))
CLASSES = frozenset(("druid", "hunter", "mage", "paladin", "priest",
                     "rogue", "shaman", "warlock", "warrior"))
LEVELS = frozenset((20, 30, 40, 60))
PASS_FIELDS = ("class", "level", "spec", "gate", "passed_at_utc", "commit",
               "run_url", "compatibility_id")
FIELDS = PASS_FIELDS + ("status", "verified", "applicable", "scope_provisional",
                        "measured_at_utc")
TOTAL = 148 * len(GATES)  # 1628: historical PASSes, NOT 1628 test implementations


def _key(row):
    return tuple(row[k] for k in ("class", "level", "spec", "gate"))


def _rows(path=LEDGER):
    path = Path(path)
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        columns = tuple(reader.fieldnames or ())
        if columns not in (PASS_FIELDS, FIELDS):
            raise ValueError("M1 ledger schema mismatch")
        rows = {}
        for row in reader:
            if columns == PASS_FIELDS:  # historical PASS-only register
                row.update(status="PASS", verified="", applicable="",
                           scope_provisional="", measured_at_utc=row["passed_at_utc"])
            if (row["class"] not in CLASSES or int(row["level"]) not in LEVELS
                    or not re.fullmatch(r"[a-z][a-z0-9_-]*", row["spec"])
                    or row["gate"] not in GATES
                    or not re.fullmatch(r"[0-9a-f]{40}", row["commit"])
                    or row["status"] not in ("PASS", "PARTIAL")
                    or not row["measured_at_utc"]):
                raise ValueError("Invalid M1 measurement row: " + str(_key(row)))
            if row["status"] == "PASS" and not row["passed_at_utc"]:
                raise ValueError("PASS requires a real acceptance timestamp")
            if row["status"] == "PARTIAL":
                # P1-P6 record actually passed behaviors. P7 records actual
                # coupled live DPS / required DPS (not fabricated test counts).
                if row["gate"].startswith("P7."):
                    n, d = float(row["verified"]), float(row["applicable"])
                    numeric_ok = math.isfinite(n) and math.isfinite(d)
                else:
                    n, d = int(row["verified"]), int(row["applicable"])
                    numeric_ok = True
                # 100% of a measured subcomponent can remain a gate FAIL.
                if not (numeric_ok and 0 < n <= d and d > 0
                        and not row["passed_at_utc"]
                        and row["scope_provisional"] in ("0", "1")):
                    raise ValueError("PARTIAL must have genuine bounded coverage")
            rows[_key(row)] = row  # latest verified measurement per gate
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
    row = _provenance(class_key, level, spec, gate, report, root)
    row.update(status="PASS", passed_at_utc=row["measured_at_utc"],
               verified="", applicable="", scope_provisional="")
    rows = _rows(path)
    if rows.get(_key(row), {}).get("status") == "PASS":
        return False  # An old compatible PASS is not retimestamped every run.
    rows[_key(row)] = row
    _write(rows, path)
    return True


def _provenance(class_key, level, spec, gate, report, root):
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
    compatibility = report.get("compatibility_id") or proof.get("compatibility_id") or ""
    return {"class": class_key, "level": str(level), "spec": spec, "gate": gate,
            "passed_at_utc": "", "commit": sha, "run_url": run_url,
            "compatibility_id": compatibility, "status": "", "verified": "",
            "applicable": "", "scope_provisional": "",
            "measured_at_utc": datetime.now(timezone.utc).isoformat()}


def record_partial(*, class_key, level, spec, gate, report, root=ROOT, path=LEDGER):
    """Record the best genuinely measured fraction, never exploration or samples.

    The authoritative gate runner makes this decision without agent grading.
    An observed 100% subcomponent may remain FAIL due to other gate clauses.
    Preserve historical best PARTIAL on a weaker run (and log regression).
    Invalidation handles a materially changed source/measurement contract.
    """
    if (class_key not in CLASSES or level not in LEVELS or gate not in GATES
            or not re.fullmatch(r"[a-z][a-z0-9_-]*", spec)):
        return False

    if gate.startswith("P7."):
        # P7 is a numerical objective, not count-based sample coverage.
        # Include a genuine executed BLOCKED-with-UI-audit-missing result.
        score = measured_p7_dps_proximity(gate, report)
        if score is None or report.get("status") not in ("FAIL", "BLOCKED"):
            return False
        n = min(float(score["dps_objective_actual"]),
                float(score["dps_objective_required"]))
        d = float(score["dps_objective_required"])
        provisional = True  # Numerical DPS proximity never certifies the gate.
    else:
        measured = measured_live_coverage(report)
        if measured is None or report.get("status") != "FAIL":
            return False
        n, d = report.get("pass_count"), report.get("reachability_count")
        if not (type(n) is int and type(d) is int and 0 < n <= d):
            return False
        provisional = measured["scope_provisional"]

    rows = _rows(path)
    row = _provenance(class_key, level, spec, gate, report, root)
    old = rows.get(_key(row))
    if old and old["status"] == "PASS":
        return False
    if old and old["status"] == "PARTIAL":
        old_ratio = float(old["verified"]) / float(old["applicable"])
        new_ratio = n / d
        if new_ratio <= old_ratio + 1e-12:
            # A failed new probe is visible in its Actions log, but cannot
            # silently erase a previously proven M1 high-water mark.
            if new_ratio < old_ratio - 1e-12:
                print(f"M1_REGRESSION_OR_SCOPE_CHANGE: {_key(row)} "
                      f"observed={new_ratio:.4f} best={old_ratio:.4f}")
            return False
        # A changed denominator may be a new or narrower test universe.
        # Don't allow shrinking scope to inflate a partial score, even when
        # its ratio is larger. Require more actual passing behaviors too.
        if old["applicable"] != str(d):
            if n < float(old["verified"]):
                print(f"M1_SCOPE_CHANGE_NOT_COMPARABLE: {_key(row)} "
                      f"old={old['verified']}/{old['applicable']} new={n}/{d}")
                return False
            provisional = True

    row.update(status="PARTIAL", verified=str(n), applicable=str(d),
               scope_provisional=str(int(provisional)))
    rows[_key(row)] = row
    _write(rows, path)
    return True


def scoreboard(path=LEDGER):
    rows = _rows(path)
    by_checkpoint = {}
    partials = []
    for row in rows.values():
        if row["status"] == "PARTIAL":
            n, d = ((float(row["verified"]), float(row["applicable"]))
                    if row["gate"].startswith("P7.")
                    else (int(row["verified"]), int(row["applicable"])))
            c = n / d
            effort = pareto_effort_fraction(c)
            partials.append({"class": row["class"], "level": row["level"],
                             "spec": row["spec"], "gate": row["gate"],
                             "verified": n, "applicable": d, "coverage": c,
                             "pareto_effort": effort,
                             "provisional": row["scope_provisional"] == "1"})
        elif row["status"] == "PASS":
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
    accepted = sum(r["status"] == "PASS" for r in rows.values())
    fractional = sum(x["coverage"] for x in partials)
    return {"passed_gates": accepted, "total_gates": TOTAL,
            "gate_percent": 100 * accepted / TOTAL,
            "measured_gate_equivalents": accepted + fractional,
            "measured_percent": 100 * (accepted + fractional) / TOTAL,
            "partial_gates": sorted(partials, key=lambda x:
                                    (x["class"], x["level"], x["spec"], x["gate"])),
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
    print(f"Best-observed fractional gate coverage (NOT PASS): "
          f"{result['measured_gate_equivalents']:.3f}/{TOTAL} "
          f"({result['measured_percent']:.4f}%, provisional where noted)")
    for p in result["partial_gates"]:
        tentative = " [provisional scope]" if p["provisional"] else ""
        unit = "DPS objective" if p["gate"].startswith("P7.") else "verified"
        print(f"  {p['class']} L{p['level']} {p['spec']} {p['gate']}: "
              f"{p['verified']:g}/{p['applicable']:g} "
              f"({100 * p['coverage']:.1f}% {unit}, "
              f"{100 * p['pareto_effort']:.1f}% Pareto-modeled work){tentative}")
    print(f"Whole checkpoints: {result['certified_checkpoints']}/148; "
          f"11/11 gate candidates: {result['complete_candidates']}")
    print("Unlinked/mismatched compatibility IDs never certify a whole checkpoint.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
