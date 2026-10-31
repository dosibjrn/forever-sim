"""WF-GEN02b: sourced buttons are really executed, not merely discovered."""
from dataclasses import replace

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.model import PeriodicEffect
from src.v2.legal_candidate_enumeration import evaluate_source_candidate_envelope
from src.v2.source_button_discovery import discover_source_combat_buttons
from src.v2.source_policy_search import (
    evaluate_discovered_policy_search, synthesize_source_policies,
)


def test_mage_unseeded_buttons_are_in_actual_scored_policies():
    source = build_game_ir_slice(class_key='mage', level=10)
    canonical = {r.action_id for r in source.policies[0].rules}
    assert {'fireball:133', 'frost_nova:122'} <= set(
        discover_source_combat_buttons(source, level=10)['action_ids']) - canonical
    result = evaluate_discovered_policy_search(class_key='mage', level=10)
    assert result['candidate_count'] == result['evaluated_count'] + result['rejected_count']
    assert result['candidate_count'] > 2
    for action in ('fireball:133', 'frost_nova:122'):
        assert any(action in row['actions'] for row in [result['winner'], *result['alternatives']])
    assert result['winner']['seconds_per_mob'] > result['winner']['combat_kill_s']
    for unseeded in ('fireball:133', 'frost_nova:122'):
        assert any(unseeded == event['action_id'] for row in [result['winner'], *result['alternatives']]
                   for event in row['selected_actions'])
    assert not result['race_source_backed']
    assert not result['optimization_ready']
    assert not result['complete_optimizer']


def test_druid_periodic_aura_guard_synthesized_and_simulated():
    ir = build_game_ir_slice(class_key='druid', level=10)
    envelope = synthesize_source_policies(ir, level=10)
    guarded = [p for p in envelope['policies'] if any(
        r.action_id == 'moonfire:8924' and any(
            c.kind == 'aura_missing' and c.aura_id == 'moonfire:8924:aura'
            for c in r.conditions) for r in p.rules)]
    assert guarded
    result = evaluate_discovered_policy_search(class_key='druid', level=10)
    assert result['evaluated_count'] >= 2
    assert result['rejected_count'] >= 1  # periodic-only filler cannot kill consistently
    assert result['source_discovery']['semantic_warnings']  # approximate Wrath tuning
    assert result['race_source_backed']


def test_pure_dot_is_guarded_and_fidelity_warning_visible():
    ir = build_game_ir_slice(class_key='priest', level=10)
    candidates = synthesize_source_policies(ir, level=10)
    for policy in candidates['policies']:
        for rule in policy.rules:
            if rule.action_id == 'shadow_word_pain:594':
                assert any(c.kind == 'aura_missing' for c in rule.conditions)
    scored = evaluate_discovered_policy_search(class_key='priest', level=10)
    assert scored['evaluated_count'] == 2
    assert [a['action_id'] for a in scored['winner']['selected_actions']].count(
        'shadow_word_pain:594') == 1
    assert any(w['warning'].get('semantic') == 'periodic_crit'
               for w in scored['source_discovery']['semantic_warnings'])


def test_policy_synthesis_does_not_require_canonical_seed_or_named_class():
    mage = build_game_ir_slice(class_key='mage', level=10)
    first, second = mage.actions[:2]
    synthetic = replace(mage, id='synthetic:any:L10', policies=(), actions=(
        replace(first, id='alpha'), replace(second, id='beta'),
    ))
    generated = synthesize_source_policies(synthetic, level=10)
    assert generated['candidate_count'] > 1
    scored = evaluate_discovered_policy_search(class_key='any', level=10, ir_slice=synthetic)
    assert scored['evaluated_count'] > 1
    assert {'alpha', 'beta'} <= {a for p in [scored['winner'], *scored['alternatives']]
                                 for a in p['actions']}


def test_cap_fails_closed_not_truncated():
    ir = build_game_ir_slice(class_key='mage', level=10)
    with pytest.raises(ValueError, match='exceeds explicit bound'):
        synthesize_source_policies(ir, level=10, max_policies=2)
    with pytest.raises(ValueError, match='exceeds explicit bound'):
        evaluate_discovered_policy_search(class_key='mage', level=10, max_policies=2)


def test_source_requirements_are_honored_in_policy_generation():
    ir = build_game_ir_slice(class_key='mage', level=10)
    a = ir.actions[0]
    gated = replace(ir, actions=(replace(a, requirements=({'kind': 'minimum_level', 'value': 30},)),
                                 *ir.actions[1:]))
    e = synthesize_source_policies(gated, level=10)
    assert a.id not in e['eligible_buttons']
    assert all(a.id not in [r.action_id for r in p.rules] for p in e['policies'])


def test_missing_fallback_fails_closed():
    ir = build_game_ir_slice(class_key='priest', level=10)
    periodic_only = replace(ir, actions=(ir.actions[1],), policies=())
    with pytest.raises(ValueError, match='no safe sourced direct-damage fallback'):
        synthesize_source_policies(periodic_only, level=10)


def test_mode_with_unrestricted_action_ids_is_legal():
    ir = build_game_ir_slice(class_key='shaman', level=10)
    assert ir.modes[0].enabled_action_ids is None
    e = synthesize_source_policies(ir, level=10)
    assert 'lightning_bolt:529' in e['eligible_buttons']
    assert e['candidate_count'] >= 1


def test_periodic_without_aura_id_is_rejected_not_spammed():
    ir = build_game_ir_slice(class_key='priest', level=10)
    swp = ir.actions[1]
    dot = swp.effects[0]
    assert isinstance(dot, PeriodicEffect)
    bad = replace(ir, actions=(ir.actions[0], replace(swp, effects=(replace(dot, aura_id=''),))))
    e = synthesize_source_policies(bad, level=10)
    assert any(row['id'] == swp.id and row['reason'] == 'unsupported_periodic_condition'
               for row in e['excluded'])


def test_existing_druid_envelope_opt_in_real_discovered_scoring():
    old = evaluate_source_candidate_envelope(class_key='druid', level=10)
    new = evaluate_source_candidate_envelope(class_key='druid', level=10,
                                             include_discovered_policy_search=True)
    assert old['source_discovered_evaluated_count'] == 0
    assert new['source_discovered_evaluated_count'] > 0
    assert new['evaluated_count'] == old['evaluated_count'] + new['source_discovered_evaluated_count']
    assert new['mode_auto_attack_evaluated_count'] == old['mode_auto_attack_evaluated_count']
    assert not new['complete_optimizer']
