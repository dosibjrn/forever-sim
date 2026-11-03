"""The generic priority-policy optimizer must remain game-model independent."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_optimizer_policy_search_is_game_independent_and_legacy_api_is_preserved():
    source = r"""
from dataclasses import dataclass
import sys

from src.optimization.policy_search import (
    PolicyLike,
    PolicyRuleLike,
    PolicySearchResult,
    search_priority_policy,
)

for module in (
    "src.game",
    "src.game.model.ir",
    "src.game.runtime.simulator",
    "src.rulesets",
):
    assert module not in sys.modules, module

@dataclass(frozen=True)
class Rule:
    id: str
    action_id: str
    phase: str

@dataclass(frozen=True)
class Policy:
    id: str
    label: str
    rules: tuple[Rule, ...]
    provenance: dict

seed = Policy(
    id="fixture",
    label="fixture",
    rules=(
        Rule("a", "action-a", "combat"),
        Rule("b", "action-b", "combat"),
        Rule("pre", "pre-action", "prepull"),
    ),
    provenance={"authority": "test"},
)

def evaluate(policy):
    ids = tuple(rule.id for rule in policy.rules if rule.phase == "combat")
    scores = {
        ("a",): None,
        ("b",): 2.0,
        ("a", "b"): 4.0,
        ("b", "a"): 1.0,
    }
    return scores[ids], {"fixture_evaluator": True}

result = search_priority_policy(seed, evaluate=evaluate, max_candidates=8)
assert isinstance(result, PolicySearchResult)
assert result.search_performed is True
assert len(result.candidates) == 4
assert len(result.valid_candidates) == 3
assert result.seed_candidate["candidate_id"] == "priority:a>b"
assert result.seed_candidate["is_seed"] is True
assert result.candidates[0]["valid"] is False
assert result.selected_candidate["candidate_id"] == "priority:b>a"
assert result.selected_policy is not None
assert tuple(rule.id for rule in result.selected_policy.rules) == ("b", "a", "pre")
assert result.selected_policy.provenance["candidate_count"] == 4
assert result.as_dict()["selected_seconds_per_mob"] == 1.0

# The optimizer import above must not pull in the old game package. The old
# import path remains a compatibility re-export for downstream callers.
from src.game.policy_search import (
    PolicySearchResult as LegacyPolicySearchResult,
    search_priority_policy as legacy_search_priority_policy,
)
assert legacy_search_priority_policy is search_priority_policy
assert LegacyPolicySearchResult is PolicySearchResult
assert PolicyLike is not None and PolicyRuleLike is not None
"""
    completed = subprocess.run(
        [sys.executable, "-c", source],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
