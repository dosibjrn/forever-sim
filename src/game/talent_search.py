from __future__ import annotations

"""Backend-neutral bounded talent allocation search.

G19 treats Talent IR definitions as the only candidate authority.  Candidate
construction knows nothing about classes, spells, rotations, or external talent
scorers: it enumerates legal rank allocations and delegates scoring to the
caller.  The caller is responsible for applying the allocation and running the
same policy/runtime/Evaluation stack used by production.
"""

from typing import TYPE_CHECKING

from src.optimization.talent_search import (
    TalentCandidateResult,
    TalentEvaluator,
    TalentSearchResult,
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
    # Source-backed rows first, ordered by tier, so impossible point budgets
    # and tier gates are pruned before producing a Cartesian explosion.
    # No class or talent names are privileged by this search order.
    definitions = sorted(executable_talent_definitions(ir_slice),
        key=lambda t: (t.tree_key, t.metadata.get('row') is None,
                       -1 if t.metadata.get('row') is None else int(t.metadata['row']), t.id))
    if not definitions:
        return ({},), False
    candidates: list[dict[str,int]] = []
    # Preserve the existing legacy legality path until a native provider is
    # migrated; do not duplicate talent point/rank rules in this client.
    from src.game.talents import available_talent_points, validate_talent_selection
    budget=available_talent_points(level, bonus_talent_points=bonus_talent_points)
    points_per_row=int((ir_slice.provenance.get('talent_tree_rules') or {}).get('points_per_row',0))
    selection: dict[str,int] = {}
    truncated=False

    def walk(index: int, spent: int) -> None:
        nonlocal truncated
        if truncated:
            return
        if index == len(definitions):
            try:
                validate_talent_selection(ir_slice,selection,level=level,bonus_talent_points=bonus_talent_points)
            except ValueError:
                return
            if len(candidates)>=max_candidates:
                truncated=True
                return
            candidates.append(dict(selection))
            return
        talent=definitions[index]
        row=talent.metadata.get('row')
        earlier=0
        if row is not None and int(row)>0:
            earlier=sum(rank for tid,rank in selection.items()
                if any(d.id==tid and d.tree_key==talent.tree_key and
                       d.metadata.get('row') is not None and
                       int(d.metadata['row'])<int(row) for d in definitions[:index]))
        for rank in range(0,min(int(talent.max_rank),budget-spent)+1):
            if rank:
                if row is not None and int(row)>0 and (
                    points_per_row<=0 or earlier<int(row)*points_per_row):
                    continue
                if not any(r.rank==rank and r.modifiers for r in talent.ranks):
                    continue
                selection[talent.id]=rank
            walk(index+1,spent+rank)
            if rank:
                del selection[talent.id]
            if truncated:
                break
    walk(0,0)
    return tuple(candidates),truncated


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
