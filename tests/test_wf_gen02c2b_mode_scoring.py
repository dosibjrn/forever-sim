"""Source mode policies must pay for entry, fight, exit and recovery."""
from dataclasses import replace

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_button_discovery import discover_source_combat_buttons
from src.v2.source_mode_search import evaluate_discovered_mode_search


def _alter_action(ir, action_id, **changes):
    return replace(ir, actions=tuple(
        replace(action, **changes) if action.id == action_id else action
        for action in ir.actions))


def test_bear_l10_really_enters_swings_exits_and_recovers():
    result = evaluate_discovered_mode_search(class_key='druid', level=10)
    winner = result['winner']
    assert result['status'] == 'EVALUATED_SOURCE_MODE_POLICY'
    assert result['candidate_count'] == result['evaluated_count'] + result['rejected_count'] == 1
    assert winner['selected_actions'][0]['action_id'] == 'bear_form:5487'
    assert winner['auto_attack_damage'] > 0
    assert winner['entry_costs'][0]['amount'] > 0
    assert winner['post_combat_mode_actions'][0]['action_id'] == 'cancel_mode:bear'
    assert winner['recovery_mode_id'] == 'caster'
    assert winner['recovery_s'] > 0
    assert winner['seconds_per_mob'] > winner['combat_kill_s']
    assert not result['optimization_ready']


def test_paid_entry_cost_changes_actual_scored_recovery():
    ir = build_game_ir_slice(class_key='druid', level=10)
    paid = evaluate_discovered_mode_search(class_key='other', level=10, ir_slice=ir)['winner']
    free = evaluate_discovered_mode_search(
        class_key='other', level=10, ir_slice=_alter_action(ir, 'bear_form:5487', costs=()))['winner']
    assert paid['resources_after_combat']['mana'] < free['resources_after_combat']['mana']
    assert paid['recovery_s'] > free['recovery_s']
    assert paid['seconds_per_mob'] > free['seconds_per_mob']
    assert paid['combat_kill_s'] == free['combat_kill_s']


def test_sourced_cast_time_on_entry_is_paid():
    ir = build_game_ir_slice(class_key='druid', level=10)
    original = evaluate_discovered_mode_search(class_key='other', level=10, ir_slice=ir)['winner']
    timed = evaluate_discovered_mode_search(
        class_key='other', level=10, ir_slice=_alter_action(ir, 'bear_form:5487', cast_time_s=2.0))['winner']
    assert timed['combat_kill_s'] >= original['combat_kill_s'] + 2 - 1e-8
    assert timed['selected_actions'][0]['end_time_s'] == pytest.approx(2.0)


def test_paid_exit_is_not_a_free_recovery_reset():
    ir = build_game_ir_slice(class_key='druid', level=10)
    from src.game.model import ResourceCost
    paid_exit = _alter_action(ir, 'cancel_mode:bear', costs=(ResourceCost('mana', 1.0),))
    with pytest.raises(ValueError, match='no executable source mode policy'):
        evaluate_discovered_mode_search(class_key='other', level=10, ir_slice=paid_exit)


def test_missing_exit_or_unsupported_mode_fails_closed():
    ir = build_game_ir_slice(class_key='druid', level=10)
    no_exit = replace(ir, actions=tuple(a for a in ir.actions if a.id != 'cancel_mode:bear'))
    with pytest.raises(ValueError, match='no executable source mode policy'):
        evaluate_discovered_mode_search(class_key='other', level=10, ir_slice=no_exit)
    with pytest.raises(ValueError, match='source-defined'):
        discover_source_combat_buttons(ir, level=10, mode_id='nonexistent')


def test_cat_l20_sourced_claw_and_auto_compete_without_canonical_seed():
    ir = build_game_ir_slice(class_key='druid', level=20)
    synthetic = replace(ir, id='generic:renamed:L20', policies=())
    result = evaluate_discovered_mode_search(class_key='unregistered', level=20, ir_slice=synthetic)
    assert result['source_ir_id'] == synthetic.id
    assert result['candidate_count'] == result['evaluated_count'] + result['rejected_count']
    assert any(row['path']['combat_mode'] == 'cat' for row in [result['winner'], *result['alternatives']])
    assert any(row['path']['combat_mode'] == 'cat' and
               any(a['action_id'].startswith('claw:') for a in row['selected_actions'])
               for row in [result['winner'], *result['alternatives']])
    assert all(row['recovery_mode_id'] == row['path']['initial_mode']
               for row in [result['winner'], *result['alternatives']])


def test_explicit_mode_policy_cap_is_not_silent_truncation():
    ir = build_game_ir_slice(class_key='druid', level=20)
    with pytest.raises(ValueError, match='no executable source mode policy'):
        evaluate_discovered_mode_search(class_key='druid', level=20, ir_slice=ir,
                                        max_policies_per_path=1)
