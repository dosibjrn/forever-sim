"""Real Forever executor, not a synthetic scorer."""
from dataclasses import replace

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.v2.generic_backend import _policy_combat_evaluation
from src.v2.source_stateful_budgeted import _make_policy, run_source_stateful_budgeted


def _druid_pair():
    ir = build_game_ir_slice(class_key='druid', level=10)
    return ir, _make_policy(ir, 'wrath:5177'), ('moonfire:8924', 'wrath:5177')


def test_actual_partial_rollout_preserves_queue_auras_resources():
    ir, policy, prefix = _druid_pair()
    cache = {}
    score, execution, details = _policy_combat_evaluation(
        ir, level=10, policy_override=policy, opening_action_ids=prefix,
        schedule_incoming_attacks=True, prefix_cache=cache,
        stop_after_opening_actions=1)
    assert score is None
    assert execution.stopped_reason == 'PARTIAL_OPENING_CHECKPOINT'
    assert details['status'] == 'PARTIAL_REAL_EXECUTOR'
    assert details['terminal_objective'] is None
    assert details['remaining_queue_events'] > 0
    assert details['active_target_auras']
    assert details['actor_resources']['mana'] < 259
    assert len(cache) == 1


def test_resumed_vs_scratch_exact_timeline_and_recovery():
    ir, policy, prefix = _druid_pair()
    cache = {}
    _policy_combat_evaluation(ir, level=10, policy_override=policy,
                              opening_action_ids=prefix, schedule_incoming_attacks=True,
                              prefix_cache=cache, stop_after_opening_actions=1)
    resumed, re, rd = _policy_combat_evaluation(ir, level=10, policy_override=policy,
        opening_action_ids=prefix, schedule_incoming_attacks=True, prefix_cache=cache)
    scratch, se, sd = _policy_combat_evaluation(ir, level=10, policy_override=policy,
        opening_action_ids=prefix, schedule_incoming_attacks=True)
    assert rd['checkpoint_hit_length'] == 1
    assert rd['event_transitions_new'] < sd['event_transitions_new']
    assert resumed.seconds_per_mob == scratch.seconds_per_mob
    assert re.timeline.as_dict() == se.timeline.as_dict()
    assert rd['recovery'] == sd['recovery']
    assert re.selected_actions == se.selected_actions


def test_exact_checkpoint_context_invalidation_for_source_gear_and_scenario():
    ir, policy, prefix = _druid_pair()
    cache = {}
    _policy_combat_evaluation(ir, level=10, policy_override=policy,
        opening_action_ids=prefix, prefix_cache=cache, stop_after_opening_actions=1)
    original, _, details = _policy_combat_evaluation(ir, level=10,
        policy_override=policy, opening_action_ids=prefix, prefix_cache=cache)
    assert details['checkpoint_hit_length'] == 1
    altered = replace(ir, actor=replace(ir.actor, base_stats={**ir.actor.base_stats, 'spell_power': 20.0}))
    _, _, changed = _policy_combat_evaluation(altered, level=10,
        policy_override=policy, opening_action_ids=prefix, prefix_cache=cache)
    assert changed['checkpoint_hit_length'] == 0
    assert changed['checkpoint_context'] != details['checkpoint_context']
    _, _, incoming = _policy_combat_evaluation(ir, level=10,
        policy_override=policy, opening_action_ids=prefix, prefix_cache=cache,
        schedule_incoming_attacks=True)
    assert incoming['checkpoint_hit_length'] == 0
    assert incoming['checkpoint_context'] != details['checkpoint_context']
    source = replace(ir, actor=replace(ir.actor, metadata={**ir.actor.metadata, 'build': 'other'}))
    _, _, changed_source = _policy_combat_evaluation(source, level=10,
        policy_override=policy, opening_action_ids=prefix, prefix_cache=cache)
    assert changed_source['checkpoint_hit_length'] == 0


def test_hard_event_budget_aborts_before_exceeding_limit():
    for cap in (1, 3, 8, 20, 80):
        r = run_source_stateful_budgeted(class_key='druid', level=10,
            max_l2_attempts=12, max_event_transitions=cap)
        assert r['event_transitions'] <= cap
        assert r['l2_attempts'] <= 12
        assert r['l1_attempts'] >= 1
    ir, policy, prefix = _druid_pair()
    from src.game.runtime.simulator import EventTransitionBudgetExceeded
    with pytest.raises(EventTransitionBudgetExceeded) as exc:
        _policy_combat_evaluation(ir, level=10, policy_override=policy,
            opening_action_ids=prefix, max_new_event_transitions=2)
    assert exc.value.events_processed == 2


def test_real_l0_l1_l2_and_blocked_unmodeled_semantics():
    r = run_source_stateful_budgeted(class_key='druid', level=10, max_l2_attempts=12, use_prefix_cache=True)
    assert r['seed_count'] == 12
    assert r['blocked_source_semantics']
    assert all(x['reason'] == 'BLOCKED_UNMODELED_SOURCE_SEMANTICS' for x in r['blocked_source_semantics'])
    assert r['l0_candidates_generated'] >= r['seed_count']
    assert r['l1_attempts'] > 0 and r['l2_attempts'] == 12
    assert r['l2_evaluated'] > 0
    assert r['winner']['survived']
    assert r['winner']['score_s_per_mob'] > 0
    assert r['cache_hits_l2'] > 0
    assert r['event_transitions'] > 0
    assert all(x['tier'] == 'L2' for x in [r['winner'], r['runner_up']])
    assert any(x['tier'] == 'L1' and x['status'] == 'PARTIAL_REAL_EXECUTOR' for x in r['observations'])
    assert all('l0_error_s' in x for x in r['predictions'])


def test_online_next_expensive_call_changes_after_real_feedback():
    hits = run_source_stateful_budgeted(class_key='druid', level=10,
        max_l2_attempts=16, schedule_incoming_attacks=True)
    no_hits = run_source_stateful_budgeted(class_key='druid', level=10,
        max_l2_attempts=16, schedule_incoming_attacks=False)
    ha = [(x['prefix'], x['fallback']) for x in hits['observations'] if x['tier'] == 'L2']
    na = [(x['prefix'], x['fallback']) for x in no_hits['observations'] if x['tier'] == 'L2']
    assert ha[:5] == na[:5] and ha[6:] != na[6:]  # feedback affects later L2 scheduling
    assert hits['winner']['score_s_per_mob'] != no_hits['winner']['score_s_per_mob']


def test_cross_class_real_mage_and_negative_ir_mismatch():
    r = run_source_stateful_budgeted(class_key='mage', level=20, max_l2_attempts=6)
    assert r['l2_evaluated'] > 0
    assert r['winner']['score_s_per_mob'] > 0
    assert r['source_context'] != run_source_stateful_budgeted(
        class_key='druid', level=10, max_l2_attempts=2)['source_context']
    ir = build_game_ir_slice(class_key='druid', level=10)
    with pytest.raises(ValueError, match='class/level mismatch'):
        run_source_stateful_budgeted(class_key='mage', level=10,
                                     ir_slice=ir, max_l2_attempts=1)


def test_cpu_and_walltime_guards_stop_future_expensive_calls():
    from src.game.runtime.simulator import ComputeDeadlineExceeded
    ir, policy, prefix = _druid_pair()
    from time import process_time_ns, monotonic_ns
    with pytest.raises(ComputeDeadlineExceeded) as cpu:
        _policy_combat_evaluation(ir, level=10, policy_override=policy,
            opening_action_ids=prefix, cpu_deadline_ns=process_time_ns() - 1)
    assert cpu.value.kind == 'CPU'
    with pytest.raises(ComputeDeadlineExceeded) as wall:
        _policy_combat_evaluation(ir, level=10, policy_override=policy,
            opening_action_ids=prefix, wall_deadline_ns=monotonic_ns() - 1)
    assert wall.value.kind == 'WALL'
    for mode in ({'max_cpu_ns': 1}, {'max_wall_ns': 1}):
        r = run_source_stateful_budgeted(class_key='druid', level=10,
            max_l2_attempts=12, **mode)
        assert r['l2_attempts'] == 0
        assert r['event_transitions'] == 0


def test_partial_predictor_cost_aware_fallback_keeps_l2_authority():
    r = run_source_stateful_budgeted(class_key='druid', level=10,
                                     max_l2_attempts=24, max_event_transitions=1000)
    assert r['winner']['score_s_per_mob'] > 0
    assert r['scratch_verification']
    assert all(x['matches_scratch'] for x in r['scratch_verification'])
    assert any(x.get('status') == 'L1_SKIPPED_COST_AWARE' for x in r['observations'])
    assert r['l1_attempts'] < r['l2_attempts']
