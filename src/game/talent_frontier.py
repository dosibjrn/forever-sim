"""Source-legal talent neighbor frontier over the transitional GameIR adapter.

The generic mutation walk and neighbor identity live in src.optimization. This
module supplies the current source-derived rank options and legality callback
until each live consumer has moved to the selected native MythicSim interface.
"""
from __future__ import annotations

from typing import Mapping

from src.game.source_objective_relevance import solo_threat_exclusion
from src.optimization.talent_frontier import (
    Neighbor,
    TalentNeighborOption,
    allocation_key,
    generate_talent_neighbors,
)


def source_legal_talent_neighbors(
    ir,
    allocation: Mapping[str, int],
    *,
    level: int,
    bonus_talent_points: int = 0,
) -> dict:
    """Generate source-supported one-point edits, transfers and rank sweeps.

    A rank sweep is an acceleration proposal, not an instantaneous leveling
    transition. Every proposal is checked against the full current source-derived
    validator; unsupported ranks are never silently converted to no-op states.
    """
    from src.game.talents import validate_talent_selection, available_talent_points

    # Preserve the existing fail-closed behavior for an invalid starting state.
    validate_talent_selection(
        ir, allocation, level=level, bonus_talent_points=bonus_talent_points
    )
    roster = tuple(ir.talents)
    options = tuple(
        TalentNeighborOption(
            talent_id=talent.id,
            max_rank=int(talent.max_rank),
            supported_ranks=frozenset(
                int(rank.rank)
                for rank in talent.ranks
                if rank.modifiers or solo_threat_exclusion(ir, rank) is not None
            ),
        )
        for talent in roster
    )

    def validate(selection: Mapping[str, int]) -> None:
        validate_talent_selection(
            ir,
            dict(selection),
            level=level,
            bonus_talent_points=bonus_talent_points,
        )

    frontier = generate_talent_neighbors(
        options,
        allocation,
        max_points=available_talent_points(
            level, bonus_talent_points=bonus_talent_points
        ),
        validate_selection=validate,
    )
    return {
        'neighbors': frontier['neighbors'],
        'generated': frontier['generated'],
        'legal': frontier['legal'],
        'rejected_by_reason': frontier['rejected_by_reason'],
        'unsupported_talent_ids': frontier['unsupported_option_ids'],
        'source_talent_families': frontier['option_count'],
        'executable_talent_families': frontier['supported_option_count'],
    }
