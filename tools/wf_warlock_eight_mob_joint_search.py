#!/usr/bin/env python3
"""Native 8-mob adaptive search operators; no fixed build or APL priorities.

Source Rust get_options owns the actions, legal item levels/slots and talents.
The objective is the trained prediction of a *real* 100-mob duration from
native eight-mob receipts. APL *order* is an evolvable gene, not a recipe.
Every mutation must be executed by canonical Rust before it gets a score.
"""
from __future__ import annotations

import copy
import json
import random

from wf_warlock_native_optimizer import actor, set_native_pet


SLOT_POSITIONS = {
    "head": (0,), "neck": (1,), "shoulder": (2,),
    "back": (3,), "chest": (4,), "wrist": (5,), "hands": (6,),
    "waist": (7,), "legs": (8,), "feet": (9,),
    "finger": (10, 11), "trinket": (12, 13),
    "main_hand": (14,), "one_hand": (14,), "two_hand": (14,),
    "off_hand": (15,), "ranged": (16,),
}


def source_item_pools(options):
    """Only source-confirmed item levels/slots; Rust accepts/refuses full gear."""
    level = options["level"]
    result = {p: set() for p in range(17)}
    for item in options["items"]:
        native = item.get("native") if item.get("eligibility") == "native_eligible" else None
        if not isinstance(native, dict):
            continue
        min_level = native.get("required_level")
        if type(min_level) is not int or not 0 < min_level <= level:
            continue
        item_id = item.get("item_id")
        if type(item_id) is not int or item_id <= 0:
            continue
        for p in SLOT_POSITIONS.get(native.get("slot"), ()):
            result[p].add(item_id)
    return {p: tuple(sorted(ids)) for p, ids in result.items() if ids}


def request_signature(request):
    p = actor(request)
    return json.dumps((
        p.get("talentsString"),
        ((p.get("warlock") or {}).get("options") or {}).get("classOptions", {}).get("summon"),
        [row.get("id") for row in p["equipment"]["items"]],
        p["rotation"]["priorityList"],
    ), sort_keys=True, separators=(",", ":"))


def native_cast_identifiers(prepared):
    """Actual actions exposed by Rust prepare, including OtherActionShoot.

    OtherActionShoot is NOT a class spell rank in get_options. It appears only
    for an equipped wand in Rust's shared ranged-auto-attack registration.
    Python never asserts that a missing native spell is available.
    """
    ids = {}
    for spell in prepared["player"].get("spells") or []:
        action_id = spell.get("action_id") or {}
        number = action_id.get("spell_id")
        other = action_id.get("other_id")
        if type(number) is int and number > 0:
            ids[("spell", number)] = {"spellId": number}
        if other in ("OtherActionShoot", 4):
            ids[("other", "OtherActionShoot")] = {"otherId": "OtherActionShoot"}
    return list(ids.values())


def apl_mutation(actions, action_ids, source_module, rng):
    """Evolve ordered source-native APL actions, including wand Shoot."""
    result = copy.deepcopy(actions)
    if not action_ids:
        raise ValueError("No Rust-prepared native actions")
    choice = rng.choice(("insert", "delete", "swap", "replace", "condition"))
    if choice == "insert" and len(result) >= 12:
        choice = "replace"
    if choice == "delete" and len(result) <= 1:
        choice = "insert"
    if choice == "swap" and len(result) <= 1:
        choice = "insert"
    if choice == "condition" and not result:
        choice = "insert"

    def native_entry():
        action = rng.choice(action_ids)
        if "otherId" in action:
            # Only source-native Shoot can be inserted. Native APL interprets
            # the condition; Python does not simulate wand swings.
            entry = {"action": {"castSpell": {"spellId": action}}}
            if rng.random() < .65:
                threshold = rng.randrange(10, 100, 5)
                entry["action"]["condition"] = {"cmp": {
                    "lhs": {"currentManaPercent": {}},
                    "op": "OpLt",
                    "rhs": {"const": {"val": str(threshold) + "%"}},
                }}
            return entry
        guard = rng.choice((None, None, "dot_missing", "aura_missing"))
        return source_module.cast_apl(action["spellId"], guard=guard)

    if choice == "insert":
        result.insert(rng.randrange(len(result)+1), native_entry())
    elif choice == "delete":
        del result[rng.randrange(len(result))]
    elif choice == "swap":
        a, b = rng.sample(range(len(result)), 2)
        result[a], result[b] = result[b], result[a]
    elif choice == "replace":
        result[rng.randrange(len(result))] = native_entry()
    elif choice == "condition":
        index = rng.randrange(len(result))
        identity = (((result[index].get("action") or {}).get("castSpell") or {})
                    .get("spellId") or {})
        spell_id = identity.get("spellId")
        other_id = identity.get("otherId")
        if other_id == "OtherActionShoot":
            result[index] = native_entry()
        elif type(spell_id) is not int:
            result[index] = native_entry()
        else:
            # The native conditional syntax is source-owned.
            result[index] = source_module.cast_apl(
                spell_id, guard=rng.choice((None, "dot_missing", "aura_missing")))
    return result


def mutate_talents(encoded, options, rng):
    """Move a single talent point using native get_options rank metadata.

    Only Rust prepare can accept the resulting build; this generator never
    validates game rules or changes gameplay mechanics.
    """
    trees = options["talents"]["trees"]
    values = []
    for part, tree in zip(encoded.split("-"), trees):
        numbers = [int(part[row["index"]]) if row["index"] < len(part) else 0
                   for row in tree["talents"]]
        values.append(numbers)
    donors = [(t, row["index"]) for t, tree in enumerate(trees)
              for row in tree["talents"] if values[t][row["index"]] > 0]
    receivers = [(t, row["index"]) for t, tree in enumerate(trees)
                 for row in tree["talents"]
                 if values[t][row["index"]] < row["max_rank"]
                 and row["minimum_level"] <= options["level"]]
    if not donors or not receivers:
        return encoded
    src_t, src_i = rng.choice(donors)
    dst_t, dst_i = rng.choice(receivers)
    if (src_t, src_i) == (dst_t, dst_i):
        return encoded
    values[src_t][src_i] -= 1
    values[dst_t][dst_i] += 1
    return "-".join("".join(map(str, ranks)).rstrip("0") or "0"
                    for ranks in values)


def mutate_request(parent, *, talent_proposals, pets, pools, action_ids,
                   source_module, options, rng):
    """Uniform selection among all four axes; no per-axis quotas or priorities."""
    child = copy.deepcopy(parent)
    unit = actor(child)
    axis = rng.choice(("talents", "pet", "gear", "apl"))
    if axis == "talents":
        if rng.random() < .75:
            unit["talentsString"] = mutate_talents(
                unit["talentsString"], options, rng)
        else:
            proposed = rng.choice(talent_proposals)
            unit["talentsString"] = proposed["talents"]
    elif axis == "pet":
        set_native_pet(child, rng.choice(pets))
    elif axis == "gear":
        if not pools:
            raise ValueError("Rust provided no level-eligible equipment")
        slot = rng.choice(list(pools))
        available = [item for item in pools[slot]
                     if item != unit["equipment"]["items"][slot]["id"]]
        if available:
            unit["equipment"]["items"][slot] = {"id": rng.choice(available)}
    elif axis == "apl":
        unit["rotation"]["priorityList"] = apl_mutation(
            unit["rotation"]["priorityList"], action_ids, source_module, rng)
    return child, axis


def sorted_observed_native(probes, model, *, predict, engine_sha, scenario_id):
    """Ranks paid 8-mob receipts by surrogate 100-mob time, no 30-s DPS."""
    candidates = []
    for case in probes:
        if case.get("probe") is None:
            continue
        row = predict(model, case["probe"],
                      engine_sha=engine_sha, scenario_id=scenario_id)
        estimate = row.get("estimated_100_mob_elapsed_s")
        if type(estimate) not in (int, float) or not 0 < estimate < float("inf"):
            continue
        candidates.append((float(estimate), case))
    return sorted(candidates, key=lambda row: row[0])


def adaptive_native_search(probes, *, evaluate, model, predict,
                           engine_sha, scenario_id, options, source_module,
                           talent_proposals, pets, iterations, seed, emit):
    """Actually run every new mutation; never accept predicted kills.

    No exact APL sequence, spell, talent, pet or item is privileged by code.
    Exploration is seeded from real native receipts, not handwritten recipes.
    The 8-mob model is a ranking tool; true winners require paid 100-mob truth.
    """
    rng = random.Random(seed)
    pools = source_item_pools(options)
    native_ids = {}
    wand_exposed = False
    for case in probes:
        try:
            prepared = json.loads(case["prepared"].read_text())
        except (OSError, ValueError, KeyError):
            continue
        for action in native_cast_identifiers(prepared):
            native_ids[json.dumps(action, sort_keys=True)] = action
            wand_exposed |= action.get("otherId") == "OtherActionShoot"
    action_ids = list(native_ids.values())
    # An equipped wand is not evidence of Shoot unless Rust prepared it.
    if not action_ids:
        raise RuntimeError("Selected native Rust exported no actor APL actions")
    emit({"native_apl_action_count": len(action_ids),
          "native_shoot_registered": wand_exposed,
          "wand_action": {"otherId": "OtherActionShoot"} if wand_exposed else None})
    visited = {
        request_signature(json.loads((case["folder"]/"source_request.json").read_text()))
        for case in probes
    }
    attempted = completed = 0
    for iteration in range(iterations):
        ranked = sorted_observed_native(probes, model, predict=predict,
                                        engine_sha=engine_sha, scenario_id=scenario_id)
        if not ranked:
            raise RuntimeError("No actual eight-mob native probe to optimize from")
        # Randomized elite selection + occasional wider exploration. Parent
        # selection is adaptive to the objective, not an axis preference.
        if rng.random() < .2:
            parent = rng.choice(ranked)[1]
        else:
            parent = rng.choice(ranked[:min(len(ranked), 8)])[1]
        current = json.loads((parent["folder"]/"source_request.json").read_text())
        candidate = axis = None
        for _ in range(48):
            mutant, dimension = mutate_request(
                current, talent_proposals=talent_proposals, pets=pets,
                pools=pools, action_ids=action_ids, source_module=source_module,
                options=options, rng=rng)
            key = request_signature(mutant)
            if key not in visited:
                visited.add(key)
                candidate, axis = mutant, dimension
                break
        if candidate is None:
            raise RuntimeError("Native candidate search exhausted, cannot silently reuse")
        case = evaluate(candidate, axis, iteration, ranked[0][0])
        probes.append(case)
        attempted += 1
        if case.get("probe") is not None:
            completed += 1
        scored = sorted_observed_native(
            probes, model, predict=predict, engine_sha=engine_sha,
            scenario_id=scenario_id)
        emit({"iteration": iteration, "axis": axis,
              "native_eight_valid": case.get("probe") is not None,
              "attempted": attempted, "completed_eight": completed,
              "best_predicted_100_s": scored[0][0] if scored else None,
              "candidate_id": case["result"]["candidate"],
              "candidate_status": case["result"]["status"]})
    return {"tried": attempted, "completed_eight": completed,
            "population": len(probes)}
