#!/usr/bin/env python3
"""P1 selected-Rust single-action effect diagnostic; never a formal gate.

A Go RaidSimRequest is narrowed to one existing castSpell action and an
otherwise identical no-action control. Both requests go through MythicSim's
PreparedV2 prepare and sim APIs; the positive request is also applied to the
existing live gsim 2D world bridge. MythicSim owns spell/rank availability
and all combat mechanics. Forever does not use a Python spellbook, trainer
ledger, source-index eligibility check, or GameIR action to veto the native
request.

The diagnostic reports only native execution and observed behavior. It does
not maintain a Python source catalogue or a shadow progress score.
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
    target_count: int = 2,
    mob_health: float | None = 1200.0,
    iterations: int = 10,
    seed: int = 647003,
) -> dict:
    """Run the native request pair and return only Forever-boundary observations."""
    try:
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
    except Exception as exc:
        report = {
            "status": "ERROR",
            "stage": "native_adapter",
            "reason": f"{type(exc).__name__}:{exc}",
            "native_executed": False,
            "effect_observed": False,
            "p1_certified": False,
        }
    report.update({
        "class": class_key,
        "level": level,
        "spell_id": spell_id,
        "p1_certified": False,
    })

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
    parser.add_argument(
        "--targets", type=int, default=2,
        help="sequential 2D world targets; use 100 for the full P1 world scenario",
    )
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
    except Exception as exc:
        print(
            "NOT_TESTED: " + type(exc).__name__ + ": " + str(exc),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
