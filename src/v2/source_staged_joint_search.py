"""Source-driven two-stage gear × talent × policy discovery.

Every currently executable legal talent allocation is actually scored on a
source-selected gear screening envelope; finalists receive the complete source
gear envelope. This is an approximate search, *not* an exhaustive optimum.
No class, talent, stat or guide build is privileged by the algorithm.
"""
from __future__ import annotations

from src.game.policy import remove_combat_policy_seeds_preserve_maintenance

from dataclasses import replace
from math import isfinite
from time import monotonic
from typing import Mapping

from src.game.data.forever.registry import build_game_ir_slice
from src.game.gear import apply_gear_selection
from src.game.talent_search import enumerate_legal_talent_allocations, talent_candidate_id
from src.game.talents import apply_talent_selection, validate_talent_selection
from src.v2.source_joint_discovery import (_gear_envelope, _evaluate_caster_already_talented)
from src.v2.source_mode_search import evaluate_discovered_mode_search


def _diverse_gear_indices(gears: list[dict], count: int) -> tuple[int, ...]:
    """Greedy item-set diversity; independent of class and talent selection."""
    if count < 1 or count > len(gears):
        raise ValueError('screening gear count outside source gear envelope')
    sets = [set((slot, int(item['item_id'])) for slot, item in g['selection'].slots.items())
            for g in gears]
    # Represent each source-catalogue gear role before filling remaining
    # anchors by item diversity. A caster-only screen would systematically
    # discard legal melee builds even when melee gear is in the envelope.
    chosen = []
    seen_roles = set()
    for i, gear in enumerate(gears):
        role = str(gear['gear_role'])
        if role not in seen_roles and len(chosen) < count:
            chosen.append(i)
            seen_roles.add(role)
    if not chosen:
        chosen = [0]
    while len(chosen) < count:
        def distance(i: int) -> tuple[float, int]:
            # Min-distance to chosen: cover different gear sets, not aliases.
            return (min(1.0 - len(sets[i] & sets[j]) / len(sets[i] | sets[j])
                        for j in chosen), -i)
        chosen.append(max((i for i in range(len(gears)) if i not in chosen), key=distance))
    return tuple(chosen)


def _diverse_finalists(screened: list[dict], anchors: tuple[int, ...],
                       count: int) -> tuple[list[dict], dict]:
    """Score-first, source-family and gear-anchor diversity; no legacy hints.

    Every reachable executable talent family gets a representative if the
    finalist budget permits. A small budget remains explicitly incomplete.
    """
    if count < 1:
        raise ValueError('finalist count must be positive')
    ranked = sorted(screened, key=lambda row:
                    (row['best_screening_s_per_mob'], row['talent_id']))
    selected: list[dict] = []
    seen: set[str] = set()

    def take(row):
        if len(selected) < count and row['talent_id'] not in seen:
            selected.append(row)
            seen.add(row['talent_id'])

    take(ranked[0])  # Never sacrifice the independent score leader.
    reachable = sorted({tid for row in ranked for tid, rank in row['allocation'].items()
                        if int(rank) > 0})
    # Rank by the best *actual combat/recovery score* for each legal family.
    # Ordering the families by that score makes a tight budget useful.
    family_best = []
    for family in reachable:
        candidates = [row for row in ranked if int(row['allocation'].get(family, 0)) > 0]
        family_best.append((candidates[0]['best_screening_s_per_mob'], family, candidates[0]))
    for _, _, row in sorted(family_best):
        take(row)
    # Preserve contenders favored by each screened source gear anchor, not
    # only those that happen to win on the globally fastest anchor.
    for gear_index in anchors:
        with_score = [row for row in ranked if gear_index in row['screening_scores']]
        if with_score:
            take(min(with_score, key=lambda row:
                (row['screening_scores'][gear_index], row['talent_id'])))
    for row in ranked:
        take(row)
    represented = sorted({tid for row in selected for tid, rank in row['allocation'].items()
                          if int(rank) > 0})
    return selected, {'reachable_screened_families': reachable,
                      'finalist_represented_families': represented,
                      'finalist_missing_families': sorted(set(reachable)-set(represented)),
                      'strategy': 'independent_score_leader_then_source_family_and_gear_diversity'}


def evaluate_staged_joint_search(*, class_key: str, level: int, ir_slice=None,
                                 max_gear_candidates: int = 64,
                                 screening_gear_count: int = 3,
                                 finalist_talent_count: int = 16,
                                 max_talent_candidates: int = 10000,
                                 max_policies_per_path: int = 256,
                                 max_caster_policies: int = 96,
                                 required_level_policy: str = 'observed',
                                 schedule_incoming_attacks: bool = True,
                                 held_out_allocation: Mapping[str, int] | None = None) -> dict:
    """Independently search all *executable* allocations; fully rescore finalists.

    Every legal executable allocation is scored against the same real combat +
    recovery objective on the diverse screening gear set. This is not a
    completeness claim over unsupported source talents, unseen gear, or the
    finalists' unscreened gear interactions. Held-out builds are scored only
    *after* finalist selection and cannot seed the search.
    """
    started = monotonic()
    if finalist_talent_count < 1 or max_talent_candidates < 1:
        raise ValueError('talent bounds must be positive')
    source = ir_slice if ir_slice is not None else build_game_ir_slice(class_key=class_key, level=level)
    if source is None or (str(source.actor.metadata.get('class_key', '')).lower() != class_key.lower()
                          or int(source.actor.metadata.get('level', -1)) != level):
        raise ValueError('source actor class/level mismatch')
    source = remove_combat_policy_seeds_preserve_maintenance(source)  # Do not seed search with historical policy.
    allocations, truncated = enumerate_legal_talent_allocations(
        source, level=level, max_candidates=max_talent_candidates)
    if truncated:
        raise ValueError('talent candidate envelope exceeds explicit bound')
    gears = _gear_envelope(class_key, level, max_gear_candidates=max_gear_candidates,
                           required_level_policy=required_level_policy,
                           include_melee_gear=True, ir_slice=source)
    geared = []
    for gear in gears:
        ir, application = apply_gear_selection(
            source, aggregate_stats=gear['selection'].aggregate_stats,
            selected_items=tuple(gear['selection'].slots.values()),
            source='canonical_sqlite_forever_catalogue')
        geared.append((ir, application))

    # Score source gear with a neutral (zero-talent) allocation first. Choose
    # each *executable combat branch's* best gear as an anchor, then cover
    # source gear roles and item-set diversity. This prevents caster-dominated
    # screens from eliminating melee talents before their relevant gear is seen.
    branch_anchors = {}
    for branch in ('caster', 'mode'):
        options = []
        for i, (ir, _) in enumerate(geared):
            try:
                if branch == 'caster':
                    r = _evaluate_caster_already_talented(
                        ir, level=level, max_policies=max_caster_policies,
                        schedule_incoming_attacks=schedule_incoming_attacks)
                else:
                    r = evaluate_discovered_mode_search(
                        class_key=class_key, level=level, ir_slice=ir,
                        max_policies_per_path=max_policies_per_path,
                        schedule_incoming_attacks=schedule_incoming_attacks)
                options.append((float(r['winner']['seconds_per_mob']), i))
            except (ValueError, RuntimeError, KeyError):
                continue
        if options:
            branch_anchors[branch] = min(options)[1]
    anchors_list = list(dict.fromkeys(branch_anchors.values()))[:screening_gear_count]
    if len(anchors_list) < screening_gear_count:
        for i in _diverse_gear_indices(gears, len(gears)):
            if i not in anchors_list:
                anchors_list.append(i)
            if len(anchors_list) == screening_gear_count:
                break
    anchors = tuple(anchors_list)

    evaluated: dict[tuple[int, str], dict] = {}
    rejected: list[dict] = []
    runtime_evaluations = 0

    def score(gear_idx: int, allocation: Mapping[str, int], *, detailed: bool = False) -> dict | None:
        nonlocal runtime_evaluations
        cid = talent_candidate_id(allocation)
        key = (gear_idx, cid)
        if key in evaluated and (not detailed or evaluated[key].get("detailed")):
            return evaluated[key]
        runtime_evaluations += 1
        ir, gear_application = geared[gear_idx]
        try:
            talented, application = apply_talent_selection(ir, allocation, level=level)
        except (ValueError, RuntimeError) as exc:
            rejected.append({'gear_index': gear_idx, 'talent_id': cid,
                             'branch': 'talent', 'reason': str(exc)})
            return None
        branches = []
        for branch in ('caster', 'mode'):
            try:
                if branch == 'caster':
                    result = _evaluate_caster_already_talented(
                        talented, level=level, max_policies=max_caster_policies,
                        schedule_incoming_attacks=schedule_incoming_attacks)
                else:
                    result = evaluate_discovered_mode_search(
                        class_key=class_key, level=level, ir_slice=talented,
                        max_policies_per_path=max_policies_per_path,
                        schedule_incoming_attacks=schedule_incoming_attacks)
                winner = result['winner']
                if not isfinite(float(winner['seconds_per_mob'])):
                    raise ValueError('non-finite combat/recovery score')
                branches.append({'branch': branch,
                                 'seconds_per_mob': float(winner['seconds_per_mob']),
                                 'policy_id': winner['policy_id'],
                                 'policy': winner['policy'],
                                 'selected_actions': winner['selected_actions'],
                                 'combat_kill_s': winner['combat_kill_s'],
                                 'recovery_s': winner['recovery_s'],
                                 'combat_mode': (winner['path']['combat_mode']
                                                 if branch == 'mode' else 'initial'),
                                 'evaluated_policy_count': result['evaluated_count']})
            except (ValueError, RuntimeError, KeyError) as exc:
                rejected.append({'gear_index': gear_idx, 'talent_id': cid,
                                 'branch': branch, 'reason': str(exc)})
        if not branches:
            return None
        branches.sort(key=lambda b: (b['seconds_per_mob'], b['branch'], b['policy_id']))
        row = {'talent_id': cid, 'talent_allocation': dict(allocation),
               'gear_index': gear_idx, 'gear_id': gears[gear_idx]['id'],
               'gear_role': gears[gear_idx]['gear_role'],
               'gear_slots': {s: dict(i) for s, i in gears[gear_idx]['selection'].slots.items()},
               'gear_applied_stats': dict(gear_application.applied_stats),
               'gear_unsupported_stats': dict(gear_application.unsupported_stats),
               'gear_partial_stats': dict(gear_application.partial_stats or {}),
               'talent_application': application.as_dict(),
               'seconds_per_mob': branches[0]['seconds_per_mob'],
               'best_policy': branches[0], 'branches': branches}
        if not detailed:
            # The screening pass retains only a scalar score and IDs. Keeping
            # thousands of full policy/action/provenance graphs alive causes
            # pathological GC/memory growth without improving selection.
            row = {'talent_id': cid, 'gear_index': gear_idx,
                   'gear_id': gears[gear_idx]['id'],
                   'seconds_per_mob': row['seconds_per_mob'], 'detailed': False}
        else:
            row['detailed'] = True
        evaluated[key] = row
        return row

    # No old winner, talent-name whitelist, or guide build influences screening.
    screened = []
    for allocation in allocations:
        rows = [score(i, allocation) for i in anchors]
        valid = [r for r in rows if r is not None]
        if valid:
            best = min(valid, key=lambda r: (r['seconds_per_mob'], r['gear_id']))
            screened.append({'allocation': allocation, 'talent_id': talent_candidate_id(allocation),
                             'best_screening_s_per_mob': best['seconds_per_mob'],
                             'screening_scores': {int(r['gear_index']):float(r['seconds_per_mob'])
                                                  for r in valid},
                             'screening_gear_evaluated': len(valid)})
        else:
            rejected.append({'talent_id': talent_candidate_id(allocation),
                             'reason': 'no_executable_screening_gear'})
    if not screened:
        raise ValueError('no executable legal talent candidate in screening')
    screened.sort(key=lambda x: (x['best_screening_s_per_mob'], x['talent_id']))
    finalists, finalist_coverage = _diverse_finalists(
        screened, anchors, finalist_talent_count)
    for row in finalists:
        for i in range(len(gears)):
            score(i, row['allocation'], detailed=True)
    finalist_ids = {row['talent_id'] for row in finalists}
    finalist_states = [row for (_, tid), row in evaluated.items()
                       if tid in finalist_ids and row.get('detailed')]
    finalist_states.sort(key=lambda r: (r['seconds_per_mob'], r['gear_id'], r['talent_id']))
    winner = finalist_states[0]

    # Held-out replay is deliberately AFTER independent finalist selection.
    held_out = None
    if held_out_allocation is not None:
        try:
            validate_talent_selection(source, held_out_allocation, level=level)
            held_rows = [score(i, held_out_allocation, detailed=True) for i in range(len(gears))]
            valid = [r for r in held_rows if r is not None]
            held_out = {'legal': True, 'evaluated_gear_count': len(valid),
                        'best': (min(valid, key=lambda r: (r['seconds_per_mob'], r['gear_id']))
                                 if valid else None),
                        'same_objective': True,
                        'used_to_seed_discovery': False}
        except ValueError as exc:
            held_out = {'legal': False, 'reason': str(exc),
                        'used_to_seed_discovery': False}

    # This membership check happens only after independent finalist selection.
    # It establishes whether the old build was genuinely in the discoverable
    # allocation universe, rather than merely evaluated as a held-out replay.
    held_out_in_independent_universe = (None if held_out_allocation is None else
        any(dict(allocation) == {str(k):int(v) for k,v in held_out_allocation.items()
                                  if int(v)>0} for allocation in allocations))
    coverage = source.provenance.get('talent_sqlite_coverage') or {}
    return {
        'status': 'EVALUATED_STAGED_JOINT_SEARCH_NOT_GLOBAL_OPTIMUM',
        'class_key': class_key, 'level': level, 'source_ir_id': source.id,
        'source_gear': 'canonical_sqlite_forever_catalogue',
        'incoming_attacks_scored': bool(schedule_incoming_attacks and source.incoming_attacks),
        'talent_allocations_enumerated': len(allocations),
        'talent_allocations_screened': len(screened),
        'source_talent_families': len(source.talents),
        'executable_talent_families': sum(any(r.modifiers for r in t.ranks) for t in source.talents),
        'talent_sqlite_coverage': dict(coverage),
        'gear_envelope_count': len(gears),
        'screening_gear_indices': list(anchors),
        'neutral_branch_gear_anchors': branch_anchors,
        'finalist_talent_count': len(finalists),
        'finalist_coverage': finalist_coverage,
        'evaluated_state_count': len(evaluated),
        'runtime_state_evaluation_count': runtime_evaluations,
        'screened_all_executable_legal_allocations': len(screened) == len(allocations),
        'full_gear_envelope_evaluated_for_all_talents': len(finalists) == len(allocations),
        'global_optimum_claim': False,
        'winner': winner,
        'finalists': [{'talent_id': r['talent_id'],
                       'best_screening_s_per_mob': r['best_screening_s_per_mob'],
                       'best_full_envelope_s_per_mob': min(
                           row['seconds_per_mob'] for (_, tid), row in evaluated.items()
                           if tid == r['talent_id'])}
                      for r in finalists],
        'held_out': held_out,
        'held_out_in_independent_allocation_universe': held_out_in_independent_universe,
        'rejected': rejected,
        'elapsed_s': round(monotonic() - started, 3),
        'missing': ['non_executable_source_talents', 'unverified_talent_tiers_and_prerequisites',
                    'non_exhaustive_item_combinations', 'screening_can_miss_gear_talent_synergies',
                    'full_policy_coverage_and_level_route'],
    }
