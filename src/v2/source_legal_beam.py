"""Score-driven, on-demand source-legal joint talent/gear/policy frontier.

This does not enumerate the Cartesian talent universe. Every admitted allocation
is checked against the canonical Game IR, and every ranking score comes from
exactly the same repeated-pull combat/recovery evaluator as frozen challengers.
The bounded beam is NOT a proof of global optimality.
"""
from __future__ import annotations

from math import isfinite
from time import monotonic
from typing import Mapping

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_search import executable_talent_definitions, talent_candidate_id
from src.game.talents import validate_talent_selection, available_talent_points
from src.shared.leveling.objective import representative_hp
from src.v2.source_joint_discovery import _gear_envelope
from src.v2.source_staged_joint_search import _diverse_gear_indices


def legal_point_frontier(source, allocation: Mapping[str, int], *, level: int,
                         allow_transfers: bool = True, bonus_talent_points: int = 0):
    """Legal +1-point moves, plus -1/+1 transfers at the point cap.

    No class, talent, spell or fixture IDs appear in the generator.  A rank is
    selectable only if its own source-normalized modifier row exists. Invalid
    tier, prerequisite, rank and point-budget transitions fail closed.
    """
    validate_talent_selection(source, allocation, level=level, bonus_talent_points=bonus_talent_points)
    definitions = executable_talent_definitions(source)
    point_cap = available_talent_points(level, bonus_talent_points=bonus_talent_points)
    spent = sum(int(v) for v in allocation.values())
    seen = set()
    out = []
    bases = [dict(allocation)]
    if allow_transfers and spent >= point_cap:
        for old in definitions:
            rank = int(allocation.get(old.id, 0))
            if rank:
                base = dict(allocation)
                if rank == 1:
                    del base[old.id]
                else:
                    base[old.id] = rank - 1
                bases.append(base)
    for base in bases:
        if sum(base.values()) >= point_cap:
            continue
        for talent in definitions:
            next_rank = int(base.get(talent.id, 0)) + 1
            if next_rank > int(talent.max_rank):
                continue
            if not any(r.rank == next_rank and r.modifiers for r in talent.ranks):
                continue
            candidate = dict(base)
            candidate[talent.id] = next_rank
            cid = talent_candidate_id(candidate)
            if cid == talent_candidate_id(allocation) or cid in seen:
                continue
            try:
                validate_talent_selection(source, candidate, level=level, bonus_talent_points=bonus_talent_points)
            except ValueError:
                continue
            seen.add(cid)
            out.append(candidate)
    return out


def _interleave_tree_candidates(candidates, tree_of):
    """Deterministic fair admission across canonical tree identities."""
    groups = {}
    for candidate, added_family in candidates:
        groups.setdefault(str(tree_of.get(added_family, 'unknown')), []).append(candidate)
    result = []
    while any(groups.values()):
        for tree in sorted(groups):
            if groups[tree]:
                result.append(groups[tree].pop(0))
    return result


def source_tier_unlock_corridors(source, *, level: int, max_corridors: int = 8, bonus_talent_points: int = 0):
    """Deterministic source-legal routes to executable higher-tier actions.

    This is not a guide/legacy winner seed: only canonical tree rows, rank caps
    and the shared legality validator determine the corridor. It prevents a
    narrow score-driven beam from *never reaching* a talent behind row gates.
    """
    definitions=executable_talent_definitions(source)
    out=[]
    for target in sorted(definitions,key=lambda t:(t.tree_key,t.metadata.get('row') or 0,t.id)):
        row=target.metadata.get('row')
        if row is None or int(row)<1:
            continue
        rule=source.provenance.get('talent_tree_rules') or {}
        gate=int(row)*int(rule.get('points_per_row',5))
        donors=sorted((t for t in definitions if t.tree_key==target.tree_key
                       and t.id!=target.id and t.metadata.get('row') is not None
                       and int(t.metadata['row'])<int(row)),
                      key=lambda t:(int(t.metadata['row']),t.id))
        for ordering in (donors,list(reversed(donors))):
            allocation={}
            for donor in ordering:
                for rank in range(1,int(donor.max_rank)+1):
                    if sum(allocation.values())>=gate:
                        break
                    trial={**allocation,donor.id:rank}
                    try:
                        validate_talent_selection(source,trial,level=level,bonus_talent_points=bonus_talent_points)
                    except ValueError:
                        break
                    allocation=trial
                if sum(allocation.values())>=gate:
                    break
            if sum(allocation.values())<gate:
                continue
            trial={**allocation,target.id:1}
            try:
                validate_talent_selection(source,trial,level=level,bonus_talent_points=bonus_talent_points)
            except ValueError:
                continue
            cid=talent_candidate_id(trial)
            if all(talent_candidate_id(existing)!=cid for existing in out):
                out.append(trial)
            if len(out)>=max_corridors:
                return out
    return out


def search_source_legal_beam(*, class_key: str, level: int, pulls: int = 3,
                             max_allocations: int = 64, screening_gear_count: int = 1,
                             finalists: int = 2, policy_cap: int = 12,
                             beam_width: int = 1,
                             held_out_allocation: Mapping[str, int] | None = None,
                             sustained_scenario: dict | None = None,
                             bonus_talent_points: int = 0):
    """On-demand scored beam, then complete *known gear-envelope* finalist race.

    Source ranks, tree gates and prereqs are validated at every expansion. A
    frozen challenger is excluded from search and must be replayed separately.
    The search is anytime/bounded: legal unexplored moves remain explicit.
    """
    if (pulls < 2 or max_allocations < 1 or screening_gear_count < 1
            or finalists < 1 or policy_cap < 1 or beam_width < 1):
        raise ValueError('invalid source legal beam budget')
    start = monotonic()
    source = build_game_ir_slice(class_key=class_key, level=level)
    if source is None:
        raise ValueError('no canonical source Game IR')
    if held_out_allocation is not None:
        validate_talent_selection(source, held_out_allocation, level=level, bonus_talent_points=bonus_talent_points)
    held_id = None if held_out_allocation is None else talent_candidate_id(held_out_allocation)
    gears = _gear_envelope(class_key, level, max_gear_candidates=256,
                           required_level_policy='observed', include_melee_gear=True,
                           ir_slice=source)
    if screening_gear_count > len(gears):
        raise ValueError('screening gear count exceeds source gear envelope')
    screening = [gears[i] for i in _diverse_gear_indices(gears, screening_gear_count)]
    from src.v2.source_multi_pull_joint import _score_state  # shared scorer, no fork
    hp = representative_hp(level)
    cached = {}
    evaluated = {}
    candidates_generated = 0
    candidates_skipped = 0
    frontier_depth = 0
    tree_of = {t.id: t.tree_key for t in source.talents}

    def score_one(allocation, gear):
        key = (talent_candidate_id(allocation), gear['id'])
        if key not in cached:
            cached[key] = _score_state(source, level=level, gear=gear,
                                       allocation=allocation, pulls=pulls,
                                       policy_cap=policy_cap, target_health=hp,
                                       sustained_scenario=sustained_scenario, bonus_talent_points=bonus_talent_points)
        return cached[key]

    def evaluate(allocation):
        cid = talent_candidate_id(allocation)
        if cid in evaluated or cid == held_id:
            return evaluated.get(cid)
        rows = [score_one(allocation, gear) for gear in screening]
        valid = [r for r in rows if r['seconds_per_mob'] is not None]
        best = min(valid, key=lambda r: (r['seconds_per_mob'], r['gear_id'])) if valid else None
        evaluated[cid] = {'allocation': dict(allocation), 'best': best,
                          'score': float('inf') if best is None else best['seconds_per_mob']}
        return evaluated[cid]

    # Empty is a legitimate source-legal root and never a guide/fixture seed.
    root = {}
    if talent_candidate_id(root) != held_id:
        evaluate(root)
    corridors=source_tier_unlock_corridors(source,level=level,max_corridors=8,bonus_talent_points=bonus_talent_points)
    corridor_reserve=min(len(corridors),max_allocations//8)
    beam = [root]
    while len(evaluated) < max_allocations-corridor_reserve and beam:
        next_candidates = {}
        for allocation in beam:
            for candidate in legal_point_frontier(source, allocation, level=level, bonus_talent_points=bonus_talent_points):
                cid = talent_candidate_id(candidate)
                candidates_generated += 1
                if cid == held_id or cid in evaluated:
                    candidates_skipped += 1
                    continue
                # The +1 family is known from the actual parent transition,
                # not guessed from the largest existing rank.
                additions = [f for f in candidate if candidate.get(f, 0) > allocation.get(f, 0)]
                added = additions[0] if additions else ''
                next_candidates[cid] = (candidate, added)
        if not next_candidates:
            break
        frontier_depth += 1
        # Each expansion is evaluated with the *real* repeated-pull scorer.
        # Source-tree round robin avoids dropping entire trees by lexical ID.
        admitted = _interleave_tree_candidates(list(next_candidates.values()), tree_of)
        layer = []
        for candidate in admitted:
            if len(evaluated) >= max_allocations-corridor_reserve:
                break
            row = evaluate(candidate)
            if row is not None and isfinite(row['score']):
                layer.append(row)
        if not layer:
            break
        layer.sort(key=lambda row: (row['score'], -sum(row['allocation'].values()),
                                    talent_candidate_id(row['allocation'])))
        beam = [row['allocation'] for row in layer[:beam_width]]
    for allocation in corridors[:corridor_reserve]:
        evaluate(allocation)
    scored = sorted((r for r in evaluated.values() if isfinite(r['score'])),
                    key=lambda row: (row['score'], sum(row['allocation'].values()),
                                     talent_candidate_id(row['allocation'])))
    if not scored:
        raise ValueError('no source-legal beam candidate defeated target')
    # Preserve a source-family representative before filling score-ranked
    # finalists. A talent that is gear-dependent must not vanish simply
    # because the screening anchor favors a different stat distribution.
    finalist_allocations = []
    finalist_ids = set()
    def admit(row):
        cid = talent_candidate_id(row['allocation'])
        if len(finalist_allocations) < finalists and cid not in finalist_ids:
            finalist_allocations.append(row['allocation'])
            finalist_ids.add(cid)
    admit(scored[0])
    reachable_families = sorted({f for row in scored for f,v in row['allocation'].items() if v > 0})
    family_leaders = []
    for family in reachable_families:
        rows = [row for row in scored if row['allocation'].get(family,0) > 0]
        family_leaders.append((rows[0]['score'], family, rows[0]))
    for _, _, row in sorted(family_leaders):
        admit(row)
    for row in scored:
        admit(row)
    finalist_rows = []
    for allocation in finalist_allocations:
        for gear in gears:
            finalist_rows.append(score_one(allocation, gear))
    valid = [r for r in finalist_rows if r['seconds_per_mob'] is not None]
    if not valid:
        raise ValueError('no source-legal beam finalist defeated target')
    winner = min(valid, key=lambda r: (r['seconds_per_mob'],
                                      sum(r['talent_allocation'].values()), r['gear_id'],
                                      talent_candidate_id(r['talent_allocation'])))
    blocked = [t.id for t in source.talents if not any(rank.modifiers for rank in t.ranks)]
    covered = {family for row in evaluated.values() for family, rank in row['allocation'].items() if rank > 0}
    return {
        'status': 'EVALUATED_BOUNDED', 'strategy': 'on_demand_source_legal_scored_beam',
        'class_key': class_key, 'level': level, 'pull_count': pulls, 'bonus_talent_points': bonus_talent_points, 'target_health': hp,
        'objective': 'stateful repeated incoming-inclusive combat + scenario-defined recovery/travel, seconds per mob',
        'sustained_scenario': dict(sustained_scenario or {}),
        'independent_winner': winner, 'full_gear_envelope_count': len(gears),
        'screening_gear_ids': [g['id'] for g in screening],
        'total_independent_evaluated_allocations': len(evaluated),
        'allocation_coverage': {
            'strategy': 'legal_next_rank_beam_no_cartesian_materialization',
            'evaluated_total': len(evaluated), 'generated_transitions': candidates_generated,
            'revisited_or_held_out_transitions': candidates_skipped,
            'deepest_expansion': frontier_depth,
            'beam_width': beam_width, 'budget': max_allocations,
            'represented_families': sorted(covered),
            'source_executable_families': len(executable_talent_definitions(source)),
            'unrepresented_families': sorted({t.id for t in executable_talent_definitions(source)}-covered),
            'source_tier_corridors_generated':len(corridors),
            'source_tier_corridors_evaluated':corridor_reserve,
            'unexplored_source_legal_universe': True,
        },
        'scored_state_count': len(cached),
        'valid_policy_evaluations': sum(r['policy_evaluated'] for r in cached.values()),
        'finalist_allocation_count': len(finalist_allocations),
        'finalist_state_count': len(finalist_rows),
        'finalist_summaries': [dict(gear_id=r['gear_id'], talents=r['talent_allocation'],
                                   seconds_per_mob=r['seconds_per_mob']) for r in finalist_rows],
        'blocked_source_talent_ids': blocked,
        'source_coverage_complete': False, 'global_optimum_proven': False,
        'held_out_allocation_id': held_id,
        'held_out_not_sampled': held_id not in evaluated,
        'elapsed_s': monotonic()-start,
    }
