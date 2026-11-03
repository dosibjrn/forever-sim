"""Game-model-independent talent allocation, candidate identity and scoring.

GameIR adaptation and source-legality validation remain in src.game.talent_search.
This module owns pure candidate enumeration and callback-driven scoring.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping


TalentEvaluator = Callable[[Mapping[str, int]], tuple[float | None, Mapping[str, Any]]]
TalentSelectionValidator = Callable[[Mapping[str, int]], None]


@dataclass(frozen=True)
class TalentAllocationOption:
    """Minimal candidate identity and executable-rank data for generic search."""

    talent_id: str
    max_rank: int
    executable_ranks: frozenset[int]


TalentRankAdmission = Callable[
    [TalentAllocationOption, int, Mapping[str, int], int], bool
]


def enumerate_talent_allocations(
    options: Iterable[TalentAllocationOption],
    *,
    max_points: int,
    rank_is_admissible: TalentRankAdmission,
    validate_selection: TalentSelectionValidator,
    max_candidates: int = 1024,
) -> tuple[tuple[dict[str, int], ...], bool]:
    """Enumerate bounded allocations using caller-owned partial/full legality.

    The optimizer only traverses the supplied ordered options and enforces the
    generic point budget. Callbacks own all game-specific admission decisions.
    """
    if max_candidates < 1:
        raise ValueError("max_candidates must be positive")
    definitions = tuple(options)
    if not definitions:
        return ({},), False

    candidates: list[dict[str, int]] = []
    selection: dict[str, int] = {}
    truncated = False

    def walk(index: int, spent: int) -> None:
        nonlocal truncated
        if truncated:
            return
        if index == len(definitions):
            try:
                validate_selection(selection)
            except ValueError:
                return
            if len(candidates) >= max_candidates:
                truncated = True
                return
            candidates.append(dict(selection))
            return

        talent = definitions[index]
        for rank in range(0, min(int(talent.max_rank), int(max_points) - spent) + 1):
            if rank:
                if rank not in talent.executable_ranks:
                    continue
                if not rank_is_admissible(talent, rank, selection, index):
                    continue
                selection[talent.talent_id] = rank
            walk(index + 1, spent + rank)
            if rank:
                del selection[talent.talent_id]
            if truncated:
                break

    walk(0, 0)
    return tuple(candidates), truncated


def talent_candidate_id(selection: Mapping[str, int]) -> str:
    normalized = sorted((str(k), int(v)) for k, v in selection.items() if int(v) > 0)
    if not normalized:
        return "talents:none"
    return "talents:" + ";".join(f"{key}={rank}" for key, rank in normalized)


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


def score_talent_allocations(
    allocations: Iterable[Mapping[str, int]],
    *,
    evaluate: TalentEvaluator,
) -> tuple[tuple[TalentCandidateResult, ...], TalentCandidateResult | None]:
    """Score supplied candidates and choose a stable winner without game imports."""
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
    selected = min(
        valid_rows,
        key=lambda row: (float(row.seconds_per_mob), int(row.spent_points), row.candidate_id),
    ) if valid_rows else None
    return tuple(results), selected


__all__ = (
    "TalentAllocationOption",
    "TalentCandidateResult",
    "TalentEvaluator",
    "TalentSearchResult",
    "TalentRankAdmission",
    "TalentSelectionValidator",
    "enumerate_talent_allocations",
    "score_talent_allocations",
    "talent_candidate_id",
)
