"""Regression: one P6 source search, paid snapshot, replay reuse and real 1% test."""
from pathlib import Path
from unittest.mock import patch

from tools.wf_gate_p6_full_source import run_full_source_comparison


def _winner(policy='a'):
    return dict(allocation={'point': 1}, equipped_gear={'slots': {}},
                opening_action_ids=[1], policy_ir={'policy': policy},
                policy_signature=policy, recovery='always')


def _report(*, final=None, snapshot=None, continuation=4):
    final = final or _winner('a')
    snapshot = snapshot or _winner('a')
    return {'requested_wall_budget_s': 300, 'search_only': True,
            'search_winner': final, 'source_db_sha256': 'pinned-source',
            'source_gear_catalogue_snapshot': {'catalogue_sha256': 'pinned'},
            'unique_full_builds': 12, 'wall_s': 299.,
            'shared_search_snapshot': {
                'elapsed_boundary_s': 30., 'winner': snapshot,
                'unique_full_builds': 4,
                'post_boundary_paid_evaluations': continuation},
            'validation_shortlist': [final],
            'validation': {'rows': [{'id': '0', 'status': 'COMPLETE',
                                     'count': 100, 'mob_completed': 100,
                                     'full_s_per_mob': 10., 'events': 200}]}}


def test_p6_one_cold_search_and_identical_paid_winner_reused():
    calls = []
    def execute(root, args, output, timeout):
        calls.append(args)
        return _report(), None
    with patch('tools.wf_gate_p6_full_source._execute', side_effect=execute):
        result = run_full_source_comparison(Path('.'), 'druid', 30)
    assert result['status'] == 'PASS'
    assert result['shared_cold_search'] is True
    assert len(calls) == 1 and calls[0][:2] == ['--budget', '300']
    assert result['source_replay_T30_T300'] == 1.
    assert all(row['count'] == 100 and row['reused']
               for row in result['source_replay_results'])


def test_p6_distinct_snapshot_pays_only_missing_winner_and_checks_1pct():
    calls = []
    def execute(root, args, output, timeout):
        calls.append(args)
        if '--budget' in args:
            return _report(snapshot=_winner('earlier')), None
        return {'validation': {'rows': [
            {'id': '0', 'status': 'COMPLETE', 'count': 100,
             'mob_completed': 100, 'full_s_per_mob': 10.2}]}}, None
    with patch('tools.wf_gate_p6_full_source._execute', side_effect=execute):
        result = run_full_source_comparison(Path('.'), 'druid', 30)
    assert len(calls) == 2
    assert calls[1][0] == '--replay-from'
    assert result['status'] == 'FAIL'
    assert result['reasons'] == ['P6_NUMERIC_SATURATION_EXCEEDS_1_PERCENT']
    assert result['source_replay_T30_T300'] == 1.02
    assert result['source_replay_results'][0]['reused'] is False
    assert result['source_replay_results'][1]['reused'] is True


def test_p6_missing_snapshot_never_substitutes_300s_winner():
    report = _report()
    report['shared_search_snapshot']['winner'] = None
    with patch('tools.wf_gate_p6_full_source._execute', return_value=(report, None)) as run:
        result = run_full_source_comparison(Path('.'), 'druid', 30)
    assert result['status'] == 'FAIL'
    assert 'P6_SHARED_COLD_30S_300S_PAID_WINNERS_MISSING' in result['reasons']
    assert run.call_count == 1


def test_p6_no_paid_continuation_never_passes():
    with patch('tools.wf_gate_p6_full_source._execute',
               return_value=(_report(continuation=0), None)):
        result = run_full_source_comparison(Path('.'), 'druid', 30)
    assert result['status'] == 'FAIL'
    assert 'P6_NO_GENUINE_PAID_30S_TO_300S_CONTINUATION' in result['reasons']


def test_p6_partial_100mob_cannot_pass_despite_positive_time():
    def execute(root, args, output, timeout):
        if '--budget' in args:
            return _report(snapshot=_winner('earlier')), None
        return {'validation': {'rows': [
            {'id': '0', 'status': 'COMPLETE', 'count': 99,
             'mob_completed': 99, 'full_s_per_mob': 9.}]}}, None
    with patch('tools.wf_gate_p6_full_source._execute', side_effect=execute):
        result = run_full_source_comparison(Path('.'), 'druid', 30)
    assert result['status'] == 'FAIL'
    assert 'P6_SHARED_WINNER_REAL_100MOB_REPLAY_INCOMPLETE' in result['reasons']
    assert result['source_replay_T30_T300'] is None
