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
    prepared_spell_id, replace_cast_spell_id,
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
    # MythicSim's ordinary multi-target contract requires IDENTICAL
    # target definitions. They are still distinct native runtime units
    # with target positions 0 and 1; names must not encode identity.
    base_target["name"] = "World candidate mob"
    other = copy.deepcopy(base_target)
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
    # The options API is a *proposal* source, not an assertion that a rank
    # exists in this particular prepared actor. At L30 it suggested Drain
    # Life 403686 but real Rust prepared rank was 709. Require the actual
    # spellbook's identity before paying the APL.
    available = {
        name: prepared_spell_id(prepared, name)
        for name in ("immolate", "bane_of_agony", "siphon_life",
                     "corruption", "drain_life", "life_tap")
    }
    if any(id is None for id in available.values()):
        raise RuntimeError("Native prepared L30 Warlock missing actual APL abilities: "
                           + json.dumps(available))
    option_drain = requested["native_spell_ids"]["drain life"]
    real_drain = available["drain_life"]
    policy["native_prepared_spell_ids"] = available
    policy["proposed_drain_life_spell_id"] = option_drain
    if real_drain != option_drain:
        replaced = replace_cast_spell_id(apl, option_drain, real_drain)
        proposed_replaced = replace_cast_spell_id(
            requested_rolling_apl, option_drain, real_drain)
        if replaced < 1 or proposed_replaced < 1:
            raise RuntimeError("Failed to replace inactive native Drain Life proposal rank")
        request.write_text(json.dumps(req, indent=2) + "\n")
        call([binary, "prepare", "--request", request,
              "--actor-level", "30", "--outfile", prepared_path], seconds=120)
        prepared = json.loads(prepared_path.read_text())
        if prepared_spell_id(prepared, "drain_life") != real_drain:
            raise RuntimeError("Rust preparer changed previously verified Drain Life rank")
    policy["native_prepared_fear_id"] = prepared_spell_id(prepared, "fear")
    policy["native_prepared_health_funnel_id"] = prepared_spell_id(
        prepared, "health_funnel")
    policy["native_prepared_wand_id"] = prepared_spell_id(prepared, "shoot")
    call([binary, "sim", "--infile", prepared_path,
          "--rng-mode", "balanced", "--outfile", paid_path], seconds=240)
    paid = json.loads(paid_path.read_text())
    metrics = paid["result"]["raidMetrics"]["parties"][0]["players"][0]
    damage = [0., 0.]
    casts = [0, 0]
    casts_by_spell = {}
    for action in metrics.get("actions", []):
        spell_id = (action.get("id") or {}).get("spellId")
        target_casts = 0
        for index, target in enumerate((action.get("targets") or [])[:2]):
            damage[index] += float(target.get("damage") or 0.)
            n = int(target.get("casts") or 0)
            casts[index] += n
            target_casts += n
        if type(spell_id) is int:
            casts_by_spell[str(spell_id)] = (
                casts_by_spell.get(str(spell_id), 0) + target_casts)

    # A source-owned 30%-player-HP predicate is never true in a stationary
    # fight without incoming damage. Zero conditioned Drain Life casts is
    # correct here; requiring them would turn a *healthy* Warlock into a
    # spurious failure. Prove castability separately with a real paid Rust
    # spell-only APL and the same prepared actor/equipment/pet.
    direct_request = copy.deepcopy(req)
    actor(direct_request)["rotation"]["priorityList"] = [
        {"action": {"castSpell": {"spellId": {"spellId": real_drain}}}}
    ]
    direct_src = args.out / "source_native_drain_cast_request.json"
    direct_prepared = args.out / "prepared_native_drain_cast.json"
    direct_paid = args.out / "paid_native_drain_cast.json"
    direct_src.write_text(json.dumps(direct_request, indent=2) + "\n")
    call([binary, "prepare", "--request", direct_src, "--actor-level", "30",
          "--outfile", direct_prepared], seconds=120)
    direct_p = json.loads(direct_prepared.read_text())
    if prepared_spell_id(direct_p, "drain_life") != real_drain:
        raise RuntimeError("Native Drain Life cast probe prepared an unexpected spell")
    call([binary, "sim", "--infile", direct_prepared,
          "--rng-mode", "balanced", "--outfile", direct_paid], seconds=240)
    direct_result = json.loads(direct_paid.read_text())
    direct_metrics = direct_result["result"]["raidMetrics"]["parties"][0]["players"][0]
    direct_casts = 0
    for action in direct_metrics.get("actions", []):
        if (action.get("id") or {}).get("spellId") == real_drain:
            direct_casts += sum(
                int(t.get("casts") or 0) for t in action.get("targets", [])
            )

    # The two encounter units must both be actually damaged by native
    # Warlock actions. This is necessary, NOT sufficient, to certify an
    # overlapping world pull, and does not prove all four DoTs landed.
    result = {
        "objective": "source-native single-fight two-target APL diagnostic",
        "world_100_mob_result": False,
        "50_percent_next_pull_executed": False,
        "world_two_simultaneously_living_mob_ACKs": False,
        "candidate": policy,
        "targets": ["native target index 0", "native target index 1"],
        "native_paid_damage_by_target": damage,
        "native_paid_casts_by_target": casts,
        "native_paid_casts_by_spell_id": casts_by_spell,
        "native_paid_drain_life_casts_under_30pct_guard": casts_by_spell.get(str(real_drain), 0),
        "native_drain_life_unconditional_paid_casts": direct_casts,
        "low_health_condition_ever_proved_in_this_stationary_test": False,
        "native_paid_dps": metrics.get("dps", {}).get("avg"),
        "native_two_target_damage_observed": all(v > 0 for v in damage),
        "not_a_world_chain_or_target_hp_threshold_test": True,
    }
    (args.out / "two_target_diagnostic.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n")
    print("NATIVE_WARLOCK_TWO_TARGET_DIAGNOSTIC", json.dumps(result), flush=True)
    if not result["native_drain_life_unconditional_paid_casts"]:
        raise RuntimeError("Verified prepared Drain Life rank failed paid native cast-only probe")
    if not result["native_two_target_damage_observed"]:
        raise RuntimeError(
            "Rust native APL did not damage both targets; see paid_two_target.json")


if __name__ == "__main__":
    main()
