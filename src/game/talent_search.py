from __future__ import annotations

"""Backend-neutral bounded talent allocation search.

G19 treats Talent IR definitions as the only candidate authority.  Candidate
construction knows nothing about classes, spells, rotations, or external talent
scorers: it enumerates legal rank allocations and delegates scoring to the
caller.  The caller is responsible for applying the allocation and running the
same policy/runtime/Evaluation stack used by production.
"""

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from src.game.model.ir import GameIRSlice, TalentDefinition
from src.game.talents import validate_talent_selection


TalentEvaluator = Callable[[Mapping[str, int]], tuple[float | None, Mapping[str, Any]]]


def talent_candidate_id(selection: Mapping[str, int]) -> str:
    normalized = sorted((str(k), int(v)) for k, v in selection.items() if int(v) > 0)
    if not normalized:
        return "talents:none"
    return "talents:" + ";".join(f"{key}={rank}" for key, rank in normalized)


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
    from src.game.talents import available_talent_points
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


@dataclass(frozen=True)
class TalentCandidateResult:
    candidate_id: str
    selection: Mapping[str, int]
    spent_points: int
    seconds_per_mob: float | None
    valid: bool
    detail: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "selection": {str(k): int(v) for k, v in self.selection.items()},
            "spent_points": int(self.spent_points),
            "seconds_per_mob": self.seconds_per_mob,
            "valid": bool(self.valid),
            "detail": dict(self.detail),
        }


@dataclass(frozen=True)
class TalentSearchResult:
    selected_candidate_id: str | None
    selected_selection: Mapping[str, int]
    selected_seconds_per_mob: float | None
    selected_detail: Mapping[str, Any]
    candidates: tuple[TalentCandidateResult, ...]
    truncated: bool
    executable_talent_ids: tuple[str, ...]
    blocked_talent_ids: tuple[str, ...] = ()
    complete_source_talent_coverage: bool = False

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    @property
    def valid_candidate_count(self) -> int:
        return sum(1 for x in self.candidates if x.valid)

    def as_dict(self) -> dict[str, Any]:
        return {
            "search_performed": True,
            "search_dimensions": [
                "talent_rank_allocation",
                "policy_action_inclusion_exclusion",
                "policy_priority_order",
                "policy_numeric_condition_thresholds",
            ],
            "candidate_count": self.candidate_count,
            "valid_candidate_count": self.valid_candidate_count,
            "truncated": bool(self.truncated),
            "executable_talent_ids": list(self.executable_talent_ids),
            "blocked_talent_ids": list(self.blocked_talent_ids),
            "complete_source_talent_coverage": bool(self.complete_source_talent_coverage),
            "selected_candidate_id": self.selected_candidate_id,
            "selected_selection": {str(k): int(v) for k, v in self.selected_selection.items()},
            "selected_seconds_per_mob": self.selected_seconds_per_mob,
            "selected_detail": dict(self.selected_detail),
            "candidates": [x.as_dict() for x in self.candidates],
        }


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
    results: list[TalentCandidateResult] = []
    for selection in allocations:
        cid = talent_candidate_id(selection)
        score: float | None
        detail: Mapping[str, Any]
        try:
            score, detail = evaluate(selection)
        except (ValueError, RuntimeError, KeyError) as exc:
            score, detail = None, {"error": f"{type(exc).__name__}: {exc}"}
        valid = score is not None
        results.append(TalentCandidateResult(
            candidate_id=cid,
            selection=dict(selection),
            spent_points=sum(int(v) for v in selection.values()),
            seconds_per_mob=(None if score is None else float(score)),
            valid=valid,
            detail=dict(detail or {}),
        ))

    valid_rows = [row for row in results if row.valid and row.seconds_per_mob is not None]
    if not valid_rows:
        selected = None
    else:
        # Score is authoritative.  Equal-score ties prefer fewer spent points,
        # then stable candidate identity so irrelevant/no-op points do not win.
        selected = min(
            valid_rows,
            key=lambda row: (float(row.seconds_per_mob), int(row.spent_points), row.candidate_id),
        )
    definitions = executable_talent_definitions(ir_slice)
    return TalentSearchResult(
        selected_candidate_id=(None if selected is None else selected.candidate_id),
        selected_selection=({} if selected is None else dict(selected.selection)),
        selected_seconds_per_mob=(None if selected is None else float(selected.seconds_per_mob)),
        selected_detail=({} if selected is None else dict(selected.detail)),
        candidates=tuple(results),
        truncated=truncated,
        executable_talent_ids=tuple(t.id for t in definitions),
        blocked_talent_ids=tuple(t.id for t in ir_slice.talents if not _definition_is_executable(t)),
        complete_source_talent_coverage=(
            bool(ir_slice.talents) and
            len(definitions) == len(ir_slice.talents) and
            not bool((ir_slice.provenance.get('talent_sqlite_coverage') or {}).get('blockers'))
        ),
    )
