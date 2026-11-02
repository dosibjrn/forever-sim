#!/usr/bin/env python3
"""Bounded direct execution of the existing live P1-P7.5 production gates.

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
    """Execute one REAL gate in an isolated process, with an absolute timeout."""
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
    verified = result.get("pass_count")
    applicable = result.get("reachability_count")
    if (type(verified) is int and type(applicable) is int and applicable > 0
            and 0 <= verified <= applicable):
        # Comparable executed production rank probes, not a gate PASS.
        response["verified"] = verified
        response["applicable"] = applicable
    for key in ("production_engine", "engine_id", "source_id",
                "source_context_sha256", "real_source_search_evaluated",
                "real_catalogue_top5_items_scored"):
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
    print("Only measured verified/applicable is partial coverage; BLOCKED/TIMEOUT is never PASS.")
    print("GATE    RESULT   REAL MEASURED    BACKEND            FIRST BLOCKER")
    for row in probe_all(args.class_key, args.level, args.spec,
                         per_gate_s=args.gate_seconds, total_s=args.total_seconds):
        measured = (f"{row['verified']}/{row['applicable']}" if "verified" in row
                    else f"{row['real_catalogue_top5_items_scored']} scored items"
                    if "real_catalogue_top5_items_scored" in row else "-")
        engine = str(row.get("production_engine") or row.get("engine_id") or "-")[:18]
        print(f"{row['gate']:<7} {row['status']:<8} {measured:<16} {engine:<18} {str(row.get('reason', ''))[:110]}")
    print("Read-only diagnostic. Only Merge may record accepted PASS/PARTIAL in M1.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
