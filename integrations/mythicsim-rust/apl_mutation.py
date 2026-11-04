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


def _source_cast_templates(source_actions):
    """Preserve exact source cast payloads (including healing targets) for proposals."""
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
        variants.setdefault(_spell_key(cast), copy.deepcopy(cast))
    return {key: tuple(variants.values()) for key, variants in templates.items()}


def _cast_from_source(spell, cast_templates, rng):
    variants = cast_templates.get(_spell_key(spell), ())
    if not variants:
        return {"spellId": copy.deepcopy(spell)}
    return copy.deepcopy(variants[0] if len(variants) == 1 else rng.choice(variants))


def _new_cast(spells, predicates_by_spell, compatible_predicates, rng,
              cast_templates=None):
    spell = copy.deepcopy(rng.choice(spells))
    action = {"castSpell": _cast_from_source(spell, cast_templates or {}, rng)}
    preferred = _predicates_for_spell(
        predicates_by_spell.get(_spell_key(spell), ()), spell
    )
    cross_spell = _predicates_for_spell(compatible_predicates, spell)
    predicates = preferred
    # Same-spell remains a preference; compatible cross-spell predicates
    # remain eligible unless their self-refresh test is unsafe for this cast.
    if not preferred or rng.random() >= 0.8:
        predicates = cross_spell
    if predicates and rng.random() < 0.8:
        condition = copy.deepcopy(rng.choice(predicates))
        if rng.random() < 0.7:
            _tune_literal(condition, rng)
        action["condition"] = condition
    return {"action": action}


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
        # A missing unconditional cast is a termination hazard: repair it.
        if len(actions) >= 20:
            actions.pop()
        actions.append(source_fallback)

    # Unconditional casts are priority fallbacks, not ordinary actions.
    # Preserve the order of the conditional/opaque prefix and the fallback
    # suffix independently so a fallback cannot shadow a useful condition.
    fallbacks = [entry for entry in actions if _is_unconditional_cast(entry)]
    actions[:] = [entry for entry in actions if not _is_unconditional_cast(entry)] + fallbacks

def mutate_apl(actions, source_actions, rng, *, cold=False,
               preserve_source_conditions=False):
    """Return a new source-bounded priority list.

    HPS/TPS callers preserve the exact source action -> condition AST. In that
    mode cold generation samples complete source entries, later mutations may
    reorder/insert/drop complete source entries, and no condition is sanitized,
    replaced, tuned or synthesized. MythicSim remains the legality authority.
    DPS keeps the broader predicate/cast mutation grammar.
    """
    if preserve_source_conditions:
        # Do not run the Python predicate grammar or legality filters in this
        # mode. The complete source entry is the unit of mutation.
        spells = []
        predicates_by_spell = {}
        compatible_predicates = []
        source_aura_keys = set()
        cast_templates = {}
        allowed = {
            _spell_key(cast.get("spellId"))
            for entry in source_actions
            for cast in [entry.get("action", {}).get("castSpell")]
            if isinstance(cast, dict) and isinstance(cast.get("spellId"), dict)
        }
    else:
        spells, predicates_by_spell, allowed, compatible_predicates, source_aura_keys = _corpus(source_actions)
        cast_templates = _source_cast_templates(source_actions)

    if cold:
        if preserve_source_conditions:
            if len(source_actions) < 2:
                raise ValueError(
                    "Condition-preserving cold APL requires at least two source actions"
                )
            length = rng.randint(2, min(20, len(source_actions)))
            result = [copy.deepcopy(entry) for entry in rng.sample(source_actions, length)]
        else:
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
                    result.append(_new_cast(spells, predicates_by_spell, compatible_predicates, rng,
                                            cast_templates=cast_templates))
            # A fallback is a freshly sampled source spell, never a copied saved
            # reference priority entry. Keep the real native action legality check.
            if not _has_fallback(result):
                if len(result) >= 20:
                    result.pop()
                result.append({"action": {"castSpell": _cast_from_source(
                    rng.choice(spells), cast_templates, rng)}})
        rng.shuffle(result)
    else:
        result = copy.deepcopy(actions)
        if not preserve_source_conditions:
            source_spell_keys = frozenset(_spell_key(spell) for spell in spells)
            # Do not let an inherited, source-unknown aura/spell reference survive
            # merely because the elite mutation happened not to replace it. This
            # sanitizes only spell-cast predicates; opaque/item actions stay frozen.
            for entry in result:
                action = entry.get("action", {})
                cast = action.get("castSpell")
                spell = cast.get("spellId") if isinstance(cast, dict) else None
                if not isinstance(spell, dict) or not (
                    isinstance(spell.get("spellId"), int)
                    and not isinstance(spell.get("spellId"), bool)
                    and spell["spellId"] > 0
                ):
                    continue
                condition = action.get("condition")
                if not isinstance(condition, dict) or not condition:
                    continue
                spell_refs, aura_refs, valid = _condition_spell_identity_keys(condition)
                if (not valid
                        or not set(spell_refs).issubset(source_spell_keys)
                        or not set(aura_refs).issubset(source_aura_keys)
                        or not _condition_is_safe_for_cast(condition, spell)):
                    action.pop("condition", None)

    if len(result) < 2:
        raise ValueError("APL requires at least two priority actions")
    operations = 0 if cold else 1
    for _ in range(operations):
        if preserve_source_conditions:
            modes = ["swap", "insert_source_action", "drop_action"]
            mode = rng.choices(modes, weights=(55, 30, 15))[0]
        else:
            modes = ["swap", "replace_condition", "tune_condition", "insert_cast", "drop_action"]
            mode = rng.choices(modes, weights=(27, 25, 20, 20, 8))[0]
        if mode == "swap":
            i, j = rng.sample(range(len(result)), 2)
            result[i], result[j] = result[j], result[i]
        elif mode == "insert_source_action" and len(result) < 20:
            present = {_spell_key(entry) for entry in result}
            candidates = [
                entry for entry in source_actions
                if _spell_key(entry) not in present
            ]
            if candidates:
                result.insert(rng.randrange(len(result) + 1),
                              copy.deepcopy(rng.choice(candidates)))
        elif mode == "insert_cast" and len(result) < 20:
            result.insert(rng.randrange(len(result) + 1), _new_cast(
                spells, predicates_by_spell, compatible_predicates, rng,
                cast_templates=cast_templates))
        elif mode == "drop_action" and len(result) > 3:
            result.pop(rng.randrange(len(result)))
        elif mode == "replace_condition":
            casts = [a for a in result if "castSpell" in a.get("action", {})]
            if casts:
                entry = rng.choice(casts)["action"]
                cast = entry.get("castSpell", {})
                spell = cast.get("spellId") if isinstance(cast, dict) else None
                preferred = _predicates_for_spell(
                    predicates_by_spell.get(_spell_key(spell), ()), spell
                )
                cross_spell = _predicates_for_spell(compatible_predicates, spell)
                predicates = preferred
                if not preferred or rng.random() >= 0.8:
                    predicates = cross_spell
                if predicates and rng.random() < 0.80:
                    entry["condition"] = copy.deepcopy(rng.choice(predicates))
                    _tune_literal(entry["condition"], rng)
                else:
                    entry.pop("condition", None)
        elif mode == "tune_condition":
            casts = [a for a in result if isinstance(a.get("action", {}).get("condition"), dict)]
            if casts:
                _tune_literal(rng.choice(casts)["action"]["condition"], rng)
    if preserve_source_conditions:
        # This lane only swaps, inserts, or drops complete entries copied from
        # the original native source request. Do not silently reorder its
        # unconditional casts, insert a Python-mandated fallback, or apply a
        # second Warcraft action-identity veto: the paid native scorer owns
        # whether this distinct APL can execute.
        return result
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
