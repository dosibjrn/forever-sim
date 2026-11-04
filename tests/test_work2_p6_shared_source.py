"""Regression: one P6 cold search, paid snapshot, replay reuse and original 1% saturation."""
from pathlib import Path

import pytest
from unittest.mock import patch

from tools.wf_gate_p6_full_source import (run_full_source_comparison,
    _shared_replay_winners, _measured_best_frozen_winner)
from tools.wf_gate import _p6_replay_receipts


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
            'source_search_space': {'class_key': 'druid',
                                    'level': 30, 'pack_size': 2},
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
    assert len(calls) == 1 and calls[0][:3] == [
        '--budget', '300', '--p6-shared-finalists']
    assert result['source_replay_T30_T300'] == 1.
    assert all(row['count'] == 100 and row['reused']
               for row in result['source_replay_results'])
    # Both frozen points share ONE paid 100-mob result, not two executions.
    # Ensure the public no-record CLI keeps the fact and the 30/300 labels.
    receipts = _p6_replay_receipts(result)
    assert [row['budget_s'] for row in receipts] == [30, 300]
    assert [row['reused'] for row in receipts] == [True, True]
    assert 'shared_with_30s' not in receipts[0]
    assert receipts[1]['shared_with_30s'] is True
    # The paid cold report lives in a temporary directory. Both P6 winners
    # must retain their actual executable builds in the public gate result.
    for frozen in result['selected_paid_winners']:
        assert frozen['allocation'] == _winner()['allocation']
        assert frozen['equipped_gear'] == _winner()['equipped_gear']
        assert frozen['opening_action_ids'] == _winner()['opening_action_ids']
        assert frozen['policy_ir'] == _winner()['policy_ir']


def test_p6_paid_replay_recovers_faster_30s_incumbent_after_incomplete_validation():
    """Missing first-stage 30s receipt can recover without a second cold run."""
    calls = []
    def execute(root, args, output, timeout):
        calls.append(args)
        if '--budget' in args:
            # First-stage search only has the late completed 100-mob route:
            # the 30s candidate's initial replay was incomplete.
            return _report(snapshot=_winner('earlier')), None
        # Existing paid gate replay now successfully completes the 30s route.
        return {'validation': {'rows': [
            {'id': '0', 'status': 'COMPLETE', 'count': 100,
             'mob_completed': 100, 'full_s_per_mob': 9.8}]}}, None
    with patch('tools.wf_gate_p6_full_source._execute', side_effect=execute):
        result = run_full_source_comparison(Path('.'), 'druid', 30)
    assert len(calls) == 2
    assert calls[1][0] == '--replay-from'
    assert result['status'] == 'PASS'
    assert result['reasons'] == []
    assert result['source_replay_T30_T300'] == 1.
    assert result['source_replay_numeric_saturation'] is True
    assert result['source_replay_results'][0]['reused'] is False
    assert result['source_replay_results'][1]['shared_with_30s'] is True
    assert result['retained_paid_30s_incumbent_after_replay'] is True
    assert result['unselected_late_paid_100mob_receipt']['s_per_mob'] == 10.
    assert result['unselected_late_paid_100mob_receipt']['count'] == 100
    # The final 300s build is the genuine paid retained incumbent, not a
    # late two-mob proxy that took 10 s/mob on its paid 100-mob route.
    assert [x['policy_ir'] for x in result['selected_paid_winners']] == [
        _winner('earlier')['policy_ir'], _winner('earlier')['policy_ir']]


def test_p6_original_saturation_rejects_large_improvement():
    """Restore the original asymmetric T30 <= 1.01*T300 predicate."""
    def execute(root, args, output, timeout):
        if '--budget' in args:
            return _report(snapshot=_winner('earlier')), None
        return {'validation': {'rows': [{
            'id': '0', 'status': 'COMPLETE', 'count': 100,
            'mob_completed': 100, 'full_s_per_mob': 12.0}]}}, None
    with patch('tools.wf_gate_p6_full_source._execute', side_effect=execute):
        result = run_full_source_comparison(Path('.'), 'druid', 30)
    assert result['status'] == 'FAIL'
    assert 'P6_NUMERIC_SATURATION_EXCEEDS_1_PERCENT' in result['reasons']
    assert result['source_replay_T30_T300'] == 1.2
    assert result['source_replay_numeric_saturation'] is False


def test_p6_300s_slightly_slower_within_one_percent_is_allowed():
    """100-mob timing noise within 1% must not reject a longer search."""
    def execute(root, args, output, timeout):
        if '--budget' in args:
            return _report(snapshot=_winner('earlier')), None
        return {'validation': {'rows': [{
            'id': '0', 'status': 'COMPLETE', 'count': 100,
            'mob_completed': 100, 'full_s_per_mob': 9.95}]}}, None
    with patch('tools.wf_gate_p6_full_source._execute', side_effect=execute):
        result = run_full_source_comparison(Path('.'), 'druid', 30)
    assert result['status'] == 'PASS'
    assert result['source_replay_T30_T300'] == 1.
    assert result['source_replay_numeric_saturation'] is True
    assert result['source_replay_results'][1]['shared_with_30s'] is True


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


def test_p6_only_selected_30s_and_300s_full_builds_need_real_replay():
    report = _report(snapshot=_winner('early'))
    # Extra highly ranked proxy finalists are NOT P6-selected builds and
    # should never incur another 100-mob production replay.
    report['validation_shortlist'] = [
        _winner('unselected-' + str(index)) for index in range(20)]
    winners = _shared_replay_winners(report)
    assert [w['policy_signature'] for w in winners] == ['early', 'a']


def test_p6_identical_frozen_build_pays_one_shared_100mob_replay():
    assert len(_shared_replay_winners(_report())) == 1


def test_p6_missing_frozen_snapshot_does_not_forge_30s_winner():
    report = _report()
    report['shared_search_snapshot']['winner'] = None
    assert [w['policy_signature'] for w in _shared_replay_winners(report)] == ['a']


def test_p6_l40_runs_selected_checkpoint_without_a_second_search():
    report = _report()
    report['source_search_space']['level'] = 40
    calls = []
    def execute(root, args, output, timeout):
        calls.append(args)
        return report, None
    with patch('tools.wf_gate_p6_full_source._execute', side_effect=execute):
        result = run_full_source_comparison(Path('.'), 'druid', 40)
    assert result['status'] == 'PASS'
    assert len(calls) == 1
    assert calls[0][-6:] == [
        '--checkpoint-class', 'druid', '--checkpoint-level', '40',
        '--checkpoint-spec', 'unrestricted']
    assert result['source_search_space'] == report['source_search_space']
    assert len(result['selected_paid_winners']) == 2


def test_p6_incomplete_unselected_row_cannot_crash_selected_paid_replay():
    report = _report(snapshot=_winner('early'))
    report['validation_shortlist'] = [{'allocation': {'preview': 1}}]
    calls = []
    def execute(root, args, output, timeout):
        calls.append(args)
        if '--budget' in args:
            return report, None
        return {'validation': {'rows': [{
            'id': '0', 'status': 'COMPLETE', 'count': 100,
            'mob_completed': 100, 'full_s_per_mob': 10.}]}}, None
    with patch('tools.wf_gate_p6_full_source._execute', side_effect=execute):
        result = run_full_source_comparison(Path('.'), 'druid', 40)
    assert result['status'] == 'PASS'
    assert len(calls) == 3
    assert sum(args[0] == '--replay-from' for args in calls) == 2
    assert all(row['reused'] is False for row in result['source_replay_results'])


def test_measured_100mob_frozen_best_of_keeps_faster_early_incumbent():
    """Late proxy rank is not an actual 100-mob search objective."""
    report = _report(final=_winner('late'), snapshot=_winner('early'))
    candidates = [report['shared_search_snapshot']['winner'],
                  report['search_winner']]
    # Late proxy was ranked first by the search, but early is genuinely
    # faster on the completed paid 100-mob objective.
    receipt = {'rows': [
        {'id': '0', 'status': 'COMPLETE', 'count': 100,
         'mob_completed': 100, 'full_s_per_mob': 7.},
        {'id': '1', 'status': 'COMPLETE', 'count': 100,
         'mob_completed': 100, 'full_s_per_mob': 9.},
    ]}
    winner = _measured_best_frozen_winner(report, candidates, receipt)
    assert winner['policy_signature'] == 'early'


def test_measured_100mob_frozen_best_of_promotes_genuine_late_improvement():
    report = _report(final=_winner('late'), snapshot=_winner('early'))
    candidates = [report['shared_search_snapshot']['winner'],
                  report['search_winner']]
    receipt = {'rows': [
        {'id': '0', 'status': 'COMPLETE', 'count': 100,
         'mob_completed': 100, 'full_s_per_mob': 9.},
        {'id': '1', 'status': 'COMPLETE', 'count': 100,
         'mob_completed': 100, 'full_s_per_mob': 7.},
    ]}
    winner = _measured_best_frozen_winner(report, candidates, receipt)
    assert winner['policy_signature'] == 'late'


def test_measured_100mob_frozen_best_of_never_promotes_unpaid_or_partial():
    report = _report(final=_winner('late'), snapshot=_winner('early'))
    candidates = [report['shared_search_snapshot']['winner'],
                  report['search_winner']]
    receipt = {'rows': [
        {'id': '0', 'status': 'COMPLETE', 'count': 99,
         'mob_completed': 99, 'full_s_per_mob': 1.},
        {'id': '1', 'status': 'COMPLETE', 'count': 100,
         'mob_completed': 100, 'full_s_per_mob': 8.},
    ]}
    assert _measured_best_frozen_winner(
        report, candidates, receipt)['policy_signature'] == 'late'
    receipt['rows'][1]['id'] = '0'  # Wrong candidate/receipt identity.
    assert _measured_best_frozen_winner(report, candidates, receipt) is None
    receipt['rows'][1]['id'] = '1'
    receipt['rows'][1]['status'] = 'FAIL'
    assert _measured_best_frozen_winner(report, candidates, receipt) is None
