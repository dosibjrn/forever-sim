"""G18's reusable cache bookkeeping belongs to optimization, not GameIR."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_policy_cache_core_is_game_independent_and_preserves_paid_metrics():
    source = r"""
import sys

from src.optimization.policy_evaluation_cache import PolicyEvaluationCacheCore

for forbidden in ("src.game", "src.game.model.ir", "src.game.runtime.simulator", "src.rulesets"):
    assert forbidden not in sys.modules, forbidden

calls = []

def prepare(policy):
    return policy["effective"], policy["pruned"]

def signature(effective):
    return effective["key"]

def paid(effective):
    calls.append(effective)
    if effective.get("raise"):
        raise RuntimeError("real evaluator refusal")
    return effective["score"], {"marker": "paid"}

cache = PolicyEvaluationCacheCore(prune=prepare, signature=signature, expensive_evaluate=paid)
first = {"effective": {"score": 3.5, "key": "normalized"}, "pruned": ({"rule_id": "later"},), "key": "normalized"}
second = {"effective": {"score": 99.0, "key": "normalized"}, "pruned": (), "key": "normalized"}

score, detail = cache.evaluate(first)
assert score == 3.5
assert detail["policy_cache_hit"] is False
assert detail["dominance_pruned"] is True
assert detail["dominance_pruned_rules"] == [{"rule_id": "later"}]
score, detail = cache.evaluate(second)
assert score == 3.5
assert detail["policy_cache_hit"] is True
assert detail["dominance_pruned"] is False
assert detail["dominance_pruned_rules"] == []
assert len(calls) == 1
assert cache.as_dict() == {
    "requests": 2,
    "expensive_evaluations": 1,
    "cache_hits": 1,
    "cache_entries": 1,
    "dominance_pruned_requests": 1,
    "dominance_pruned_rule_count": 1,
    "expensive_evaluations_avoided": 1,
}

try:
    cache.evaluate({"effective": {"raise": True, "key": "failed"}, "pruned": (), "key": "failed"})
except RuntimeError as exc:
    assert str(exc) == "real evaluator refusal"
else:
    raise AssertionError("failed paid evaluations must propagate")
assert "failed" not in cache._cache
assert cache.as_dict()["requests"] == 3
assert cache.as_dict()["expensive_evaluations"] == 2
"""
    completed = subprocess.run(
        [sys.executable, "-c", source],
        cwd=ROOT, capture_output=True, text=True, timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
