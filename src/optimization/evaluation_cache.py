from __future__ import annotations

"""Game-model-independent memoization for callback-evaluated optimizer candidates.

The caller supplies both the semantic cache key and the expensive evaluator.
Candidate normalization, game rules and result interpretation stay outside
this module; this module owns only memoization and its counters.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Mapping, TypeVar


CandidateT = TypeVar("CandidateT")


@dataclass
class EvaluationCache(Generic[CandidateT]):
    """Cache successful and unsuccessful evaluations by caller-owned key."""

    _cache: dict[str, tuple[float | None, Mapping[str, Any]]] = field(default_factory=dict)
    requests: int = 0
    expensive_evaluations: int = 0
    cache_hits: int = 0

    def evaluate(
        self,
        key: str,
        candidate: CandidateT,
        *,
        expensive_evaluate: Callable[[CandidateT], tuple[float | None, Mapping[str, Any]]],
    ) -> tuple[float | None, Mapping[str, Any], bool]:
        cache_key = str(key)
        self.requests += 1
        cached = self._cache.get(cache_key)
        if cached is not None:
            self.cache_hits += 1
            score, detail = cached
            return score, dict(detail), True

        self.expensive_evaluations += 1
        score, detail = expensive_evaluate(candidate)
        stored = (score, dict(detail or {}))
        self._cache[cache_key] = stored
        return stored[0], dict(stored[1]), False

    def as_dict(self) -> dict[str, int]:
        return {
            "requests": int(self.requests),
            "expensive_evaluations": int(self.expensive_evaluations),
            "cache_hits": int(self.cache_hits),
            "cache_entries": len(self._cache),
            "expensive_evaluations_avoided": int(self.requests - self.expensive_evaluations),
        }


__all__ = ("EvaluationCache",)
