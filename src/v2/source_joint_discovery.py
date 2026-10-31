"""Bounded source-only gear x executable-talent x policy evaluation.

This is a *discovery probe*, not a complete gear optimizer or fixed point.
Candidate gear sets are selected from legal catalogue items using generic
executable stat axes, not guide builds. Every gear/talent state re-synthesizes
and re-executes source-derived caster and mode policies with recovery.
"""
from __future__ import annotations

from src.game.policy import remove_combat_policy_seeds_preserve_maintenance

from dataclasses import replace
from itertools import combinations, product
from time import monotonic
from math import isfinite
from typing import Mapping

from src.version import SOFTWARE_VERSION
from src.game.data.forever.gear import select_named_gear, available_gear_roles
from src.game.data.forever.registry import build_game_ir_slice
from src.game.gear import EXECUTABLE_CASTER_GEAR_STATS, executable_gear_stats, apply_gear_selection
from src.game.talent_search import enumerate_legal_talent_allocations, talent_candidate_id
from src.game.talents import apply_talent_selection
from src.v2.source_mode_search import evaluate_discovered_mode_search
from src.v2.source_policy_search import synthesize_source_policies
from src.v2.generic_backend import _policy_combat_evaluation
from src.v2.source_joint_feedback import trace_joint_feedback
from src.v2.source_db_authority import audit_ir_database_authority


def _gear_envelope(class_key: str, level: int, *, max_gear_candidates: int,
                   gear_weight_order: int = 1,
                   gear_weight_ratios: tuple[float, ...] = (1.0,),
                   required_level_policy: str = "catalogue",
                   include_melee_gear: bool = False,
                   ir_slice=None) -> list[dict]:
    """Finite, source-selected alternatives. Never silently clip the envelope."""
    if required_level_policy not in {"catalogue", "observed"}:
        raise ValueError("required_level_policy must be catalogue or observed")
    if max_gear_candidates < 1:
        raise ValueError('gear envelope cap must be positive')
    axes = tuple(executable_gear_stats(
        ir_slice if ir_slice is not None else build_game_ir_slice(class_key=class_key, level=level))
        if include_melee_gear else EXECUTABLE_CASTER_GEAR_STATS)
    roles = available_gear_roles(class_key) if include_melee_gear else (None,)
    if not isinstance(gear_weight_order, int) or isinstance(gear_weight_order, bool) or not 1 <= gear_weight_order <= len(axes):
        raise ValueError('gear weight combination order outside supported axes')
    # Normalize each non-anchor axis relative to the first axis. Enumerate
    # ratio variants deterministically; never use a class-specific stat hint.
    if (not isinstance(gear_weight_ratios, (tuple, list)) or not gear_weight_ratios
            or len(gear_weight_ratios) > 5 or any(
                isinstance(v, bool) or not isinstance(v, (int, float))
                or not isfinite(v) or v <= 0 for v in gear_weight_ratios)):
        raise ValueError('gear weight ratios must be 1..5 finite positive numbers')
    ratios = tuple(sorted(float(v) for v in gear_weight_ratios))
    if 1.0 not in ratios or len(set(ratios)) != len(ratios):
        raise ValueError('gear weight ratios must include 1.0 and be distinct')
    if gear_weight_order == 1 and ratios != (1.0,):
        raise ValueError('non-unit gear weight ratios require combination order >= 2')
    weight_vectors = []
    for order in range(1, gear_weight_order + 1):
        for combo in combinations(axes, order):
            for tail in product(ratios, repeat=order - 1):
                weight_vectors.append(dict(zip(combo, (1.0, *tail))))
    if len(weight_vectors) > 256:
        raise ValueError('gear weight vector envelope exceeds explicit bound')
    if len(axes) > gear_weight_order:
        # Preserve the previously evaluated caster-all set when broadening
        # to melee stats; otherwise a valid old candidate silently disappears.
        if include_melee_gear:
            weight_vectors.append(dict.fromkeys(EXECUTABLE_CASTER_GEAR_STATS, 1.0))
        weight_vectors.append(dict.fromkeys(axes, 1.0))
    seen: set[tuple] = set()
    rows = []
    for weights in weight_vectors:
        for role in roles:
            selection = select_named_gear(class_key=class_key, level=level, stat_weights=weights,
                                          required_level_policy=required_level_policy, role=role)
            if not selection.slots:
                raise ValueError('catalogue selector returned no legal named equipment')
            ids = tuple(sorted((str(slot), int(item['item_id'])) for slot, item in selection.slots.items()))
            if ids in seen:
                continue
            seen.add(ids)
            rows.append({'id': 'gear:' + ','.join(f'{slot}={iid}' for slot, iid in ids),
                         'selection': selection, 'gear_role': selection.role, 'weight_vector': dict(weights)})
            if len(rows) > max_gear_candidates:
                raise ValueError('source gear candidate envelope exceeds explicit bound')
    return rows


def _evaluate_caster_already_talented(ir, *, level: int, max_policies: int,
                                       schedule_incoming_attacks: bool = False) -> dict:
    """Score directly; never reapply an empty talent selection over provenance."""
    envelope = synthesize_source_policies(
        ir, level=level, max_policies=max_policies,
        include_auto_resource_fallback=True)
    scored = []
    for policy in envelope['policies']:
        result, execution, details = _policy_combat_evaluation(
            ir, level=level, policy_override=policy,
            schedule_incoming_attacks=schedule_incoming_attacks)
        if result is None or execution is None or not execution.timeline.target_defeated:
            continue
        scored.append({'policy_id': policy.id, 'policy': policy.as_dict(),
                       'seconds_per_mob': result.seconds_per_mob,
                       'combat_kill_s': execution.timeline.target_death_s,
                       'recovery_s': details['recovery']['total_s'],
                       'selected_actions': [dict(a) for a in execution.selected_actions]})
    if not scored:
        raise ValueError('no executable source caster policy')
    scored.sort(key=lambda x: (x['seconds_per_mob'], x['policy_id']))
    return {'winner': scored[0], 'alternatives': scored[1:],
            'candidate_count': len(envelope['policies']), 'evaluated_count': len(scored)}


def evaluate_bounded_joint_discovery(*, class_key: str, level: int, ir_slice=None,
                                     max_gear_candidates: int = 8,
                                     gear_weight_order: int = 1,
                                     gear_weight_ratios: tuple[float, ...] = (1.0,),
                                     required_level_policy: str = "catalogue",
                                     include_melee_gear: bool = False,
                                     max_talent_candidates: int = 64,
                                     max_states: int = 256,
                                     max_policies_per_path: int = 96,
                                     max_caster_policies: int = 96,
                                     schedule_incoming_attacks: bool = False) -> dict:
    """Evaluate an explicit finite grid, retaining evidence and incomplete scope.

    No legacy policy, build, guide or gear winner is used as an input. A source
    catalogue or executable-talent truncation fails closed. Non-executable
    talents and stats are reported as blockers rather than credited as scored.
    """
    started = monotonic()
    if max_states < 1 or max_talent_candidates < 1:
        raise ValueError('state and talent envelope caps must be positive')
    source = ir_slice if ir_slice is not None else build_game_ir_slice(class_key=class_key, level=level)
    if source is None:
        raise ValueError(f'no source-backed IR for {class_key} L{level}')
    if (str(source.actor.metadata.get('class_key', '')).lower() != str(class_key).lower()
            or int(source.actor.metadata.get('level', -1)) != int(level)):
        raise ValueError('source actor class/level does not match requested gear legality')
    # Canonical priority policies must not seed discovery.
    source = remove_combat_policy_seeds_preserve_maintenance(source)
    talents, truncated = enumerate_legal_talent_allocations(
        source, level=level, max_candidates=max_talent_candidates)
    if truncated:
        raise ValueError('executable talent candidate envelope exceeds explicit bound')
    gears = _gear_envelope(class_key, level, max_gear_candidates=max_gear_candidates,
                           gear_weight_order=gear_weight_order,
                           gear_weight_ratios=gear_weight_ratios,
                           required_level_policy=required_level_policy,
                           include_melee_gear=include_melee_gear, ir_slice=source)
    if len(gears) * len(talents) > max_states:
        raise ValueError('joint gear x talent state envelope exceeds explicit bound')

    states, rejected = [], []
    for gear in gears:
        selection = gear['selection']
        geared, gear_application = apply_gear_selection(
            source, aggregate_stats=selection.aggregate_stats,
            selected_items=tuple(selection.slots.values()),
            source='canonical_sqlite_forever_catalogue')
        for allocation in talents:
            ir, talent_application = apply_talent_selection(geared, allocation, level=level)
            branch_results = []
            for branch, evaluate, kwargs in (
                ('caster', _evaluate_caster_already_talented,
                 {'max_policies': max_caster_policies,
                  'schedule_incoming_attacks': schedule_incoming_attacks}),
                ('mode', evaluate_discovered_mode_search,
                 {'max_policies_per_path': max_policies_per_path,
                  'schedule_incoming_attacks': schedule_incoming_attacks}),
            ):
                try:
                    # No talent reapplication: it was already applied to this IR.
                    result = (evaluate(ir, level=level, **kwargs) if branch == 'caster' else
                              evaluate(class_key=class_key, level=level, ir_slice=ir, **kwargs))
                except ValueError as exc:
                    # No executable branch is an explicit blocker. Caps and
                    # other search-incompleteness errors must not be suppressed.
                    message = str(exc)
                    if ('envelope exceeds explicit bound' in message
                            or ('no executable source' not in message and 'no safe sourced' not in message)):
                        raise
                    rejected.append({'gear_id': gear['id'],
                                     'talent_id': talent_candidate_id(allocation),
                                     'branch': branch, 'reason': message})
                    continue
                winner = result['winner']
                branch_results.append({
                    'branch': branch,
                    'score_s_per_mob': float(winner['seconds_per_mob']),
                    'policy_id': winner['policy_id'],
                    'policy': winner['policy'],
                    'selected_actions': winner['selected_actions'],
                    'combat_kill_s': winner['combat_kill_s'],
                    'recovery_s': winner['recovery_s'],
                    'combat_mode': winner['path']['combat_mode'] if branch == 'mode' else 'initial',
                    'evaluated_policy_count': result['evaluated_count'],
                    'generated_policy_count': result['candidate_count'],
                    'top_alternatives': [
                        {'score_s_per_mob': float(row['seconds_per_mob']),
                         'policy_id': row['policy_id']}
                        for row in result['alternatives'][:3]],
                })
            if not branch_results:
                rejected.append({'gear_id': gear['id'], 'talent_id': talent_candidate_id(allocation),
                                 'reason': 'no_executable_policy_for_this_state'})
                continue
            branch_results.sort(key=lambda row: (row['score_s_per_mob'], row['branch'], row['policy_id']))
            states.append({
                'gear_id': gear['id'],
                'gear_role': gear['gear_role'],
                'gear_weight_vector': gear['weight_vector'],
                'gear_slots': {slot: dict(item) for slot, item in selection.slots.items()},
                'gear_applied_stats': dict(gear_application.applied_stats),
                'gear_unsupported_stats': dict(gear_application.unsupported_stats),
                'gear_partial_stats': dict(gear_application.partial_stats or {}),
                'talent_id': talent_candidate_id(allocation),
                'talents': talent_application.as_dict(),
                'score_s_per_mob': branch_results[0]['score_s_per_mob'],
                'best_policy': branch_results[0],
                'evaluated_branches': branch_results,
            })
    if not states:
        raise ValueError('no executable joint gear/talent/policy state')
    states.sort(key=lambda row: (row['score_s_per_mob'], row['gear_id'], row['talent_id']))
    # Detect an observed policy difference across gear states at equal talents.
    policies_by_talent: dict[str, set[tuple]] = {}
    for state in states:
        p = state['best_policy']
        signature = (p['branch'], p['combat_mode'], tuple(
            (r['action_id'], tuple((c['kind'], str(c.get('value'))) for c in r.get('conditions', [])))
            for r in p['policy']['rules']))
        policies_by_talent.setdefault(state['talent_id'], set()).add(signature)
    feedback = trace_joint_feedback(states)
    return {
        'feedback': {k: v for k, v in feedback.items() if k not in ('winner', 'global_grid_winner')},
        'status': 'EVALUATED_BOUNDED_JOINT_GRID',
        'incoming_attacks_scored': bool(schedule_incoming_attacks and source.incoming_attacks),
        'software_version': SOFTWARE_VERSION,
        'optimization_ready': False,
        'full_fixed_point': False,
        'class_key': class_key, 'level': level, 'source_ir_id': source.id,
        'source_gear': 'canonical_sqlite_forever_catalogue',
        'source_authority_audit': audit_ir_database_authority(source),
        'gear_candidate_count': len(gears),
        'gear_weight_combination_order': gear_weight_order,
        'melee_gear_search_enabled': bool(include_melee_gear),
        'required_level_policy': required_level_policy,
        'gear_required_level_observed': all(
            item.get('required_level_origin') == 'observed'
            for state in states for item in state['gear_slots'].values()
        ) if required_level_policy == 'observed' else False,
        'gear_weight_ratios': list(sorted(float(v) for v in gear_weight_ratios)),
        'executable_talent_candidate_count': len(talents),
        'evaluated_state_count': len(states),
        'generated_policy_count': sum(
            b['generated_policy_count'] for state in states for b in state['evaluated_branches']),
        'evaluated_policy_count': sum(
            b['evaluated_policy_count'] for state in states for b in state['evaluated_branches']),
        'elapsed_s': round(monotonic() - started, 3),
        'represented_talent_ids': [t.id for t in source.talents],
        'talent_sqlite_coverage': dict(source.provenance.get('talent_sqlite_coverage') or {}),
        'unscored_talent_ids': [t.id for t in source.talents if not any(r.modifiers for r in t.ranks)],
        'talent_legality_verified': not bool((source.provenance.get('talent_sqlite_coverage') or {}).get('blockers')),

        'gear_acquisition_verified': False,
        # A Wowhead list/detail identity proves the item exists, not where/how
        # the player gets it. This catalogue has no sourced acquisition gates.
        'winner_gear_acquisition_blockers': [
            {'slot': slot, 'item_id': item['item_id'],
             'source_type': item.get('source_type'),
             'reason': 'acquisition_method_and_prerequisites_not_in_catalogue'}
            for slot, item in sorted(states[0]['gear_slots'].items())
        ],
        'all_talents_represented': False,
        'rejected': rejected,
        'winner': states[0],
        'alternatives': states[1:],
        'policy_changed_across_gear_at_fixed_talents': any(len(s) > 1 for s in policies_by_talent.values()),
        'missing': [
            'canonical_sqlite_ability_talent_actor_field_lineage_unverified',
            'complete_talent_tree_representation', 'all_legal_gear_combinations',
            'source_gear_role_bridge_is_class_limited',
            'unsupported_gear_stats_and_weapon_effects', 'item_acquisition_cost_and_reachability',
            'cross_mode_policy_mixing', 'iterative_fixed_point_or_global_optimum',
            'multi_pull_survival_and_route', 'independent_fidelity',
        ],
    }
