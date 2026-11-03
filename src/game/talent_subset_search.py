"""Transitional GameIR-backed bounded talent allocation enumeration.

Only executable ranks are traversed. This helper is still used by the
legacy joint-frontier caller; it does not execute combat or certify gates.
"""
from __future__ import annotations

from math import prod

from src.game.talents import validate_talent_selection
from src.optimization.talent_search import (
    TalentAllocationOption,
    enumerate_talent_allocations,
)


def enumerate_executable_allocations(compiled, *, level: int, bonus_talent_points: int = 0,
                                     max_enumerations: int = 100000):
    """Adapt sourced executable ranks to the game-independent optimizer walk.

    The optimizer owns bounded allocation traversal. This adapter owns the
    current GameIR rank facts and final source-legality validation. The raw
    Cartesian budget is checked before traversal, preserving the old
    fail-closed exhaustive-subspace contract.
    """
    if not 1 <= max_enumerations <= 10000000:
        raise ValueError('INVALID_ALLOCATION_ENUMERATION_BUDGET')
    budget = max(0, level-9) + bonus_talent_points
    rule = compiled.provenance.get('talent_tree_rules') or {}
    per_row = int(rule.get('points_per_row', 5))
    eligible = [t for t in compiled.talents if t.metadata.get('row') is not None
                and int(t.metadata['row'])*per_row < budget
                and any(r.modifiers for r in t.ranks)]
    executable_ranks = [
        tuple(int(rank.rank) for rank in talent.ranks if rank.modifiers)
        for talent in eligible
    ]
    combinations = prod(len(ranks) + 1 for ranks in executable_ranks)
    if combinations > max_enumerations:
        return [], {'status': 'BLOCKED_EXACT_SUBSPACE_ENUMERATION_BUDGET',
                    'raw_combinations': combinations, 'max_enumerations': max_enumerations,
                    'complete_supported_subspace': False}

    def validate(selection):
        if sum(int(rank) for rank in selection.values()) != budget:
            raise ValueError('TALENT_ALLOCATION_MUST_SPEND_EXACT_POINT_BUDGET')
        validate_talent_selection(compiled, selection, level=level,
                                  bonus_talent_points=bonus_talent_points)

    if not eligible:
        accepted = []
        if budget == 0:
            try:
                validate({})
            except ValueError:
                pass
            else:
                accepted.append({})
        return accepted, {
            'status': ('COMPLETE_SUPPORTED_SUBSPACE_ENUMERATION' if accepted
                       else 'NO_EXECUTABLE_LEGAL_ALLOCATION'),
            'raw_combinations': combinations,
            'eligible_talent_ids': [],
            'legal_allocations': len(accepted),
            'points': budget,
            'complete_supported_subspace': True,
            'all_source_talent_ranks_covered': False,
        }

    options = tuple(
        TalentAllocationOption(
            talent_id=talent.id,
            max_rank=max(ranks),
            executable_ranks=frozenset(ranks),
        )
        for talent, ranks in zip(eligible, executable_ranks)
    )
    allocations, truncated = enumerate_talent_allocations(
        options,
        max_points=budget,
        rank_is_admissible=lambda *_: True,
        validate_selection=validate,
        max_candidates=max_enumerations,
    )
    if truncated:
        return [], {'status': 'BLOCKED_EXACT_SUBSPACE_ENUMERATION_BUDGET',
                    'raw_combinations': combinations, 'max_enumerations': max_enumerations,
                    'complete_supported_subspace': False}
    accepted = [dict(candidate) for candidate in allocations]
    return accepted, {
        'status': ('COMPLETE_SUPPORTED_SUBSPACE_ENUMERATION' if accepted
                   else 'NO_EXECUTABLE_LEGAL_ALLOCATION'),
        'raw_combinations': combinations,
        'eligible_talent_ids': [t.id for t in eligible],
        'legal_allocations': len(accepted),
        'points': budget,
        'complete_supported_subspace': True,
        'all_source_talent_ranks_covered': False,
    }
