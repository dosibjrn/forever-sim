"""Work2 production paid-100mob receipt boundaries (not a gate PASS).

These negative controls isolate the common validation and saved-winner
selection logic. A separate sourced 100-mob CombatRuntime run remains
necessary to demonstrate P4/P5/P6 production acceptance.
"""
from copy import deepcopy

import pytest

from src.v2.source_bounded_joint_frontier import independently_compare_shortlist
from src.v2.source_paid_cold_comparison import _saved_winner


def _full_receipt(seconds=12.5, *, count=100, kills=100):
    return {'status': 'COMPLETE', 'count': count, 'mob_completed': kills,
            'mean_s_per_mob': seconds, 'events': 1400}


@pytest.mark.parametrize('bad_time', [
    -1.0, 0.0, float('nan'), float('inf'), -float('inf'),
    True, '12.5', None,
])
def test_common_paid_shortlist_rejects_invalid_completed_time(bad_time):
    screened = [{'id': '0', 'screen_s_per_mob': 4.0}]
    outcome = independently_compare_shortlist(
        screened, lambda _: _full_receipt(bad_time))
    assert outcome['status'] == 'INCOMPLETE_FULL_HORIZON_EVIDENCE'
    assert outcome['validated_winner_id'] is None
    assert outcome['complete_100mob_replays'] == 0
    assert outcome['rows'][0]['full_s_per_mob'] is None


@pytest.mark.parametrize('count,kills', [
    (99, 99), (100.0, 100), (True, 100), (100, 99), (100, 100.0),
])
def test_common_paid_shortlist_rejects_missing_or_false_kills(count, kills):
    screened = [{'id': '0', 'screen_s_per_mob': 4.0}]
    outcome = independently_compare_shortlist(
        screened, lambda _: _full_receipt(12.5, count=count, kills=kills))
    assert outcome['complete_100mob_replays'] == 0
    assert outcome['validated_winner_id'] is None


def test_common_paid_shortlist_keeps_real_positive_complete_ranking():
    rows = [{'id': '0', 'screen_s_per_mob': 4.0},
            {'id': '1', 'screen_s_per_mob': 5.0}]
    receipts = {'0': _full_receipt(14.0), '1': _full_receipt(12.0)}
    outcome = independently_compare_shortlist(
        rows, lambda row: receipts[row['id']])
    assert outcome['status'] == 'SEARCH_RANKING_REVERSAL'
    assert outcome['validated_winner_id'] == '1'
    assert outcome['complete_100mob_replays'] == 2


def _saved_source_report():
    return {
        'class_key': 'druid', 'level': 30,
        'source_db_sha256': 'test-source-sha',
        'search_only': True, 'complete_100mob_candidates': 0,
        'requested_wall_budget_s': 30, 'wall_s': 29.9,
        'validation_shortlist': [{
            'allocation': {}, 'equipped_gear': {},
            'opening_action_ids': [], 'policy_ir': {},
            'policy_signature': 'source-policy', 'recovery': 'always',
        }],
        'validation': {
            'validated_winner_id': '0',
            'rows': [{'id': '0', 'status': 'COMPLETE', 'count': 100,
                      'full_s_per_mob': 12.5}],
        },
    }


@pytest.mark.parametrize('bad_time', [
    -1.0, 0.0, float('nan'), float('inf'), -float('inf'),
    True, '12.5', None,
])
def test_saved_30s_winner_cannot_select_invalid_paid_time(bad_time):
    report = _saved_source_report()
    report['validation']['rows'][0]['full_s_per_mob'] = bad_time
    with pytest.raises(ValueError, match='COLD_COMPARISON_WINNER_NOT_100MOB_COMPLETE'):
        _saved_winner(report, expected_budget=30,
                      source_hash='test-source-sha', class_key='druid', level=30)


def test_saved_30s_winner_keeps_positive_receipt_and_full_source_build():
    report = _saved_source_report()
    selected = _saved_winner(report, expected_budget=30,
                            source_hash='test-source-sha', class_key='druid',
                            level=30)
    assert selected == deepcopy(report['validation_shortlist'][0])
