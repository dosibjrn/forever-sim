"""P3 gear-scoring smoke over source-legal native item alternatives.

Selected native items are sampled as one or two representative candidates per
slot, never an exhaustive top-five-by-ilvl certificate. The legacy SQLite
scorer retains its previous scope until its native consumer is migrated.
No invented positive stat weights or separate game-legality rules live here.
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
DEFENSIVE_STAT_AXES = frozenset({
    'armor', 'stamina', 'dodge', 'parry', 'health_regeneration_per_5s',
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


# Axis names that canonical equipped-weapon source facts may expose. The same
# string on a qualified scenario proxy is not evidence of an item dependency.
# Weapon DPS and equipped mean hit are separate channels: a fixed-speed form
# can use equipped DPS without using an item's min/max/speed.
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
            # A stat-axis label alone is not proof that an equipped item
            # supplies this effect. Mirror the gear applicator: an action is
            # rewritten only when its explicit mode requirement matches.
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
        # A stat-axis label alone is not proof that this auto attack uses an
        # equipped item. Match the canonical source fact and exact mode; None
        # intentionally matches only a mode-free auto attack and a '*' fact.
        for fact, mode_id in facts:
            if (mode == mode_id
                    and source.kind == fact.damage_source_kind
                    and fact.source_stat in _EQUIPPED_WEAPON_DPS_AXES):
                equipped_dps = True
                equipped_mean_hit |= fact.weapon_speed_semantics == 'equipped'
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
                  defensive_positive_required: bool = True,
                  required_level_policy: str = 'catalogue',
                  native_options_binary: str | None = None,
                  native_options_response: dict | None = None) -> dict:
    """Measure the current source catalogue's fast P3 score coverage.

    Failures are explicit, not silently clipped or filled with tiny positives.
    The caller must supply weights tied to the evaluated build/policy; the
    smoke validator itself cannot invent a beneficial value for any axis.
    """
    if not class_key or not 1 <= int(level) <= 60:
        raise ValueError('P3_INVALID_CHECKPOINT')
    if native_options_response is not None and native_options_binary is None:
        raise ValueError('P3_NATIVE_OPTIONS_SNAPSHOT_REQUIRES_SELECTED_BINARY')
    if not isinstance(defensive_positive_required, bool):
        raise ValueError('P3_DEFENSIVE_APPLICABILITY_NOT_BOOLEAN')
    # The legacy SQLite-only smoke retains its historic positivity diagnostic.
    # Native item alternatives follow the approved P3 contract: an irrelevant
    # stat may have a genuinely measured zero, and a negative trade-off is not
    # invalid solely because the item exposes that axis.
    strictly_positive_axes = (
        (POSITIVE_WHEN_PRESENT if defensive_positive_required
         else POSITIVE_WHEN_PRESENT - DEFENSIVE_STAT_AXES)
        if native_options_binary is None else frozenset())
    native_options_metadata = None
    if native_options_binary is not None:
        from src.game.native_p3_item_options import native_p3_item_records
        rows, unmapped_by_item, native_options_metadata = native_p3_item_records(
            native_options_binary, class_key, level,
            native_response=native_options_response)
        source_name = 'MYTHICSIM_NATIVE_ITEM_OPTIONS'
    else:
        rows = available_items(class_key, level, required_level_policy=required_level_policy)
        unmapped_by_item = {}
        source_name = 'CURRENT_CANONICAL_SQLITE_LEGAL_ITEMS'
    if not rows and native_options_metadata is None:
        raise ValueError('P3_NO_LEGAL_ITEMS_IN_CURRENT_DB')
    blockers = set()
    if native_options_metadata is not None:
        if native_options_metadata['status'] == 'partial_level_unknown':
            blockers.add(
                'NATIVE_ITEM_OPTIONS_PARTIAL_LEVEL_UNKNOWN:'
                + str(native_options_metadata['unverified_candidate_count']))
        if not rows:
            blockers.add('NATIVE_ITEM_OPTIONS_NO_VERIFIED_CANDIDATES')
    if weight_evidence_kind not in SOURCE_CONTEXT_WEIGHT_KINDS:
        blockers.add('UNVERIFIED_CONTEXT_WEIGHTS')
    parsed = {str(axis): _weight_value(value) for axis, value in weights.items()}
    for axis, weight in parsed.items():
        if weight is not None and weight < 0 and native_options_binary is None:
            blockers.add('NEGATIVE_WEIGHT:' + axis)
    by_slot = defaultdict(list)
    for item in rows:
        for slot in source_item_slots(item):
            by_slot[slot].append(item)
    slots = {}
    tested = 0
    tested_stat_assertions = 0
    verified_stat_assertions = 0
    encountered_dps = set()
    for slot, items in sorted(by_slot.items()):
        # Candidate legality comes solely from the selected source. Sample up
        # to two real native alternatives, favoring a different stat vector so
        # the gear scorer can distinguish meaningful candidate configurations.
        # The untouched SQLite fallback retains its historical diagnostic set.
        ordered = sorted(items, key=lambda item:(
            -(item.item_level if item.item_level is not None else -1), item.item_id))
        if native_options_binary is not None:
            selected = ordered[:1]
            if len(ordered) > 1:
                first_stats = _ordinary_stats(ordered[0])
                alternative = next((item for item in ordered[1:]
                                    if _ordinary_stats(item) != first_stats),
                                   ordered[1])
                selected.append(alternative)
        else:
            selected = ordered[:5]
        reports = []
        for item in selected:
            tested += 1
            for native_axis in unmapped_by_item.get(item.item_id, ()):
                blockers.add('NATIVE_UNMAPPED_STAT_AXIS:' + native_axis)
            stats = _ordinary_stats(item)
            if not weapon_damage_dependent:
                stats.pop('mean_weapon_hit_damage', None)
            dps_axes=('weapon_dps','wand_dps','ranged_weapon_dps')
            encountered_dps.update(set(stats) & set(dps_axes))
            parts = {}
            item_weight_checks = 0
            item_valid_weight_checks = 0
            for axis, amount in sorted(stats.items()):
                weight = parsed.get(axis)
                # Each (real ilvl-top-five legal item, ordinary required stat)
                # is a comparable executed scorer assertion. A slot becomes
                # all-or-nothing near the end and would hide incremental work.
                required_axis = (axis in POSITIVE_WHEN_PRESENT
                    or (axis in dps_axes and equipped_weapon_dps_relevant is not False)
                    or (axis == 'mean_weapon_hit_damage' and weapon_damage_dependent))
                if required_axis:
                    tested_stat_assertions += 1
                    item_weight_checks += 1
                if weight is None:
                    # Only named required ordinary axes must have positive
                    # weights. Unmodeled resistances/procs cannot veto P3.
                    if axis in POSITIVE_WHEN_PRESENT:
                        blockers.add('MISSING_WEIGHT:' + axis)
                    continue
                if weight < 0 and native_options_binary is None:
                    blockers.add('NEGATIVE_WEIGHT:' + axis)
                    continue
                if weight <= 0 and axis in strictly_positive_axes:
                    blockers.add('NONPOSITIVE_RELEVANT_WEIGHT:' + axis)
                contribution = weight * amount
                if not isfinite(contribution):
                    blockers.add('NONFINITE_CONTRIBUTION:' + axis)
                    continue
                parts[axis] = contribution
                if required_axis and (native_options_binary is not None or weight > 0 or
                        (weight == 0 and axis in DEFENSIVE_STAT_AXES
                         and not defensive_positive_required)):
                    # Native scoring of a zero/negative measured weight is a
                    # legitimate finite selector assertion, not a claim that
                    # the underlying native combat effect is beneficial.
                    item_valid_weight_checks += 1
            # Check the ACTUAL selector scorer; do not certify a parallel
            # dot-product that the optimizer itself never uses.
            scorer_weights = {axis:weight for axis,weight in parsed.items()
                              if weight is not None and (weapon_damage_dependent or axis!='mean_weapon_hit_damage')}
            score = item_score(item,scorer_weights)
            if not isfinite(score):
                blockers.add('NONFINITE_SCORE:' + str(item.item_id))
            elif abs(score-sum(parts.values()))>1e-7*max(1.,abs(score)):
                blockers.add('SCORER_MISMATCH:' + str(item.item_id))
            else:
                # Never award a weighted-field check if the real selector's
                # score does not agree with the executed contributions.
                verified_stat_assertions += item_valid_weight_checks
            reports.append({'item_id': int(item.item_id), 'name': item.name,
                            'item_level': item.item_level,
                            'required_level': item.required_level,
                            'score': score if isfinite(score) else None,
                            'contributions': parts,
                            # Preserve native/source item units independently
                            # of their weighted score contributions. Paid P3
                            # sensitivity must use actual item-sized deltas.
                            'stat_values': {str(axis): float(amount)
                                            for axis, amount in sorted(stats.items())},
                            'source_url': item.source_url})
        slots[slot] = {'legal_count': len(items),
                       'selected_ids': [int(x.item_id) for x in selected],
                       'items': reports,
                       'selection': ('NATIVE_REPRESENTATIVE_UP_TO_TWO' if
                                     native_options_binary is not None else
                                     'HIGHEST_ITEM_LEVEL_NOT_SCORE')}
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
            'source': source_name,
            'legal_item_count': len(rows), 'tested_item_count': tested,
            'slot_count': len(slots), 'slots': slots,
            'tested_stat_assertions': tested_stat_assertions,
            'verified_stat_assertions': verified_stat_assertions,
            'weight_evidence_kind': weight_evidence_kind,
            'defensive_positive_required': defensive_positive_required,
            'weapon_damage_dependent': bool(weapon_damage_dependent),
            'equipped_weapon_dps_relevant': bool(equipped_weapon_dps_relevant),
            'native_item_options_status': (native_options_metadata or {}).get('status'),
            'native_unverified_candidate_count': (native_options_metadata or {}).get(
                'unverified_candidate_count', 0),
            'native_excluded_non_client_item_count': (native_options_metadata or {}).get(
                'excluded_non_client_item_count', 0),
            'native_item_options_source': (native_options_metadata or {}).get('source'),
            'blockers': sorted(blockers), 'p3_pass': not blockers,
            'scope': 'PROCESS_V2_FAST_P3_SMOKE_NOT_GLOBAL_BIS'}


def _policy_uses_bear_form(ir, policy) -> bool:
    """Require positive defensive weights only for a selected Bear-form policy.

    Merely having a legal Bear spell or autoattack in the full source IR does
    not make a caster or Cat policy a Bear policy.
    """
    if any(str(mode.id) == 'bear' and bool(mode.initial)
           for mode in getattr(ir, 'modes', ())):
        return True
    by_id = {action.id: action for action in ir.actions}
    for rule in policy.rules:
        action = by_id.get(rule.action_id)
        if action is None:
            raise ValueError('P3_POLICY_ACTION_NOT_IN_SOURCE_IR:' + str(rule.action_id))
        if any(req.get('kind') == 'mode_is' and str(req.get('value')) == 'bear'
               for req in getattr(action, 'requirements', ())):
            return True
        if any(getattr(effect, 'effect_type', None) == 'mode_change'
               and str(effect.target_mode_id) == 'bear'
               for effect in action.effects):
            return True
    return False


def fast_p3_smoke_for_policy(*, source_ir, policy, **kwargs) -> dict:
    """Bind P3's mean-hit condition to the *actual* source-IR policy actions."""
    if ('weapon_damage_dependent' in kwargs or 'equipped_weapon_dps_relevant' in kwargs
            or 'defensive_positive_required' in kwargs):
        raise ValueError('P3_MANUAL_POLICY_APPLICABILITY_OVERRIDE_FORBIDDEN')
    has_weapon_effect = policy_uses_weapon_damage(source_ir, policy)
    uses_equipped_weapon, uses_equipped_mean_hit = _policy_equipped_weapon_dependencies(source_ir, policy)
    defensive_positive_required = (str(kwargs.get('class_key', '')).lower() == 'warrior'
                                   or _policy_uses_bear_form(source_ir, policy))
    report = fast_p3_smoke(
        weapon_damage_dependent=uses_equipped_mean_hit,
        equipped_weapon_dps_relevant=uses_equipped_weapon,
        defensive_positive_required=defensive_positive_required,
        **kwargs,
    )
    report['source_policy'] = {
        'source_ir_id': str(source_ir.id),
        'policy_id': str(policy.id),
        'action_ids': [str(rule.action_id) for rule in policy.rules],
        'weapon_damage_effect_derived_from_ir': bool(has_weapon_effect),
        'equipped_weapon_dependency_derived_from_canonical_mode_source_facts': True,
        'equipped_weapon_mean_hit_relevant': bool(uses_equipped_mean_hit),
        'equipped_weapon_damage_relevant': bool(uses_equipped_weapon),
        'defensive_positive_required': defensive_positive_required,
    }
    return report
