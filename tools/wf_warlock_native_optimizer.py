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


def native_pet_candidates(proto_schema_path: Path) -> list[str]:
    """Read the selected MythicSim protobuf summon enum; no shadow pet list."""
    schema = json.loads(proto_schema_path.read_text())
    rows = schema["enums"]["proto.WarlockOptions.Summon"]
    result = [entry["name"] for entry in rows]
    if "NoSummon" not in result or len(result) < 2:
        raise RuntimeError("Selected Rust schema exposes no usable Warlock summon options")
    return result


def set_native_pet(request: dict, summon: str) -> None:
    """Set the existing source-native Warlock option, not a Python pet model."""
    options = actor(request).setdefault("warlock", {}).setdefault(
        "options", {}).setdefault("classOptions", {})
    options["summon"] = summon
    # A normal active pet must not inherit another build's sacrifice settings.
    options.pop("pactSacrifice", None)
    options.pop("sacrificeSummon", None)


def talent_has_native_rank(options: dict, encoded: str, field_name: str) -> bool:
    """Inspect exact get_options tree metadata, not a hard-coded talent index."""
    for part, tree in zip(encoded.split("-"), options["talents"]["trees"]):
        for talent in tree["talents"]:
            if talent["field_name"] == field_name:
                index = talent["index"]
                return index < len(part) and part[index].isdigit() and int(part[index]) > 0
    return False


def native_pet_strategies(pets: list[str]) -> list[dict]:
    """Enumerate request configurations, not a second pet/ability simulator.

    The selected Rust engine validates each candidate and owns effects.
    """
    demons = [p for p in pets if p != "NoSummon"]
    strategies = [
        {"mode": "active", "pet": pet, "sacrifice": None,
         "key": "active:" + pet}
        for pet in pets
    ]
    for sacrificed in demons:
        strategies.append({
            "mode": "sacrifice", "pet": "NoSummon", "sacrifice": sacrificed,
            "key": "sacrifice:" + sacrificed,
        })
    for pet in demons:
        for sacrificed in demons:
            if pet == sacrificed:
                continue
            strategies.append({
                "mode": "pact", "pet": pet, "sacrifice": sacrificed,
                "key": "pact:" + pet + "+" + sacrificed,
            })
    return strategies


def set_native_strategy(request: dict, strategy: dict) -> None:
    """Use native classOptions; pets, sacrifice and regen belong to Rust."""
    mode = strategy["mode"]
    sacrificed = strategy["sacrifice"]
    set_native_pet(request, sacrificed if mode == "sacrifice" else strategy["pet"])
    class_options = actor(request)["warlock"]["options"]["classOptions"]
    if mode == "sacrifice":
        class_options["sacrificeSummon"] = True
    elif mode == "pact":
        class_options["pactSacrifice"] = sacrificed


def native_sacrifice_receipt(prepared: dict, strategy: dict) -> list[dict]:
    """Check that Rust actually exports the chosen sacrifice effect.

    In particular, never score an absent Felhunter HP regen as if it existed.
    """
    if strategy["mode"] == "active":
        return []
    active = [
        aura for aura in prepared["player"].get("auras", [])
        if aura.get("label") == "Demonic Sacrifice" and aura.get("active")
    ]
    if not active:
        raise RuntimeError("NATIVE_SACRIFICE_EFFECT_NOT_EXPORTED: "
                           + strategy["key"])
    return [{"label": a.get("label"), "action_id": a.get("action_id")}
            for a in active]


def native_pet_autocast_receipt(prepared: dict, chosen_pet: str) -> list[dict]:
    """Read the chosen demon's own autonomous spells from Rust-prepared state.

    These are NOT actions in the Warlock player's priorityList. The Rust
    warlock_pet effect supplies spellbook positions to its independent AI.
    """
    if chosen_pet == "NoSummon":
        return []
    selected = [
        pet for pet in prepared.get("pets", [])
        if pet.get("label", "").casefold().endswith(" - " + chosen_pet.casefold())
    ]
    if len(selected) != 1:
        raise RuntimeError(
            "Native prepared pet selection is ambiguous: " + chosen_pet)
    pet = selected[0]
    effects = [
        effect for effect in prepared.get("effects", [])
        if effect.get("kind") == "warlock_pet"
        and effect.get("pet") == pet["label"]
    ]
    if len(effects) != 1:
        raise RuntimeError(
            "Native warlock_pet autonomous AI effect missing: " + pet["label"])
    spellbook = pet.get("spells") or []
    actions = []
    for position in effects[0].get("autocast_spells", []):
        if type(position) is not int or not 0 <= position < len(spellbook):
            raise RuntimeError(
                "Native pet autocast points outside exported spellbook: "
                + repr(position))
        spell = spellbook[position]
        actions.append({
            "class_spell": spell.get("class_spell"),
            "action_id": spell.get("action_id"),
        })
    return actions


def native_pet_receipt(prepared: dict, paid: dict, chosen_pet: str) -> dict:
    """Collect explicit Rust prepared/paid pet evidence for every candidate."""
    pets = prepared.get("pets") or []
    labels = [p.get("label", "") for p in pets]
    selected = [
        p for p in pets
        if p.get("label", "").casefold().endswith(" - " + chosen_pet.casefold())
    ]
    if chosen_pet != "NoSummon" and not selected:
        raise RuntimeError(
            "PET_NOT_IN_NATIVE_PREPARED: requested " + chosen_pet +
            " but Rust exported " + repr(labels))
    if chosen_pet == "NoSummon" and selected:
        raise RuntimeError("Native NoSummon unexpectedly exported selected pet")
    player_metrics = paid["raidMetrics"]["parties"][0]["players"][0]
    pet_rows = player_metrics.get("pets") or []
    pet_details = []
    for row in pet_rows:
        value = row.get("dps", {}).get("avg", 0) or 0
        if not isinstance(value, (float, int)) or not math.isfinite(value):
            raise RuntimeError("Rust returned nonfinite pet DPS")
        pet_details.append({"name": row.get("name", ""), "dps": float(value)})
    return {
        "summon": chosen_pet,
        "native_prepared_pets": labels,
        "native_pet_dps": sum(p["dps"] for p in pet_details),
        "native_pet_autocast_spells": native_pet_autocast_receipt(prepared, chosen_pet),
        "native_pet_metrics": pet_details,
    }


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

    # Force native-prerequisite Demonology capstone exploration at L40.
    # Unlike a random 31-point sampler, this reliably reaches Demonic Pact
    # (requires Soul Link, which requires Demonic Sacrifice).
    demon_tree = next((i for i, tree in enumerate(trees)
                       if tree["name"] == "Demonology"), None)
    if demon_tree is not None:
        for k in range(8):
            alloc = [[0] * len(tree["talents"]) for tree in trees]
            tree = trees[demon_tree]
            target_fields = ("demonicSacrifice", "soulLink", "demonicPact")
            for spent in range(budget):
                choices = []
                for talent in tree["talents"]:
                    index = talent["index"]
                    if alloc[demon_tree][index] >= talent["max_rank"]:
                        continue
                    if (talent["minimum_level"] > level or
                            talent["points_required_in_tree"] > spent):
                        continue
                    parent = talent.get("prerequisite") or {}
                    if parent:
                        prereq = next((p for p in tree["talents"]
                                       if p["field_name"] == parent.get("field_name")), None)
                        if (prereq is None or
                                alloc[demon_tree][prereq["index"]] < parent["required_rank"]):
                            continue
                    choices.append(talent)
                if not choices:
                    break
                forced = next((talent for field in target_fields
                               for talent in choices
                               if talent["field_name"] == field), None)
                picked = forced if forced is not None else rng.choice(choices)
                alloc[demon_tree][picked["index"]] += 1
            else:
                encoded = serialize(alloc)
                row = emit(encoded, "native_demonology_pact_" + str(k))
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
                if tap is not None and fallback_name in ("shadow_bolt", "drain_life"):
                    for threshold in (20, 45, 65):
                        tap_action = source_module.mana_conditioned_apl(tap, threshold)
                        # Health gating is a native APL condition, not an
                        # extra Life Tap implementation. Prevent low-health
                        # self-damage while the engine handles regeneration.
                        mana_cond = tap_action["action"]["condition"]
                        tap_action["action"]["condition"] = {"and": {"vals": [
                            mana_cond,
                            {"cmp": {"lhs": {"currentHealthPercent": {}},
                                     "op": "OpGt",
                                     "rhs": {"const": {"val": "35%"}}}},
                        ]}}
                        candidates.append((
                            name + "_tap" + str(threshold) + "_hp35",
                            [tap_action, *apl]))
        candidates.append(("filler_" + fallback_name,
                           source_module.multi_apl([(fallback, None)])))
        if tap is not None and fallback_name in ("shadow_bolt", "drain_life"):
            for threshold in (30, 60):
                tap_action = source_module.mana_conditioned_apl(tap, threshold)
                tap_action["action"]["condition"] = {"and": {"vals": [
                    tap_action["action"]["condition"],
                    {"cmp": {"lhs": {"currentHealthPercent": {}},
                             "op": "OpGt",
                             "rhs": {"const": {"val": "35%"}}}},
                ]}}
                candidates.append((
                    "filler_" + fallback_name + "_tap" + str(threshold) + "_hp35",
                    [tap_action, *source_module.multi_apl([(fallback, None)])]))
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
    # The second exploration track is health maximization, NOT a new stat
    # weight model: source item Stamina/Health only proposes candidates;
    # Rust prepare determines the actual equipped actor's maximum HP.
    hp_path = out / "gear_health_request.json"
    hp_prepared_path = out / "gear_health_prepared.json"
    hp_count = 0
    hp_refusals = []

    def paid_native_max_hp(request):
        nonlocal hp_count
        hp_count += 1
        hp_path.write_text(json.dumps(request))
        try:
            call([binary, "prepare", "--request", hp_path,
                  "--actor-level", str(level), "--outfile", hp_prepared_path])
            unit = json.loads(hp_prepared_path.read_text())["player"]
            if unit.get("class") != "ClassWarlock" or unit.get("level") != level:
                raise RuntimeError("Rust prepared wrong actor during native HP gear search")
            value = unit["stats"]["Health"]
            if not isinstance(value, (float, int)) or not math.isfinite(value):
                raise RuntimeError("Invalid native prepared Health")
            return float(value)
        except (RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
            if len(hp_refusals) < 25:
                hp_refusals.append(str(exc)[-400:])
            return None

    def source_stat(item, stat):
        value = (item.get("stats") or {}).get(stat, 0)
        return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else 0.0

    survival = copy.deepcopy(working)
    hp_baseline = paid_native_max_hp(survival)
    if hp_baseline is None:
        raise RuntimeError("Native Rust refused DPS gear during HP search")
    native_dps_gear_max_hp = hp_baseline
    for position in range(17):
        # Include high-Stamina and direct-Health source leads, not just the
        # highest item levels that the legacy 30s-DPS pass screened.
        highest_stamina = sorted(
            pools[position], key=lambda n: (-source_stat(n, "Stamina"), n["item_id"]))[:8]
        highest_health = sorted(
            pools[position], key=lambda n: (-source_stat(n, "Health"), n["item_id"]))[:3]
        seen_ids = set()
        for native in highest_stamina + highest_health:
            if native["item_id"] in seen_ids:
                continue
            seen_ids.add(native["item_id"])
            candidate = copy.deepcopy(survival)
            actor(candidate)["equipment"]["items"][position] = {"id": native["item_id"]}
            native_hp = paid_native_max_hp(candidate)
            if native_hp is not None and native_hp > hp_baseline + 1e-8:
                survival = candidate
                hp_baseline = native_hp
        print("NATIVE_MAX_HP_GEAR_SLOT", json.dumps({
            "level": level, "slot": position, "native_prepared_max_hp": hp_baseline,
            "item_id": actor(survival)["equipment"]["items"][position]["id"],
        }), flush=True)
    hp_gear_items = [
        {"position": i, "item_id": item["id"],
         "name": item_meta.get(item["id"], {}).get("name")}
        for i, item in enumerate(actor(survival)["equipment"]["items"])
    ]
    (out / "native_max_hp_gear_request.json").write_text(
        json.dumps(survival, indent=2) + "\n")
    audit = {"source":"exact Rust get_options",
             "level":level,"class":"warlock",
             "native_eligible_item_count":len(item_meta),
             "evaluated_equipment_requests":tried,
             "native_paid_requests":paid_count,
             "native_refusal_samples":refusals,
             "native_paid_initial_gear_dps":baseline,
             "native_prepared_dps_gear_max_hp": native_dps_gear_max_hp,
             "native_prepared_max_hp_gear_max_hp": hp_baseline,
             "native_max_hp_gear_preparations": hp_count,
             "native_max_hp_gear_refusals": hp_refusals,
             "max_hp_equipped": hp_gear_items,
             "equipped":equipped}
    (out/"native_gear.json").write_text(json.dumps(audit,indent=2)+"\n")
    (out/"native_gear_request.json").write_text(json.dumps(working,indent=2)+"\n")
    print("NATIVE_GEAR",json.dumps(audit),flush=True)
    return working, audit, survival


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--level", type=int, required=True, help="Rust actor and target level")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--engine-tools", type=Path, required=True)
    parser.add_argument("--proto-schema", type=Path, required=True,
                        help="The selected Rust engine's data/proto-schema.json")
    parser.add_argument("--pet-smoke-only", action="store_true",
                        help="Paid Rust comparisons of all source summon choices only")
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
    source, gear_audit, survival_gear_source = native_level_equipment(
        binary, source, option_source, args.out, level=level)
    source_build = actor(source)["talentsString"]
    talents = list(proposals_from_native_talents(option_source, source_build, args.seed))
    apls, discovery = apl_proposals(option_source, source, source_search)
    pet_options = native_pet_candidates(args.proto_schema)
    print("NATIVE_SOURCE_SEARCH_DOMAIN", json.dumps({
        "level":level,"talent_proposals":len(talents),
        "apl_proposals":len(apls), "pet_options":pet_options,
        "talent_points":talent_budget,
        "gear_paid_requests":gear_audit["native_paid_requests"], **discovery}), flush=True)

    # A small direct Rust smoke verifies each existing Warlock summon option.
    # A source option may be natively refused with this initial talent build;
    # it is still explored with the other talent allocations below.
    smoke_rows = []
    smoke_request = args.out / "pet_smoke_request.json"
    smoke_prepared = args.out / "pet_smoke_prepared.json"
    smoke_paid = args.out / "pet_smoke_paid.json"
    for chosen_pet in pet_options:
        proposal = copy.deepcopy(source)
        set_native_pet(proposal, chosen_pet)
        proposal["simOptions"]["iterations"] = 8
        proposal["simOptions"]["randomSeed"] = "4242"
        smoke_request.write_text(json.dumps(proposal))
        row = {"pet": chosen_pet, "status": "RUST_REFUSED"}
        try:
            call([binary, "prepare", "--request", smoke_request,
                  "--actor-level", str(level), "--outfile", smoke_prepared])
            prepared_data = json.loads(smoke_prepared.read_text())
            call([binary, "sim", "--infile", smoke_prepared,
                  "--rng-mode", "balanced", "--outfile", smoke_paid])
            paid_data = json.loads(smoke_paid.read_text())["result"]
            pet_receipt = native_pet_receipt(prepared_data, paid_data, chosen_pet)
            row.update(status="RUST_PAID",
                       raid_dps=paid_data["raidMetrics"]["dps"]["avg"],
                       **pet_receipt)
        except (KeyError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            row["reason"] = str(exc)[-600:]
        smoke_rows.append(row)
        print("NATIVE_WARLOCK_PET_SMOKE", json.dumps(row), flush=True)
    (args.out / "native_pet_smoke.json").write_text(
        json.dumps(smoke_rows, indent=2) + "\n")
    if args.pet_smoke_only:
        # The workflow must not go green when every native summon was
        # refused. In particular, prove Imp's Rust-owned Firebolt autocast
        # actually contributes paid damage without entering the player APL.
        imp = next((row for row in smoke_rows if row["pet"] == "Imp"), None)
        if (imp is None or imp["status"] != "RUST_PAID"
                or not any(action.get("class_spell") == "imp_firebolt"
                           for action in imp.get("native_pet_autocast_spells", []))
                or not imp.get("native_pet_dps", 0) > 0):
            raise RuntimeError(
                "Native L40 Imp Firebolt autocast was not paid and observed; "
                "see native_pet_smoke.json for Rust evidence")
        return

    # Use native paid pet smoke to avoid confusing a protobuf enum choice
    # (e.g. unavailable Felguard) with a prepared, usable L40 demon.
    supported_pets = [r["pet"] for r in smoke_rows if r["status"] == "RUST_PAID"]
    strategies = native_pet_strategies(supported_pets)
    print("NATIVE_WARLOCK_STRATEGIES", json.dumps({
        "strategies": [s["key"] for s in strategies],
        "unsupported_native_summons": [r["pet"] for r in smoke_rows
                                       if r["status"] != "RUST_PAID"],
    }), flush=True)

    req_path = args.out / "screen_request.json"
    prep_path = args.out / "screen_prepared.json"
    sim_path = args.out / "screen_paid.json"
    scored = []
    rejected = Counter()
    rejected_samples = []
    tried = 0
    # Search active pet, pure sacrifice, and Demonic Pact + active pet.
    # Only Rust source talent options decide whether a proposal can carry
    # the sacrifice and Pact talent; all paid mechanics remain in Rust.
    for strategy in strategies:
        strategy_paid, strategy_rejected = 0, 0
        for t in talents:
            if (strategy["mode"] != "active" and
                    not talent_has_native_rank(option_source, t["talents"],
                                               "demonicSacrifice")):
                continue
            if (strategy["mode"] == "pact" and
                    not talent_has_native_rank(option_source, t["talents"],
                                               "demonicPact")):
                continue
            for a_label, apl in apls:
                tried += 1
                request = copy.deepcopy(source)
                set_native_strategy(request, strategy)
                actor(request)["talentsString"] = t["talents"]
                actor(request)["rotation"]["priorityList"] = copy.deepcopy(apl)
                request["simOptions"]["iterations"] = 8
                request["simOptions"]["randomSeed"] = "4242"
                req_path.write_text(json.dumps(request))
                try:
                    call([binary, "prepare", "--request", req_path,
                          "--actor-level", str(level), "--outfile", prep_path])
                    prepared_all = json.loads(prep_path.read_text())
                    prepared = prepared_all["player"]
                    if prepared.get("level") != level or prepared.get("class") != "ClassWarlock":
                        raise RuntimeError(f"Native prepared actor not Warlock L{level}")
                    sacrifice_receipt = native_sacrifice_receipt(prepared_all, strategy)
                    call([binary, "sim", "--infile", prep_path, "--rng-mode", "balanced",
                          "--outfile", sim_path])
                    paid = json.loads(sim_path.read_text())["result"]
                    team_dps = paid["raidMetrics"]["dps"]["avg"]
                    if not isinstance(team_dps, (int, float)) or not math.isfinite(team_dps):
                        raise RuntimeError("Rust returned nonfinite team DPS")
                    pet_receipt = native_pet_receipt(prepared_all, paid, strategy["pet"])
                    scored.append({
                        "dps_screen": float(team_dps),
                        "pet": strategy["pet"], "sacrifice": strategy["sacrifice"],
                        "strategy": strategy["key"], "mode": strategy["mode"],
                        "native_sacrifice_auras": sacrifice_receipt,
                        "native_pet_dps": pet_receipt["native_pet_dps"],
                        "native_pet_labels": pet_receipt["native_prepared_pets"],
                        "native_pet_autocast_spells": pet_receipt["native_pet_autocast_spells"],
                        "talents": t["talents"], "talent_label": t["label"],
                        "talent_ranks": t["ranks"], "apl_label": a_label, "apl": apl,
                    })
                    strategy_paid += 1
                except (KeyError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
                    reason = str(exc)[-500:]
                    rejected[(strategy["key"], reason)] += 1
                    strategy_rejected += 1
                    if len(rejected_samples) < 50:
                        rejected_samples.append({
                            "strategy": strategy["key"], "talents": t["talents"],
                            "apl": a_label, "reason": reason,
                        })
        print("NATIVE_STRATEGY_SEARCH", json.dumps({
            "strategy": strategy["key"], "paid": strategy_paid,
            "refused": strategy_rejected,
            "best_team_dps": max(
                (row["dps_screen"] for row in scored
                 if row["strategy"] == strategy["key"]), default=None),
        }), flush=True)
    scored.sort(key=lambda x:x["dps_screen"], reverse=True)
    print("NATIVE_SCREEN_RESULTS",json.dumps({
        "tried":tried,
        "paid":len(scored),"refused":sum(rejected.values()),
        "top10":[{k:v for k,v in row.items() if k not in ("apl", "talent_ranks")}
                 for row in scored[:10]]}),flush=True)

    # Guarantee a real native-paid finalist for EACH available summon option,
    # then fill remaining places with top-paid diverse pet/talent/APL builds.
    # Otherwise a top-DPS pet could silently crowd out Voidwalker or Felhunter
    # before the real 100-mob survival objective is measured.
    selected = []
    selected_keys = set()
    talent_counts = Counter()
    apl_counts = Counter()
    pet_counts = Counter()
    strategy_counts = Counter()

    def add_finalist(row):
        key = (row["strategy"], row["talents"], row["apl_label"])
        if key in selected_keys:
            return False
        selected.append(row)
        selected_keys.add(key)
        talent_counts[row["talents"]] += 1
        apl_counts[row["apl_label"]] += 1
        pet_counts[row["pet"]] += 1
        strategy_counts[row["strategy"]] += 1
        return True

    baseline = next((row for row in scored if row["pet"] == "NoSummon"
                     and row["talents"] == source_build
                     and row["apl_label"] == "saved_multi_spell"), None)
    if baseline is not None:
        add_finalist(baseline)
    # Keep an active pet baseline, plus examples of *each* sacrifice effect.
    # A 30-second DPS ranking alone must not drop regeneration strategies.
    family_order = (
        ["sacrifice:" + s for s in supported_pets if s != "NoSummon"] +
        ["active:" + s for s in supported_pets if s != "NoSummon"] +
        ["pact:" + s["pet"] + "+" + s["sacrifice"]
         for s in strategies if s["mode"] == "pact"]
    )
    for family in family_order:
        if len(selected) >= args.max_finalists:
            break
        first = next((row for row in scored if row["strategy"] == family), None)
        if first is not None:
            add_finalist(first)
    for row in scored:
        if len(selected) >= args.max_finalists:
            break
        if (talent_counts[row["talents"]] >= 3
                or apl_counts[row["apl_label"]] >= 4
                or strategy_counts[row["strategy"]] >= 2):
            continue
        add_finalist(row)

    chain_results = []
    for index,row in enumerate(selected):
        req = copy.deepcopy(source)
        actor(req)["talentsString"] = row["talents"]
        actor(req)["rotation"]["priorityList"] = copy.deepcopy(row["apl"])
        set_native_strategy(req, {
            "mode": row["mode"], "pet": row["pet"],
            "sacrifice": row["sacrifice"], "key": row["strategy"],
        })
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
        result["confirmed_kills"] = 0
        try:
            call([binary, "prepare", "--request", scenario_file,
                  "--actor-level", str(level), "--outfile", prepared_file])
            prepared_data = json.loads(prepared_file.read_text())
            rust_actor = prepared_data["player"]
            if rust_actor.get("level") != level or rust_actor.get("class") != "ClassWarlock":
                raise RuntimeError("wrong prepared Rust actor")
            result["native_prepared_pets"] = [
                pet.get("label") for pet in prepared_data.get("pets", [])]
            result["native_sacrifice_auras"] = native_sacrifice_receipt(
                prepared_data, {
                    "mode": row["mode"], "key": row["strategy"],
                })
            result["native_pet_autocast_spells"] = native_pet_autocast_receipt(
                prepared_data, row["pet"])
            world = native_world_chain(
                binary, prepared_file, classic_mob_level=level,
                target_count=100, rng_mode="balanced")
            (folder / "native_world.json").write_text(
                json.dumps(world, indent=2, allow_nan=False)+"\n")
            result.update(status="COMPLETED", kills=world["world_targets_killed"],
                          confirmed_kills=world["world_targets_killed"],
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
            # Preserve verified actual lethal ACK count even on a failed run.
            # The native world driver reports len(kills) as tuple element 3.
            detail = exc.args[0] if isinstance(exc, AssertionError) and exc.args else None
            if (isinstance(detail, tuple) and len(detail) >= 5
                    and detail[0] == "RUST_TWO_WORLD_NATIVE_FAILED"
                    and type(detail[3]) is int):
                result["confirmed_kills"] = detail[3]
                result["native_damage_events_before_stop"] = detail[4]
            death = re.search(r'RUST_MULTI_WORLD_NATIVE_ACTOR_NOT_ALIVE:index=(\d+)', reason)
            if death:
                result["confirmed_kills"] = max(0, int(death.group(1)) - 1)
                result["last_live_target_index"] = int(death.group(1))-1
        (folder / "result.json").write_text(json.dumps(result, indent=2)+"\n")
        chain_results.append(result)
        print("NATIVE_100_MOB_FINALIST",json.dumps(result), flush=True)

    winners = sorted((r for r in chain_results if r["status"]=="COMPLETED"),
                     key=lambda x:x["elapsed_s"])
    incomplete = sorted((r for r in chain_results if r["status"] != "COMPLETED"),
                        key=lambda x:(-x["confirmed_kills"],-x["dps_screen"]))
    result = {
        "source":"Rust get_options + native paid balanced screening + real gsim retained 100 mob",
        "gear_held_fixed_after_native_selection":True, "native_level_gear":gear_audit,
        "mob_level":level, "mob_hp_classic_proxy":representative_hp(level),
        "test_mob_min_base_damage":20,
        "talents_considered":len(talents), "apl_considered":len(apls),
        "pets_considered":pet_options,
        "native_strategies_considered": [s["key"] for s in strategies],
        "native_pet_smoke":smoke_rows,
        "paid_by_pet":dict(Counter(r["pet"] for r in scored)),
        "paid_by_strategy":dict(Counter(r["strategy"] for r in scored)),
        "paid_30s_combinations":len(scored),
        "refused_30s_combinations":sum(rejected.values()),
        "screen_top20":[{k:v for k,v in row.items() if k != "apl"} for row in scored[:20]],
        "finalist_results":chain_results,
        "refusal_examples":rejected_samples,
        "winner":winners[0] if winners else None,
        "best_partial":incomplete[0] if incomplete else None,
        "status":"COMPLETED_100_MOBS" if winners else "NO_100_MOB_SURVIVOR",
    }
    (args.out / "optimization_results.json").write_text(
        json.dumps(result,indent=2,allow_nan=False)+"\n")
    print("WARLOCK_TALENT_APL_100MOB_OPTIMIZATION",json.dumps({
        "talents":len(talents),"apls":len(apls),"pets":pet_options,
        "paid":len(scored),"paid_by_pet":dict(Counter(r["pet"] for r in scored)),
        "finalists":len(chain_results), "completed":len(winners),
        "winner":result["winner"], "best_partial":result["best_partial"],
        "status":result["status"],
    }), flush=True)
    # A completed optimization run can find NO viable full-chain build.
    # Preserve that honest outcome without misreporting it as an infrastructure
    # failure or discarding partial native lethal-ACK counts.


if __name__ == "__main__":
    main()
