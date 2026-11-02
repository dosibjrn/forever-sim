"""PROCESS v2 P3: fast, source-legal top-five-by-ilvl gear scorer smoke.

The five *test* items per slot are selected by item level, never by their
computed score. This is NOT a BiS ranking, complete-source attestation, or a
replacement for gear×talent×policy optimization. No game/class-specific
weights or invented positive epsilons are created by this validator.
"""
from __future__ import annotations

from collections import defaultdict
from math import isfinite
from typing import Mapping

from src.game.data.forever.source_checkpoint_p3 import source_item_slots
from src.rulesets.forever.items.runtime_selection import available_items, item_score, item_scoring_vector

# Ordinary sourced fields with a positive-impact requirement when present in
# the *selected* legal item set. Other numeric axes must remain non-negative.
POSITIVE_WHEN_PRESENT = frozenset({
    'armor', 'stamina', 'spirit', 'agility', 'strength', 'intellect',
    'attack_power', 'spell_power', 'crit', 'hit', 'dodge', 'parry',
    'mp5', 'health_regeneration_per_5s', 'ranged_attack_power',
})
SOURCE_CONTEXT_WEIGHT_KINDS = frozenset({'MEASURED_SOURCE_CONTEXT', 'SOURCE_FORMULA_CONTEXT'})


def policy_uses_weapon_damage(ir, policy) -> bool:
    """Check executable policy actions against the common sourced effect IR."""
    by_id = {a.id: a for a in ir.actions}
    for rule in policy.rules:
        action = by_id.get(rule.action_id)
        if action is None:
            raise ValueError('P3_POLICY_ACTION_NOT_IN_SOURCE_IR:' + str(rule.action_id))
        if any(
            getattr(effect, 'effect_type', None) == 'weapon_damage'
            for effect in action.effects
        ):
            return True
    return False


# Equipment DPS can reach CombatRuntime through either an actor DPS stat or
# a source-authorized replacement of a form-specific flat_dps anchor. A flat
# number is NOT proof of a non-equipment source. Also, weapon *DPS* and the
# equipped weapon's *mean hit* are separate channels: a fixed-speed form may
# benefit from weapon DPS while ignoring the equipped weapon's min/max/speed.
_EQUIPPED_WEAPON_DPS_AXES = frozenset({
    'weapon_dps', 'wand_dps', 'ranged_weapon_dps',
})


def _policy_equipped_weapon_dependencies(ir, policy) -> tuple[bool, bool]:
    """Return (equipped weapon DPS, equipped mean weapon hit) dependencies.

    Source facts use the same canonical resolver as actual gear application.
    All source-specific equipment behavior remains in SQLite, not class checks.
    """
    by_id = {action.id: action for action in ir.actions}
    actions = []
    reachable_modes = set()
    for rule in policy.rules:
        action = by_id.get(rule.action_id)
        if action is None:
            raise ValueError('P3_POLICY_ACTION_NOT_IN_SOURCE_IR:' + str(rule.action_id))
        actions.append(action)
        reachable_modes.update(
            str(req['value']) for req in getattr(action, 'requirements', ())
            if req.get('kind') == 'mode_is'
        )
        for effect in action.effects:
            if getattr(effect, 'effect_type', '') == 'mode_change':
                reachable_modes.add(str(effect.target_mode_id))
    # Use the exact source-authorized rules the production gear applicator
    # uses to replace a fixed feral DPS anchor with the selected weapon.
    if getattr(ir, 'actor', None) is not None:
        from src.game.gear import _weapon_facts_for_ir
        facts = _weapon_facts_for_ir(ir)
    else:
        facts = ()
    equipped_dps = False
    equipped_mean_hit = False
    for action in actions:
        action_modes = {
            str(req['value']) for req in getattr(action, 'requirements', ())
            if req.get('kind') == 'mode_is'
        }
        for effect in action.effects:
            if getattr(effect, 'effect_type', None) != 'weapon_damage':
                continue
            source = getattr(effect, 'damage_source', None)
            if source is None:
                raise ValueError('P3_UNRESOLVED_WEAPON_DAMAGE_SOURCE:' + str(action.id))
            if getattr(source, 'dps_stat_id', None) in _EQUIPPED_WEAPON_DPS_AXES:
                equipped_dps = True
                equipped_mean_hit = True
            for fact, mode_id in facts:
                if (mode_id in action_modes
                        and source.kind == fact.damage_source_kind
                        and fact.source_stat in _EQUIPPED_WEAPON_DPS_AXES):
                    equipped_dps = True
                    # A fixed-speed cat/bear attack depends on equipped DPS,
                    # not on weapon speed or the original weapon hit range.
                    equipped_mean_hit |= fact.weapon_speed_semantics == 'equipped'
    for attack in getattr(ir, 'auto_attacks', ()):
        mode = getattr(attack, 'required_mode_id', None)
        if mode is not None and str(mode) not in reachable_modes:
            continue
        source = getattr(attack, 'damage_source', None)
        if source is None:
            raise ValueError('P3_UNRESOLVED_AUTO_DAMAGE_SOURCE:' + str(attack.id))
        if getattr(source, 'dps_stat_id', None) in _EQUIPPED_WEAPON_DPS_AXES:
            equipped_dps = True
        for fact, mode_id in facts:
            if (mode == mode_id
                    and source.kind == fact.damage_source_kind
                    and fact.source_stat in _EQUIPPED_WEAPON_DPS_AXES):
                equipped_dps = True
    return equipped_dps, equipped_mean_hit


def policy_uses_equipped_weapon_damage(ir, policy) -> bool:
    """Does the evaluated policy use the equipped weapon's DPS?"""
    return _policy_equipped_weapon_dependencies(ir, policy)[0]


def policy_uses_equipped_weapon_mean_hit(ir, policy) -> bool:
    """Does a policy ability use the equipped weapon's own hit range/speed?"""
    return _policy_equipped_weapon_dependencies(ir, policy)[1]


def _ordinary_stats(item) -> dict[str, float]:
    """Use the same production item-scoring fields as gear selection.

    DPS channel distinctions, raw hit/crit/dodge/parry units, source HP5 and
    mean weapon hit damage must not be duplicated in a separate test scorer.
    """
    return {key: value for key, value in item_scoring_vector(item).items() if value != 0.}


def _weight_value(value):
    if isinstance(value, Mapping):
        value = value.get('weight_s_saved_per_mob_per_unit')
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if isfinite(result) else None


def fast_p3_smoke(*, class_key: str, level: int, weights: Mapping,
                  weight_evidence_kind: str, weapon_damage_dependent: bool,
                  equipped_weapon_dps_relevant: bool | None = None,
                  required_level_policy: str = 'catalogue') -> dict:
    """Measure the current source catalogue's fast P3 score coverage.

    Failures are explicit, not silently clipped or filled with tiny positives.
    The caller must supply weights tied to the evaluated build/policy; the
    smoke validator itself cannot invent a beneficial value for any axis.
    """
    if not class_key or not 1 <= int(level) <= 60:
        raise ValueError('P3_INVALID_CHECKPOINT')
    rows = available_items(class_key, level, required_level_policy=required_level_policy)
    if not rows:
        raise ValueError('P3_NO_LEGAL_ITEMS_IN_CURRENT_DB')
    blockers = set()
    if weight_evidence_kind not in SOURCE_CONTEXT_WEIGHT_KINDS:
        blockers.add('UNVERIFIED_CONTEXT_WEIGHTS')
    parsed = {str(axis): _weight_value(value) for axis, value in weights.items()}
    for axis, weight in parsed.items():
        if weight is not None and weight < 0:
            blockers.add('NEGATIVE_WEIGHT:' + axis)
    by_slot = defaultdict(list)
    for item in rows:
        for slot in source_item_slots(item):
            by_slot[slot].append(item)
    slots = {}
    tested = 0
    encountered_dps = set()
    for slot, items in sorted(by_slot.items()):
        # The legal test set is chosen *only* by item level and stable ID.
        selected = sorted(items, key=lambda item:(
            -(item.item_level if item.item_level is not None else -1), item.item_id))[:5]
        reports = []
        for item in selected:
            tested += 1
            stats = _ordinary_stats(item)
            if not weapon_damage_dependent:
                stats.pop('mean_weapon_hit_damage', None)
            dps_axes=('weapon_dps','wand_dps','ranged_weapon_dps')
            encountered_dps.update(set(stats) & set(dps_axes))
            parts = {}
            for axis, amount in sorted(stats.items()):
                weight = parsed.get(axis)
                if weight is None:
                    # Only named required ordinary axes must have positive
                    # weights. Unmodeled resistances/procs cannot veto P3.
                    if axis in POSITIVE_WHEN_PRESENT:
                        blockers.add('MISSING_WEIGHT:' + axis)
                    continue
                if weight < 0:
                    blockers.add('NEGATIVE_WEIGHT:' + axis)
                    continue
                if weight <= 0 and axis in POSITIVE_WHEN_PRESENT:
                    blockers.add('NONPOSITIVE_RELEVANT_WEIGHT:' + axis)
                contribution = weight * amount
                if not isfinite(contribution):
                    blockers.add('NONFINITE_CONTRIBUTION:' + axis)
                    continue
                parts[axis] = contribution
            # Check the ACTUAL selector scorer; do not certify a parallel
            # dot-product that the optimizer itself never uses.
            scorer_weights = {axis:weight for axis,weight in parsed.items()
                              if weight is not None and (weapon_damage_dependent or axis!='mean_weapon_hit_damage')}
            score = item_score(item,scorer_weights)
            if not isfinite(score):
                blockers.add('NONFINITE_SCORE:' + str(item.item_id))
            elif abs(score-sum(parts.values()))>1e-7*max(1.,abs(score)):
                blockers.add('SCORER_MISMATCH:' + str(item.item_id))
            reports.append({'item_id': int(item.item_id), 'name': item.name,
                            'item_level': item.item_level,
                            'required_level': item.required_level,
                            'score': score if isfinite(score) else None,
                            'contributions': parts, 'source_url': item.source_url})
        slots[slot] = {'legal_count': len(items),
                       'selected_ids': [int(x.item_id) for x in selected],
                       'items': reports, 'selection': 'HIGHEST_ITEM_LEVEL_NOT_SCORE'}
    # At least ONE legally applicable DPS channel is required, not every
    # melee/wand/ranged weapon in the world. Its axis must be from actual gear.
    # Legacy direct callers retain the original default smoke semantics. The
    # source-bound policy entry point derives actual equipped-weapon relevance.
    if equipped_weapon_dps_relevant is None:
        equipped_weapon_dps_relevant = bool(encountered_dps)
    if equipped_weapon_dps_relevant and encountered_dps and not any(
        (parsed.get(axis) or 0) > 0 for axis in encountered_dps
    ):
        blockers.add('MISSING_APPLICABLE_DPS_WEIGHT')
    if weapon_damage_dependent:
        mean_weight = parsed.get('mean_weapon_hit_damage')
        if mean_weight is None:
            blockers.add('MISSING_WEIGHT:mean_weapon_hit_damage')
        elif mean_weight <= 0:
            blockers.add('NONPOSITIVE_RELEVANT_WEIGHT:mean_weapon_hit_damage')
    return {'checkpoint': f'{class_key}:L{int(level)}',
            'source': 'CURRENT_CANONICAL_SQLITE_LEGAL_ITEMS',
            'legal_item_count': len(rows), 'tested_item_count': tested,
            'slot_count': len(slots), 'slots': slots,
            'weight_evidence_kind': weight_evidence_kind,
            'weapon_damage_dependent': bool(weapon_damage_dependent),
            'equipped_weapon_dps_relevant': bool(equipped_weapon_dps_relevant),
            'blockers': sorted(blockers), 'p3_pass': not blockers,
            'scope': 'PROCESS_V2_FAST_P3_SMOKE_NOT_GLOBAL_BIS'}


def fast_p3_smoke_for_policy(*, source_ir, policy, **kwargs) -> dict:
    """Bind P3's mean-hit condition to the *actual* source-IR policy actions."""
    if 'weapon_damage_dependent' in kwargs or 'equipped_weapon_dps_relevant' in kwargs:
        raise ValueError('P3_MANUAL_WEAPON_DAMAGE_OVERRIDE_FORBIDDEN')
    has_weapon_effect = policy_uses_weapon_damage(source_ir, policy)
    uses_equipped_weapon, uses_equipped_mean_hit = _policy_equipped_weapon_dependencies(source_ir, policy)
    report = fast_p3_smoke(
        weapon_damage_dependent=uses_equipped_mean_hit,
        equipped_weapon_dps_relevant=uses_equipped_weapon,
        **kwargs,
    )
    report['source_policy'] = {
        'source_ir_id': str(source_ir.id),
        'policy_id': str(policy.id),
        'action_ids': [str(rule.action_id) for rule in policy.rules],
        'weapon_damage_effect_derived_from_ir': bool(has_weapon_effect),
        'equipped_weapon_dependency_derived_from_source_dps_stat_or_canonical_mode_facts': True,
        'equipped_weapon_mean_hit_relevant': bool(uses_equipped_mean_hit),
        'equipped_weapon_damage_relevant': bool(uses_equipped_weapon),
    }
    return report
