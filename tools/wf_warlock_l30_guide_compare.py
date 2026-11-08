#!/usr/bin/env python3
"""Native Rust L30 head-to-head of exact Icy Veins vs Mobalytics talents.

Each guide gets the SAME source-paid gear, Succubus and two matching APL
families (drain and native wand Shoot). The native Rust world actor persists
through 100 successive level-30 2D world kills. Do not infer overlapping pulls
or unsupported troll regeneration from this experiment.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations/mythicsim-rust"))
from live_two_world_pulls import run as native_world_chain
from wf_warlock_native_optimizer import (
    actor, call, native_level_equipment, native_pet_autocast_receipt,
    native_sustain_receipt, profile, set_native_pet, set_native_sustain_buffs,
)

GUIDE_RANKS = {
    "icy": {
        "Improved Corruption": 5,
        "Suppression": 4,
        "Grim Reach": 1,
        "Improved Bane of Agony": 2,
        "Pandemic": 3,
        "Malevolence": 3,
        "Nightfall": 2,
        "Siphon Life": 1,
    },
    "mobalytics": {
        "Improved Corruption": 5,
        "Suppression": 5,
        "Grim Reach": 2,
        "Improved Drains": 3,
        "Nightfall": 2,
        "Fel Concentration": 3,
        "Soul Siphon": 1,
    },
}
ICY_KNOWN_CODE = "04510020033201-0-0"

def talent_code(options, requested):
    trees = options["talents"]["trees"]
    matched = {}
    encoded = []
    for tree in trees:
        values = [0] * len(tree["talents"])
        for row in tree["talents"]:
            name = row["name"].casefold().strip()
            for target, count in requested.items():
                if name == target.casefold().strip():
                    if target in matched or count > row["max_rank"]:
                        raise ValueError("Duplicate/over-ranked talent: " + target)
                    matched[target] = row["field_name"]
                    values[row["index"]] = count
        encoded.append("".join(map(str, values)).rstrip("0") or "0")
    if set(matched) != set(requested):
        raise ValueError("Rust get_options missing talents: " + repr(set(requested) - set(matched)))
    if sum(requested.values()) != options["talents"]["points_available"]:
        raise ValueError("Wrong native talent budget")
    return "-".join(encoded), matched

def native_apl(search, ids, *, guide, filler):
    dot_names = ["corruption", "agony", "immolate"]
    if guide == "icy":
        dot_names.insert(0, "siphon life")
    actions = search.multi_apl([(ids[name], "dot_missing") for name in dot_names])
    if filler == "drain":
        actions.extend(search.multi_apl([(ids["drain life"], None)]))
    elif filler == "wand":
        actions.append({"action": {"castSpell": {"spellId": {"otherId": "OtherActionShoot"}}}})
    else:
        raise ValueError("Unknown filler " + filler)
    tap = search.mana_conditioned_apl(ids["life tap"], 45)
    tap["action"]["condition"] = {"and": {"vals": [
        tap["action"]["condition"],
        {"cmp": {"lhs": {"currentHealthPercent": {}},
                 "op": "OpGt", "rhs": {"const": {"val": "35%"}}}},
    ]}}
    return [tap, *actions]

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--engine-tools", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--guide", choices=tuple(GUIDE_RANKS), required=True)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    binary = args.binary.resolve()
    request = json.loads(args.source.read_text())
    actor(request)["race"] = "RaceTroll"
    actor(request)["name"] = "Warlock L30 Troll guide comparison"
    actor(request)["equipment"]["items"] = [{"id": 0} for _ in range(17)]
    request["encounter"]["targets"][0]["level"] = 30
    set_native_sustain_buffs(request)

    sys.path.insert(0, str(args.engine_tools.resolve()))
    import warlock_l20_native_search as search
    options = json.loads(call([binary, "options", "--class", "warlock", "--level", "30"], seconds=60))
    if options["class"] != "warlock" or options["level"] != 30:
        raise RuntimeError("Wrong Rust actor")
    codes = {name: talent_code(options, ranks)[0] for name, ranks in GUIDE_RANKS.items()}
    if codes["icy"] != ICY_KNOWN_CODE:
        raise RuntimeError("Icy screenshot does not match native metadata: " + codes["icy"])
    spells = search.native_spell_candidates(options, request)
    ids = {}
    for fragment in ("corruption", "agony", "immolate", "siphon life",
                     "drain life", "shadow bolt", "life tap"):
        candidates = [row for row in spells if fragment in row["name"].casefold()]
        if not candidates:
            raise RuntimeError("Rust lacks source spell " + fragment)
        ids[fragment] = candidates[0]["spell_id"]

    # Do one deterministic Rust gear search starting from the same Icy seed
    # in both jobs, so neither guide is favored in the gear selection.
    actor(request)["talentsString"] = codes["icy"]
    actor(request)["rotation"]["priorityList"] = search.multi_apl([
        (ids["corruption"], "dot_missing"), (ids["agony"], "dot_missing"),
        (ids["shadow bolt"], None)])
    gear_request, gear_audit, _ = native_level_equipment(
        binary, request, options, args.out, level=30)
    gear = [x["id"] for x in actor(gear_request)["equipment"]["items"]]
    if gear[16] == 0:
        raise RuntimeError("Shared native gear search did not equip a wand")
    report = {
        "guide": args.guide,
        "engine": "native Rust, 100 successive level-30 world kills",
        "talents": codes[args.guide],
        "icy_talents": codes["icy"],
        "mobalytics_talents": codes["mobalytics"],
        "ranks": GUIDE_RANKS[args.guide],
        "pet": "Succubus",
        "gear": gear,
        "gear_source": "same source-native paid L30 gear search from Icy seed",
        "target_type": "CMaNGOS level-30 ordinary melee proxy, not verified Forever mob",
        "movement": "2D world path between successive mobs, no 50% HP overlapping pulls",
        "rng": "balanced",
        "apl_family": "same Corruption/Agony/Immolate, plus Icy's talent-only Siphon Life; Life Tap below 45% mana above 35% health",
        "results": [],
    }
    (args.out / "comparison.json").write_text(json.dumps(report, indent=2) + "\n")
    for filler in ("drain", "wand"):
        folder = args.out / filler
        folder.mkdir(exist_ok=True)
        scenario = copy.deepcopy(gear_request)
        actor(scenario)["talentsString"] = codes[args.guide]
        set_native_pet(scenario, "Succubus")
        actor(scenario)["rotation"]["priorityList"] = native_apl(
            search, ids, guide=args.guide, filler=filler)
        scenario = profile(scenario, level=30)
        source_path = folder / "source_request.json"
        prepared_path = folder / "prepared.json"
        source_path.write_text(json.dumps(scenario, indent=2) + "\n")
        result = {
            "guide": args.guide, "filler": filler,
            "status": "INCOMPLETE", "confirmed_kills": 0,
            "talents": codes[args.guide], "pet": "Succubus", "gear": gear,
        }
        try:
            call([binary, "prepare", "--request", source_path,
                  "--actor-level", "30", "--outfile", prepared_path], seconds=120)
            prepared = json.loads(prepared_path.read_text())
            if prepared["player"]["level"] != 30 or prepared["player"]["class"] != "ClassWarlock":
                raise RuntimeError("Rust did not prepare a L30 Warlock")
            if filler == "wand":
                if not any((row.get("action_id") or {}).get("other_id") == "OtherActionShoot"
                           for row in prepared["player"].get("spells", [])):
                    raise RuntimeError("Rust did not register native wand Shoot")
                if prepared["melee"].get("auto_swing_ranged") is not True:
                    raise RuntimeError("Native wand auto-swing missing")
            result["native_pet_autocast"] = native_pet_autocast_receipt(prepared, "Succubus")
            result["native_sustain"] = native_sustain_receipt(prepared, scenario)
            world = native_world_chain(binary, prepared_path, classic_mob_level=30,
                                       target_count=100, rng_mode="balanced")
            (folder / "native_world.json").write_text(json.dumps(world, indent=2, allow_nan=False) + "\n")
            if (world["world_targets_killed"] != 100
                    or world.get("continuous_native_actor") is not True
                    or world.get("actual_2d_ack") is not True):
                raise RuntimeError("Missing 100 native world kills")
            result.update(status="COMPLETED", confirmed_kills=100,
                          elapsed_s=world["world_elapsed_seconds"],
                          seconds_per_mob=world["world_elapsed_seconds"]/100,
                          min_hp=world["minimum_native_actor_health"],
                          min_mana=world["minimum_native_actor_mana"],
                          paid_recovery=world["paid_recovery"])
        except (RuntimeError, ValueError, KeyError, AssertionError, OSError,
                subprocess.TimeoutExpired) as exc:
            result["error"] = str(exc)[-1800:]
            detail = exc.args[0] if isinstance(exc, AssertionError) and exc.args else None
            if (isinstance(detail, tuple) and len(detail) >= 5
                    and detail[0] == "RUST_TWO_WORLD_NATIVE_FAILED"
                    and type(detail[3]) is int):
                result["confirmed_kills"] = detail[3]
            hit = re.search(r"RUST_MULTI_WORLD_NATIVE_ACTOR_NOT_ALIVE:index=(\\d+)",
                            result["error"])
            if hit:
                result["confirmed_kills"] = max(0, int(hit.group(1)) - 1)
        report["results"].append(result)
        (folder / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        (args.out / "comparison.json").write_text(json.dumps(report, indent=2) + "\n")
        print("GUIDE_L30_NATIVE_100_MOBS", json.dumps(result), flush=True)
    print("GUIDE_L30_100_SUMMARY", json.dumps({
        "guide": args.guide, "talents": codes[args.guide],
        "gear": gear, "results": report["results"]}), flush=True)

if __name__ == "__main__":
    main()
