#!/usr/bin/env python3
"""P1 selected-Rust single-action effect diagnostic; never a formal gate.

A Go RaidSimRequest is narrowed to one existing castSpell action and an
otherwise identical no-action control. Both requests go through MythicSim's
PreparedV2 prepare and sim APIs; the positive request is also applied to the
existing live gsim 2D world bridge. MythicSim owns spell/rank availability
and all combat mechanics. Forever does not use a Python spellbook, trainer
ledger, source-index eligibility check, or GameIR action to veto the native
request.

Source inventory is consulted only after execution to display diagnostic
candidate-scope progress. It never blocks or changes the native call.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.engine_client.native_p1_effect_probe import (
    native_single_action_pair,
    run_native_p1_direct_effect_probe,
)
from tools.p1_native_progress import native_p1_progress
from tools.p1_native_source_inventory import inventory

VERIFIED_EFFECT = "NATIVE_DIRECT_BEHAVIOR_VERIFIED"


def run_native(
    binary: Path,
    request: dict,
    *,
    class_key: str,
    level: int,
    spell_id: int,
    timeout_s: float = 120.0,
    root: Path = ROOT,
    db_path: Path | None = None,
    target_count: int = 2,
    mob_health: float | None = 1200.0,
    iterations: int = 10,
    seed: int = 647003,
) -> dict:
    """Run native first; source inventory can annotate progress but cannot veto."""
    report = run_native_p1_direct_effect_probe(
        binary=binary,
        engine_root=root / "integrations" / "mythicsim-rust" / "engine",
        request=request,
        spell_id=spell_id,
        timeout_seconds=timeout_s,
        iterations=iterations,
        seed=seed,
        target_count=target_count,
        world_mob_health=mob_health,
    )
    report.update({
        "class": class_key,
        "level": level,
        "spell_id": spell_id,
        "p1_certified": False,
    })

    # Candidate inventory is diagnostic-only, after the native call. In
    # particular, missing or non-castable Python source metadata never blocks
    # an explicit request from reaching MythicSim.
    try:
        scope = inventory(class_key, level, root=root, db_path=db_path)
        candidates = {row["spell_id"] for row in scope["candidates"]}
        known = candidates | {row["spell_id"] for row in scope["separate"]}
        report["source_candidate_membership"] = spell_id in candidates
        report["source_scope_membership"] = spell_id in known
        runtime_results = []
        if spell_id in known:
            runtime_results.append({
                "spell_id": spell_id,
                "status": report.get("status"),
                "proof_kind": report.get("proof_kind"),
                "executor": report.get("executor"),
                "native_executed": report.get("native_executed") is True,
                "controlled_behavior_assertion_passed":
                    report.get("controlled_behavior_assertion_passed") is True,
                "observable_effects": report.get("observable_effects") or {},
            })
        report["p1_native_progress"] = native_p1_progress(scope, runtime_results)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # A diagnostic denominator failure is not a native execution veto.
        report["p1_native_progress_error"] = (
            f"{type(exc).__name__}:{exc}"
        )
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True,
                        help="Go RaidSimRequest JSON; not a PreparedV2 report")
    parser.add_argument("--class", dest="class_key", required=True)
    parser.add_argument("--level", type=int, required=True)
    parser.add_argument("--spell-id", type=int, required=True)
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--seed", type=int, default=647003)
    parser.add_argument("--targets", type=int, default=2)
    parser.add_argument("--mob-health", type=float, default=1200.0)
    args = parser.parse_args(argv)
    try:
        report = run_native(
            args.binary.resolve(),
            json.loads(args.request.read_text(encoding="utf-8")),
            class_key=args.class_key,
            level=args.level,
            spell_id=args.spell_id,
            timeout_s=args.timeout_s,
            target_count=args.targets,
            mob_health=args.mob_health,
            iterations=args.iterations,
            seed=args.seed,
        )
        print(json.dumps(report, sort_keys=True, allow_nan=False))
        return 0 if report.get("status") == VERIFIED_EFFECT else 2
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(
            "NOT_TESTED: " + type(exc).__name__ + ": " + str(exc),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
