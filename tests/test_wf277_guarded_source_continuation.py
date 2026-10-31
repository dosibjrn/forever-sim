"""WF277: real conditional continuation in the *same* budgeted L2 scorer.

The unverified Rogue finisher fixture deliberately removes a source blocker
only within the test. It is never a canonical or production combat result.
"""
from dataclasses import replace

from src.game.data.forever.registry import build_game_ir_slice
from src.v2.generic_backend import _policy_combat_evaluation
from src.v2.source_budgeted_prefix import PrefixCandidate, source_prefix_envelope
from src.v2.source_policy_search import _rule_options
from src.v2.source_stateful_budgeted import (
    _make_policy, _resource_flow_proxy, run_source_stateful_budgeted,
)


def test_real_druid_l10_guarded_continuation_changes_executed_actions_and_objective():
    ir = build_game_ir_slice(class_key='druid', level=10)
    moonfire = next(a for a in ir.actions if a.family_key == 'moonfire')
    guard = next(g for g in _rule_options(moonfire, ir.resources) if g)
    kwargs = dict(level=10, opening_action_ids=('wrath:5177',),
                  schedule_incoming_attacks=True)
    unguarded, unguarded_exec, _ = _policy_combat_evaluation(
        ir, policy_override=_make_policy(ir, 'wrath:5177'), **kwargs)
    guarded, guarded_exec, _ = _policy_combat_evaluation(
        ir, policy_override=_make_policy(ir, 'wrath:5177',
            guarded_action=moonfire.id, guarded_conditions=guard), **kwargs)
    assert unguarded.seconds_per_mob == 16.111809753559438
    assert guarded.seconds_per_mob == 16.129032258064516
    assert [x['action_id'] for x in unguarded_exec.selected_actions][:3] == ['wrath:5177'] * 3
    assert [x['action_id'] for x in guarded_exec.selected_actions][:3] == [
        'wrath:5177', 'moonfire:8924', 'wrath:5177']
    assert guarded_exec.timeline.target_defeated


def test_online_real_guarded_candidates_charge_budget_and_scratch_verify():
    result = run_source_stateful_budgeted(
        class_key='druid', level=10, max_l2_attempts=20,
        max_event_transitions=1800, use_l1=False,
        search_guarded_continuations=True)
    assert result['status'] == 'BEST_KNOWN_BOUNDED'
    assert result['guarded_continuation_options'] == 2
    assert result['seed_count'] == 24
    assert result['event_transitions'] <= 1800
    assert result['l2_attempts'] <= 20
    assert result['verification_complete']
    scored_guarded = [x for x in result['observations'] if x['tier'] == 'L2'
                      and x.get('guarded_action') == 'moonfire:8924'
                      and x['status'] == 'FULL_L2_VERIFIED']
    assert scored_guarded
    assert all(x['guarded_conditions'][0]['kind'] == 'aura_missing'
               for x in scored_guarded)
    assert result['winner']['score_s_per_mob'] == 16.111809753559438
    assert result['seed_unattempted'] > 0  # bounded, not a complete optimum


def test_source_finisher_thresholds_and_nonrepeatable_fallback_are_generic():
    ir = build_game_ir_slice(class_key='rogue', level=20)
    finisher = next(a for a in ir.actions if a.family_key == 'eviscerate')
    guards = _rule_options(finisher, ir.resources)
    assert [g[0].value for g in guards] == [1., 2., 3., 4., 5.]
    assert all(g[0].resource_id == 'combo_points' for g in guards)
    envelope = source_prefix_envelope(ir, level=20)
    assert finisher.id in envelope['actions']
    assert finisher.id not in envelope['fillers']
    # Target-bound resource gains are source-IR actor resources with target scope.
    candidate = PrefixCandidate(('sinister_strike:1758',), 'sinister_strike:1758')
    flow = _resource_flow_proxy(candidate, {a.id: a for a in ir.actions}, ir, 0)
    assert flow['end_resources_proxy']['combo_points'] == 1.
    assert flow['end_resources_proxy']['energy'] == 65.  # 100 - 45 + 10*1


def test_unverified_finisher_is_not_promoted_but_executor_can_use_synthetic_guard():
    ir = build_game_ir_slice(class_key='rogue', level=20)
    blocked = run_source_stateful_budgeted(
        class_key='rogue', level=20, max_l2_attempts=8,
        max_event_transitions=700, use_l1=False,
        search_guarded_continuations=True)
    assert blocked['guarded_continuation_options'] == 1
    assert blocked['source_actions'] == ['sinister_strike:1758']
    assert blocked['blocked_source_semantics'][0]['id'] == 'eviscerate:6761'
    # Synthetic fixture only: remove the AP-gap flag, never write to canonical DB.
    unverified = replace(ir, actions=tuple(
        replace(a, effects=(replace(a.effects[0], unsupported_semantics=()),
                            *a.effects[1:])) if a.family_key == 'eviscerate' else a
        for a in ir.actions))
    finisher = next(a for a in unverified.actions if a.family_key == 'eviscerate')
    guard = next(g for g in _rule_options(finisher, unverified.resources)
                 if g[0].value == 2.)
    result, execution, _ = _policy_combat_evaluation(
        unverified, level=20, policy_override=_make_policy(
            unverified, 'sinister_strike:1758',
            guarded_action=finisher.id, guarded_conditions=guard),
        opening_action_ids=('sinister_strike:1758',),
        schedule_incoming_attacks=True)
    assert result is not None and execution.timeline.target_defeated
    ids = [x['action_id'] for x in execution.selected_actions]
    assert ids[:3] == ['sinister_strike:1758', 'sinister_strike:1758', 'eviscerate:6761']
    assert result.seconds_per_mob > 0


def test_guarded_continuation_survives_action_id_rename_without_name_switch():
    ir = build_game_ir_slice(class_key='druid', level=10)
    moonfire = next(a for a in ir.actions if a.family_key == 'moonfire')
    renamed_id = 'source_generic_periodic_damage'
    renamed = replace(ir, actions=tuple(
        replace(a, id=renamed_id, name='Anonymous periodic attack')
        if a.id == moonfire.id else a for a in ir.actions),
        modes=tuple(replace(m, enabled_action_ids=tuple(
            renamed_id if aid == moonfire.id else aid for aid in m.enabled_action_ids))
            if m.enabled_action_ids is not None else m for m in ir.modes))
    renamed_action = next(a for a in renamed.actions if a.id == renamed_id)
    guard = next(g for g in _rule_options(renamed_action, renamed.resources) if g)
    result, execution, _ = _policy_combat_evaluation(
        renamed, level=10,
        policy_override=_make_policy(renamed, 'wrath:5177',
            guarded_action=renamed_id, guarded_conditions=guard),
        opening_action_ids=('wrath:5177',), schedule_incoming_attacks=True)
    assert result.seconds_per_mob == 16.129032258064516
    assert execution.selected_actions[1]['action_id'] == renamed_id


def test_guarded_policy_cached_dot_prefix_equals_scratch_with_full_event_queue():
    ir = build_game_ir_slice(class_key='druid', level=10)
    moon = next(a for a in ir.actions if a.family_key == 'moonfire')
    guard = next(g for g in _rule_options(moon, ir.resources) if g)
    cache = {}
    kwargs = dict(level=10, opening_action_ids=('moonfire:8924', 'wrath:5177'),
                  schedule_incoming_attacks=True)
    policy = _make_policy(ir, 'wrath:5177', guarded_action=moon.id,
                          guarded_conditions=guard)
    first, first_exec, first_details = _policy_combat_evaluation(
        ir, policy_override=_make_policy(ir, 'wrath:5177'),
        prefix_cache=cache, **kwargs)
    resumed, resumed_exec, resumed_details = _policy_combat_evaluation(
        ir, policy_override=policy, prefix_cache=cache, **kwargs)
    scratch, scratch_exec, scratch_details = _policy_combat_evaluation(
        ir, policy_override=policy, **kwargs)
    assert first is not None and resumed is not None and scratch is not None
    assert resumed_details['checkpoint_hit_length'] >= 1
    assert resumed.seconds_per_mob == scratch.seconds_per_mob
    assert resumed_exec.selected_actions == scratch_exec.selected_actions
    assert resumed_exec.timeline.target_death_s == scratch_exec.timeline.target_death_s
    assert resumed_details['event_transitions_new'] <= scratch_details['event_transitions_new']


def test_real_guarded_frontier_l1_is_partial_and_not_terminal_authority():
    result = run_source_stateful_budgeted(
        class_key='druid', level=10, max_l2_attempts=20,
        max_event_transitions=1800, use_l1=True,
        search_guarded_continuations=True)
    assert result['l1_attempts'] > 0
    assert result['l2_attempts'] > 0
    assert result['event_transitions'] <= 1800
    assert result['verification_complete']
    assert any(x['tier'] == 'L1' and x['status'] == 'PARTIAL_REAL_EXECUTOR'
               and 'score_s_per_mob' not in x for x in result['observations'])
    assert any(x['tier'] == 'L2' and x.get('guarded_action') == 'moonfire:8924'
               and x['status'] == 'FULL_L2_VERIFIED' for x in result['observations'])
