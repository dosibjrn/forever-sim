#!/usr/bin/env python3
"""Optimize native L20 Warlock TALENTS + conditional APL for a real 100-mob chain.

Two stages, no alternative gameplay simulator:
- Broad candidates from Rust get_options (native source talent/spell metadata).
  Rust prepare + balanced simulate pays for each candidate's combat behavior.
- Diverse paid finalists fight 100 *distinct* gsim targets on ONE retained
  Rust actor/clock/resources with native damage and world death acknowledgments.
The final objective is completed mobs first and measured seconds per mob, NOT
30-second DPS. Gear is intentionally held fixed to isolate talents/APL.
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


def profile(request):
    from tools.wf_warlock_l20_100mob import create_scenario
    return create_scenario(request, variant="best_apl")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--engine-tools", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-finalists", type=int, default=6)
    parser.add_argument("--seed", type=int, default=10916)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    binary = args.binary.resolve()
    source = json.loads(args.source.read_text())
    sys.path.insert(0, str(args.engine_tools.resolve()))
    import warlock_l20_native_search as source_search
    option_source = json.loads(call(
        [binary, "options", "--class", "warlock", "--level", "20"], seconds=60))
    if option_source["class"] != "warlock" or option_source["level"] != 20:
        raise RuntimeError("Wrong Rust get_options actor")
    if option_source["talents"]["points_available"] != 11:
        raise RuntimeError("Unexpected Rust source L20 talent budget")
    source_build = actor(source)["talentsString"]
    talents = list(proposals_from_native_talents(option_source, source_build, args.seed))
    apls, discovery = apl_proposals(option_source, source, source_search)
    print("NATIVE_SOURCE_SEARCH_DOMAIN", json.dumps({
        "talent_proposals":len(talents), "apl_proposals":len(apls),
        "talent_points":11, **discovery}), flush=True)

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
                call([binary, "prepare", "--request", req_path, "--actor-level", "20",
                      "--outfile", prep_path])
                prepared = json.loads(prep_path.read_text())["player"]
                if prepared.get("level") != 20 or prepared.get("class") != "ClassWarlock":
                    raise RuntimeError("Native prepared actor not Warlock L20")
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
        scenario = profile(req)
        folder = args.out / ("chain_" + str(index).zfill(2))
        folder.mkdir(exist_ok=True)
        scenario_file = folder / "source_request.json"
        prepared_file = folder / "prepared.json"
        scenario_file.write_text(json.dumps(scenario, indent=2) + "\n")
        result = {k:v for k,v in row.items() if k != "apl"}
        result["candidate"] = index
        result["objective"] = "100 successive L20 world kills, min elapsed seconds"
        result["status"] = "INCOMPLETE"
        try:
            call([binary, "prepare", "--request", scenario_file,
                  "--actor-level", "20", "--outfile", prepared_file])
            rust_actor = json.loads(prepared_file.read_text())["player"]
            if rust_actor.get("level") != 20 or rust_actor.get("class") != "ClassWarlock":
                raise RuntimeError("wrong prepared Rust actor")
            world = native_world_chain(
                binary, prepared_file, classic_mob_level=20,
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
        "gear_held_fixed":True,
        "mob_level":20, "mob_hp_classic_proxy":representative_hp(20),
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
    print("WARLOCK_L20_TALENT_APL_100MOB_OPTIMIZATION",json.dumps({
        "talents":len(talents),"apls":len(apls),"paid":len(scored),
        "finalists":len(chain_results), "completed":len(winners),
        "winner":result["winner"],
    }), flush=True)
    if not winners:
        raise SystemExit("No screened talent/APL finalist survived 100 mobs")


if __name__ == "__main__":
    main()
