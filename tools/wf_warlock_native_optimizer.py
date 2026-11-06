#!/usr/bin/env python3
"""Optimize source-native Warlock at the selected level TALENTS + conditional APL for a real 100-mob chain.

Two stages, no alternative gameplay simulator:
- Broad candidates from Rust get_options (native source talent/spell metadata).
  Rust prepare + balanced simulate pays for each candidate's combat behavior.
- Diverse paid finalists fight 100 *distinct* gsim targets on ONE retained
  Rust actor/clock/resources with native damage and world death acknowledgments.
The final objective is completed mobs first and measured seconds per mob, NOT
30-second DPS. Gear is native-paid at selected level, then fixed for talent/APL.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import random
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "integrations/mythicsim-rust"))
from live_two_world_pulls import run as native_world_chain
from src.scenarios.leveling_targets import representative_hp


def call(command, *, seconds=45):
    result = subprocess.run(list(map(str, command)), text=True,
                            capture_output=True, timeout=seconds, check=False)
    if result.returncode:
        raise RuntimeError("Rust exit " + str(result.returncode) + ": " +
                           (result.stderr or result.stdout)[-1800:])
    return result.stdout


def actor(request):
    return request["raid"]["parties"][0]["players"][0]


def proposals_from_native_talents(options, source_encoded: str, seed: int):
    """Generate allocations using *source-returned* tree/tier/parent metadata.

    These are proposals, not a second talent validator: only the paid Rust
    executable judges any combat effects and accepts/refuses the full request.
    """
    trees = options["talents"]["trees"]
    level = options["level"]
    budget = options["talents"]["points_available"]
    rng = random.Random(seed)
    seen = set()

    def serialize(ranks):
        return "-".join("".join(map(str, x)).rstrip("0") or "0" for x in ranks)

    def annotated(encoded):
        labels = []
        for part, tree in zip(encoded.split("-"), trees):
            for row in tree["talents"]:
                rank = int(part[row["index"]]) if row["index"] < len(part) else 0
                if rank:
                    labels.append(f'{row["name"]} {rank}/{row["max_rank"]}')
        return labels

    def emit(encoded, label):
        if encoded not in seen:
            seen.add(encoded)
            return {"talents": encoded, "label": label, "ranks": annotated(encoded)}
        return None

    first = emit(source_encoded, "saved_rust_paid_build")
    if first:
        yield first

    def sample(favored, sample_id):
        alloc = [[0] * len(tree["talents"]) for tree in trees]
        for spent in range(budget):
            choices = []
            for t, tree in enumerate(trees):
                if favored is not None and t != favored:
                    continue
                points_in_tree = sum(alloc[t])
                for row in tree["talents"]:
                    index = row["index"]
                    if alloc[t][index] >= row["max_rank"]:
                        continue
                    if (row["minimum_level"] > level
                            or row["points_required_in_tree"] > points_in_tree):
                        continue
                    parent = row.get("prerequisite") or {}
                    if parent:
                        prerequisite = next(
                            (p for p in tree["talents"]
                             if p["field_name"] == parent.get("field_name")), None)
                        if prerequisite is None or alloc[t][prerequisite["index"]] < parent["required_rank"]:
                            continue
                    # Broad exploration of first-tier and later source tiers.
                    weight = 1 + (4 if favored == t else 0)
                    if index == 1 or index == 2:
                        weight += 2
                    choices.extend([(t, index)] * weight)
            if not choices:
                return None
            t, i = rng.choice(choices)
            alloc[t][i] += 1
        return serialize(alloc)

    for tree_id, tree in enumerate(trees):
        for k in range(10):
            item = sample(tree_id, k)
            if item is not None:
                row = emit(item, "tree_" + tree["name"] + "_" + str(k))
                if row:
                    yield row
    for k in range(12):
        item = sample(None, k)
        if item is not None:
            row = emit(item, "mixed_" + str(k))
            if row:
                yield row


def apl_proposals(options, source, source_module):
    """Every considered spell identity originates from Rust's options or
    the existing Rust-paid source request. No hard-coded spell-ID whitelist.
    """
    spells = source_module.native_spell_candidates(options, source)
    def match(fragment):
        relevant = [x for x in spells if fragment in x["name"].casefold()]
        return relevant[0]["spell_id"] if relevant else None

    source_apl = actor(source)["rotation"]["priorityList"]
    candidates = [("saved_multi_spell", copy.deepcopy(source_apl))]
    filler = [("shadow_bolt", match("shadow bolt")),
              ("searing_pain", match("searing pain")),
              ("drain_life", match("drain life")),
              ("shoot", match("shoot"))]
    fillers = [(name, spell) for name, spell in filler if spell is not None]
    dot_spells = [("corruption", match("corruption")),
                  ("agony", match("agony")),
                  ("immolate", match("immolate"))]
    dots = [(name, spell) for name, spell in dot_spells if spell is not None]
    tap = match("life tap")
    if not fillers:
        raise RuntimeError("Rust get_options provides no executable APL filler proposal")
    for fallback_name, fallback in fillers:
        for start in range(len(dots)):
            # Multi-spell lists with native dotIsActive conditions and fallback.
            order = dots[start:] + dots[:start]
            for count in (2, 3):
                lead = order[:count]
                if not lead:
                    continue
                apl = source_module.multi_apl(
                    [(sid, "dot_missing") for _, sid in lead] +
                    [(fallback, None)])
                name = "dots_" + "_".join(n for n, _ in lead) + "__" + fallback_name
                candidates.append((name, apl))
                if tap is not None and fallback_name == "shadow_bolt":
                    for threshold in (10, 20):
                        candidates.append((
                            name + "_tap" + str(threshold),
                            [source_module.mana_conditioned_apl(tap, threshold), *apl]))
        candidates.append(("filler_" + fallback_name,
                           source_module.multi_apl([(fallback, None)])))
    unique = {}
    for label, actions in candidates:
        unique.setdefault(json.dumps(actions, sort_keys=True), (label, actions))
    return list(unique.values()), {"source_spell_records": len(spells),
                                    "discovered": {
                                        "filler": {k:v for k,v in filler},
                                        "dot": {k:v for k,v in dot_spells},
                                        "life_tap": tap}}


def profile(request, *, level):
    scenario = copy.deepcopy(request)
    target = scenario["encounter"]["targets"][0]
    target["level"] = level
    target["name"] = f"Classic-proxy ordinary L{level} mob"
    target["stats"][32] = representative_hp(level)
    target["minBaseDamage"] = 20.0
    target["swingSpeed"] = 2.0
    scenario["encounter"]["duration"] = 30
    scenario["simOptions"].update({
        "iterations":8,"randomSeed":"4242","debugFirstIteration":False})
    return scenario


def native_level_equipment(binary, source, options, out, *, level):
    """Pick equipment exclusively from Rust's level-specific get_options, paid scores.

    The source-provided required_level and native slot are proposal metadata.
    Every full 17-position candidate is handed to Rust prepare/simulate for its
    actual score/refusal. No Python item-profession or class rules are created.
    """
    slot_positions = {
        "head": (0,), "neck": (1,), "shoulder": (2,),
        "back": (3,), "chest": (4,), "wrist": (5,), "hands": (6,),
        "waist": (7,), "legs": (8,), "feet": (9,),
        "finger": (10,11), "trinket": (12,13),
        "main_hand": (14,), "one_hand": (14,), "two_hand": (14,),
        "off_hand": (15,), "ranged": (16,),
    }
    pools = {i: [] for i in range(17)}
    item_meta = {}
    for row in options["items"]:
        native = row.get("native") if row.get("eligibility") == "native_eligible" else None
        if native is None:
            continue
        item_id = row["item_id"]
        item_meta[item_id] = native
        for index in slot_positions.get(native.get("slot"), ()):
            pools[index].append(native)
    request_path = out / "gear_request.json"
    prepared_path = out / "gear_prepared.json"
    paid_path = out / "gear_paid.json"
    tried, paid_count, refusals = 0, 0, []
    def score(request):
        nonlocal tried, paid_count
        tried += 1
        request_path.write_text(json.dumps(request))
        try:
            call([binary, "prepare", "--request", request_path,
                  "--actor-level", str(level), "--outfile", prepared_path])
            verified = json.loads(prepared_path.read_text())["player"]
            if verified.get("class") != "ClassWarlock" or verified.get("level") != level:
                raise RuntimeError("Rust prepared an unexpected actor")
            call([binary, "sim", "--infile", prepared_path,
                  "--rng-mode", "balanced", "--outfile", paid_path])
            native_result = json.loads(paid_path.read_text())["result"]
            dps = native_result["raidMetrics"]["parties"][0]["players"][0]["dps"]["avg"]
            if not isinstance(dps,(int,float)) or not math.isfinite(dps):
                raise RuntimeError("Rust returned an invalid score")
            paid_count += 1
            return float(dps)
        except (RuntimeError,ValueError,KeyError,subprocess.TimeoutExpired) as exc:
            if len(refusals) < 25:
                refusals.append(str(exc)[-480:])
            return None
    working = copy.deepcopy(source)
    actor(working)["equipment"]["items"] = [{"id": 0} for _ in range(17)]
    baseline = score(working)
    if baseline is None:
        raise RuntimeError(f"Rust refused blank native L{level} actor: "+str(refusals[-1]))
    # Source item-level is only a discovery heuristic; paid Rust DPS decides.
    for position in range(17):
        best = baseline
        best_id = None
        candidates = sorted(pools[position], key=lambda n: (
            -(n.get("item_level") if type(n.get("item_level")) is int else -1),
            n["item_id"]))
        for native in candidates[:5]:
            candidate = copy.deepcopy(working)
            actor(candidate)["equipment"]["items"][position] = {"id":native["item_id"]}
            dps = score(candidate)
            if dps is not None and dps > best + 1e-8:
                best = dps
                best_id = native["item_id"]
        if best_id is not None:
            actor(working)["equipment"]["items"][position] = {"id":best_id}
            baseline = best
        print("NATIVE_GEAR_SLOT",json.dumps({"level":level,"slot":position,
            "equipped":actor(working)["equipment"]["items"][position]["id"],
            "native_paid_dps":baseline}),flush=True)
    equipped = []
    for position,item in enumerate(actor(working)["equipment"]["items"]):
        metadata = item_meta.get(item["id"])
        equipped.append({"position":position,"item_id":item["id"],
            "name":metadata["name"] if metadata else None,
            "required_level":metadata["required_level"] if metadata else None,
            "native_slot":metadata["slot"] if metadata else None})
    audit = {"source":"exact Rust get_options",
             "level":level,"class":"warlock",
             "native_eligible_item_count":len(item_meta),
             "evaluated_equipment_requests":tried,
             "native_paid_requests":paid_count,
             "native_refusal_samples":refusals,
             "native_paid_initial_gear_dps":baseline,
             "equipped":equipped}
    (out/"native_gear.json").write_text(json.dumps(audit,indent=2)+"\n")
    (out/"native_gear_request.json").write_text(json.dumps(working,indent=2)+"\n")
    print("NATIVE_GEAR",json.dumps(audit),flush=True)
    return working, audit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--level", type=int, required=True, help="Rust actor and target level")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--engine-tools", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-finalists", type=int, default=6)
    parser.add_argument("--seed", type=int, default=10916)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    binary = args.binary.resolve()
    source = json.loads(args.source.read_text())
    level = args.level
    if not 10 <= level <= 60:
        parser.error("Level must be in 10..60")
    source["encounter"]["targets"][0]["level"] = level
    source["encounter"]["targets"][0]["name"] = f"Source-native L{level} combat"
    actor(source)["name"] = f"Warlock L{level} Troll native"
    actor(source)["equipment"]["items"] = [{"id":0} for _ in range(17)]
    sys.path.insert(0, str(args.engine_tools.resolve()))
    import warlock_l20_native_search as source_search
    option_source = json.loads(call(
        [binary, "options", "--class", "warlock", "--level", str(level)], seconds=60))
    if option_source["class"] != "warlock" or option_source["level"] != level:
        raise RuntimeError("Wrong Rust get_options actor")
    talent_budget = option_source["talents"]["points_available"]
    if talent_budget != level - 9:
        raise RuntimeError("Unexpected Rust-native talent budget")
    # Generate a full-budget initial build from native tree metadata, never
    # carry the original L20 talent points forward to a different level.
    prelim = list(proposals_from_native_talents(option_source, "0-0-0", args.seed))
    full = [row for row in prelim
            if sum(int(ch) for ch in row["talents"] if ch.isdigit()) == talent_budget]
    source_choice = next(
        (row for row in full if row["label"].startswith("tree_Destruction")),None)
    if source_choice is None:
        raise RuntimeError(f"No source-generated {talent_budget}-point talent proposal")
    actor(source)["talentsString"] = source_choice["talents"]
    # Fetch level-correct spell ranks from Rust options for the starting APL.
    from_native = source_search.native_spell_candidates(option_source, source)
    def spell(name):
        return next((r["spell_id"] for r in from_native
                     if name in r["name"].casefold()), None)
    initial = [(spell("corruption"), "dot_missing"),
               (spell("agony"), "dot_missing"),
               (spell("shadow bolt"), None)]
    if any(spell_id is None for spell_id, _ in initial):
        raise RuntimeError("Rust spell options missing Corruption/Agony/Shadow Bolt")
    actor(source)["rotation"]["priorityList"] = source_search.multi_apl(initial)
    source, gear_audit = native_level_equipment(
        binary, source, option_source, args.out, level=level)
    source_build = actor(source)["talentsString"]
    talents = list(proposals_from_native_talents(option_source, source_build, args.seed))
    apls, discovery = apl_proposals(option_source, source, source_search)
    print("NATIVE_SOURCE_SEARCH_DOMAIN", json.dumps({
        "level":level,"talent_proposals":len(talents),
        "apl_proposals":len(apls), "talent_points":talent_budget,
        "gear_paid_requests":gear_audit["native_paid_requests"], **discovery}), flush=True)

    req_path = args.out / "screen_request.json"
    prep_path = args.out / "screen_prepared.json"
    sim_path = args.out / "screen_paid.json"
    scored = []
    rejected = Counter()
    rejected_samples = []
    # Exercise independent talent x APL candidates through actual Rust.
    for t in talents:
        for a_label, apl in apls:
            request = copy.deepcopy(source)
            actor(request)["talentsString"] = t["talents"]
            actor(request)["rotation"]["priorityList"] = copy.deepcopy(apl)
            request["simOptions"]["iterations"] = 8
            request["simOptions"]["randomSeed"] = "4242"
            req_path.write_text(json.dumps(request))
            try:
                call([binary, "prepare", "--request", req_path, "--actor-level", str(level),
                      "--outfile", prep_path])
                prepared = json.loads(prep_path.read_text())["player"]
                if prepared.get("level") != level or prepared.get("class") != "ClassWarlock":
                    raise RuntimeError(f"Native prepared actor not Warlock L{level}")
                call([binary, "sim", "--infile", prep_path, "--rng-mode", "balanced",
                      "--outfile", sim_path])
                paid = json.loads(sim_path.read_text())["result"]
                dps = paid["raidMetrics"]["parties"][0]["players"][0]["dps"]["avg"]
                if not isinstance(dps, (int, float)) or not math.isfinite(dps):
                    raise RuntimeError("Rust returned nonfinite paid DPS")
                scored.append({
                    "dps_screen": float(dps), "talents": t["talents"],
                    "talent_label":t["label"], "talent_ranks":t["ranks"],
                    "apl_label": a_label, "apl": apl,
                })
            except (KeyError, ValueError, RuntimeError, subprocess.TimeoutExpired) as e:
                reason = str(e)[-500:]
                rejected[reason] += 1
                if len(rejected_samples) < 20:
                    rejected_samples.append({"talents":t["talents"],
                                             "apl":a_label,"reason":reason})
    scored.sort(key=lambda x:x["dps_screen"], reverse=True)
    print("NATIVE_SCREEN_RESULTS",json.dumps({
        "tried":len(talents)*len(apls),
        "paid":len(scored),"refused":sum(rejected.values()),
        "top5":[{k:v for k,v in r.items() if k not in ("apl", "talent_ranks")}
                for r in scored[:5]]}),flush=True)

    # Choose diverse finalists: top-paid overall, different talent trees,
    # different APLs and the saved prior winner, not just one DPS ordering.
    selected = []
    selected_keys = set()
    talent_counts = Counter()
    apl_counts = Counter()
    for row in scored:
        if len(selected) >= args.max_finalists:
            break
        if (talent_counts[row["talents"]] >= 2 or
                apl_counts[row["apl_label"]] >= 3):
            continue
        key = (row["talents"], row["apl_label"])
        if key in selected_keys:
            continue
        selected.append(row)
        selected_keys.add(key)
        talent_counts[row["talents"]] += 1
        apl_counts[row["apl_label"]] += 1
    baseline = next((r for r in scored if r["talents"] == source_build
                     and r["apl_label"] == "saved_multi_spell"), None)
    if baseline and (baseline["talents"],baseline["apl_label"]) not in selected_keys:
        selected[-1:] = [baseline]

    chain_results = []
    for index,row in enumerate(selected):
        req = copy.deepcopy(source)
        actor(req)["talentsString"] = row["talents"]
        actor(req)["rotation"]["priorityList"] = copy.deepcopy(row["apl"])
        scenario = profile(req, level=level)
        folder = args.out / ("chain_" + str(index).zfill(2))
        folder.mkdir(exist_ok=True)
        scenario_file = folder / "source_request.json"
        prepared_file = folder / "prepared.json"
        scenario_file.write_text(json.dumps(scenario, indent=2) + "\n")
        result = {k:v for k,v in row.items() if k != "apl"}
        result["candidate"] = index
        result["objective"] = f"100 successive L{level} world kills, min elapsed seconds"
        result["status"] = "INCOMPLETE"
        try:
            call([binary, "prepare", "--request", scenario_file,
                  "--actor-level", str(level), "--outfile", prepared_file])
            rust_actor = json.loads(prepared_file.read_text())["player"]
            if rust_actor.get("level") != level or rust_actor.get("class") != "ClassWarlock":
                raise RuntimeError("wrong prepared Rust actor")
            world = native_world_chain(
                binary, prepared_file, classic_mob_level=level,
                target_count=100, rng_mode="balanced")
            (folder / "native_world.json").write_text(
                json.dumps(world, indent=2, allow_nan=False)+"\n")
            result.update(status="COMPLETED", kills=world["world_targets_killed"],
                          elapsed_s=world["world_elapsed_seconds"],
                          seconds_per_mob=world["world_elapsed_seconds"]/100,
                          min_hp=world["minimum_native_actor_health"],
                          final_mana=world["native_actor_mana_after_world_kills"][-1],
                          min_mana=world["minimum_native_actor_mana"],
                          native_damage_events=world["native_damage_events"],
                          paid_recovery=world["paid_recovery"])
        except (KeyError, ValueError, RuntimeError, AssertionError, OSError,
                subprocess.TimeoutExpired) as exc:
            reason = str(exc)[-3000:]
            result["failure_reason"] = reason
            # A dead actor at target index N has not survived all 100 mobs.
            death = re.search(r'RUST_MULTI_WORLD_NATIVE_ACTOR_NOT_ALIVE:index=(\d+)',reason)
            if death:
                result["last_live_target_index"] = int(death.group(1))-1
        (folder / "result.json").write_text(json.dumps(result, indent=2)+"\n")
        chain_results.append(result)
        print("NATIVE_100_MOB_FINALIST",json.dumps(result), flush=True)

    winners = sorted((r for r in chain_results if r["status"]=="COMPLETED"),
                     key=lambda x:x["elapsed_s"])
    result = {
        "source":"Rust get_options + native paid balanced screening + real gsim retained 100 mob",
        "gear_held_fixed_after_native_selection":True, "native_level_gear":gear_audit,
        "mob_level":level, "mob_hp_classic_proxy":representative_hp(level),
        "test_mob_min_base_damage":20,
        "talents_considered":len(talents), "apl_considered":len(apls),
        "paid_30s_combinations":len(scored),
        "refused_30s_combinations":sum(rejected.values()),
        "screen_top20":[{k:v for k,v in row.items() if k != "apl"} for row in scored[:20]],
        "finalist_results":chain_results,
        "refusal_examples":rejected_samples,
        "winner":winners[0] if winners else None,
    }
    (args.out / "optimization_results.json").write_text(
        json.dumps(result,indent=2,allow_nan=False)+"\n")
    print("WARLOCK_TALENT_APL_100MOB_OPTIMIZATION",json.dumps({
        "talents":len(talents),"apls":len(apls),"paid":len(scored),
        "finalists":len(chain_results), "completed":len(winners),
        "winner":result["winner"],
    }), flush=True)
    if not winners:
        raise SystemExit("No screened talent/APL finalist survived 100 mobs")


if __name__ == "__main__":
    main()
