#!/usr/bin/env python3
"""Generic *diagnostic* P1 paired effect experiment on real gsim GameIR/CombatRuntime.

The required gsim-2D <-> native MythicSim Rust spell-control session is not yet
implemented by the pinned Rust executable.  This runner NEVER claims P1 PASS,
and --backend hybrid-rust fails closed rather than substituting gsim results.

No mock spells, arbitrary PASS ledger, 100-mob run or historical evidence input.
The only deliberately artificial things are the toy enemy's health/hit cadence
and a zero-EFFECT copy of the actual sourced action (same costs/timing).
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.p1_ability_inventory import source_inventory
from tools.p1_toy_scenario import (
    TOY_MOB_HP, EXTRA_PLAYER_HP, MOB_HIT, SWING_SECONDS,
    _starting_state, _numeric, observable_state, _run_one, compare_action,
)
from tools.wf_gate_p1_live import P1_DEFAULT_SCENARIO

PROOF_KIND = "GSIM_ABLATION_DIAGNOSTIC_NOT_HYBRID_RUST_OR_P1_PASS"


def _source_actions(root: Path, *, class_key="druid", level=20,
                    spec="feral-cat", scenario=P1_DEFAULT_SCENARIO):
    """Compatibility wrapper for existing real-source Druid L20 tests."""
    ir, selected, mapped, live_p1, _nonimpact = source_inventory(
        root, class_key, level, spec=spec, scenario=scenario)
    return ir, selected, mapped, live_p1


def run_gsim(root=ROOT, *, class_key="druid", level=20, spec="feral-cat",
             scenario=P1_DEFAULT_SCENARIO, ability_id=None):
    """Run source-indexed, class-neutral production-gsim A/B probes.

    Pass/failed is measured only by executing live GameIR and CombatRuntime.
    Spec identifies the requested checkpoint; without a pinned talent
    allocation this uses all source-legal class-level spells, not a fabricated
    spec-specific talent allocation.
    """
    ir, inventory, mapped, live_p1, non_relevant = source_inventory(
        root, class_key, level, spec=spec, scenario=scenario)
    results = []
    for sid, row in sorted(inventory.items()):
        if ability_id is not None and sid != ability_id:
            continue
        action = mapped.get(sid)
        outcome = (compare_action(ir, action) if action is not None else
                   {"status": "MISSING_GAME_IR_ACTION", "difference": {}})
        results.append({"spell_id": sid, "name": row["name"],
                        "rank": row.get("rank_hint"),
                        "action_id": action.id if action is not None else None,
                        **outcome})
    if ability_id is not None and not results:
        raise ValueError("ABILITY_NOT_IN_P1_UNIVERSE:" + str(ability_id))
    observed = sum(x["status"] == "EFFECT_OBSERVED" for x in results)
    return {"class": class_key, "level": level, "spec": spec, "scenario": scenario,
            "proof_kind": PROOF_KIND,
            "p1_certified": False, "hybrid_rust_executed": False,
            "spec_ability_scope": "class_level_source_legal_union_no_fixed_talent_allocation",
            "live_p1_current_status": live_p1["status"],
            "checked": len(results), "observed": observed,
            "not_observed": len(results)-observed,
            "not_relevant_count": len(non_relevant),
            "not_relevant": sorted(non_relevant, key=lambda r:r["spell_id"]),
            "results": results}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backend", choices=("hybrid-rust", "gsim-diagnostic"),
                    default="hybrid-rust")
    ap.add_argument("--rust-binary", type=Path)
    ap.add_argument("--ability-id", type=int)
    ap.add_argument("--class", dest="class_key", default="druid")
    ap.add_argument("--level", type=int, default=20)
    ap.add_argument("--spec", default="feral-cat")
    ap.add_argument("--scenario", default=P1_DEFAULT_SCENARIO)
    args = ap.parse_args(argv)
    if args.backend == "hybrid-rust":
        # The existing transport has no source-action injection/ablation API.
        # Opening it is NOT equivalent to executing source-native spells.
        if args.rust_binary:
            from src.game.runtime.native_step_protocol import RustStepSession
            try:
                with RustStepSession(args.rust_binary) as _session:
                    raise RuntimeError("RUST_SOURCE_ACTION_ABLATION_API_NOT_IMPLEMENTED")
            except Exception as exc:
                print(f"BLOCKED: real Rust source-action session: {exc}", file=sys.stderr)
                return 2
        print("BLOCKED: genuine gsim-2D <-> Rust source-action ablation is not yet "
              "implemented; supply a real native session and action-control API. "
              "gsim-diagnostic is not P1 PASS.", file=sys.stderr)
        return 2
    try:
        report = run_gsim(class_key=args.class_key, level=args.level, spec=args.spec,
                          scenario=args.scenario, ability_id=args.ability_id)
    except Exception as exc:
        print("FAIL: " + type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    # Diagnostics never claim that the required hybrid-rust gate passed.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
