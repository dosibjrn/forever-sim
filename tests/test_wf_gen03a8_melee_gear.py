"""Actual physical-stat gear is executable in the existing source-mode optimizer."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.game.data.forever.gear import available_gear_roles, select_named_gear
from src.game.data.forever.registry import build_game_ir_slice
from src.game.gear import apply_gear_selection, apply_stat_delta
from src.v2.source_joint_discovery import _gear_envelope, evaluate_bounded_joint_discovery
from src.v2.source_mode_search import evaluate_discovered_mode_search


def test_melee_stat_application_includes_source_derived_strength():
    ir = build_game_ir_slice(class_key='druid', level=20)
    changed, evidence = apply_gear_selection(ir, aggregate_stats={
        'agility': 13., 'attack_power': 19., 'strength': 11., 'spell_power': 7.})
    for stat, delta in [('agility', 13.), ('attack_power', 19.), ('strength', 11.), ('spell_power', 7.)]:
        assert changed.actor.base_stats[stat] == pytest.approx(ir.actor.base_stats.get(stat, 0.) + delta)
        assert evidence.applied_stats[stat] == delta
    assert 'strength' not in evidence.unsupported_stats
    from src.game.runtime import ActorState
    actor = ActorState.from_ir(changed.actor, changed.resources, changed.modes)
    actor.transition_mode('cat')
    assert actor.stats['attack_power'] == pytest.approx(36 + 13 + 19 + 11 * 2)
    perturbed = apply_stat_delta(ir, 'strength', 11.)
    actor = ActorState.from_ir(perturbed.actor, perturbed.resources, perturbed.modes)
    actor.transition_mode('cat')
    assert actor.stats['attack_power'] == pytest.approx(36 + 11 * 2)


def test_sourced_cat_combat_responds_to_melee_gear_without_class_branch():
    ir = build_game_ir_slice(class_key='druid', level=20)
    base = evaluate_discovered_mode_search(class_key='druid', level=20, ir_slice=ir)
    changed, _ = apply_gear_selection(ir, aggregate_stats={'agility': 30., 'attack_power': 40.})
    geared = evaluate_discovered_mode_search(class_key='druid', level=20, ir_slice=changed)
    assert geared['winner']['seconds_per_mob'] < base['winner']['seconds_per_mob']
    assert geared['winner']['auto_attack_damage'] > base['winner']['auto_attack_damage']


def test_search_discovers_source_equipment_and_melee_role_not_present_before():
    old = _gear_envelope('druid', 20, max_gear_candidates=128, gear_weight_order=2,
                         gear_weight_ratios=(.5, 1., 2.), required_level_policy='observed')
    new = _gear_envelope('druid', 20, max_gear_candidates=512, gear_weight_order=2,
                         gear_weight_ratios=(.5, 1., 2.), required_level_policy='observed',
                         include_melee_gear=True)
    assert {x['id'] for x in old} <= {x['id'] for x in new}
    assert len(new) > len(old)
    assert any(x['gear_role'] == 'druid_feral' for x in new)
    assert any(x['weight_vector'].get('agility') for x in new)
    assert any(x['weight_vector'].get('strength') for x in new)
    assert any(x['selection'].aggregate_stats.get('attack_power', 0) > 0 for x in new)
    assert all(item['required_level_origin'] == 'observed'
               for x in new for item in x['selection'].slots.values())


def test_existing_gear_role_validation_and_mage_cross_class():
    assert available_gear_roles('druid') == ('druid_balance', 'druid_feral', 'druid_bear')
    with pytest.raises(ValueError, match='no Forever generic gear role bridge'):
        select_named_gear(class_key='mage', level=20, stat_weights={'agility': 1.}, role='druid_feral')
    mage = _gear_envelope('mage', 20, max_gear_candidates=128, include_melee_gear=True,
                          required_level_policy='observed')
    assert mage and all(x['selection'].role == 'mage' for x in mage)


def test_joint_search_expanded_strength_gear_envelope_fails_closed_on_old_budget():
    # Adding an independently sourced Strength gear axis expands the legal
    # equipment envelope. The historical 1024-state cap is no longer enough;
    # reject rather than silently discard physical gear candidates.
    source = build_game_ir_slice(class_key='druid', level=20)
    # Reproduce the original .234 source-talent envelope for this gear-only regression.
    historical={'improved_wrath','ferocity','savage_fury','thick_hide'}
    frozen = replace(source, talents=tuple(t for t in source.talents if t.id in historical))
    with pytest.raises(ValueError, match='joint gear x talent state envelope exceeds explicit bound'):
        evaluate_bounded_joint_discovery(
            class_key='druid', level=20, ir_slice=frozen, gear_weight_order=2,
            gear_weight_ratios=(.5, 1., 2.), max_gear_candidates=512,
            max_states=1024, required_level_policy='observed', include_melee_gear=True)
