"""Backend-neutral paid policy evaluation cache.

The caller supplies pruning and a canonical executable signature.
No Warcraft actions, rules, source facts or GameIR classes are imported.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Mapping, TypeVar


PolicyT = TypeVar("PolicyT")


@dataclass
class PolicyEvaluationCacheCore(Generic[PolicyT]):
    prune: Callable[[PolicyT], tuple[PolicyT, tuple[Mapping[str, Any], ...]]]
    signature: Callable[[PolicyT], str]
    expensive_evaluate: Callable[[PolicyT], tuple[float | None, Mapping[str, Any]]]
    _cache: dict[str, tuple[float | None, Mapping[str, Any]]] = field(default_factory=dict)
    requests: int = 0
    expensive_evaluations: int = 0
    cache_hits: int = 0
    dominance_pruned_requests: int = 0
    dominance_pruned_rule_count: int = 0

    def evaluate(self, policy: PolicyT) -> tuple[float | None, Mapping[str, Any]]:
        self.requests += 1
        effective, pruned = self.prune(policy)
        if pruned:
            self.dominance_pruned_requests += 1
            self.dominance_pruned_rule_count += len(pruned)
        key = self.signature(effective)
        cached = self._cache.get(key)
        if cached is not None:
            self.cache_hits += 1
            score, detail = cached
            return score, {
                **dict(detail),
                "policy_cache_hit": True,
                "dominance_pruned": bool(pruned),
                "dominance_pruned_rules": [dict(x) for x in pruned],
            }
        self.expensive_evaluations += 1
        score, detail = self.expensive_evaluate(effective)
        stored = (score, dict(detail or {}))
        self._cache[key] = stored
        return score, {
            **dict(stored[1]),
            "policy_cache_hit": False,
            "dominance_pruned": bool(pruned),
            "dominance_pruned_rules": [dict(x) for x in pruned],
        }

    def as_dict(self) -> dict[str, int]:
        return {
            "requests": int(self.requests),
            "expensive_evaluations": int(self.expensive_evaluations),
            "cache_hits": int(self.cache_hits),
            "cache_entries": len(self._cache),
            "dominance_pruned_requests": int(self.dominance_pruned_requests),
            "dominance_pruned_rule_count": int(self.dominance_pruned_rule_count),
            "expensive_evaluations_avoided": int(self.requests - self.expensive_evaluations),
        }
