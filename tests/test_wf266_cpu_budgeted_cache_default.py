"""WF266 CPU-first cache policy; real source executor, no synthetic score."""
from src.v2.source_stateful_budgeted import run_source_stateful_budgeted

def test_default_disables_unproven_cpu_cache_and_preserves_full_score():
    args = dict(class_key="druid", level=10, max_l2_attempts=18,
                max_event_transitions=1500, use_l1=False)
    default = run_source_stateful_budgeted(**args)
    off = run_source_stateful_budgeted(**args, use_prefix_cache=False)
    on = run_source_stateful_budgeted(**args, use_prefix_cache=True)
    assert default["cache_entries"] == default["cache_hits_l2"] == 0
    assert default["event_transitions"] == off["event_transitions"]
    assert default["winner"]["score_s_per_mob"] == off["winner"]["score_s_per_mob"]
    assert on["cache_hits_l2"] > 0
    assert on["winner"]["score_s_per_mob"] == default["winner"]["score_s_per_mob"]
    assert all(x["matches_scratch"] for x in on["scratch_verification"])


def test_budget_aborted_runner_up_is_not_claimed_verified():
    result = run_source_stateful_budgeted(
        class_key="mage", level=20, max_l2_attempts=20,
        max_event_transitions=70, use_l1=False, use_prefix_cache=True)
    assert result["status"] == "BEST_KNOWN_BOUNDED_UNVERIFIED"
    assert result["verification_required"] == 1
    assert result["verification_completed"] == 0
    assert not result["verification_complete"]
    assert result["scratch_verification"] == []  # insufficient budget to replay

def test_full_scratch_equality_remains_authoritative():
    result = run_source_stateful_budgeted(
        class_key="druid", level=10, max_l2_attempts=20,
        max_event_transitions=1500, use_l1=False, use_prefix_cache=True)
    assert result["status"] == "BEST_KNOWN_BOUNDED"
    assert result["verification_complete"]
    assert result["verification_completed"] == result["verification_required"]
