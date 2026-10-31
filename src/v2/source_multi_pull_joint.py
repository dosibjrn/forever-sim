"""Source-backed independent gear x talent x policy search on repeated pulls.

The search objective is *always* the same stateful combat/recovery objective.
No legacy build, class, talent or item identities influence discovery. Sampling,
gear screening and finalist limits are explicit, not global-optimum claims.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from time import monotonic
from typing import Mapping

from src.game.data.forever.registry import build_game_ir_slice
from src.game.gear import apply_gear_selection
from src.game.multi_pull import evaluate_repeated_pulls
from src.game.talent_search import enumerate_legal_talent_allocations, talent_candidate_id
from src.game.talents import apply_talent_selection, validate_talent_selection
from src.shared.leveling.objective import representative_hp
from src.v2.source_joint_discovery import _gear_envelope
from src.v2.source_mode_search import discover_mode_paths
from src.v2.source_policy_search import synthesize_source_policies
from src.v2.source_staged_joint_search import _diverse_gear_indices


def independent_allocation_sample(allocations, *, budget: int, excluded_ids=(), family_tree=None):
    """Deterministic family coverage then hash selection; never use scores or guides."""
    if budget < 1:
        raise ValueError('allocation budget must be positive')
    excluded = set(excluded_ids)
    pool = [a for a in allocations if talent_candidate_id(a) not in excluded]
    if not pool:
        raise ValueError('no independent allocations after held-out exclusion')
    families = sorted({key for a in pool for key, rank in a.items() if rank > 0})
    candidates = {}
    empty = next((a for a in pool if not a), None)
    if empty is not None:
        candidates[talent_candidate_id(empty)] = empty
    # Highest reachable rank per family, then fewest other points; use source
    # family identity only as an axis, never privileged family names.
    # Interleave talent trees so a small budget cannot accidentally sample
    # only one specialization because of alphabetic family names.
    tree_map = dict(family_tree or {})
    groups = {}
    for family in families:
        groups.setdefault(str(tree_map.get(family, "unknown")), []).append(family)
    ordered_families = []
    while any(groups.values()):
        for tree in sorted(groups):
            if groups[tree]:
                ordered_families.append(groups[tree].pop(0))
    for family in ordered_families:
        options = [a for a in pool if a.get(family, 0) > 0]
        if options:
            chosen = min(options, key=lambda a: (-a[family], sum(a.values()), talent_candidate_id(a)))
            candidates[talent_candidate_id(chosen)] = chosen
    ranked = sorted(pool, key=lambda a: (sha256(talent_candidate_id(a).encode()).hexdigest(),
                                        talent_candidate_id(a)))
    for a in ranked:
        if len(candidates) >= budget:
            break
        candidates.setdefault(talent_candidate_id(a), a)
    # When budget < family coverage, select in stable order and report omissions.
    selected = list(candidates.values())[:budget]
    represented = {family for a in selected for family, rank in a.items() if rank > 0}
    return selected, {'total_available': len(pool), 'sampled': len(selected),
                      'reachable_executable_families': len(families),
                      'represented_families': len(represented),
                      'unrepresented_families': sorted(set(families)-represented),
                      'unscored_allocations': len(pool)-len(selected),
                      'sampling_rule': 'empty_then_round_robin_trees_each_family_max_rank_min_spent_then_SHA256'}


def _legal_local_neighbors(allocations, incumbent, *, excluded_ids=(), budget=0):
    """Legal source-roster one-point moves, diverse by changed talent family.

    Only candidates from the already validated canonical legal universe enter
    the frontier. A move can add, remove, or transfer one talent point. There
    is no class/spell-specific preference and no incumbent fixture seeding.
    """
    if budget < 0:
        raise ValueError('negative local frontier budget')
    if budget == 0:
        return []
    excluded = set(excluded_ids)
    families = sorted({key for a in allocations for key in a} | set(incumbent))
    by_changed_family = {family: [] for family in families}
    for candidate in allocations:
        cid = talent_candidate_id(candidate)
        if cid in excluded:
            continue
        changed = [f for f in families if candidate.get(f, 0) != incumbent.get(f, 0)]
        distance = sum(abs(candidate.get(f, 0) - incumbent.get(f, 0)) for f in changed)
        if distance == 0 or distance > 2 or len(changed) > 2:
            continue
        # A 2-point move within one family is a legal adjacent rank change;
        # across two families it is a one-point transfer.
        key = min(changed)
        by_changed_family[key].append((distance, cid, candidate))
    for rows in by_changed_family.values():
        rows.sort(key=lambda row: (row[0], sha256(row[1].encode()).hexdigest()))
    chosen = []
    while len(chosen) < budget and any(by_changed_family.values()):
        for family in families:
            if by_changed_family[family]:
                chosen.append(by_changed_family[family].pop(0)[2])
                if len(chosen) >= budget:
                    break
    return chosen


def _source_policy_envelope(ir, *, level: int, policy_cap: int):
    """Generate source-derived caster and all source-reachable form policies."""
    # Classes with no source mode graph still have valid caster/weapon policies.
    # A malformed *nonempty* mode graph must continue to fail closed.
    paths = discover_mode_paths(ir, level=level) if ir.modes else {'paths': [], 'rejected': []}
    cases, blockers = [], []
    for path in [None, *paths['paths']]:
        mode = None if path is None else path['combat_mode']
        try:
            envelope = synthesize_source_policies(
                ir, level=level, max_policies=policy_cap,
                include_auto_resource_fallback=True, mode_id=mode,
                budget_mode="balanced_frontier")
        except ValueError as exc:
            blockers.append({'mode': mode, 'reason': str(exc)})
            continue
        blockers.extend({'mode': mode, **row} for row in envelope.get('excluded', ()))
        if envelope['policy_frontier_truncated']:
            blockers.append({'mode': mode, 'reason': 'bounded_policy_frontier',
                             'evaluated': len(envelope['policies']),
                             'supported_actions_not_represented': envelope['supported_actions_not_represented']})
        pre = () if path is None else (path['entry_action_id'],)
        post = () if path is None else (path['exit_action_id'],)
        for policy in envelope['policies']:
            cases.append((policy, pre, post, mode))
    if not cases:
        raise ValueError('no source-derived executable policy candidates')
    return cases, blockers


def _score_state(source, *, level, gear, allocation, pulls, policy_cap, target_health,
                 sustained_scenario: dict | None = None, bonus_talent_points: int = 0):
    selection = gear['selection']
    geared, gear_app = apply_gear_selection(
        source, aggregate_stats=selection.aggregate_stats,
        selected_items=tuple(selection.slots.values()),
        source='canonical_sqlite_forever_catalogue')
    ir, talent_app = apply_talent_selection(geared, allocation, level=level, bonus_talent_points=bonus_talent_points)
    cases, blockers = _source_policy_envelope(ir, level=level, policy_cap=policy_cap)
    evaluated = 0
    scored_action_ids = set()
    rejected = 0
    reasons = {}
    best = None
    from src.v2.source_companion_policy_search import companion_policy_envelope
    companion_variants, companion_coverage = companion_policy_envelope(ir)
    from src.game.model import HealEffect, PeriodicHealEffect
    healing = sorted(a.id for a in ir.actions if any(
        isinstance(e, (HealEffect, PeriodicHealEffect)) for e in a.effects))
    # Search the real repeated-pull objective, not merely the locally fastest
    # between-pull recovery. A faster heal may shift cooldown/swing phase and
    # make the next pull slower. All/none/each single sourced heal are legal,
    # independently executable policies; no class-specific heal list.
    recovery_variants = [None] if not healing else [None, (), *((action_id,) for action_id in healing)]
    for policy, pre, post, mode in cases:
        for companion_policy in companion_variants:
            for recovery_choice in recovery_variants:
                try:
                    result = evaluate_repeated_pulls(
                        ir_slice=ir, policy=policy, level=level, target_health=target_health,
                        count=pulls, schedule_incoming_attacks=True, apply_target_defense=True,
                        pre_combat_action_ids=pre, post_combat_action_ids=post,
                        companion_policy_override=companion_policy,
                        recovery_action_ids=recovery_choice,
                        **(sustained_scenario or {}))
                except (ValueError, RuntimeError, KeyError) as exc:
                    rejected += 1
                    reason = str(exc).split(':', 1)[0]
                    reasons[reason] = reasons.get(reason, 0) + 1
                    continue
                score = float(result.seconds_per_mob)
                if not isfinite(score) or score <= 0:
                    raise ValueError('invalid repeated-pull score')
                evaluated += 1
                scored_action_ids.update(str(a['action_id']) for pull in result.pulls
                                         for a in pull['selected_actions'])
                if best is None or (score, policy.id, str(recovery_choice)) < (
                    best['seconds_per_mob'], best['policy_id'], str(best['recovery_action_ids'])):
                    best = {'seconds_per_mob': score, 'policy_id': policy.id,
                            'recovery_action_ids':None if recovery_choice is None else list(recovery_choice),
                            'companion_policies':{k:v.as_dict() for k,v in companion_policy.items()},
                            'policy': policy.as_dict(), 'mode': mode,
                            'entry_actions': list(pre), 'exit_actions': list(post),
                            'pulls': list(result.pulls)}
    return {'gear_id': gear['id'], 'gear_role': gear['gear_role'],
            'sustained_scenario': dict(sustained_scenario or {}), 'bonus_talent_points': bonus_talent_points,
            'gear_slots': {slot: {'item_id': int(item['item_id']), 'name': item['name']}
                           for slot, item in selection.slots.items()},
            'gear_stats_applied': dict(gear_app.applied_stats),
            'gear_stats_unsupported': dict(gear_app.unsupported_stats),
            'talent_allocation': dict(allocation),
            'talent_modifiers_applied': len(talent_app.applied_modifiers),
            'policy_generated': len(cases)*len(companion_variants)*len(recovery_variants),
            'companion_policy_coverage':companion_coverage,
            'recovery_strategy_count':len(recovery_variants),
            'recovery_strategy_coverage':{'evaluated':len(recovery_variants),
                'total_subsets':2**len(healing),
                'complete':len(recovery_variants)>=2**len(healing)}, 'policy_evaluated': evaluated,
            'policy_rejected': rejected, 'rejection_reasons': reasons,
            'executed_action_ids': sorted(scored_action_ids),
            'source_policy_blockers': blockers, 'best_policy': best,
            'seconds_per_mob': None if best is None else best['seconds_per_mob']}


def search_joint_repeated_pulls(*, class_key: str, level: int, pulls: int = 3,
                                max_allocations: int = 36, screening_gear_count: int = 2,
                                finalists: int = 1, policy_cap: int = 8,
                                held_out_allocation: Mapping[str, int] | None = None,
                                refinement_budget: int = 0, refinement_rounds: int = 1,
                                strategy: str = 'beam', beam_width: int = 1,
                                sustained_scenario: dict | None = None, bonus_talent_points: int = 0):
    """Run source-independent joint search with the real repeated-pull scorer.

    Default: on-demand source-legal scored beam, no Cartesian talent universe.
    `strategy='sample'` preserves historical bounded-sample replay semantics.
    Held-out challengers are excluded and must be evaluated separately.
    Neither strategy proves a global optimum or complete source coverage.
    """
    if strategy == 'beam':
        if refinement_budget or refinement_rounds != 1:
            raise ValueError('sample-only refinement arguments invalid for beam strategy')
        from src.v2.source_legal_beam import search_source_legal_beam
        return search_source_legal_beam(
            class_key=class_key, level=level, pulls=pulls,
            max_allocations=max_allocations, screening_gear_count=screening_gear_count,
            finalists=finalists, policy_cap=policy_cap, beam_width=beam_width,
            held_out_allocation=held_out_allocation,
            sustained_scenario=sustained_scenario, bonus_talent_points=bonus_talent_points)
    if strategy != 'sample':
        raise ValueError('unknown source joint search strategy')
    if pulls < 2 or max_allocations < 1 or screening_gear_count < 1 or finalists < 1 or refinement_budget < 0 or refinement_rounds < 0:
        raise ValueError('positive budgets and at least two pulls required')
    start = monotonic()
    source = build_game_ir_slice(class_key=class_key, level=level)
    if source is None:
        raise ValueError('no canonical source Game IR for requested class and level')
    allocations, truncated = enumerate_legal_talent_allocations(
        source, level=level, max_candidates=200000, bonus_talent_points=bonus_talent_points)
    if truncated:
        raise ValueError('source executable talent universe exceeds explicit 200000 cap')
    held_out_id = None
    if held_out_allocation is not None:
        validate_talent_selection(source, held_out_allocation, level=level, bonus_talent_points=bonus_talent_points)
        held_out_id = talent_candidate_id(held_out_allocation)
    sample, coverage = independent_allocation_sample(
        allocations, budget=max_allocations,
        excluded_ids=() if held_out_id is None else (held_out_id,),
        family_tree={t.id: t.tree_key for t in source.talents})
    gears = _gear_envelope(class_key, level, max_gear_candidates=256,
                           required_level_policy='observed', include_melee_gear=True,
                           ir_slice=source)
    if screening_gear_count > len(gears):
        raise ValueError('screening gear count exceeds source gear envelope')
    screening = [gears[i] for i in _diverse_gear_indices(gears, screening_gear_count)]
    hp = representative_hp(level)
    screened = []
    all_rows = []
    for allocation in sample:
        scores = [_score_state(source, level=level, gear=g, allocation=allocation,
                               pulls=pulls, policy_cap=policy_cap, target_health=hp,
                               sustained_scenario=sustained_scenario, bonus_talent_points=bonus_talent_points)
                  for g in screening]
        all_rows.extend(scores)
        good = [s for s in scores if s['seconds_per_mob'] is not None]
        if good:
            screened.append(min(good, key=lambda s: (s['seconds_per_mob'], s['gear_id'])))
    if not screened:
        raise ValueError('all source-independent joint states failed to kill the target')
    refinement_count = 0
    visited = {talent_candidate_id(a) for a in sample}
    if held_out_id is not None:
        visited.add(held_out_id)
    # Real repeated-pull scores drive the neighborhood, not guide builds.
    # The full source-legal roster is the only authority for a move.
    for _ in range(refinement_rounds if refinement_budget else 0):
        anchor = min(screened, key=lambda r: (r['seconds_per_mob'],
                     talent_candidate_id(r['talent_allocation'])))['talent_allocation']
        neighbors = _legal_local_neighbors(allocations, anchor,
                                          excluded_ids=visited, budget=refinement_budget)
        if not neighbors:
            break
        for allocation in neighbors:
            visited.add(talent_candidate_id(allocation))
            scores = [_score_state(source, level=level, gear=g, allocation=allocation,
                                   pulls=pulls, policy_cap=policy_cap, target_health=hp,
                               sustained_scenario=sustained_scenario, bonus_talent_points=bonus_talent_points)
                      for g in screening]
            all_rows.extend(scores)
            good = [row for row in scores if row['seconds_per_mob'] is not None]
            if good:
                screened.append(min(good, key=lambda row: (row['seconds_per_mob'], row['gear_id'])))
            refinement_count += 1
    coverage['locally_refined'] = refinement_count
    coverage['evaluated_total'] = len(visited) - (1 if held_out_id else 0)
    coverage['unscored_allocations'] = len(allocations) - len(visited)
    screened.sort(key=lambda s: (s['seconds_per_mob'], talent_candidate_id(s['talent_allocation'])))
    final_allocations = []
    seen = set()
    for row in screened:
        cid = talent_candidate_id(row['talent_allocation'])
        if cid not in seen:
            seen.add(cid)
            final_allocations.append(row['talent_allocation'])
        if len(final_allocations) == finalists:
            break
    final_rows = []
    for allocation in final_allocations:
        for gear in gears:
            # Reuse already-scored gear×talent states, no cache assumptions.
            previous = next((r for r in all_rows if r['gear_id'] == gear['id']
                             and r['talent_allocation'] == allocation), None)
            final_rows.append(previous if previous is not None else _score_state(
                source, level=level, gear=gear, allocation=allocation,
                pulls=pulls, policy_cap=policy_cap, target_health=hp,
                               sustained_scenario=sustained_scenario, bonus_talent_points=bonus_talent_points))
    valid = [r for r in final_rows if r['seconds_per_mob'] is not None]
    if not valid:
        raise ValueError('no final state has a valid repeated-pull score')
    winner = min(valid, key=lambda s: (s['seconds_per_mob'], s['gear_id'],
                                      talent_candidate_id(s['talent_allocation'])))
    blocked = [t.id for t in source.talents if not any(rank.modifiers for rank in t.ranks)]
    return {'status': 'EVALUATED_BOUNDED', 'class_key': class_key, 'level': level,
            'pull_count': pulls, 'target_health': hp, 'bonus_talent_points': bonus_talent_points,
            'objective': 'stateful repeated incoming-inclusive combat + scenario-defined recovery/travel, seconds per mob',
            'sustained_scenario': dict(sustained_scenario or {}),
            'independent_winner': winner,
            'screening_gear_ids': [g['id'] for g in screening],
            'full_gear_envelope_count': len(gears),
            'full_executable_allocation_count': len(allocations),
            'allocation_coverage': coverage,
            'screened_state_count': len(all_rows),
            'local_refinement_evaluated_allocations': refinement_count,
            'total_independent_evaluated_allocations': len(visited) - (1 if held_out_id else 0),
            'finalist_allocation_count': len(final_allocations),
            'finalist_state_count': len(final_rows),
            'generated_policy_evaluations': sum(r['policy_generated'] for r in all_rows)
                                            + sum(r['policy_generated'] for r in final_rows if r not in all_rows),
            'valid_policy_evaluations': sum(r['policy_evaluated'] for r in all_rows)
                                        + sum(r['policy_evaluated'] for r in final_rows if r not in all_rows),
            'blocked_source_talent_ids': blocked,
            'source_coverage_complete': not blocked and len(visited) == len(allocations),
            'global_optimum_proven': False,
            'held_out_allocation_id': held_out_id,
            'held_out_not_sampled': held_out_id is None or all(
                talent_candidate_id(a) != held_out_id for a in sample),
            'elapsed_s': monotonic() - start,
            'screened_best': screened[0],
            'finalist_summaries': [dict(gear_id=r['gear_id'], talents=r['talent_allocation'],
                                      seconds_per_mob=r['seconds_per_mob']) for r in final_rows],
            'policy_frontier_truncation_count': sum(
                b.get('reason') == 'bounded_policy_frontier'
                for r in all_rows for b in r['source_policy_blockers']),
            'source_policy_blocker_examples': [b for r in final_rows for b in r['source_policy_blockers']][:20]}


def replay_exact_challenger(*, class_key, level, gear, allocation, policy,
                            pre_combat_action_ids=(), post_combat_action_ids=(), pulls=3,
                            recovery_action_ids=None, sustained_scenario: dict | None = None,
                            bonus_talent_points: int = 0):
    """One frozen gear/talent/policy candidate, never optimized or seeded."""
    source = build_game_ir_slice(class_key=class_key, level=level)
    if source is None:
        raise ValueError('no source Game IR for challenger')
    validate_talent_selection(source, allocation, level=level, bonus_talent_points=bonus_talent_points)
    geared, app = apply_gear_selection(
        source, aggregate_stats=gear['selection'].aggregate_stats,
        selected_items=tuple(gear['selection'].slots.values()),
        source='canonical_sqlite_forever_catalogue')
    ir, _ = apply_talent_selection(geared, allocation, level=level, bonus_talent_points=bonus_talent_points)
    actions = {a.id for a in ir.actions}
    if any(r.action_id not in actions for r in policy.rules):
        raise ValueError('held-out policy uses unavailable source action')
    result = evaluate_repeated_pulls(
        ir_slice=ir, policy=policy, level=level, target_health=representative_hp(level),
        count=pulls, schedule_incoming_attacks=True, apply_target_defense=True,
        pre_combat_action_ids=tuple(pre_combat_action_ids),
        post_combat_action_ids=tuple(post_combat_action_ids),
        recovery_action_ids=recovery_action_ids, **(sustained_scenario or {}))
    return {'seconds_per_mob': result.seconds_per_mob,
            'gear_id': gear['id'], 'talent_allocation': dict(allocation),
            'policy': policy.as_dict(), 'pulls': list(result.pulls),
            'recovery_action_ids':None if recovery_action_ids is None else list(recovery_action_ids),
            'sustained_scenario': dict(sustained_scenario or {}), 'bonus_talent_points': bonus_talent_points,
            'gear_stats_unsupported': dict(app.unsupported_stats)}
