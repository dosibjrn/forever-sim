"""Generic, typed APL mutation from a source-backed executable action corpus.

Never invent spell IDs or expression opcodes: the frozen profile's castSpell
identities and predicate ASTs are the grammar's admissible terminals. This
admits new actions, predicate rewrites, and threshold changes beyond shuffling.
It does NOT certify that a new spell/predicate combination is optimal, or that
any particular talent/spec configuration can cast it: paid native runs decide.
"""
from __future__ import annotations

import copy
import json
import random
import re


def _spell_key(spell):
    return json.dumps(spell, sort_keys=True, separators=(",", ":"))


def _corpus(source_actions):
    spells = {}
    allowed_casts = {}
    predicates_by_spell = {}
    for entry in source_actions:
        action = entry.get("action", {})
        cast = action.get("castSpell")
        if not isinstance(cast, dict):
            # Item, potion and other native-action conditions are not cast
            # predicates and must never enter the generated spell grammar.
            continue
        spell = cast.get("spellId")
        if not isinstance(spell, dict):
            continue
        # Native castSpell uses a oneof identity: spellId, itemId or
        # otherId. Preserve all identities found in the frozen source,
        # but only generate new cast actions from actual spell IDs.
        identity = (
            (isinstance(spell.get("spellId"), int) and spell["spellId"] > 0)
            or (isinstance(spell.get("itemId"), int) and spell["itemId"] > 0)
            or (isinstance(spell.get("otherId"), str) and bool(spell["otherId"]))
        )
        if not identity:
            continue
        key = _spell_key(spell)
        allowed_casts[key] = copy.deepcopy(spell)
        if isinstance(spell.get("spellId"), int) and spell["spellId"] > 0:
            spells[key] = copy.deepcopy(spell)
            condition = action.get("condition")
            if isinstance(condition, dict) and condition:
                # Conditions are source-observed on this exact spell/rank.
                # Never graft another cast's (or an item action's) AST here.
                predicates_by_spell.setdefault(key, []).append(copy.deepcopy(condition))
    if not spells:
        raise ValueError("APL source action corpus contains no known castSpell identities")
    return (
        tuple(spells.values()),
        {key: tuple(values) for key, values in predicates_by_spell.items()},
        frozenset(allowed_casts),
    )


def _condition_literals(node, out):
    """Only alter literal RHS constants of comparisons, never spell IDs."""
    if isinstance(node, dict):
        cmp = node.get("cmp")
        if isinstance(cmp, dict):
            rhs = cmp.get("rhs", {})
            val = rhs.get("const", {}).get("val") if isinstance(rhs, dict) else None
            if isinstance(val, str) and re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:ms|s)?", val):
                out.append(rhs["const"])
        for child in node.values():
            _condition_literals(child, out)
    elif isinstance(node, list):
        for child in node:
            _condition_literals(child, out)


def _tune_literal(condition, rng):
    candidates = []
    _condition_literals(condition, candidates)
    if not candidates:
        return False
    entry = rng.choice(candidates)
    old = entry["val"]
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(ms|s)?", old)
    if match is None:
        return False
    number, unit = float(match.group(1)), match.group(2) or ""
    # All substitutions keep the input AST's type/unit. A 0 remains 0 or
    # positive; thresholds are bounded to avoid pathological parser values.
    scale = rng.choice((0.5, 0.75, 1.25, 1.5, 2.0))
    next_val = min(100000.0, max(0.0, number * scale))
    if not unit:
        entry["val"] = str(int(round(next_val)))
    else:
        entry["val"] = (str(int(next_val)) if next_val.is_integer()
                        else f"{next_val:.2f}".rstrip("0").rstrip(".")) + unit
    return entry["val"] != old


def _new_cast(spells, predicates_by_spell, rng):
    spell = copy.deepcopy(rng.choice(spells))
    action = {"castSpell": {"spellId": spell}}
    predicates = predicates_by_spell.get(_spell_key(spell), ())
    if predicates and rng.random() < 0.8:
        condition = copy.deepcopy(rng.choice(predicates))
        if rng.random() < 0.7:
            _tune_literal(condition, rng)
        action["condition"] = condition
    return {"action": action}


def _is_unconditional_cast(entry):
    """Whether an entry is a castSpell action with no active condition."""
    action = entry.get("action", {})
    return (isinstance(action, dict)
            and isinstance(action.get("castSpell"), dict)
            and not action.get("condition"))


def _has_fallback(actions):
    return any(_is_unconditional_cast(entry) for entry in actions)


def _ensure_fallback(actions, source_actions):
    if _has_fallback(source_actions) and not _has_fallback(actions):
        fallback = next(copy.deepcopy(x) for x in source_actions
                        if _is_unconditional_cast(x))
        # A missing unconditional cast is a termination hazard: repair it.
        if len(actions) >= 20:
            actions.pop()
        actions.append(fallback)

    # APL priorities are first-match: an unconditional cast can shadow every
    # lower-priority conditional action while it is castable. Keep all such
    # casts as a stable suffix. Conditional casts and opaque native actions
    # retain their original relative order and are evaluated first.
    fallbacks = [entry for entry in actions if _is_unconditional_cast(entry)]
    if fallbacks:
        actions[:] = [
            entry for entry in actions if not _is_unconditional_cast(entry)
        ] + fallbacks


def mutate_apl(actions, source_actions, rng, *, cold=False):
    """Return a new legal-grammar priority list, class/gate independent.

    Cold generation samples a randomized action list, *not* a paid reference
    candidate; later elite mutations use the same operators. The grammar is
    deliberately restricted to expression trees and spell IDs present in the
    supplied frozen input. This is not full spellbook-level completeness.
    Unconditional castSpell entries remain a stable fallback suffix.
    """
    spells, predicates_by_spell, allowed = _corpus(source_actions)
    if cold:
        # A cold search may READ the saved request as a source-backed grammar,
        # but must not initialize its policy from the saved priority list.
        # Independently sample new casts/predicates and optional opaque native
        # actions; an identical policy can still arise by chance and is legal.
        opaque = [entry for entry in source_actions
                  if "castSpell" not in entry.get("action", {})]
        # The saved request is a source vocabulary, not an APL length prior.
        # Keep the full native action-list budget available to cold search:
        # a 10-action source grammar must still admit 19-action legal policies.
        length = rng.randint(2, 20)
        result = []
        for _ in range(length):
            if opaque and rng.random() < 0.15:
                result.append(copy.deepcopy(rng.choice(opaque)))
            else:
                result.append(_new_cast(spells, predicates_by_spell, rng))
        # A fallback is a freshly sampled source spell, never a copied saved
        # reference priority entry. Keep the real native action legality check.
        if not _has_fallback(result):
            if len(result) >= 20:
                result.pop()
            result.append({"action": {"castSpell": {
                "spellId": copy.deepcopy(rng.choice(spells))}}})
        rng.shuffle(result)
    else:
        result = copy.deepcopy(actions)
    if len(result) < 2:
        raise ValueError("APL requires at least two priority actions")
    operations = 0 if cold else 1
    for _ in range(operations):
        modes = ["swap", "replace_condition", "tune_condition", "insert_cast", "drop_action"]
        mode = rng.choices(modes, weights=(27, 25, 20, 20, 8))[0]
        if mode == "swap":
            i, j = rng.sample(range(len(result)), 2)
            result[i], result[j] = result[j], result[i]
        elif mode == "insert_cast" and len(result) < 20:
            result.insert(rng.randrange(len(result) + 1), _new_cast(spells, predicates_by_spell, rng))
        elif mode == "drop_action" and len(result) > 3:
            result.pop(rng.randrange(len(result)))
        elif mode == "replace_condition":
            casts = [a for a in result if "castSpell" in a.get("action", {})]
            if casts:
                entry = rng.choice(casts)["action"]
                cast = entry.get("castSpell", {})
                spell = cast.get("spellId") if isinstance(cast, dict) else None
                predicates = predicates_by_spell.get(_spell_key(spell), ())
                if predicates and rng.random() < 0.80:
                    entry["condition"] = copy.deepcopy(rng.choice(predicates))
                    _tune_literal(entry["condition"], rng)
                else:
                    entry.pop("condition", None)
        elif mode == "tune_condition":
            casts = [a for a in result if isinstance(a.get("action", {}).get("condition"), dict)]
            if casts:
                _tune_literal(rng.choice(casts)["action"]["condition"], rng)
    _ensure_fallback(result, source_actions)
    # Non-cast native actions (strictSequence, channelSpell, multidot, etc.)
    # are opaque source-backed actions. They may be reordered, never invented
    # or edited by this cast-oriented grammar.
    source_noncast = {
        _spell_key(entry.get("action", {}))
        for entry in source_actions
        if "castSpell" not in entry.get("action", {})
    }
    for entry in result:
        action = entry.get("action", {})
        if "castSpell" in action:
            if _spell_key(action["castSpell"].get("spellId")) not in allowed:
                raise ValueError("APL mutation created an unapproved cast identity")
        elif _spell_key(action) not in source_noncast:
            raise ValueError("APL mutation created an unsupported non-cast action")
    return result
