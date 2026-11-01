#!/usr/bin/env python3
"""Source-only P1 input matrix, no GameIR, gsim or unexecuted Rust effects.

Exactly 18 requested class-level inventories. This validates that P1 can
enumerate *what to test* independently of the combat implementation, NOT
that MythicSim implements those spells. The output never claims P1 PASS.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.p1_native_source_inventory import CLASSES, inventory


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--classes", nargs="+", default=sorted(CLASSES))
    p.add_argument("--levels", nargs="+", type=int, default=(20, 60))
    p.add_argument("--json", action="store_true", help="Print run-derived inventory to stdout")
    args = p.parse_args(argv)
    if any(x not in CLASSES for x in args.classes) or any(not 1 <= x <= 60 for x in args.levels):
        p.error("Invalid class or level")
    results = []
    for cls in args.classes:
        for level in args.levels:
            source = inventory(cls, level)
            states = Counter(x["status"] for x in source["separate"])
            results.append({
                "class":cls, "level":level,
                "candidate_count":source["candidate_count"],
                "non_relevant":states["NOT_RELEVANT_TO_SIMULATION"],
                "native_auto":states["NATIVE_AUTO_ATTACK"],
                "pet_actions":states["PET_ACTION"],
                "noncastable_source_records":states["NOT_A_PROVEN_CASTABLE_ACTION"],
                "source_acquisition_unproven":sum(
                    x["status"]=="POTENTIALLY_AVAILABLE_AT_LEVEL_NOT_PROVEN_LEARNED"
                    for x in source["candidates"]),
                "engine_effects_tested":0,
                "status":"SOURCE_INPUT_READY_NATIVE_EFFECT_EXECUTION_PENDING",
                "p1_certified":False,
            })
            if not args.json:
                row=results[-1]
                print(f"{cls:9} L{level:02d} candidates={row['candidate_count']:3d} "
                      f"nonrelevant={row['non_relevant']} auto={row['native_auto']} "
                      f"pets={row['pet_actions']} native_effects_tested=0")
    if len(results)!=len(args.classes)*len(args.levels) or not all(
            row["candidate_count"] > 0 or
            row["non_relevant"] > 0 or row["native_auto"] > 0
            for row in results):
        raise ValueError("EMPTY_SOURCE_INVENTORY_MATRIX")
    if args.json:
        print(json.dumps({"entries":results, "kind":"SOURCE_ONLY_NOT_P1_ACCEPTANCE"},
                         sort_keys=True))
    else:
        print(f"P1_SOURCE_INPUT_MATRIX {len(results)} cases; "
              "native_effects_tested=0, p1_certified=0")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
