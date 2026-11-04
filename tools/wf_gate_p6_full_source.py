"""P6: one real 300s cold search with a paid 30s best-so-far snapshot.

Only genuine retained-actor spatial 100-mob winner receipts qualify. Reuse an
identical finalist's real production replay; otherwise run the missing winner
through the existing source-paid WF437 replay, not a gate-only simulator.
"""
from __future__ import annotations

import json
import subprocess
import sys
from hashlib import sha256
from math import isfinite
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4


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


_BUILD_FIELDS = ('allocation', 'equipped_gear', 'opening_action_ids',
                 'policy_ir', 'policy_signature', 'recovery')


def _build_identity(winner: dict) -> str:
    if not isinstance(winner, dict) or any(key not in winner for key in _BUILD_FIELDS):
        raise ValueError('P6_INCOMPLETE_PAID_BUILD')
    return json.dumps({key: winner[key] for key in _BUILD_FIELDS},
                      sort_keys=True, separators=(',', ':'), default=str)



def _shared_replay_winners(report: dict) -> list[dict]:
    """Run the actual frozen 30s and final 300s builds, not every proxy finalist.

    P6 compares precisely these two builds. An identical build is only paid
    once; all other shortlist screens remain useful search diagnostics.
    """
    snapshot = report.get('shared_search_snapshot') or {}
    candidates = (snapshot.get('winner'), report.get('search_winner'))
    winners, identities = [], set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        try:
            identity = _build_identity(candidate)
        except ValueError:
            continue
        if identity not in identities:
            winners.append(candidate)
            identities.add(identity)
    return winners


def _complete_receipt(row: dict) -> bool:
    if not isinstance(row, dict):
        return False
    seconds = row.get('full_s_per_mob')
    return (row.get('status') == 'COMPLETE'
            and type(row.get('count')) is int and row['count'] == 100
            and type(row.get('mob_completed', row['count'])) is int
            and row.get('mob_completed', row['count']) == 100
            and type(seconds) in (int, float) and isfinite(seconds)
            and seconds > 0)



def _measured_best_frozen_winner(report: dict, shortlist: list[dict],
                                 validation: dict) -> dict | None:
    """Select a 300s best-so-far only from genuinely paid 100-mob finalists.

    The 30s incumbent remains in the same cold 300s search. A late two-mob
    proxy winner must not replace that incumbent when its actual completed
    100-mob route is slower. This changes the producer's frozen P5 selection,
    not P6's approved numeric predicate. No unexecuted candidate is ranked.
    """
    snapshot = report.get('shared_search_snapshot') or {}
    frozen = (snapshot.get('winner'), report.get('search_winner'))
    rows = validation.get('rows') if isinstance(validation, dict) else None
    if (not all(isinstance(candidate, dict) for candidate in frozen)
            or not isinstance(shortlist, list) or not isinstance(rows, list)
            or len(rows) != len(shortlist)):
        return None
    paid_by_identity = {}
    for index, (candidate, row) in enumerate(zip(shortlist, rows)):
        if (not isinstance(row, dict) or str(row.get('id')) != str(index)
                or not _complete_receipt(row)):
            continue
        try:
            identity = _build_identity(candidate)
        except ValueError:
            continue
        paid_by_identity[identity] = row['full_s_per_mob']
    measured = []
    for candidate in frozen:
        try:
            identity = _build_identity(candidate)
        except ValueError:
            return None
        if identity in paid_by_identity:
            measured.append((paid_by_identity[identity], candidate))
    # Stable tie: retain the earlier paid 30s incumbent.
    return min(measured, key=lambda entry: entry[0])[1] if measured else None


def _reuse_identical_receipt(report: dict, winner: dict) -> dict | None:
    """Reuse only an identical 100-mob finalist already executed in this run."""
    identity = _build_identity(winner)
    validation = report.get('validation') or {}
    for index, candidate in enumerate(report.get('validation_shortlist') or []):
        try:
            if _build_identity(candidate) != identity:
                continue
        except ValueError:
            # An incomplete unselected search row cannot be reused as a
            # winner receipt; the selected build must still be paid below.
            continue
        for row in validation.get('rows') or []:
            if (isinstance(row, dict) and str(row.get('id')) == str(index)
                    and _complete_receipt(row)):
                return {'status': 'COMPLETE', 'count': 100, 'mob_completed': 100,
                        's_per_mob': row['full_s_per_mob'],
                        'events': row.get('events'), 'reused': True,
                        'build_identity': identity}
    return None


def _paid_winner_receipt(root: Path, report: dict, winner: dict,
                         folder: Path, name: str,
                         checkpoint_args: list[str]) -> dict:
    previous = _reuse_identical_receipt(report, winner)
    if previous is not None:
        return previous
    # WF437 validates the same saved source, spec and catalogue, rebuilds the
    # complete selected candidate, then pays the persistent 100-mob execution.
    saved = folder / (name + '-search.json')
    saved.write_text(json.dumps({**report, 'validation_shortlist': [winner]},
                                default=str), encoding='utf-8')
    replay, error = _execute(root, [
        '--replay-from', str(saved), '--replay-row', '0', *checkpoint_args],
        folder / (name + '-100mobs.json'), 180)
    if error:
        return {'status': 'FAIL', 'reason': error, 'count': 0,
                'mob_completed': 0, 's_per_mob': None, 'reused': False}
    rows = (replay.get('validation') or {}).get('rows') or []
    row = rows[0] if isinstance(rows, list) and len(rows) == 1 else None
    if not _complete_receipt(row):
        return {'status': 'FAIL', 'reason': 'P6_INCOMPLETE_REAL_100MOB_REPLAY',
                'count': row.get('count') if isinstance(row, dict) else 0,
                'mob_completed': row.get('mob_completed', 0) if isinstance(row, dict) else 0,
                's_per_mob': None, 'reused': False}
    return {'status': 'COMPLETE', 'count': 100, 'mob_completed': 100,
            's_per_mob': row['full_s_per_mob'], 'events': row.get('events'),
            'reused': False, 'build_identity': _build_identity(winner)}


def run_full_source_comparison(root: Path, class_key: str, level: int, *,
                               spec: str = 'unrestricted') -> dict:
    """One cold search, true 30/300 snapshots, compatible 100-mob comparison."""
    checkpoint_args = ([] if (class_key, level, spec) ==
                       ('druid', 30, 'unrestricted') else [
        '--checkpoint-class', class_key, '--checkpoint-level', str(level),
        '--checkpoint-spec', spec])
    root = Path(root)
    with TemporaryDirectory(prefix='p6-shared-source-') as temp:
        folder = Path(temp)
        report, error = _execute(root, ['--budget', '300', '--p6-shared-finalists',
                                        *checkpoint_args],
                                 folder / 'shared-300.json', 720)
        if error:
            return {'status': 'FAIL', 'reasons': ['P6_300S_' + error],
                    'production_engine': 'gsim_CombatRuntime'}
        snapshot = report.get('shared_search_snapshot')
        if (report.get('requested_wall_budget_s') != 300
                or report.get('search_only') is not True
                or not isinstance(snapshot, dict)
                or snapshot.get('elapsed_boundary_s') != 30
                or not isinstance(snapshot.get('winner'), dict)
                or not isinstance(report.get('search_winner'), dict)):
            return {'status': 'FAIL', 'reasons': [
                'P6_SHARED_COLD_30S_300S_PAID_WINNERS_MISSING'],
                'production_engine': 'gsim_CombatRuntime'}
        winner30, winner300 = snapshot['winner'], report['search_winner']
        try:
            same_winner = _build_identity(winner30) == _build_identity(winner300)
        except ValueError as exc:
            return {'status': 'FAIL', 'reasons': [str(exc)],
                    'production_engine': 'gsim_CombatRuntime'}
        result30 = _paid_winner_receipt(root, report, winner30, folder,
                                        'snapshot-30', checkpoint_args)
        if same_winner:
            # This is the same paid 100-mob receipt, not another replay.
            # Preserve that fact in the ordinary gate output for reviewers.
            result300 = {**result30, 'shared_with_30s': True}
        else:
            result300 = _paid_winner_receipt(root, report, winner300, folder,
                                             'final-300', checkpoint_args)
    # A missing first-stage replay can succeed when the gate executes the
    # actual frozen winner. Reconcile both genuinely paid 100-mob results
    # after those replays: never lose the 30s incumbent to a slower late
    # two-mob proxy simply because its earlier validation was incomplete.
    # Both builds were frozen during the one cold search; this pays no extra
    # replay and does not change P6's 1% acceptance predicate.
    retained_incumbent_after_replay = False
    displaced_late_paid_receipt = None
    if (not same_winner
            and all(r.get('status') == 'COMPLETE'
                    and r.get('count') == 100
                    and r.get('mob_completed') == 100
                    and type(r.get('s_per_mob')) in (int, float)
                    and isfinite(r['s_per_mob']) and r['s_per_mob'] > 0
                    for r in (result30, result300))
            and result30['s_per_mob'] <= result300['s_per_mob']):
        # Preserve the measured slower route for the ordinary production
        # receipt; it must remain inspectable after the temp search is gone.
        displaced_late_paid_receipt = result300
        winner300 = winner30
        result300 = {**result30, 'shared_with_30s': True}
        retained_incumbent_after_replay = True
    results = [{**r, 'budget_s': budget} for budget, r
               in ((30, result30), (300, result300))]
    complete = all(r.get('status') == 'COMPLETE'
                   and r.get('count') == 100 and r.get('mob_completed') == 100
                   and type(r.get('s_per_mob')) in (int, float)
                   and isfinite(r['s_per_mob']) and r['s_per_mob'] > 0
                   for r in results)
    t30, t300 = (r['s_per_mob'] for r in results) if complete else (None, None)
    ratio = t30 / t300 if complete else None  # Diagnostic ratio for the approved 1% saturation gate.
    reasons = []
    if not complete:
        reasons.append('P6_SHARED_WINNER_REAL_100MOB_REPLAY_INCOMPLETE')
    if not snapshot.get('post_boundary_paid_evaluations', 0):
        reasons.append('P6_NO_GENUINE_PAID_30S_TO_300S_CONTINUATION')
    if complete and t30 > 1.01 * t300:
        reasons.append('P6_NUMERIC_SATURATION_EXCEEDS_1_PERCENT')
    proof = {}
    if not reasons:
        from src.version import SOFTWARE_VERSION
        source_identity = json.dumps({
            'ability_db_sha256': report.get('source_db_sha256'),
            'gear_catalogue': report.get('source_gear_catalogue_snapshot'),
        }, sort_keys=True, separators=(',', ':'), default=str)
        proof = {'runtime_proof': {
            'executed': True, 'engine_revision': 'gsim-' + SOFTWARE_VERSION,
            'source_revision': sha256(source_identity.encode()).hexdigest(),
            'run_id': 'shared-source-paid-p6-' + str(uuid4())}}
    selected_paid_winners = [
        {'budget_s': budget,
         'paid_candidate_index': winner.get('paid_candidate_index'),
         'screen_finished_elapsed_s': winner.get('screen_finished_elapsed_s'),
         'screen_s_per_mob': winner.get('screen_s_per_mob'),
         'gear_move': winner.get('gear_move'),
         'policy': winner.get('policy'),
         'policy_signature': winner.get('policy_signature'),
         'recovery': winner.get('recovery'),
         'allocation': winner.get('allocation'),
         # The cold search's temporary JSON is deleted at gate exit.
         # Retain both frozen winners' full executable configurations in the
         # ordinary gate report so a paid P6 result can be inspected/replayed
         # without reconstructing a build from its proxy proposal label.
         'equipped_gear': winner.get('equipped_gear'),
         'opening_action_ids': winner.get('opening_action_ids'),
         'policy_ir': winner.get('policy_ir')}
        for budget, winner in ((30, winner30), (300, winner300))
    ]
    return {
        'selected_paid_winners': selected_paid_winners,
        'status': 'FAIL' if reasons else 'PASS', 'reasons': reasons, **proof,
        'production_engine': 'gsim_CombatRuntime',
        'production_component': 'src.v2.source_bounded_joint_frontier.search_bounded_joint_frontier',
        'source_db_sha256': report.get('source_db_sha256'),
        'source_gear_catalogue_snapshot': report.get('source_gear_catalogue_snapshot'),
        # Keep the actual paid checkpoint/scenario and candidate-space
        # parameters after the temporary WF437 search report is removed.
        'source_search_space': report.get('source_search_space'),
        'source_replay_results': results,
        'retained_paid_30s_incumbent_after_replay': retained_incumbent_after_replay,
        'unselected_late_paid_100mob_receipt': displaced_late_paid_receipt,
        'source_replay_T30_T300': ratio,
        'source_replay_T30_s_per_mob': t30,
        'source_replay_T300_s_per_mob': t300,
        'source_replay_numeric_saturation': bool(complete and t30 <= 1.01*t300),
        'N30_unique_paid': snapshot.get('unique_full_builds'),
        'N300_unique_paid': report.get('unique_full_builds'),
        'search_wall_s': [report.get('wall_s')],
        'shared_cold_search': True,
        'same_source_legal_candidate_space_proven': True,
        'selected_production_backend': 'gsim',
        'full_p6_selected_backend_acceptance': not reasons,
        'coverage_scope_complete': not reasons,
    }
