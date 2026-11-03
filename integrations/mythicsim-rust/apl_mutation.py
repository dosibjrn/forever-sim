"""Generic, typed APL mutation from a source-backed executable action corpus.

Never invent spell IDs or expression opcodes. A cast action and its predicate
are an atomic source-backed pair: mutation may reorder pairs and tune numeric
thresholds inside a pair, but may not attach one spell's predicate to another.
This does NOT certify that a spell/talent/gear combination is optimal; paid
native runs decide.
"""
from __future__ import annotations

import copy
import json
import random
import re


def _spell_key(spell):
    return json.dumps(spell, sort_keys=True, separators=(",", ":"))


def _condition_shape(node):
    """Normalize tunable numeric thresholds while preserving predicate structure."""
    if isinstance(node, dict):
        result = {}
        for key, child in node.items():
            if (key == "val" and isinstance(child, str)
                    and re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?(?:ms|s)?", child)):
                result[key] = "<NUMERIC_LITERAL>"
            else:
                result[key] = _condition_shape(child)
        return result
    if isinstance(node, list):
        return [_condition_shape(child) for child in node]
    return node


def _condition_key(condition):
    if not isinstance(condition, dict) or not condition:
        return None
    return _spell_key(_condition_shape(condition))


def _corpus(source_actions):
    """Index complete source action/predicate pairs by their cast identity."""
    source_casts = []
    source_by_identity = {}
    allowed_casts = {}
    for entry in source_actions:
        action = entry.get("action", {})
        cast = action.get("castSpell")
        if isinstance(cast, dict):
            spell = cast.get("spellId")
            if isinstance(spell, dict):
                # Native castSpell uses a oneof identity: spellId, itemId or
                # otherId. Preserve all identities, but generate new casts
                # only from complete source entries with a numeric spellId.
                identity = (
                    (isinstance(spell.get("spellId"), int) and spell["spellId"] > 0)
                    or (isinstance(spell.get("itemId"), int) and spell["itemId"] > 0)
                    or (isinstance(spell.get("otherId"), str) and bool(spell["otherId"]))
                )
                if identity:
                    key = _spell_key(spell)
                    allowed_casts[key] = copy.deepcopy(spell)
                    source_by_identity.setdefault(key, []).append(copy.deepcopy(entry))
                    if isinstance(spell.get("spellId"), int) and spell["spellId"] > 0:
                        source_casts.append(copy.deepcopy(entry))
    if not source_casts:
        raise ValueError("APL source action corpus contains no known castSpell identities")
    return tuple(source_casts), source_by_identity, frozenset(allowed_casts)

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


def _new_cast(source_casts, rng):
    """Sample an atomic source cast/predicate pair; tune only its own predicate."""
    entry = copy.deepcopy(rng.choice(source_casts))
    condition = entry.get("action", {}).get("condition")
    if isinstance(condition, dict) and condition and rng.random() < 0.7:
        _tune_literal(condition, rng)
    return entry


def _source_fallback(source_actions):
    """Return the last unconditional source spell, the original APL's filler."""
    for entry in reversed(source_actions):
        action = entry.get("action", {})
        cast = action.get("castSpell")
        spell = cast.get("spellId") if isinstance(cast, dict) else None
        if (isinstance(spell, dict)
                and isinstance(spell.get("spellId"), int)
                and spell["spellId"] > 0
                and "condition" not in action):
            return entry
    return None


def _has_fallback(actions, fallback):
    if fallback is None:
        return True
    fallback_spell = fallback["action"]["castSpell"]["spellId"]
    fallback_key = _spell_key(fallback_spell)
    return any(
        "castSpell" in entry.get("action", {})
        and "condition" not in entry.get("action", {})
        and _spell_key(entry["action"]["castSpell"].get("spellId")) == fallback_key
        for entry in actions
    )


def _ensure_fallback(actions, source_actions):
    fallback = _source_fallback(source_actions)
    if fallback is not None and not _has_fallback(actions, fallback):
        # Keep the source APL's final unconditional spell as the actual
        # fallback; never invent an unconditional copy of a conditional spell.
        if len(actions) >= 20:
            actions.pop()
        actions.append(copy.deepcopy(fallback))

def mutate_apl(actions, source_actions, rng, *, cold=False):
    """Return a new legal-grammar priority list, class/gate independent.

    Cold generation samples a randomized action list, *not* a paid reference
    candidate; later elite mutations use the same operators. The grammar is
    deliberately restricted to expression trees and spell IDs present in the
    supplied frozen input. This is not full spellbook-level completeness.
    """
    source_casts, source_by_identity, allowed = _corpus(source_actions)
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
                result.append(_new_cast(source_casts, rng))
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
            result.insert(rng.randrange(len(result) + 1), _new_cast(source_casts, rng))
        elif mode == "drop_action" and len(result) > 3:
            result.pop(rng.randrange(len(result)))
        elif mode == "replace_condition":
            casts = [a for a in result if "castSpell" in a.get("action", {})]
            if casts:
                entry = rng.choice(casts)["action"]
                spell = entry.get("castSpell", {}).get("spellId")
                templates = source_by_identity.get(_spell_key(spell), ()) if isinstance(spell, dict) else ()
                if templates:
                    template = rng.choice(templates)["action"]
                    condition = template.get("condition")
                    if isinstance(condition, dict) and condition:
                        entry["condition"] = copy.deepcopy(condition)
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
            identity = action["castSpell"].get("spellId")
            identity_key = _spell_key(identity)
            if identity_key not in allowed:
                raise ValueError("APL mutation created an unapproved cast identity")
            source_variants = source_by_identity.get(identity_key, ())
            allowed_conditions = {
                _condition_key(source_entry.get("action", {}).get("condition"))
                for source_entry in source_variants
            }
            if _condition_key(action.get("condition")) not in allowed_conditions:
                raise ValueError("APL mutation created an unapproved spell-condition pair")
        elif _spell_key(action) not in source_noncast:
            raise ValueError("APL mutation created an unsupported non-cast action")
    return result
