#!/usr/bin/env python3
"""Run every requested real-source P1 toy ablation, never read saved verdicts.

One bounded independent Python execution per class/level avoids engine/process
state leaking between checkpoints. Failures are reported; no absent case can
silently be considered successful.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.game.data.forever.registry import registered_class_keys


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--levels", type=int, nargs="+", default=(20, 60))
    p.add_argument("--classes", nargs="+", default=None)
    p.add_argument("--spec", default="unrestricted")
    p.add_argument("--strict", action="store_true",
                   help="Nonzero exit if any test cannot finish or any ability lacks an observed effect.")
    p.add_argument("--timeout-s", type=int, default=100)
    args = p.parse_args(argv)
    classes = tuple(args.classes or registered_class_keys())
    unknown = set(classes)-set(registered_class_keys())
    if unknown:
        p.error("unregistered classes: "+", ".join(sorted(unknown)))
    if not args.levels or any(not 1 <= n <= 60 for n in args.levels):
        p.error("levels must be in 1..60")
    rows = []
    for cls in classes:
        for level in args.levels:
            cmd = [sys.executable, str(ROOT/"tools"/"wf_p1_toy_ablation.py"),
                   "--backend", "gsim-diagnostic", "--class", cls, "--level", str(level),
                   "--spec", args.spec]
            try:
                result = subprocess.run(cmd, cwd=ROOT, capture_output=True,
                                        text=True, timeout=args.timeout_s, check=False)
                if result.returncode:
                    row = {"class": cls, "level": level, "status": "SETUP_ERROR",
                           "reason": result.stderr.strip()[-450:],
                           "returncode": result.returncode}
                else:
                    evidence = json.loads(result.stdout)
                    if evidence.get("class") != cls or evidence.get("level") != level:
                        raise ValueError("CHECKPOINT_IDENTITY_MISMATCH")
                    if evidence.get("p1_certified") or evidence.get("hybrid_rust_executed"):
                        raise ValueError("DIAGNOSTIC_FALSE_CERTIFICATION")
                    if evidence.get("checked", 0) == 0:
                        raise ValueError("EMPTY_TEST_EXECUTION")
                    row = {
                        "class": cls, "level": level,
                        "status": ("ALL_EFFECTS_OBSERVED" if evidence["observed"]==evidence["checked"]
                                   else "INCOMPLETE"),
                        "observed": evidence["observed"], "checked": evidence["checked"],
                        "not_relevant": evidence["not_relevant_count"],
                        "failed": [
                            {"spell_id": x["spell_id"], "name": x["name"],
                             "status": x["status"], "reason": x.get("errors", [])}
                            for x in evidence["results"] if x["status"] != "EFFECT_OBSERVED"
                        ],
                        "gate_certified": False,
                    }
            except (subprocess.TimeoutExpired, ValueError, json.JSONDecodeError) as exc:
                row = {"class": cls, "level": level, "status": "SETUP_ERROR",
                       "reason": type(exc).__name__ + ": " + str(exc)[:400]}
            rows.append(row)
            print(f"{cls:9} L{level:02d} {row['status']:24} "
                  f"{row.get('observed','-')}/{row.get('checked','-')} "
                  f"not_relevant={row.get('not_relevant','-')}", flush=True)
            for failure in row.get("failed", []):
                print(f"    {failure['spell_id']} {failure['name']}: {failure['status']} "
                      f"{failure['reason']}", flush=True)
            if row.get("reason"):
                print("    " + row["reason"], flush=True)
    errors = sum(x["status"] != "ALL_EFFECTS_OBSERVED" for x in rows)
    print("P1_TOY_MATRIX total={} observed_all={} gaps={} "
          "hybrid_rust_certified=0 p1_certified=0".format(
              len(rows), len(rows)-errors, errors), flush=True)
    if len(rows) != len(classes)*len(args.levels):
        raise AssertionError("MATRIX_COVERAGE_INCOMPLETE")
    return 1 if args.strict and errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
