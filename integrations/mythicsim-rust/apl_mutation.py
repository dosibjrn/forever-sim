"""Generic APL mutation over exact source-backed action templates.

Spell identities, native cast payloads and each source action's condition tree
stay paired. Cold and elite search may add, remove and reorder source actions,
but never graft, tune or drop a source guard. MythicSim decides the submitted
action's legality and effect.
"""
from __future__ import annotations

import copy
import json
import random


def _spell_key(spell):
    return json.dumps(spell, sort_keys=True, separators=(",", ":"))


def _condition_spell_identity_keys(node):
    """Return exact cast-spell and aura identities referenced by a predicate.

    spellId references must be backed by source castSpell identities. auraId
    references are a separate vocabulary: they must have been observed in a
    predicate attached to a source castSpell action. Item/opaque actions never
    contribute predicates or aura identities.
    """
    spell_refs = []
    aura_refs = []
    valid = True

    def visit(value):
        nonlocal valid
        if isinstance(value, dict):
            for key, child in value.items():
                if key in ("spellId", "auraId"):
                    refs = spell_refs if key == "spellId" else aura_refs
                    if isinstance(child, dict):
                        spell_id = child.get("spellId")
                        if (isinstance(spell_id, int)
                                and not isinstance(spell_id, bool)
                                and spell_id > 0
                                and "itemId" not in child
                                and "otherId" not in child):
                            refs.append(_spell_key(child))
                        else:
                            valid = False
                    elif (isinstance(child, int)
                          and not isinstance(child, bool) and child > 0):
                        refs.append(_spell_key({"spellId": child}))
                    else:
                        valid = False
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(node)
    return tuple(spell_refs), tuple(aura_refs), valid


def _condition_metric_spell_ids(node, metric):
    """Return the spell IDs referenced by a DoT/cast-time metric."""
    spell_ids = []
    valid = True

    def visit(value):
        nonlocal valid
        if isinstance(value, dict):
            if metric in value:
                metric_value = value[metric]
                identity = (metric_value.get("spellId")
                            if isinstance(metric_value, dict) else None)
                spell_id = (identity.get("spellId")
                            if isinstance(identity, dict) else identity)
                if (not isinstance(spell_id, int)
                        or isinstance(spell_id, bool) or spell_id <= 0):
                    valid = False
                else:
                    spell_ids.append(spell_id)
            for key, child in value.items():
                if key != metric:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(node)
    return tuple(spell_ids), valid


def _condition_is_safe_for_cast(condition, cast_spell):
    """Reject a DoT's self-refresh predicate when attached to another cast.

    For example, dotRemainingTime(25309) <= spellCastTime(25309) is safe on
    cast 25309, but unsafe on Life Tap 11689: it is true while the DoT is
    absent and can starve a later positive-damage fallback. Cross-spell
    predicates whose DoT and cast-time spell IDs differ remain eligible.
    """
    dot_ids, dot_valid = _condition_metric_spell_ids(condition, "dotRemainingTime")
    cast_time_ids, cast_time_valid = _condition_metric_spell_ids(
        condition, "spellCastTime"
    )
    if not dot_valid or not cast_time_valid:
        return False
    if not dot_ids or not cast_time_ids:
        return True
    action_spell_id = (
        cast_spell.get("spellId") if isinstance(cast_spell, dict) else None
    )
    if (not isinstance(action_spell_id, int)
            or isinstance(action_spell_id, bool) or action_spell_id <= 0):
        return False
    return not any(
        dot_id == cast_time_id and dot_id != action_spell_id
        for dot_id in dot_ids
        for cast_time_id in cast_time_ids
    )


def _predicates_for_spell(predicates, spell):
    return tuple(
        condition for condition in predicates
        if _condition_is_safe_for_cast(condition, spell)
    )


def _corpus(source_actions):
    spells = {}
    allowed_casts = {}
    source_predicates = []
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
        spell_id = spell.get("spellId")
        if isinstance(spell_id, int) and not isinstance(spell_id, bool) and spell_id > 0:
            spells[key] = copy.deepcopy(spell)
            condition = action.get("condition")
            if (isinstance(condition, dict) and condition
                    and _condition_is_safe_for_cast(condition, spell)):
                # Keep source-bound cross-spell predicates, but not a DoT's
                # self-refresh predicate grafted onto an unrelated utility cast.
                source_predicates.append((key, copy.deepcopy(condition)))
    if not spells:
        raise ValueError("APL source action corpus contains no known castSpell identities")

    source_spell_keys = frozenset(spells)
    # Aura identities are a separate source vocabulary from castSpell IDs.
    # They may be reused only when observed in a predicate attached to an
    # actual source castSpell action whose spell references are source-bound.
    source_aura_keys = set()
    for _, condition in source_predicates:
        spell_refs, aura_refs, valid = _condition_spell_identity_keys(condition)
        if valid and set(spell_refs).issubset(source_spell_keys):
            source_aura_keys.update(aura_refs)
    source_aura_keys = frozenset(source_aura_keys)
    predicates_by_spell = {key: [] for key in source_spell_keys}
    same_seen = {key: set() for key in source_spell_keys}
    compatible_predicates = []
    compatible_seen = set()
    for source_key, condition in source_predicates:
        spell_refs, aura_refs, valid = _condition_spell_identity_keys(condition)
        if (not valid
                or not set(spell_refs).issubset(source_spell_keys)
                or not set(aura_refs).issubset(source_aura_keys)):
            continue
        condition_key = _spell_key(condition)
        if condition_key not in same_seen[source_key]:
            predicates_by_spell[source_key].append(condition)
            same_seen[source_key].add(condition_key)
        if condition_key not in compatible_seen:
            compatible_predicates.append(condition)
            compatible_seen.add(condition_key)

    return (
        tuple(spells.values()),
        {key: tuple(values) for key, values in predicates_by_spell.items()},
        frozenset(allowed_casts),
        tuple(compatible_predicates),
        source_aura_keys,
    )

def _source_action_templates(source_actions):
    """Return exact cast action payloads keyed by their source spell identity."""
    templates = {}
    for entry in source_actions:
        action = entry.get("action", {}) if isinstance(entry, dict) else {}
        cast = action.get("castSpell") if isinstance(action, dict) else None
        spell = cast.get("spellId") if isinstance(cast, dict) else None
        spell_id = spell.get("spellId") if isinstance(spell, dict) else None
        if (not isinstance(spell_id, int) or isinstance(spell_id, bool)
                or spell_id <= 0):
            continue
        variants = templates.setdefault(_spell_key(spell), {})
        variants.setdefault(_spell_key(action), copy.deepcopy(action))
    return {key: tuple(variants.values()) for key, variants in templates.items()}


def _new_cast(spells, predicates_by_spell, compatible_predicates, rng,
              source_action_templates=None):
    """Sample a source action intact; its condition never leaves its cast."""
    spell = copy.deepcopy(rng.choice(spells))
    variants = (source_action_templates or {}).get(_spell_key(spell), ())
    if not variants:
        raise ValueError("APL source spell has no exact source action template")
    return {"action": copy.deepcopy(rng.choice(variants))}


def _is_unconditional_cast(entry):
    action = entry.get("action", {})
    return (
        isinstance(action, dict)
        and isinstance(action.get("castSpell"), dict)
        and not action.get("condition")
    )


def _has_fallback(actions):
    return any(_is_unconditional_cast(entry) for entry in actions)


def _ensure_fallback(actions, source_actions):
    source_fallback = next(
        (copy.deepcopy(entry) for entry in source_actions
         if _is_unconditional_cast(entry)),
        None,
    )
    if source_fallback is not None and not _has_fallback(actions):
        # Restore only the exact source fallback; never synthesize an unguarded cast.
        if len(actions) >= 20:
            actions.pop()
        actions.append(source_fallback)

    # Unconditional casts are priority fallbacks, not ordinary actions.
    # Preserve the order of the conditional/opaque prefix and the fallback
    # suffix independently so a fallback cannot shadow a useful condition.
    fallbacks = [entry for entry in actions if _is_unconditional_cast(entry)]
    actions[:] = [entry for entry in actions if not _is_unconditional_cast(entry)] + fallbacks

def mutate_apl(actions, source_actions, rng, *, cold=False):
    """Add, remove and reorder exact source actions without rewriting guards.

    Cold generation samples a randomized action list from the selected source
    action corpus. Elite mutations first restore any changed cast payload or
    condition to an exact source action, then perform one structural mutation.
    Native MythicSim remains responsible for game-semantic legality.
    """
    spells, predicates_by_spell, _allowed_casts, compatible_predicates, _source_aura_keys = (
        _corpus(source_actions)
    )
    source_action_templates = _source_action_templates(source_actions)
    if not source_action_templates:
        raise ValueError("APL source action corpus contains no exact spell templates")

    source_cast_action_keys = {
        _spell_key(entry["action"])
        for entry in source_actions
        if isinstance(entry, dict)
        and isinstance(entry.get("action"), dict)
        and isinstance(entry["action"].get("castSpell"), dict)
    }
    source_noncast = {
        _spell_key(entry.get("action", {}))
        for entry in source_actions
        if isinstance(entry, dict)
        and isinstance(entry.get("action"), dict)
        and "castSpell" not in entry["action"]
    }
    source_action_keys_by_spell = {
        key: {_spell_key(action) for action in variants}
        for key, variants in source_action_templates.items()
    }

    if cold:
        # The saved request supplies only an action grammar. It does not seed
        # the saved priority list or authorize synthetic unconditional casts.
        opaque = [
            entry for entry in source_actions
            if isinstance(entry, dict)
            and isinstance(entry.get("action"), dict)
            and "castSpell" not in entry["action"]
        ]
        length = rng.randint(2, 20)
        result = []
        for _ in range(length):
            if opaque and rng.random() < 0.15:
                result.append(copy.deepcopy(rng.choice(opaque)))
            else:
                result.append(_new_cast(
                    spells, predicates_by_spell, compatible_predicates, rng,
                    source_action_templates=source_action_templates,
                ))
        rng.shuffle(result)
    else:
        result = copy.deepcopy(actions)
        # A candidate may only carry an exact source action/condition pair.
        # If an inherited candidate has a rewritten or missing guard, restore
        # one exact source variant for that same spell before mutating it.
        for index, entry in enumerate(result):
            action = entry.get("action", {}) if isinstance(entry, dict) else None
            if not isinstance(action, dict):
                raise ValueError("APL mutation contains a malformed action")
            cast = action.get("castSpell")
            if isinstance(cast, dict):
                spell = cast.get("spellId")
                spell_id = spell.get("spellId") if isinstance(spell, dict) else None
                if (isinstance(spell_id, int) and not isinstance(spell_id, bool)
                        and spell_id > 0):
                    key = _spell_key(spell)
                    variants = source_action_templates.get(key, ())
                    if not variants:
                        raise ValueError("APL mutation created an unapproved cast identity")
                    if _spell_key(action) not in source_action_keys_by_spell[key]:
                        result[index] = {"action": copy.deepcopy(rng.choice(variants))}
                elif _spell_key(action) not in source_cast_action_keys:
                    raise ValueError("APL mutation created an unsupported native cast action")
            elif _spell_key(action) not in source_noncast:
                raise ValueError("APL mutation created an unsupported non-cast action")

    # Source conditions are immutable grammar terminals. Only structural
    # operators remain: priority swap, exact source-action insertion and drop.
    operations = 0 if cold else 1
    for _ in range(operations):
        mode = rng.choices(
            ["swap", "insert_cast", "drop_action"],
            weights=(45, 40, 15),
        )[0]
        if mode == "swap":
            i, j = rng.sample(range(len(result)), 2)
            result[i], result[j] = result[j], result[i]
        elif mode == "insert_cast" and len(result) < 20:
            result.insert(rng.randrange(len(result) + 1), _new_cast(
                spells, predicates_by_spell, compatible_predicates, rng,
                source_action_templates=source_action_templates,
            ))
        elif mode == "drop_action" and len(result) > 3:
            result.pop(rng.randrange(len(result)))

    # Keep a source-backed unconditional fallback only when the source APL
    # actually contains one. Never manufacture an unguarded copy of a guarded
    # healing/damage action merely to satisfy a generic fallback convention.
    _ensure_fallback(result, source_actions)

    for entry in result:
        action = entry.get("action", {}) if isinstance(entry, dict) else None
        if not isinstance(action, dict):
            raise ValueError("APL mutation contains a malformed action")
        cast = action.get("castSpell")
        if isinstance(cast, dict):
            spell = cast.get("spellId")
            spell_id = spell.get("spellId") if isinstance(spell, dict) else None
            if (isinstance(spell_id, int) and not isinstance(spell_id, bool)
                    and spell_id > 0):
                key = _spell_key(spell)
                if _spell_key(action) not in source_action_keys_by_spell.get(key, set()):
                    raise ValueError("APL mutation changed a source cast payload or condition")
            elif _spell_key(action) not in source_cast_action_keys:
                raise ValueError("APL mutation created an unsupported native cast action")
        elif _spell_key(action) not in source_noncast:
            raise ValueError("APL mutation created an unsupported non-cast action")
    return result

