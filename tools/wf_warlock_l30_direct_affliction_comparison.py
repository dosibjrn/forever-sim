#!/usr/bin/env python3
"""Direct native L30 100-world-mob comparison: user's exact Affliction vs Destro.

No 30s DPS preselection of talent, pet or APL finalists. Gear has two
source-native prepared variants (DPS and max-HP) and is *not* a global
100-mob gear optimum. Paid comparison means the actual retained Rust world
actor kills successive targets with native balanced RNG, including all
health, mana, mob damage and combat-time costs the selected engine implements.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
import sys
from pathlib import Path

from wf_warlock_native_optimizer import (
    actor, call, native_level_equipment, native_pet_autocast_receipt,
    native_sustain_receipt, profile, set_native_pet, set_native_sustain_buffs,
)
from live_two_world_pulls import run as native_world_chain

USER_AFFLICTION = "04510020033201-0-0"
OLD_DESTRO_COMPARATOR = "0-0-25512201021"


def exact_source_ranks(options, code):
    result = {}
    for part, tree in zip(code.split("-"), options["talents"]["trees"]):
        for talent in tree["talents"]:
            index = talent["index"]
            count = int(part[index]) if index < len(part) else 0
            if count:
                result[talent["field_name"]] = count
    return result


def make_apl(source_search, ids, *, affliction, filler):
    spells = []
    if affliction:
        spells.append((ids["siphon life"], "dot_missing"))
    spells.extend([
        (ids["corruption"], "dot_missing"),
        (ids["agony"], "dot_missing"),
    ])
    spells.append((ids[filler], None))
    result = source_search.multi_apl(spells)
    # Existing native APL predicates: Life Tap needs mana and a safe HP pool.
    action = source_search.mana_conditioned_apl(ids["life tap"], 45)
    action["action"]["condition"] = {"and": {"vals": [
        action["action"]["condition"],
        {"cmp": {
            "lhs": {"currentHealthPercent": {}}, "op": "OpGt",
            "rhs": {"const": {"val": "35%"}}}},
    ]}}
    return [action, *result]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--engine-tools", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    binary = args.binary.resolve()
    level = 30
    source = json.loads(args.source.read_text())
    source["encounter"]["targets"][0]["level"] = level
    actor(source)["name"] = "Warlock L30 Troll native"
    actor(source)["equipment"]["items"] = [{"id": 0} for _ in range(17)]
    set_native_sustain_buffs(source)
    sys.path.insert(0, str(args.engine_tools.resolve()))
    import warlock_l20_native_search as search

    options = json.loads(call(
        [binary, "options", "--class", "warlock", "--level", str(level)], seconds=60))
    if options["level"] != level or options["class"] != "warlock":
        raise RuntimeError("Wrong source-native actor")
    if options["talents"]["points_available"] != 21:
        raise RuntimeError("Wrong native talent point budget")
    expected = {
        "improvedCorruption": 5, "suppression": 4, "grimReach": 1,
        "improvedBaneOfAgony": 2, "pandemic": 3,
        "malevolence": 3, "nightfall": 2, "siphonLife": 1,
    }
    actual = exact_source_ranks(options, USER_AFFLICTION)
    if actual != expected:
        raise RuntimeError("User's exact 21-point Affliction code does not match native metadata: " +
                           repr(actual))

    available = search.native_spell_candidates(options, source)
    ids = {}
    for fragment in (
        "corruption", "agony", "siphon life",
        "shadow bolt", "drain life", "life tap",
    ):
        row = next((row for row in available if fragment in row["name"].casefold()), None)
        if row is None:
            raise RuntimeError("Missing native source spell: " + fragment)
        ids[fragment] = row["spell_id"]
    actor(source)["talentsString"] = OLD_DESTRO_COMPARATOR
    actor(source)["rotation"]["priorityList"] = search.multi_apl([
        (ids["corruption"], "dot_missing"),
        (ids["agony"], "dot_missing"),
        (ids["shadow bolt"], None),
    ])
    dps_gear, audit, hp_gear = native_level_equipment(
        binary, source, options, args.out, level=level)
    (args.out / "exact_user_affliction.json").write_text(json.dumps({
        "talents": USER_AFFLICTION, "native_ranks": actual,
        "comparison": OLD_DESTRO_COMPARATOR,
        "source_spell_ids": ids,
        "gear_source": "Rust get_options with required_level 1..30 only",
        "gear_search": "two native source gear baselines; no global 100-mob gear optimum",
        "selection": "No 30s DPS preselection of build, pet or APL",
        "objective": "100 consecutive native world kills, rank completed first then elapsed seconds",
    }, indent=2) + "\n")

    rows = []
    for gear_label, gear_base in (("native_dps", dps_gear), ("native_max_hp", hp_gear)):
        for label, build in (
            ("user_affliction", USER_AFFLICTION),
            ("prior_destro", OLD_DESTRO_COMPARATOR),
        ):
            for pet in ("Succubus", "Felhunter"):
                for filler in ("drain life", "shadow bolt"):
                    index = len(rows)
                    req = copy.deepcopy(gear_base)
                    actor(req)["talentsString"] = build
                    set_native_pet(req, pet)
                    actor(req)["rotation"]["priorityList"] = make_apl(
                        search, ids, affliction=(label=="user_affliction"), filler=filler)
                    scenario = profile(req, level=level)
                    folder = args.out / ("case_%02d" % index)
                    folder.mkdir(exist_ok=True)
                    request_path = folder / "source_request.json"
                    prepared_path = folder / "prepared.json"
                    request_path.write_text(json.dumps(scenario, indent=2) + "\n")
                    result = {
                        "candidate": index, "build": label, "talents": build,
                        "gear": gear_label, "pet": pet,
                        "apl": ("siphon_life+" if label=="user_affliction" else "") +
                               "corruption+agony+" + filler + "+life_tap_below45_mana_above35_hp",
                        "confirmed_kills": 0, "status": "INCOMPLETE",
                    }
                    try:
                        call([binary, "prepare", "--request", request_path,
                              "--actor-level", str(level), "--outfile", prepared_path], seconds=60)
                        prepared = json.loads(prepared_path.read_text())
                        result["native_pet_autocast_spells"] = native_pet_autocast_receipt(prepared, pet)
                        result["native_sustain"] = native_sustain_receipt(prepared, scenario)
                        world = native_world_chain(
                            binary, prepared_path, classic_mob_level=level,
                            target_count=100, rng_mode="balanced")
                        (folder / "native_world.json").write_text(
                            json.dumps(world, indent=2, allow_nan=False) + "\n")
                        result.update(
                            status="COMPLETED", confirmed_kills=world["world_targets_killed"],
                            elapsed_s=world["world_elapsed_seconds"],
                            seconds_per_mob=world["world_elapsed_seconds"]/100,
                            min_hp=world["minimum_native_actor_health"],
                            min_mana=world["minimum_native_actor_mana"],
                            paid_recovery=world["paid_recovery"],
                            native_damage_events=world["native_damage_events"],
                        )
                    except (RuntimeError, ValueError, KeyError, AssertionError, OSError,
                            subprocess.TimeoutExpired) as exc:
                        result["error"] = str(exc)[-1700:]
                        detail = exc.args[0] if isinstance(exc, AssertionError) and exc.args else None
                        if (isinstance(detail, tuple) and len(detail)>=5
                                and detail[0]=="RUST_TWO_WORLD_NATIVE_FAILED"
                                and type(detail[3]) is int):
                            result["confirmed_kills"]=detail[3]
                            result["native_damage_events_before_stop"]=detail[4]
                        m = re.search(r'RUST_MULTI_WORLD_NATIVE_ACTOR_NOT_ALIVE:index=(\d+)',
                                      result["error"])
                        if m:
                            result["confirmed_kills"]=max(0,int(m.group(1))-1)
                    (folder / "result.json").write_text(
                        json.dumps(result, indent=2) + "\n")
                    rows.append(result)
                    print("DIRECT_L30_100_MOB_PAID", json.dumps(result), flush=True)
                    (args.out / "comparison.json").write_text(
                        json.dumps({"candidate_count":len(rows),"rows":rows},
                                   indent=2, allow_nan=False) + "\n")

    winners = sorted(
        (row for row in rows if row["status"]=="COMPLETED"),
        key=lambda r:r["elapsed_s"])
    partial = sorted(
        (row for row in rows if row["status"]!="COMPLETED"),
        key=lambda r:-r["confirmed_kills"])
    summary = {
        "objective":"100 completed L30 mob kills, then lowest total elapsed seconds",
        "selection":"No 30s DPS preselection of build/pet/APL finalists",
        "source_gear": audit,
        "user_affliction":USER_AFFLICTION, "reference_destro":OLD_DESTRO_COMPARATOR,
        "winner":winners[0] if winners else None,
        "best_partial":partial[0] if partial else None,
        "completed":len(winners), "candidates":len(rows),
        "rows":rows,
    }
    (args.out/"comparison.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n")
    print("DIRECT_L30_100_MOB_COMPARISON", json.dumps({
        "completed":len(winners), "candidates":len(rows),
        "winner":summary["winner"], "best_partial":summary["best_partial"],
    }), flush=True)


if __name__ == "__main__":
    main()
