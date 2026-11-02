"""Explicit P6 source-paid independent cold search and 100-mob replay.

The actual selected source-backed 2D CombatRuntime is a valid production
backend under COMMON. Never invent a native-hybrid or catalog-completeness
gate on top of the approved P6 independent winner saturation predicate.
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
    """Cold 30/300s plus independent 100-mob winner replays on selected gsim.

    The existing WF437 production command owns all search/replay mechanics.
    Files exist only in a temporary directory during this one explicit run.
    """
    # The same WF437 source-paid CLI is parameterized by checkpoint.
    # Its historical Druid L30 unrestricted defaults stay unchanged.
    checkpoint_args = ([] if (class_key, level, spec) ==
                       ('druid', 30, 'unrestricted') else [
        '--checkpoint-class', class_key, '--checkpoint-level', str(level),
        '--checkpoint-spec', spec])
    root = Path(root)
    with TemporaryDirectory(prefix='p6-source-paid-') as temp:
        folder = Path(temp)
        searches = []
        for budget, timeout_s in ((30, 420), (300, 720)):
            report, error = _execute(root, ['--budget', str(budget), *checkpoint_args],
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
            '--compare-300', str(folder / 'cold-300.json'),
            *checkpoint_args],
            folder / 'comparison.json', 240, allowed_codes=(0, 1))
        if error:
            return {'status': 'FAIL', 'reasons': ['P6_COMPARE_' + error],
                    'production_engine': 'gsim_CombatRuntime'}
    # Production replay receipts are independently recomputed from the two
    # cold-selected full builds. Zero or partial kills cannot satisfy P6.
    from math import isfinite
    replays = compared.get('replays') or []
    complete = (isinstance(replays, list) and len(replays) == 2 and all(
        isinstance(r, dict) and r.get('status') == 'COMPLETE'
        and type(r.get('count')) is int and r['count'] == 100
        and type(r.get('mob_completed')) is int and r['mob_completed'] == 100
        and type(r.get('s_per_mob')) in (int, float)
        and isfinite(r['s_per_mob']) and r['s_per_mob'] > 0
        for r in replays))
    # Do not credit bare matching report labels: the production comparator
    # confirms the same executed source proposal, item snapshot, winning gear
    # legality, and actual 100-mob replay for both cold winners.
    reasons = []
    if not complete:
        reasons.append('P6_INDEPENDENT_100MOB_REPLAY_INCOMPLETE')
    if compared.get('same_source_legal_candidate_space_proven') is not True:
        reasons.append('P6_INDEPENDENT_COLD_SOURCE_SPACE_NOT_MATCHED')
    if compared.get('winning_gear_source_legality_verified') is not True:
        reasons.append('P6_WINNING_GEAR_SOURCE_LEGALITY_NOT_VERIFIED')
    if any(s.get('p4_talent_unlock_coverage_pass') is not True for s in searches):
        reasons.append('P6_SOURCE_UNLOCK_PAID_EVALUATIONS_INCOMPLETE')
    if compared.get('p5_2x_breadth') is not True:
        reasons.append('P6_P5_COLD_WINNER_PAID_BREADTH_NOT_VERIFIED')
    if complete and compared.get('numeric_p6_within_1pct') is not True:
        reasons.append('P6_NUMERIC_SATURATION_EXCEEDS_1_PERCENT')
    proof = {}
    if not reasons:
        from hashlib import sha256
        from json import dumps
        from uuid import uuid4
        from src.version import SOFTWARE_VERSION
        source_identity = dumps({
            'ability_db_sha256': searches[0]['source_db_sha256'],
            'gear_catalogue': searches[0]['source_gear_catalogue_snapshot'],
        }, sort_keys=True, separators=(',', ':'), default=str)
        proof = {'runtime_proof': {
            'executed': True, 'engine_revision': 'gsim-' + SOFTWARE_VERSION,
            'source_revision': sha256(source_identity.encode()).hexdigest(),
            'run_id': 'source-paid-p6-' + str(uuid4())}}

    return {
        'status': 'FAIL' if reasons else 'PASS', 'reasons': reasons,
        **proof,
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
        'selected_production_backend': 'gsim',
        'native_hybrid_diagnostic_pending': True,
        'full_p6_selected_backend_acceptance': not reasons,
        'coverage_scope_complete': not reasons,
    }
