#!/usr/bin/env python3
"""Native L30 100-mob serial-chain APL challengers. NO surrogate and NO rolling-pull claim."""
from __future__ import annotations
import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path

from wf_warlock_l30_direct_affliction_comparison import USER_AFFLICTION, make_apl
from wf_warlock_native_optimizer import (
    actor, call, native_level_equipment, native_pet_autocast_receipt,
    profile, set_native_pet, set_native_sustain_buffs,
)
from wf_warlock_rolling_apl import prepared_spell_id, replace_cast_spell_id
from live_two_world_pulls import run as native_world_chain


def challenge_apl(search, ids, variant):
    """One base policy and three separately paid variants, all Rust spell actions."""
    apl = make_apl(search, ids, affliction=True, filler=(
        "shadow bolt" if "bolt" in variant else "drain life"))
    if variant.startswith("immolate"):
        # Spell casting, DoT tick damage and mana cost all belong to Rust.
        immo = search.multi_apl([(ids["immolate"], "dot_missing")])
        # After conditional Life Tap, but before other DoTs and filler.
        apl[1:1] = immo
    return apl


def main():
    p = argparse.ArgumentParser()
    for key in ("binary", "source", "engine-tools", "out"):
        p.add_argument("--" + key, required=True, type=Path)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    binary = args.binary.resolve()
    req = json.loads(args.source.read_text())
    actor(req)["equipment"]["items"] = [{"id": 0} for _ in range(17)]
    req["encounter"]["targets"][0]["level"] = 30
    set_native_sustain_buffs(req)
    sys.path.insert(0, str(args.engine_tools.resolve()))
    import warlock_l20_native_search as search
    options = json.loads(call([binary, "options", "--class", "warlock", "--level", "30"], seconds=60))
    available = search.native_spell_candidates(options, req)
    ids = {}
    for key in ("immolate", "corruption", "agony", "siphon life",
                "shadow bolt", "drain life", "life tap"):
        row = next((x for x in available if key in x["name"].casefold()), None)
        if row is None:
            raise RuntimeError("Missing Rust native option: " + key)
        ids[key] = row["spell_id"]
    actor(req)["talentsString"] = USER_AFFLICTION
    actor(req)["rotation"]["priorityList"] = challenge_apl(search, ids, "baseline_drain")
    dps_gear, audit, hp_gear = native_level_equipment(binary, req, options, args.out, level=30)
    rows = []
    cases = [
        ("baseline_drain", "Succubus", "native_dps"),
        ("immolate_drain", "Succubus", "native_dps"),
        ("immolate_bolt", "Succubus", "native_dps"),
        ("immolate_drain", "Felhunter", "native_dps"),
        ("immolate_bolt", "Felhunter", "native_dps"),
        ("immolate_drain", "Succubus", "native_max_hp"),
        ("immolate_bolt", "Succubus", "native_max_hp"),
    ]
    for i, (variant, pet, gear) in enumerate(cases):
        folder = args.out / ("candidate_%02d" % i)
        folder.mkdir(exist_ok=True)
        req = copy.deepcopy(dps_gear if gear == "native_dps" else hp_gear)
        actor(req)["talentsString"] = USER_AFFLICTION
        set_native_pet(req, pet)
        actor(req)["rotation"]["priorityList"] = challenge_apl(search, ids, variant)
        request_path = folder / "source_request.json"
        prepared_path = folder / "prepared.json"
        row = dict(index=i, talents=USER_AFFLICTION, apl=variant,
                   pet=pet, gear=gear, status="INCOMPLETE", confirmed_kills=0)
        try:
            scenario = profile(req, level=30)
            request_path.write_text(json.dumps(scenario, indent=2) + "\n")
            call([binary, "prepare", "--request", request_path, "--actor-level", "30",
                  "--outfile", prepared_path], seconds=120)
            prepared = json.loads(prepared_path.read_text())
            row["native_pet_autocasts"] = native_pet_autocast_receipt(prepared, pet)
            # get_options may return inactive ranks. Reconcile EVERY proposed
            # cast with the actual prepared native spellbook before benchmarking.
            native = {key: prepared_spell_id(prepared, key.replace(" ", "_"))
                      for key in ids}
            row["prepared_spells"] = native
            required = ("immolate", "corruption", "siphon life", "drain life",
                        "life tap") if variant.startswith("immolate") else (
                        "corruption", "siphon life", "drain life", "life tap")
            for key in required:
                if native[key] is None:
                    raise RuntimeError("Prepared native spell missing: " + key)
            changed = 0
            for key, active in native.items():
                if active is not None and active != ids[key]:
                    changed += replace_cast_spell_id(
                        actor(scenario)["rotation"]["priorityList"], ids[key], active)
            if changed:
                request_path.write_text(json.dumps(scenario, indent=2) + "\n")
                call([binary, "prepare", "--request", request_path,
                      "--actor-level", "30", "--outfile", prepared_path], seconds=120)
            world = native_world_chain(binary, prepared_path, classic_mob_level=30,
                                       target_count=100, rng_mode="balanced")
            (folder / "world.json").write_text(json.dumps(world, indent=2) + "\n")
            row.update(status="COMPLETED", confirmed_kills=world["world_targets_killed"],
                       elapsed_s=world["world_elapsed_seconds"],
                       min_hp=world["minimum_native_actor_health"],
                       min_mana=world["minimum_native_actor_mana"])
        except (RuntimeError, ValueError, KeyError, OSError,
                subprocess.TimeoutExpired, AssertionError) as exc:
            row["error"] = str(exc)[-1200:]
        rows.append(row)
        (folder / "result.json").write_text(json.dumps(row, indent=2) + "\n")
        (args.out / "leaderboard.json").write_text(json.dumps(
            {"objective": "100 native serial-world mob deaths (not rolling pulls)",
             "gear_audit": audit, "rows": rows}, indent=2) + "\n")
        print("NATIVE_L30_CHALLENGER", json.dumps(row), flush=True)
    winners = sorted((x for x in rows if x["status"] == "COMPLETED"
                      and x["confirmed_kills"] == 100), key=lambda x: x["elapsed_s"])
    print("NATIVE_L30_CHALLENGER_WINNER", json.dumps(
        winners[0] if winners else {"status": "NO_COMPLETED_100_MOB_CASE"}), flush=True)


if __name__ == "__main__":
    main()
