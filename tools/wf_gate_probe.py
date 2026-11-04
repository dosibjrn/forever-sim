#!/usr/bin/env python3
"""Bounded direct execution of the existing active P3-P6 and P7.1-P7.5 production gates.

This probes the SAME source-backed gate CLI; no cached evidence, ledger reads,
alternative simulator, or PASS recording. A timeout is NOT partial success.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from time import monotonic

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.wf_gate import GATES


def probe_gate(class_key: str, level: int, spec: str, gate: str,
               timeout_s: float, *, root: Path = ROOT) -> dict:
    """Execute one active gate in an isolated process, with an absolute timeout."""
    if gate not in GATES:
        return {"gate": gate, "status": "RETIRED",
                "reason": "GATE_NOT_IN_ACTIVE_ACCEPTANCE_SCOPE"}
    command = [sys.executable, str(root / "tools" / "wf_gate.py"),
               "--class", class_key, "--level", str(level),
               "--spec", spec, "--gate", gate]
    start = monotonic()
    try:
        completed = subprocess.run(command, cwd=root, capture_output=True,
                                   text=True, timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired:
        return {"gate": gate, "status": "TIMEOUT", "reason": "PRODUCTION_PROBE_BUDGET_EXHAUSTED",
                "elapsed_s": monotonic() - start}
    except OSError as exc:
        return {"gate": gate, "status": "ERROR", "reason": "EXECUTION_ERROR:" + str(exc),
                "elapsed_s": monotonic() - start}
    elapsed = monotonic() - start
    try:
        # Only process output from the code we just executed. Never open
        # stored JSON evidence or a previous run's result.
        payload = json.loads(completed.stdout.strip())
        if (payload.get("class") != class_key or payload.get("level") != level
                or payload.get("spec") != spec or payload.get("gate") != gate
                or not isinstance(payload.get("results"), list)
                or len(payload["results"]) != 1):
            raise ValueError("unexpected production checkpoint identity")
        result = payload["results"][0]
        status = result.get("status")
        if (result.get("gate") != gate or status not in ("PASS", "FAIL", "BLOCKED")
                or (completed.returncode == 0) != (status == "PASS")):
            raise ValueError("inconsistent production gate verdict")
    except (ValueError, TypeError, KeyError, AttributeError, IndexError) as exc:
        return {"gate": gate, "status": "ERROR",
                "reason": "INVALID_LIVE_OUTPUT:" + str(exc),
                "elapsed_s": elapsed}
    reasons = result.get("reasons") or []
    response = {"gate": gate, "status": status, "elapsed_s": elapsed,
                "reason": str(reasons[0]) if reasons else ""}
    # Read the SAME calculated values as the production gate CLI.
    # No duplicate success/Pareto calculation and no unexecuted inventory.
    for key in ("verified", "applicable", "partial_coverage_percent",
                "pareto_effort_estimate_percent", "coverage_component",
                "dps_objective_actual", "dps_objective_required",
                "dps_objective_proximity_percent",
                "dps_objective_pareto_effort_estimate_percent",
                "dps_objective_scope", "dps_objective_provisional",
                "scope_provisional", "behavior_probes_executed",
                "production_engine", "engine_id", "source_id",
                "source_context_sha256", "real_source_search_evaluated",
                "real_catalogue_top5_items_scored", "source_policy_stat_witnesses",
                "real_measured_stat_weights", "real_stat_probe_axis_selection",
                "real_catalogue_legal_items",
                "real_catalogue_slots_scored", "source_profile_production_build",
                "actual_search_result_status"):
        if key in result:
            response[key] = result[key]
    return response


def probe_all(class_key: str, level: int, spec: str, *,
              per_gate_s: float = 45.0, total_s: float = 120.0,
              root: Path = ROOT, gates=GATES) -> list[dict]:
    deadline = monotonic() + total_s
    results = []
    for gate in gates:
        remaining = deadline - monotonic()
        if remaining <= 0:
            results.append({"gate": gate, "status": "NOT_RUN",
                            "reason": "TOTAL_PROBE_BUDGET_EXHAUSTED"})
        else:
            results.append(probe_gate(class_key, level, spec, gate,
                                      min(per_gate_s, remaining), root=root))
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Run bounded real production gate probes without recording M1")
    parser.add_argument("--class", dest="class_key", required=True)
    parser.add_argument("--level", type=int, required=True)
    parser.add_argument("--spec", default="unrestricted")
    parser.add_argument("--gate-seconds", type=float, default=45)
    parser.add_argument("--total-seconds", type=float, default=120)
    args = parser.parse_args(argv)
    if not 1 <= args.level <= 60 or args.gate_seconds <= 0 or args.total_seconds <= 0:
        parser.error("level 1..60 and positive time budgets required")
    import re
    if not re.fullmatch("[a-z][a-z0-9_-]*", args.class_key) or not re.fullmatch(
            "[a-z][a-z0-9_-]*", args.spec):
        parser.error("class and spec must be lower-case source keys")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True, check=False)
    print("Live production gate probe | HEAD", head.stdout.strip() if head.returncode == 0 else "UNKNOWN")
    print("Verified success% and per-gate Pareto% are reported ONLY after executed production tests.")
    print("A * means provisional SUBCOMPONENT coverage, not total gate completion.")
    print("For P7, SUCCESS% means live DPS / required DPS (clamped), NOT gate success or sample count.")
    print("GATE    RESULT   VERIFIED     SUCCESS%   80/20%     ENGINE             COMPONENT / FIRST BLOCKER")
    for row in probe_all(args.class_key, args.level, args.spec,
                         per_gate_s=args.gate_seconds, total_s=args.total_seconds):
        measured = (f"{row['verified']}/{row['applicable']}" if "verified" in row else "-")
        mark = "*" if row.get("scope_provisional") else ""
        success = (f"{row['partial_coverage_percent']:.2f}%{mark}"
                   if "partial_coverage_percent" in row else "-")
        pareto = (f"{row['pareto_effort_estimate_percent']:.2f}%{mark}"
                  if "pareto_effort_estimate_percent" in row else "-")
        if "dps_objective_proximity_percent" in row:
            # These columns become *DPS objective proximity* and its
            # indicative Pareto curve, NOT production functionality or PASS.
            mark = "*"
            success = f"{row['dps_objective_proximity_percent']:.2f}%{mark}"
            pareto = f"{row['dps_objective_pareto_effort_estimate_percent']:.2f}%{mark}"
        engine = str(row.get("production_engine") or row.get("engine_id") or "-")[:18]
        detail = str(row.get("dps_objective_scope") or row.get("coverage_component") or row.get("reason") or "-")
        if "dps_objective_proximity_percent" in row:
            detail += (" (DPS "+str(row["dps_objective_actual"])+"/"+
                       str(row["dps_objective_required"])+")")
        if row.get("coverage_component") and row.get("reason"):
            detail += " | " + str(row["reason"])
        print(f"{row['gate']:<7} {row['status']:<8} {measured:<12} {success:<10} {pareto:<10} {engine:<18} {detail[:110]}")
        if row.get("gate") == "P3":
            diagnostic_keys = ("source_policy_stat_witnesses", "real_measured_stat_weights",
                               "real_catalogue_legal_items", "real_catalogue_slots_scored",
                               "source_profile_production_build", "actual_search_result_status")
            diagnostics = {key: row[key] for key in diagnostic_keys if key in row}
            print("P3_SOURCE_DIAGNOSTICS " + json.dumps(diagnostics, ensure_ascii=False, sort_keys=True))
    print("Read-only diagnostic. Only Merge may record accepted PASS/PARTIAL in M1.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
