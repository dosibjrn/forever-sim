from __future__ import annotations

"""Backend-neutral memoization for expensive candidate evaluation.

Callers own candidate normalization and cache identity through `key_for`.
This module only stores evaluator results and reports cache efficiency; it has
no dependency on a game model or a particular candidate representation.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Hashable, Mapping, TypeVar


CandidateT = TypeVar("CandidateT")
EvaluationFunction = Callable[[CandidateT], tuple[float | None, Mapping[str, Any]]]


@dataclass
class EvaluationCache(Generic[CandidateT]):
    """Memoize expensive candidate evaluations by a caller-supplied key."""

    key_for: Callable[[CandidateT], Hashable]
    expensive_evaluate: EvaluationFunction
    _cache: dict[Hashable, tuple[float | None, Mapping[str, Any]]] = field(
        default_factory=dict,
        repr=False,
    )
    requests: int = 0
    expensive_evaluations: int = 0
    cache_hits: int = 0

    def evaluate(
        self,
        candidate: CandidateT,
    ) -> tuple[float | None, Mapping[str, Any], bool]:
        """Return score, copied detail, and whether the result was cached.

        Invalid candidates (a `None` score) are cached too. Their detail is
        retained exactly like a successful evaluation so repeated invalid
        candidates do not trigger another expensive simulation.
        """
        self.requests += 1
        key = self.key_for(candidate)
        cached = self._cache.get(key)
        if cached is not None:
            self.cache_hits += 1
            score, detail = cached
            return score, dict(detail), True

        self.expensive_evaluations += 1
        score, detail = self.expensive_evaluate(candidate)
        stored = (score, dict(detail or {}))
        self._cache[key] = stored
        return score, dict(stored[1]), False

    def as_dict(self) -> dict[str, int]:
        return {
            "requests": int(self.requests),
            "expensive_evaluations": int(self.expensive_evaluations),
            "cache_hits": int(self.cache_hits),
            "cache_entries": len(self._cache),
            "expensive_evaluations_avoided": int(self.requests - self.expensive_evaluations),
        }


__all__ = ("EvaluationCache", "EvaluationFunction")
