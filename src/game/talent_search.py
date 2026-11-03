from __future__ import annotations

"""Transitional GameIR adapter for source-backed talent allocation search.

The generic allocation enumerator, candidate identity and scoring live in
src.optimization.talent_search. This module adapts current Talent IR definitions
and supplies the retained source-legality validator until native migration.
"""

from typing import TYPE_CHECKING, Mapping

from src.optimization.talent_search import (
    TalentAllocationOption,
    TalentCandidateResult,
    TalentEvaluator,
    TalentSearchResult,
    enumerate_talent_allocations,
    score_talent_allocations,
    talent_candidate_id,
)

if TYPE_CHECKING:
    from src.game.model.ir import GameIRSlice, TalentDefinition


def _definition_is_executable(definition: TalentDefinition) -> bool:
    return any(rank.modifiers for rank in definition.ranks)


def executable_talent_definitions(ir_slice: GameIRSlice) -> tuple[TalentDefinition, ...]:
    """Return only Talent IR families with at least one executable modifier.

    Source-backed identity without normalized executable semantics is useful
    provenance, but it must not become a no-op optimization candidate.
    """
    return tuple(t for t in ir_slice.talents if _definition_is_executable(t))


def enumerate_legal_talent_allocations(
    ir_slice: GameIRSlice,
    *,
    level: int,
    max_candidates: int = 1024,
    bonus_talent_points: int = 0,
) -> tuple[tuple[dict[str, int], ...], bool]:
    if max_candidates < 1:
        raise ValueError('max_candidates must be positive')
    # Preserve the original deterministic source-tree ordering in the adapter;
    # the optimizer receives an already ordered, game-neutral option sequence.
    definitions = sorted(
        executable_talent_definitions(ir_slice),
        key=lambda talent: (
            talent.tree_key,
            talent.metadata.get('row') is None,
            -1 if talent.metadata.get('row') is None else int(talent.metadata['row']),
            talent.id,
        ),
    )
    if not definitions:
        return ({},), False

    # All source facts and partial/complete legality decisions remain here until
    # the corresponding native MythicSim interface is proven and adopted.
    from src.game.talents import available_talent_points, validate_talent_selection

    options = tuple(
        TalentAllocationOption(
            talent_id=definition.id,
            max_rank=int(definition.max_rank),
            executable_ranks=frozenset(
                int(rank.rank) for rank in definition.ranks if rank.modifiers
            ),
        )
        for definition in definitions
    )
    budget = available_talent_points(level, bonus_talent_points=bonus_talent_points)
    points_per_row = int(
        (ir_slice.provenance.get('talent_tree_rules') or {}).get('points_per_row', 0)
    )
    def rank_is_admissible(
        option: TalentAllocationOption,
        rank: int,
        selection: Mapping[str, int],
        index: int,
    ) -> bool:
        definition = definitions[index]
        row = definition.metadata.get('row')
        if row is None or int(row) <= 0:
            return True
        earlier = sum(
            selected_rank
            for selected_id, selected_rank in selection.items()
            if any(
                prior.id == selected_id
                and prior.tree_key == definition.tree_key
                and prior.metadata.get('row') is not None
                and int(prior.metadata['row']) < int(row)
                for prior in definitions[:index]
            )
        )
        return points_per_row > 0 and earlier >= int(row) * points_per_row

    def validate(selection: Mapping[str, int]) -> None:
        validate_talent_selection(
            ir_slice,
            selection,
            level=level,
            bonus_talent_points=bonus_talent_points,
        )

    return enumerate_talent_allocations(
        options,
        max_points=budget,
        rank_is_admissible=rank_is_admissible,
        validate_selection=validate,
        max_candidates=max_candidates,
    )


def search_talent_allocations(
    ir_slice: GameIRSlice,
    *,
    level: int,
    evaluate: TalentEvaluator,
    max_candidates: int = 1024,
    bonus_talent_points: int = 0,
) -> TalentSearchResult:
    allocations, truncated = enumerate_legal_talent_allocations(
        ir_slice, level=level, max_candidates=max_candidates, bonus_talent_points=bonus_talent_points,
    )
    results, selected = score_talent_allocations(allocations, evaluate=evaluate)
    definitions = executable_talent_definitions(ir_slice)
    return TalentSearchResult(
        selected_candidate_id=(None if selected is None else selected.candidate_id),
        selected_selection=({} if selected is None else dict(selected.selection)),
        selected_seconds_per_mob=(None if selected is None else float(selected.seconds_per_mob)),
        selected_detail=({} if selected is None else dict(selected.detail)),
        candidates=results,
        truncated=truncated,
        executable_talent_ids=tuple(t.id for t in definitions),
        blocked_talent_ids=tuple(t.id for t in ir_slice.talents if not _definition_is_executable(t)),
        complete_source_talent_coverage=(
            bool(ir_slice.talents) and
            len(definitions) == len(ir_slice.talents) and
            not bool((ir_slice.provenance.get('talent_sqlite_coverage') or {}).get('blockers'))
        ),
    )
