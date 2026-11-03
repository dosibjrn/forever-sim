"""Game-model-independent talent candidate identity, scoring and result types.

Source-backed talent enumeration and legality remain in src.game.talent_search.
This module owns only stable candidate representation and callback-driven scoring.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping


TalentEvaluator = Callable[[Mapping[str, int]], tuple[float | None, Mapping[str, Any]]]


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
    "TalentCandidateResult",
    "TalentEvaluator",
    "TalentSearchResult",
    "score_talent_allocations",
    "talent_candidate_id",
)
