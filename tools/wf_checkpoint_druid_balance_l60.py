#!/usr/bin/env python3
"""One real P1–P7.5 checkpoint audit through the canonical live gate CLI.

This does not award a checkpoint by parsing old JSON evidence. It invokes the
actual providers anew and reports their unmodified verdicts and missing runners.
A final certified 1/148 needs gate evidence + integrator acceptance, not a
handwritten status flag or this diagnostic wrapper.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATES = (*[f"P{i}" for i in range(1, 7)], *[f"P7.{i}" for i in range(1, 6)])


def analyze_live_result(report: dict) -> dict:
    """Fail closed on partial/malformed subprocess output."""
    if not isinstance(report, dict):
        raise ValueError("INVALID_LIVE_GATE_OUTPUT")
    if (report.get("class"), report.get("level"), report.get("spec"), report.get("gate")) != (
            "druid", 60, "balance", "all"):
        raise ValueError("WRONG_CHECKPOINT_OR_GATE_SET")
    rows = report.get("results")
    if not isinstance(rows, list) or [row.get("gate") for row in rows if isinstance(row, dict)] != list(GATES):
        raise ValueError("MISSING_OR_REORDERED_REAL_GATES")
    result = {}
    for row in rows:
        gate, status = row["gate"], row.get("status")
        if status not in ("PASS", "FAIL", "BLOCKED"):
            raise ValueError("INVALID_GATE_STATUS:" + gate)
        reasons = row.get("reasons")
        if not isinstance(reasons, list) or any(not isinstance(x, str) for x in reasons):
            raise ValueError("INVALID_GATE_REASONS:" + gate)
        if status == "PASS" and reasons:
            raise ValueError("FAKE_GATE_PASS_WITH_FAILURES:" + gate)
        if status != "PASS" and not reasons:
            raise ValueError("UNEXPLAINED_GATE_FAILURE:" + gate)
        if gate not in ("P1", "P2") and status == "PASS":
            proof = row.get("runtime_proof")
            if not isinstance(proof, dict) or proof.get("executed") is not True or any(
                not isinstance(proof.get(k), str) or not proof[k]
                for k in ("engine_revision", "source_revision", "run_id")
            ):
                raise ValueError("NO_REAL_RUNTIME_PROOF:" + gate)
        result[gate] = {"status": status, "reasons": reasons}
        if row.get("runtime_proof"):
            result[gate]["runtime_proof"] = row["runtime_proof"]
    return {
        "checkpoint": "druid:L60:balance",
        "gate_status": result,
        "live_gate_pass_count": sum(x["status"] == "PASS" for x in result.values()),
        "total_required_gates": len(GATES),
        "pending": [gate for gate, x in result.items() if x["status"] != "PASS"],
        "all_live_providers_pass": all(x["status"] == "PASS" for x in result.values()),
        "checkpoint_certified": False,
        "checkpoint_certification_reason": "REQUIRES_INDEPENDENT_PRODUCTION_EVIDENCE_AND_INTEGRATOR_PROMOTION",
    }


def audit(root: Path, *, timeout_s: int = 900) -> dict:
    cmd = [sys.executable, str(root / "tools" / "wf_gate.py"),
           "--class", "druid", "--level", "60", "--spec", "balance", "--gate", "all"]
    started = datetime.now(timezone.utc).isoformat()
    try:
        finished = subprocess.run(cmd, cwd=str(root), text=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  timeout=timeout_s, check=False)
        report = json.loads(finished.stdout)
        result = analyze_live_result(report)
        if (finished.returncode == 0) != result["all_live_providers_pass"]:
            raise ValueError("LIVE_EXIT_STATUS_DISAGREES_WITH_GATES")
        result["runner_exit_code"] = finished.returncode
        result["runner_stderr_tail"] = finished.stderr[-3000:]
    except (subprocess.TimeoutExpired, ValueError, OSError, json.JSONDecodeError) as exc:
        result = {
            "checkpoint": "druid:L60:balance",
            "gate_status": {},
            "pending": list(GATES),
            "checkpoint_certified": False,
            "audit_error": type(exc).__name__ + ":" + str(exc)[:300],
            "runner_exit_code": None,
        }
    result["started_utc"] = started
    result["live_entrypoint"] = "tools/wf_gate.py --class druid --level 60 --spec balance --gate all"
    try:
        result["live_runner_sha256"] = hashlib.sha256(
            (root / "tools" / "wf_gate.py").read_bytes()).hexdigest()
    except OSError:
        result["live_runner_sha256"] = None
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args()
    result = audit(ROOT, timeout_s=args.timeout)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"checkpoint": result["checkpoint"], "pending": result["pending"],
                      "live_gate_pass_count": result.get("live_gate_pass_count"),
                      "audit_error": result.get("audit_error"),
                      "checkpoint_certified": False}))
    # Diagnostic wrapper returns nonzero on incomplete gates, as it should.
    return 1 if result["pending"] else 0


if __name__ == "__main__":
    sys.exit(main())
