"""Generic talent result helpers must not import the retiring Python game model.

This test covers the import boundary, not native talent legality or P2 acceptance.
The existing source-backed legacy talent enumeration regressions remain separate.
"""

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def test_talent_result_helpers_are_importable_without_gameir_or_legacy_validator():
    source = """
import sys

from src.optimization.talent_search import (
    talent_candidate_id as optimizer_talent_candidate_id,
    TalentCandidateResult as OptimizerTalentCandidateResult,
    TalentSearchResult as OptimizerTalentSearchResult,
)
from src.game.talent_search import (
    talent_candidate_id, TalentCandidateResult, TalentSearchResult,
)

assert optimizer_talent_candidate_id is talent_candidate_id
assert OptimizerTalentCandidateResult is TalentCandidateResult
assert OptimizerTalentSearchResult is TalentSearchResult

assert 'src.game.model.ir' not in sys.modules
assert 'src.game.talents' not in sys.modules
assert 'src.game.runtime.simulator' not in sys.modules

assert talent_candidate_id({}) == 'talents:none'
assert talent_candidate_id({'z': 2, 'a': 1, 'ignored': 0}) == 'talents:a=1;z=2'
candidate = TalentCandidateResult(
    candidate_id='talents:a=1', selection={'a': 1}, spent_points=1,
    seconds_per_mob=8.5, valid=True, detail={'executor': 'native'},
)
result = TalentSearchResult(
    selected_candidate_id=candidate.candidate_id,
    selected_selection=candidate.selection,
    selected_seconds_per_mob=candidate.seconds_per_mob,
    selected_detail=candidate.detail,
    candidates=(candidate,), truncated=False,
    executable_talent_ids=('a',),
)
payload = result.as_dict()
assert payload['candidate_count'] == 1
assert payload['valid_candidate_count'] == 1
assert payload['selected_seconds_per_mob'] == 8.5
assert payload['candidates'][0]['detail']['executor'] == 'native'

assert 'src.game.model.ir' not in sys.modules
assert 'src.game.talents' not in sys.modules
assert 'src.game.runtime.simulator' not in sys.modules
"""
    completed = subprocess.run(
        [sys.executable, "-c", source], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
