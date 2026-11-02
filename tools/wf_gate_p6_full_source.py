"""Explicit expensive P6 source-paid cold comparison using the existing runner.

This is a *diagnostic* until the same paid evaluator runs the selected
native↔2D world backend and source/legal-space completeness is demonstrated.
Never read historical search files or treat a gsim-only ratio as gate PASS.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def _execute(root: Path, arguments: list[str], output: Path, timeout_s: int,
             *, allowed_codes: tuple[int, ...] = (0,)) -> tuple[dict | None, str | None]:
    command = [sys.executable, '-m', 'tools.wf437_direct_budgeted_run',
               *arguments, '--output', str(output)]
    try:
        completed = subprocess.run(command, cwd=root, capture_output=True,
                                   text=True, timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired:
        return None, 'PAID_SOURCE_RUN_TIMEOUT'
    except OSError as exc:
        return None, 'PAID_SOURCE_RUN_START_FAILED:' + type(exc).__name__
    if completed.returncode not in allowed_codes or not output.is_file():
        return None, ('PAID_SOURCE_RUN_FAILED:rc=' + str(completed.returncode)
                      + ':' + (completed.stderr or completed.stdout)[-240:])
    try:
        report = json.loads(output.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None, 'PAID_SOURCE_RUN_INVALID_JSON'
    if not isinstance(report, dict):
        return None, 'PAID_SOURCE_RUN_NOT_OBJECT'
    return report, None


def run_full_source_comparison(root: Path, class_key: str, level: int, *,
                               spec: str = 'unrestricted') -> dict:
    """Cold 30/300s plus independent finalist and winner replays; NO hybrid PASS.

    The existing WF437 production command owns all search/replay mechanics.
    Files exist only in a temporary directory during this one explicit run.
    """
    if (class_key, level, spec) != ('druid', 30, 'unrestricted'):
        return {'status': 'BLOCKED', 'reasons': [
            'P6_FULL_SOURCE_RUNNER_CURRENTLY_SUPPORTS_DRUID_L30_UNRESTRICTED_ONLY']}
    root = Path(root)
    with TemporaryDirectory(prefix='p6-source-paid-') as temp:
        folder = Path(temp)
        searches = []
        for budget, timeout_s in ((30, 420), (300, 720)):
            report, error = _execute(root, ['--budget', str(budget)],
                                     folder / f'cold-{budget}.json', timeout_s)
            if error:
                return {'status': 'FAIL', 'reasons': [f'P6_{budget}S_' + error],
                        'production_engine': 'gsim_CombatRuntime'}
            if (report.get('requested_wall_budget_s') != budget
                    or report.get('search_only') is not True
                    or not report.get('validation_shortlist')):
                return {'status': 'FAIL', 'reasons': [
                    f'P6_{budget}S_MISSING_REAL_COLD_SEARCH_OR_FINALISTS']}
            searches.append(report)
        compared, error = _execute(root, [
            '--compare-30', str(folder / 'cold-30.json'),
            '--compare-300', str(folder / 'cold-300.json')],
            folder / 'comparison.json', 240, allowed_codes=(0, 1))
        if error:
            return {'status': 'FAIL', 'reasons': ['P6_COMPARE_' + error],
                    'production_engine': 'gsim_CombatRuntime'}
    # A numeric saturation result is useful even if its 1% target fails.
    # The source comparator itself verifies source hash, candidate-space
    # fingerprint, gear legality and fresh 100/100-mob replay completeness.
    replays = compared.get('replays') or []
    complete = (len(replays) == 2 and all(
        r.get('status') == 'COMPLETE' and r.get('count') == 100
        and isinstance(r.get('s_per_mob'), (int, float))
        and 0 < r['s_per_mob'] < float('inf') for r in replays))
    reasons = ['P6_SELECTED_NATIVE_2D_WORLD_BACKEND_NOT_VERIFIED',
               'P6_SOURCE_LEGAL_SPACE_COMPLETENESS_NOT_PROVEN']
    if not complete:
        reasons.append('P6_INDEPENDENT_100MOB_REPLAY_INCOMPLETE')
    elif compared.get('numeric_p6_within_1pct') is not True:
        reasons.append('P6_NUMERIC_SATURATION_EXCEEDS_1_PERCENT')
    return {
        'status': 'FAIL', 'reasons': reasons,
        'production_engine': 'gsim_CombatRuntime',
        'production_component': 'src.v2.source_paid_cold_comparison.compare_saved_cold_winners',
        'source_db_sha256': searches[0].get('source_db_sha256'),
        'source_gear_catalogue_snapshot': searches[0].get('source_gear_catalogue_snapshot'),
        'source_replay_results': replays,
        'source_replay_T30_T300': compared.get('ratio_T30_T300'),
        'source_replay_T30_s_per_mob': compared.get('T30_s_per_mob'),
        'source_replay_T300_s_per_mob': compared.get('T300_s_per_mob'),
        'source_replay_numeric_saturation': compared.get('numeric_p6_within_1pct'),
        'N30_unique_paid': compared.get('N30_unique_paid'),
        'N300_unique_paid': compared.get('N300_unique_paid'),
        'search_wall_s': [s.get('wall_s') for s in searches],
        'same_source_legal_candidate_space_proven': compared.get(
            'same_source_legal_candidate_space_proven'),
        'winning_gear_source_legality_verified': compared.get(
            'winning_gear_source_legality_verified'),
        'full_p6_selected_backend_acceptance': False,
        'coverage_scope_complete': False,
    }
