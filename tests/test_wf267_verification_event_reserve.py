"""WF267: real-executor event reservation for mandatory scratch replays."""
from src.v2.source_stateful_budgeted import run_source_stateful_budgeted


def test_mage_event_cap_reserves_two_scratch_replays():
    result = run_source_stateful_budgeted(
        class_key='mage', level=20, max_l2_attempts=20,
        max_event_transitions=1500, use_l1=False, use_prefix_cache=False)
    assert result['event_transitions'] <= 1500
    assert result['verification_required'] == 2
    assert result['verification_completed'] == 2
    assert result['verification_complete']
    assert result['status'] == 'BEST_KNOWN_BOUNDED'
    assert all(x['matches_scratch'] for x in result['scratch_verification'])
    assert all(x['full_executor_events'] >= x['events'] for x in result['observations']
               if x.get('status') == 'FULL_L2_VERIFIED')


def test_druid_low_cap_reserves_scratch_without_score_shift():
    result = run_source_stateful_budgeted(
        class_key='druid', level=10, max_l2_attempts=20,
        max_event_transitions=500, use_l1=False, use_prefix_cache=False)
    assert result['event_transitions'] <= 500
    assert result['verification_complete']
    assert result['winner']['score_s_per_mob'] == 16.111809753559438


def test_cached_full_executor_count_not_cache_discounted():
    result = run_source_stateful_budgeted(
        class_key='druid', level=10, max_l2_attempts=20,
        max_event_transitions=1500, use_l1=False, use_prefix_cache=True)
    assert result['verification_complete']
    assert result['cache_hits_l2'] > 0
    assert any(x['full_executor_events'] > x['events'] for x in result['observations']
               if x.get('status') == 'FULL_L2_VERIFIED')


def test_no_verification_capacity_is_not_vacuously_verified():
    result = run_source_stateful_budgeted(
        class_key='druid', level=10, max_l2_attempts=2,
        max_event_transitions=500, use_l1=False)
    assert result['l2_evaluated'] > 0
    assert result['verification_required'] == 0
    assert not result['verification_complete']
    assert result['status'] == 'BEST_KNOWN_BOUNDED_UNVERIFIED'
