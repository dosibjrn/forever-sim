#!/usr/bin/env python3
"""Paid L30 stationary native two-target DoT capability (NOT a 2D world run).

The single prepared Rust multi-target encounter must do genuine paid damage to
both distinct targets from actual native multidot casts. A 50%-HP switch
is deliberately NOT executed without an ACKed gsim world. This demonstrates native
target-side APL/DoT capability without inventing damage or claiming that the
existing ACK-serial 100-world-target chain has become overlapping.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

from wf_warlock_rolling_apl import (
    build_rolling_two_target_apl, build_stationary_native_multidot_smoke,
)
from wf_warlock_l30_direct_affliction_comparison import USER_AFFLICTION
from wf_warlock_native_optimizer import (
    actor, call, native_pet_autocast_receipt, profile, set_native_pet,
)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--engine-tools", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--pull-threshold", type=int, default=50)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    binary = args.binary.resolve()

    sys.path.insert(0, str(args.engine_tools.resolve()))
    from warlock_l20_native_search import native_spell_candidates

    options = json.loads(call(
        [binary, "options", "--class", "warlock", "--level", "30"], seconds=60))
    source = json.loads(args.source.read_text())
    req = profile(source, level=30)
    spells = native_spell_candidates(options, req)
    requested_rolling_apl, requested = build_rolling_two_target_apl(
        spells, pull_threshold=args.pull_threshold)
    # Native stationary two-target Fight has no enemy HP ledger: its parser
    # cannot execute a real 50%-HP retarget from world evidence. Test the
    # underlying two-live-target DoT capability separately without claiming
    # the requested rolling-world policy was executed.
    apl, policy = build_stationary_native_multidot_smoke(spells)
    policy["requested_rolling_policy"] = requested
    policy["unexecuted_rolling_apl"] = requested_rolling_apl
    player = actor(req)
    player["talentsString"] = USER_AFFLICTION
    player["name"] = "L30 Troll two-target native rolling Affliction"
    set_native_pet(req, "Succubus")
    player["rotation"]["priorityList"] = apl
    req["simOptions"]["iterations"] = 1
    req["simOptions"]["randomSeed"] = "4242"
    req["encounter"]["duration"] = 90
    # Two independent source-native targets from the SAME chosen template.
    # Rust owns both target actors, HP, dot ticking and target switching.
    base_target = req["encounter"]["targets"][0]
    base_target["name"] = "World candidate mob 0"
    other = copy.deepcopy(base_target)
    other["name"] = "World candidate mob 1"
    req["encounter"]["targets"] = [base_target, other]

    request = args.out / "source_two_target_request.json"
    prepared_path = args.out / "prepared_two_target.json"
    paid_path = args.out / "paid_two_target.json"
    request.write_text(json.dumps(req, indent=2) + "\n")
    call([binary, "prepare", "--request", request,
          "--actor-level", "30", "--outfile", prepared_path], seconds=120)
    prepared = json.loads(prepared_path.read_text())
    if (prepared["player"]["level"] != 30
            or prepared["player"]["class"] != "ClassWarlock"):
        raise RuntimeError("Native Rust prepared wrong actor")
    policy["native_pet_autocasts"] = native_pet_autocast_receipt(prepared, "Succubus")
    call([binary, "sim", "--infile", prepared_path,
          "--rng-mode", "balanced", "--outfile", paid_path], seconds=240)
    paid = json.loads(paid_path.read_text())
    metrics = paid["result"]["raidMetrics"]["parties"][0]["players"][0]
    damage = [0., 0.]
    casts = [0, 0]
    for action in metrics.get("actions", []):
        for index, target in enumerate((action.get("targets") or [])[:2]):
            damage[index] += float(target.get("damage") or 0.)
            casts[index] += int(target.get("casts") or 0)

    # The two encounter units must both be actually damaged by native
    # Warlock actions. This is necessary, NOT sufficient, to certify an
    # overlapping world pull, and does not prove all four DoTs landed.
    result = {
        "objective": "source-native single-fight two-target APL diagnostic",
        "world_100_mob_result": False,
        "50_percent_next_pull_executed": False,
        "world_two_simultaneously_living_mob_ACKs": False,
        "candidate": policy,
        "targets": ["World candidate mob 0", "World candidate mob 1"],
        "native_paid_damage_by_target": damage,
        "native_paid_casts_by_target": casts,
        "native_paid_dps": metrics.get("dps", {}).get("avg"),
        "native_two_target_damage_observed": all(v > 0 for v in damage),
        "not_a_world_chain_or_target_hp_threshold_test": True,
    }
    (args.out / "two_target_diagnostic.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n")
    print("NATIVE_WARLOCK_TWO_TARGET_DIAGNOSTIC", json.dumps(result), flush=True)
    if not result["native_two_target_damage_observed"]:
        raise RuntimeError(
            "Rust native APL did not damage both targets; see paid_two_target.json")


if __name__ == "__main__":
    main()
