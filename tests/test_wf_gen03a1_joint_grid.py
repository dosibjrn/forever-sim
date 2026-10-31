"""WF-GEN03a1: actual source gear/talent/policy re-evaluation; not full D0."""
from dataclasses import replace

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talents import validate_talent_selection
from src.v2.source_joint_discovery import evaluate_bounded_joint_discovery


@pytest.fixture(scope='module')
def result():
    # Historical 255-state regression fixture, not current complete talent scope.
    ir = build_game_ir_slice(class_key='druid', level=20)
    old_ir = replace(ir, talents=tuple(t for t in ir.talents if t.id in ('improved_wrath', 'ferocity', 'savage_fury', 'thick_hide')))
    return evaluate_bounded_joint_discovery(class_key='druid', level=20, ir_slice=old_ir)


def test_source_only_real_joint_grid_executes_and_reports_scope(result):
    assert result['status'] == 'EVALUATED_BOUNDED_JOINT_GRID'
    assert not result['optimization_ready'] and not result['full_fixed_point']
    assert result['gear_candidate_count'] == 5
    assert result['executable_talent_candidate_count'] == 51
    assert result['evaluated_state_count'] == 255
    assert result['generated_policy_count'] >= result['evaluated_policy_count'] > 30
    assert result['winner']['score_s_per_mob'] > 0
    assert result['winner']['best_policy']['selected_actions']
    assert result['winner']['best_policy']['recovery_s'] >= 0
    assert 'all_legal_gear_combinations' in result['missing']
    assert not result['gear_acquisition_verified']
    assert not result['all_talents_represented']


def test_real_gear_reoptimization_can_flip_policy_at_same_talents(result):
    # No injected reference or expected policy. The genuine L20 source state
    # finds caster Wrath with spell-power gear and Cat with spirit gear.
    empty = [x for x in [result['winner'], *result['alternatives']]
             if x['talent_id'] == 'talents:none']
    by_axis = {next(iter(x['gear_weight_vector'])): x for x in empty
               if len(x['gear_weight_vector']) == 1}
    assert by_axis['spell_power']['best_policy']['branch'] == 'caster'
    assert by_axis['spirit']['best_policy']['branch'] == 'mode'
    assert by_axis['spirit']['best_policy']['combat_mode'] == 'cat'
    assert result['policy_changed_across_gear_at_fixed_talents']
    assert by_axis['spell_power']['score_s_per_mob'] < by_axis['spirit']['score_s_per_mob']


def test_real_talent_changes_runtime_and_reoptimizes_policy(result):
    rows = [result['winner'], *result['alternatives']]
    spell_power = [x for x in rows if x['gear_weight_vector'] == {'spell_power': 1.0}]
    naked_talents = next(x for x in spell_power if x['talent_id'] == 'talents:none')
    selected = next(x for x in spell_power if x['talent_id'] == 'talents:improved_wrath=5')
    assert selected['score_s_per_mob'] < naked_talents['score_s_per_mob']
    assert selected['best_policy']['selected_actions'][0]['action_id'].startswith('wrath:')
    assert selected['talents']['applied_modifiers']
    assert selected['talents']['spent_points'] == 5
    assert selected['talents']['available_points'] == 11  # incomplete talent tree, not DONE


def test_winner_has_named_sourced_legal_items_and_inspectable_rotation(result):
    source = build_game_ir_slice(class_key='druid', level=20)
    winner = result['winner']
    validate_talent_selection(source, winner['talents']['selection'], level=20)
    assert len(winner['gear_slots']) >= 10
    for slot, item in winner['gear_slots'].items():
        assert slot and isinstance(item['item_id'], int) and item['name']
        assert item['source_type'] and item['source']
        assert item['effective_level'] is None or item['effective_level'] <= 20
    assert winner['best_policy']['policy']['rules']
    assert all('action_id' in row for row in winner['best_policy']['selected_actions'])
    # Unsupported stats are explicit when present; newer engines may support
    # every stat in this historical gear envelope.
    assert isinstance(winner['gear_unsupported_stats'], dict)


def test_canonical_policy_not_a_search_hint(result):
    source = build_game_ir_slice(class_key='druid', level=20)
    fake_policy = replace(source.policies[0], id='reference-cannot-be-used')
    poisoned = replace(source, policies=(fake_policy,))
    old_ir = replace(poisoned, talents=tuple(t for t in poisoned.talents if t.id in ('improved_wrath', 'ferocity', 'savage_fury', 'thick_hide')))
    other = evaluate_bounded_joint_discovery(class_key='druid', level=20, ir_slice=old_ir)
    assert other['winner']['score_s_per_mob'] == pytest.approx(result['winner']['score_s_per_mob'])
    assert 'reference-cannot-be-used' not in other['winner']['best_policy']['policy_id']


@pytest.mark.parametrize('kwargs,match', [
    ({'max_gear_candidates': 1}, 'gear candidate envelope'),
    ({'max_talent_candidates': 1}, 'talent candidate envelope'),
    ({'max_states': 29}, 'joint gear x talent state envelope'),
    ({'max_states': 0}, 'caps must be positive'),
    ({'max_policies_per_path': 1}, 'source policy envelope exceeds explicit bound'),
])
def test_budget_caps_fail_closed(kwargs, match):
    ir=build_game_ir_slice(class_key='druid', level=20)
    old_ir=replace(ir,talents=tuple(t for t in ir.talents if t.id in ('improved_wrath', 'ferocity', 'savage_fury', 'thick_hide')))
    with pytest.raises(ValueError, match=match):
        evaluate_bounded_joint_discovery(class_key='druid', level=20, ir_slice=old_ir, **kwargs)


def test_wrong_source_actor_fails_closed():
    ir = build_game_ir_slice(class_key='druid', level=20)
    actor = replace(ir.actor, metadata={**ir.actor.metadata, 'class_key': 'mage'})
    with pytest.raises(ValueError, match='class/level'):
        evaluate_bounded_joint_discovery(class_key='druid', level=20, ir_slice=replace(ir, actor=actor))


def test_missing_source_fails_closed():
    with pytest.raises(ValueError, match='no source-backed IR'):
        evaluate_bounded_joint_discovery(class_key='hunter', level=20)


def test_cross_class_missing_gear_bridge_fails_closed():
    with pytest.raises(ValueError, match='no Forever generic gear role bridge'):
        evaluate_bounded_joint_discovery(class_key='warlock', level=20)


def test_cross_class_policy_envelope_fails_closed_not_silently_pruned():
    with pytest.raises(ValueError, match='source policy envelope exceeds explicit bound'):
        evaluate_bounded_joint_discovery(class_key='mage', level=20)


def test_readable_report_exposes_all_three_decisions(result):
    from tools.run_source_joint_discovery import render
    rendered = render(result)
    assert '## Rotation / policy' in rendered
    assert '## Talents' in rendered
    assert '## Gear' in rendered
    assert '## Top alternative joint states' in rendered
    assert 'NOT full optimization / NOT DONE' in rendered
    assert 'Wrath' in rendered


def test_current_heart_expanded_universe_fails_closed_on_old_joint_budget():
    with pytest.raises(ValueError, match='talent candidate envelope'):
        evaluate_bounded_joint_discovery(class_key='druid', level=20)
