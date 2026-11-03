"""The generic evaluation cache must remain independent of GameIR."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_optimizer_evaluation_cache_is_game_independent_and_caches_invalid_results():
    source = r"""
from dataclasses import dataclass
import sys

from src.optimization.evaluation_cache import EvaluationCache

assert "src.game" not in sys.modules

@dataclass(frozen=True)
class Candidate:
    key: str
    payload: float

calls = []

def expensive_evaluate(candidate):
    calls.append(candidate.payload)
    if candidate.payload < 0:
        return None, {"reason": "invalid", "payload": candidate.payload}
    return candidate.payload, {"reason": "evaluated", "payload": candidate.payload}

cache = EvaluationCache(
    key_for=lambda candidate: candidate.key,
    expensive_evaluate=expensive_evaluate,
)

first_score, first_detail, first_hit = cache.evaluate(Candidate("same", -1.0))
cached_score, cached_detail, cached_hit = cache.evaluate(Candidate("same", -2.0))
other_score, other_detail, other_hit = cache.evaluate(Candidate("other", 3.0))

assert first_score is None and cached_score is None
assert first_detail == cached_detail == {"reason": "invalid", "payload": -1.0}
assert first_hit is False and cached_hit is True
assert other_score == 3.0
assert other_detail == {"reason": "evaluated", "payload": 3.0}
assert other_hit is False
assert calls == [-1.0, 3.0]
assert cache.as_dict() == {
    "requests": 3,
    "expensive_evaluations": 2,
    "cache_hits": 1,
    "cache_entries": 2,
    "expensive_evaluations_avoided": 1,
}
assert "src.game" not in sys.modules
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
