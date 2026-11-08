#!/usr/bin/env python3
"""Native Rust 100-world-mob coordinate search across talents, APL, pet and gear.

No enumerated seven-case recipe, no Python combat model, no 30-second DPS
selection. Mutations come from the canonical Rust source metadata and the
existing Forever optimizer's proposal generators. Each accepted improvement
is measured by the actual 100 native serial-world deaths.
NOT a rolling/overlap world simulator or an assertion of global optimality.
"""
from __future__ import annotations

import argparse
import copy
import json
import random
import re
import subprocess
import sys
from pathlib import Path

from wf_warlock_l30_direct_affliction_comparison import USER_AFFLICTION, make_apl
from wf_warlock_native_optimizer import (
    actor, apl_proposals, call, native_level_equipment, native_pet_candidates,
    profile, proposals_from_native_talents, set_native_pet, set_native_sustain_buffs,
)
from live_two_world_pulls import run as native_world_chain


def proposal_key(row):
    return json.dumps(
        [row["talents"], row["pet"], row["gear"], row["apl"]],
        sort_keys=True, separators=(",", ":"))


def choose_diverse_apls(rows, limit, rng):
    """Sample source-proposed distinct APL families without a fixed recipe."""
    unique = {}
    for name, apl in rows:
        unique.setdefault(json.dumps(apl, sort_keys=True), (name, apl))
    groups = {}
    for name, apl in unique.values():
        # Different fallback spell and DoT sets should get real paid chances.
        actions = [(entry.get("action") or {}).get("castSpell", {}).get("spellId", {}).get("spellId")
                   for entry in apl]
        dots = [(entry.get("action") or {}).get("castSpell", {}).get("spellId", {}).get("spellId")
                for entry in apl
                if "dotIsActive" in json.dumps(entry.get("action") or {})]
        group = (actions[-1] if actions else None, len(dots))
        groups.setdefault(group, []).append((name, apl))
    for choices in groups.values():
        rng.shuffle(choices)
    result = []
    while len(result) < limit and any(groups.values()):
        for key in sorted(groups, key=str):
            if groups[key] and len(result) < limit:
                result.append(groups[key].pop())
    return result


def build_source_domain(binary, source, engine_tools, proto_schema, out, seed):
    sys.path.insert(0, str(engine_tools.resolve()))
    import warlock_l20_native_search as source_search

    options = json.loads(call(
        [binary, "options", "--class", "warlock", "--level", "30"], seconds=60))
    if options["level"] != 30:
        raise RuntimeError("Unexpected native source level")
    found = source_search.native_spell_candidates(options, source)
    ids = {}
    for name in ("corruption", "agony", "siphon life", "shadow bolt",
                 "drain life", "life tap"):
        choice = next((row for row in found if name in row["name"].casefold()), None)
        if choice is None:
            raise RuntimeError("Native spell options lack initial seed: " + name)
        ids[name] = choice["spell_id"]
    actor(source)["talentsString"] = USER_AFFLICTION
    actor(source)["rotation"]["priorityList"] = make_apl(
        source_search, ids, affliction=True, filler="drain life")
    dps_gear, gear_audit, hp_gear = native_level_equipment(
        binary, source, options, out, level=30)
    apl_options, apl_audit = apl_proposals(options, dps_gear, source_search)
    talents = [
        row for row in proposals_from_native_talents(options, USER_AFFLICTION, seed)
        if sum(int(ch) for ch in row["talents"] if ch.isdigit())
           == options["talents"]["points_available"]]
    pets = [p for p in native_pet_candidates(proto_schema) if p != "NoSummon"]
    return dict(source=source, gear={"native_dps": dps_gear,
                                    "native_max_hp": hp_gear},
                apls=apl_options, talents=talents, pets=pets,
                audit={"gear": gear_audit, "apl": apl_audit,
                       "talent_proposals": len(talents),
                       "apl_proposals": len(apl_options), "native_pets": pets})


def propose_neighborhood(current, domain, axis, quota, rng):
    """Mutate one axis around the best actual 100-kill solution so far."""
    choices = []
    if axis == "apl":
        pool = choose_diverse_apls(domain["apls"], max(quota * 3, 12), rng)
        for name, apl in pool:
            choices.append({**current, "apl": copy.deepcopy(apl), "apl_label": name})
    elif axis == "talents":
        pool = domain["talents"].copy()
        rng.shuffle(pool)
        for row in pool:
            choices.append({**current, "talents": row["talents"],
                            "talent_label": row["label"]})
    elif axis == "pet":
        for name in domain["pets"]:
            choices.append({**current, "pet": name})
    elif axis == "gear":
        for name in domain["gear"]:
            choices.append({**current, "gear": name})
    else:
        raise ValueError(axis)
    # Deterministic but not a hard-coded list of build combinations.
    if axis != "apl":
        rng.shuffle(choices)
    seen = {proposal_key(current)}
    for row in choices:
        key = proposal_key(row)
        if key not in seen:
            seen.add(key)
            yield row


def evaluate(binary, domain, candidate, folder):
    folder.mkdir(parents=True, exist_ok=True)
    scenario = copy.deepcopy(domain["gear"][candidate["gear"]])
    actor(scenario)["talentsString"] = candidate["talents"]
    actor(scenario)["rotation"]["priorityList"] = copy.deepcopy(candidate["apl"])
    set_native_pet(scenario, candidate["pet"])
    scenario = profile(scenario, level=30)
    source_file = folder / "source_request.json"
    native_file = folder / "native_prepared.json"
    source_file.write_text(json.dumps(scenario, indent=2) + "\n")
    row = {
        "talents": candidate["talents"], "pet": candidate["pet"],
        "gear": candidate["gear"],
        "apl_label": candidate.get("apl_label"),
        "talent_label": candidate.get("talent_label"),
        "status": "INCOMPLETE", "confirmed_kills": 0,
    }
    try:
        call([binary, "prepare", "--request", source_file, "--actor-level", "30",
              "--outfile", native_file], seconds=120)
        # Rust owns spell rank resolution and legality. Do not reimplement
        # its spellbook constraints in a competing Python validator.
        world = native_world_chain(binary, native_file, classic_mob_level=30,
                                   target_count=100, rng_mode="balanced")
        (folder / "native_world.json").write_text(
            json.dumps(world, indent=2, allow_nan=False) + "\n")
        row.update(
            status="COMPLETED", confirmed_kills=world["world_targets_killed"],
            elapsed_s=world["world_elapsed_seconds"],
            seconds_per_mob=world["world_elapsed_seconds"] / 100,
            min_hp=world["minimum_native_actor_health"],
            min_mana=world["minimum_native_actor_mana"],
            paid_recovery=world["paid_recovery"])
    except (RuntimeError, ValueError, KeyError, OSError, AssertionError,
            subprocess.TimeoutExpired) as exc:
        row["error"] = str(exc)[-1400:]
        detail = exc.args[0] if isinstance(exc, AssertionError) and exc.args else None
        if (isinstance(detail, tuple) and len(detail) >= 5
                and detail[0] == "RUST_TWO_WORLD_NATIVE_FAILED"
                and type(detail[3]) is int):
            row["confirmed_kills"] = detail[3]
        match = re.search(r'RUST_MULTI_WORLD_NATIVE_ACTOR_NOT_ALIVE:index=(\\d+)',
                          row["error"])
        if match:
            row["confirmed_kills"] = max(0, int(match.group(1)) - 1)
    (folder / "result.json").write_text(json.dumps(row, indent=2) + "\n")
    return row


def run_search(binary, domain, out, budget, seed):
    rng = random.Random(seed)
    baseline_gear = domain["gear"]["native_dps"]
    champion = {
        "talents": USER_AFFLICTION, "pet": "Succubus",
        "gear": "native_dps",
        "apl": copy.deepcopy(actor(baseline_gear)["rotation"]["priorityList"]),
        "apl_label": "seed_user_affliction", "talent_label": "user_seed",
    }
    rows, visited, best = [], set(), None

    def trial(candidate, axis):
        nonlocal champion, best
        key = proposal_key(candidate)
        if key in visited:
            return False
        visited.add(key)
        index = len(rows)
        result = evaluate(binary, domain, candidate, out / ("case_%03d" % index))
        result["index"] = index
        result["mutation_axis"] = axis
        rows.append(result)
        is_complete = result["status"] == "COMPLETED" and result["confirmed_kills"] == 100
        if is_complete and (best is None or result["elapsed_s"] < best["elapsed_s"]):
            champion = copy.deepcopy(candidate)
            best = result
            result["new_champion"] = True
        (out / "leaderboard.json").write_text(json.dumps({
            "objective": "minimum actual 100 native serial world kills elapsed time",
            "rolling_overlap_executed": False, "native_source_domain": domain["audit"],
            "tried": len(rows), "completed_100": sum(
                r["status"] == "COMPLETED" and r["confirmed_kills"] == 100
                for r in rows),
            "best": best, "rows": rows,
        }, indent=2, allow_nan=False) + "\n")
        print("NATIVE_AUTOMATIC_100_MOB_TRIAL", json.dumps(result), flush=True)
        return True

    trial(champion, "seed")
    # Four search dimensions are explored and revisited around the measured
    # incumbent, rather than an explicitly chosen cross-product of seven.
    axes = (("apl", 5), ("pet", 3), ("talents", 4), ("gear", 2))
    rounds = 0
    while len(rows) < budget:
        rounds += 1
        any_new = False
        for axis, quota in axes:
            paid_axis = 0
            for candidate in propose_neighborhood(champion, domain, axis, quota, rng):
                if len(rows) >= budget or paid_axis >= quota:
                    break
                if trial(candidate, axis):
                    paid_axis += 1
                    any_new = True
            if len(rows) >= budget:
                break
        if not any_new or rounds >= 6:
            break
    complete = sum(r["status"] == "COMPLETED" and r["confirmed_kills"] == 100
                   for r in rows)
    summary = {"tried": len(rows), "completed_100": complete, "winner": best,
               "rolling_overlap_executed": False}
    print("NATIVE_AUTOMATIC_100_MOB_WINNER", json.dumps(summary), flush=True)
    if complete == 0:
        raise RuntimeError("ZERO_SUCCESSFUL_100_MOB_RUNS: all candidates failed; "
                           "workflow must not pass as a false green")
    return summary


def main():
    p = argparse.ArgumentParser()
    for key in ("binary", "source", "engine-tools", "proto-schema", "out"):
        p.add_argument("--" + key, required=True, type=Path)
    p.add_argument("--budget", type=int, default=20)
    p.add_argument("--seed", type=int, default=1093)
    args = p.parse_args()
    if args.budget < 2:
        p.error("Budget must include seed and at least one mutation")
    args.out.mkdir(parents=True, exist_ok=True)
    binary = args.binary.resolve()
    source = json.loads(args.source.read_text())
    source["encounter"]["targets"][0]["level"] = 30
    actor(source)["equipment"]["items"] = [{"id": 0} for _ in range(17)]
    set_native_sustain_buffs(source)
    domain = build_source_domain(
        binary, source, args.engine_tools, args.proto_schema, args.out, args.seed)
    print("NATIVE_AUTOMATIC_SEARCH_DOMAIN", json.dumps(domain["audit"]), flush=True)
    run_search(binary, domain, args.out, args.budget, args.seed)


if __name__ == "__main__":
    main()
