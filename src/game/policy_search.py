"""Compatibility imports for the former game-layer policy-search module.

The bounded combinatorial search is game-independent and lives in
src.optimization.policy_search. Game-aware threshold/evaluation adapters remain
in src.game and keep using the shared public types through this re-export.
"""

from src.optimization.policy_search import (
    PolicyEvaluator,
    PolicyLike,
    PolicyRuleLike,
    PolicySearchResult,
    search_priority_policy,
)

__all__ = (
    "PolicyEvaluator",
    "PolicyLike",
    "PolicyRuleLike",
    "PolicySearchResult",
    "search_priority_policy",
)
