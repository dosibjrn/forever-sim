#!/usr/bin/env python3
"""One user invocation of the source-native level-range optimizer.

The command supplied with --evaluator-command is the exact native evaluator
adapter (Work1's source/native scorer). It receives a JSON request on stdin
for each active native frontier and returns a JSON list of paid receipts on
stdout. Forever does NOT simulate spells, recovery, or legal talent transitions.
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

# Allow both python -m tools... and python tools/... from repository root.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.v2.native_range_optimizer import optimize


def native_command_evaluator(command: list[str], *, timeout_s: float = 300):
    if not command:
        raise ValueError("an executable native evaluator command is required")

    def evaluate(**request: Any):
        completed = subprocess.run(
            command, input=json.dumps(request), capture_output=True,
            text=True, timeout=timeout_s, check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"native evaluator exit {completed.returncode}: "
                + completed.stderr[-1500:]
            )
        rows = json.loads(completed.stdout)
        if not isinstance(rows, list):
            raise ValueError("native evaluator must return a JSON list of receipts")
        return rows

    return evaluate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-level", type=int, default=20)
    parser.add_argument("--end-level", type=int, default=60)
    parser.add_argument("--level-stride", type=int, default=10)
    parser.add_argument("--mob-count", type=int, default=3)
    parser.add_argument("--budget", type=int, default=100)
    parser.add_argument("--beam-width", type=int, default=3)
    parser.add_argument("--rng-mode", default="balanced")
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--evaluator-command", required=True,
                        help="Exact source-native scorer command; JSON stdin/list stdout")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    result = optimize(
        args.start_level, args.end_level, args.level_stride,
        args.mob_count, args.budget,
        evaluate=native_command_evaluator(shlex.split(args.evaluator_command)),
        beam_width=args.beam_width, rng_mode=args.rng_mode,
        iterations=args.iterations, recover_to_full=True,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "status": result["status"], "levels": result["sampled_levels_completed"],
        "examined": result["native_candidates_examined"],
        "ranked": len(result["ranked_alternatives"]),
        "out": str(args.out),
    }, sort_keys=True))
    return 0 if result["status"] == "SAMPLED_NATIVE_PATH_RANKED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
