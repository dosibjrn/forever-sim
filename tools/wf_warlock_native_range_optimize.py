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
import tempfile
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


def live_native_frontier_evaluator(
    command: list[str], *, binary: Path, target_hp: float,
    scorer_command: list[str], artifact_dir: Path,
    run_command=None,
):
    """Ask a live native source producer for the next competing frontier.

    The producer must return native-prepared source paths and original native
    refusal records, NOT Python-asserted gameplay legality or mock measurements.
    The existing Work1 scorer and strict ACK/full-recovery adapter then decide
    which alternatives are actually comparable.
    """
    if not command:
        raise ValueError("native frontier producer command required")
    if run_command is None:
        run_command = subprocess.run

    def evaluate(**request: Any):
        folder = Path(tempfile.mkdtemp(prefix="source-frontier-", dir=artifact_dir))
        completed = run_command(
            command, input=json.dumps(request), capture_output=True,
            text=True, timeout=1800, check=False,
        )
        if completed.returncode:
            raise RuntimeError(
                f"native frontier producer exit {completed.returncode}: "
                + completed.stderr[-1500:]
            )
        payload = json.loads(completed.stdout)
        if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
            raise ValueError("native frontier producer must return JSON entries")
        manifest = folder / "native-prepared-manifest.json"
        manifest.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
        from tools.wf_warlock_native_range_scored_adapter import evaluate_request
        return evaluate_request(
            request, manifest=manifest, binary=binary, target_hp=target_hp,
            scorer_command=scorer_command, artifact_dir=folder,
        )

    return evaluate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-level", type=int, default=20)
    parser.add_argument("--end-level", type=int, default=60)
    parser.add_argument("--level-stride", type=int, default=10)
    parser.add_argument("--mob-count", type=int, default=3)
    parser.add_argument("--budget", type=int, default=100)
    parser.add_argument("--beam-width", type=int, default=3)
    parser.add_argument("--mode", choices=("independent", "continuing"),
                        default="independent",
                        help="Independent native-prepared per-level rankings (default), "
                             "or source-attested continuing sampled paths")
    parser.add_argument("--rng-mode", default="balanced")
    parser.add_argument("--iterations", type=int, default=1)
    evaluator = parser.add_mutually_exclusive_group(required=True)
    evaluator.add_argument("--evaluator-command",
                           help="Exact source-native evaluator command; JSON stdin/list stdout")
    evaluator.add_argument("--native-prepared-manifest", type=Path,
                           help="Native-produced prepared frontier files for Work1 scorer")
    evaluator.add_argument("--native-frontier-command",
                           help="Live native source producer; JSON request stdin, "
                                "prepared entries/refusals JSON stdout")
    parser.add_argument("--native-binary", type=Path,
                        help="Exact pinned native executable for manifest scoring")
    parser.add_argument("--native-target-hp", type=float,
                        help="Exact native 2D world target HP for manifest scoring")
    parser.add_argument("--native-scorer-command",
                        default=sys.executable + " tools/wf_warlock_native_candidate_scoring.py",
                        help="Work1 native prepared-candidate scorer CLI")
    parser.add_argument("--native-receipts-dir", type=Path,
                        help="Directory retaining original native scorer raw receipts")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if (args.native_prepared_manifest is not None
            or args.native_frontier_command is not None):
        if (args.native_binary is None or args.native_target_hp is None
                or args.native_receipts_dir is None):
            parser.error("native manifest requires --native-binary, --native-target-hp "
                         "and --native-receipts-dir")
        args.native_receipts_dir.mkdir(parents=True, exist_ok=True)
        if args.native_frontier_command is not None:
            native_evaluator = live_native_frontier_evaluator(
                shlex.split(args.native_frontier_command),
                binary=args.native_binary, target_hp=args.native_target_hp,
                scorer_command=shlex.split(args.native_scorer_command),
                artifact_dir=args.native_receipts_dir,
            )
        else:
            from tools.wf_warlock_native_range_scored_adapter import evaluate_request
            def native_evaluator(**request: Any):
                return evaluate_request(
                    request, manifest=args.native_prepared_manifest,
                    binary=args.native_binary, target_hp=args.native_target_hp,
                    scorer_command=shlex.split(args.native_scorer_command),
                    artifact_dir=args.native_receipts_dir,
                )
    else:
        native_evaluator = native_command_evaluator(
            shlex.split(args.evaluator_command))
    result = optimize(
        args.start_level, args.end_level, args.level_stride,
        args.mob_count, args.budget,
        evaluate=native_evaluator,
        beam_width=args.beam_width, rng_mode=args.rng_mode,
        iterations=args.iterations, recover_to_full=True, mode=args.mode,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "status": result["status"], "levels": result["sampled_levels_completed"],
        "examined": result["native_candidates_examined"],
        "ranked": len(result["ranked_alternatives"]),
        "out": str(args.out),
    }, sort_keys=True))
    return 0 if result["status"] in ("SAMPLED_NATIVE_PATH_RANKED",
                                     "INDEPENDENT_NATIVE_ANCHORS_RANKED") else 2


if __name__ == "__main__":
    raise SystemExit(main())
