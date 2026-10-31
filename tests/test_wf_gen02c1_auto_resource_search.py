"""WF-GEN02c1: opt-in sourced auto fallback and resource actions, no class scorer."""
from dataclasses import replace

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.model import ResourceChangeEffect
from src.v2.source_button_discovery import discover_source_combat_buttons
from src.v2.source_policy_search import synthesize_source_policies, evaluate_discovered_policy_search


def _rows(result):
    return [result['winner'], *result['alternatives']]


def test_warrior_auto_fallback_and_sourced_rage_actions_really_execute():
    result = evaluate_discovered_policy_search(
        class_key='warrior', level=10, include_auto_resource_fallback=True)
    assert result['candidate_count'] == result['evaluated_count'] + result['rejected_count']
    assert result['source_discovery']['auto_attack_fallback_ids'] == ['warrior:auto:mainhand']
    assert result['winner']['auto_attack_damage'] > 0
    assert result['winner']['seconds_per_mob'] > 0
    assert any(row['actions'] == [] and row['auto_attack_damage'] > 0 for row in _rows(result))
    rage = [row for row in _rows(result) if {'bloodrage:2687', 'rend:6546'} <= set(row['actions'])]
    assert rage
    assert any({'bloodrage:2687', 'rend:6546'} <= {a['action_id'] for a in row['selected_actions']}
               for row in rage)
    assert any(row['recovery_s'] > 0 for row in rage)  # health cost is not free
    assert not result['optimization_ready']


def test_rogue_auto_energy_combo_and_target_resource_requirement_execute():
    result = evaluate_discovered_policy_search(
        class_key='rogue', level=10, include_auto_resource_fallback=True)
    assert {'sinister_strike:1757', 'eviscerate:6760'} <= set(result['source_discovery']['eligible_buttons'])
    assert result['winner']['auto_attack_damage'] > 0
    combos = [row for row in _rows(result) if {'sinister_strike:1757', 'eviscerate:6760'} <= set(row['actions'])]
    assert combos
    assert any({'sinister_strike:1757', 'eviscerate:6760'} <= {a['action_id'] for a in row['selected_actions']}
               for row in combos)
    assert any(row['ending_resources']['energy'] < 100 for row in combos)


def test_no_seed_and_no_named_class_for_auto_resource_policy():
    source = build_game_ir_slice(class_key='rogue', level=10)
    synthetic = replace(source, id='generic:unknown:scenario', policies=())
    result = evaluate_discovered_policy_search(class_key='unknown', level=10, ir_slice=synthetic,
                                               include_auto_resource_fallback=True)
    assert result['evaluated_count'] >= 3
    assert result['winner']['auto_attack_damage'] > 0
    assert result['source_ir_id'] == synthetic.id


def test_existing_offensive_scope_unchanged_without_opt_in():
    rogue = build_game_ir_slice(class_key='rogue', level=10)
    with pytest.raises(ValueError, match='no safe sourced direct-damage fallback'):
        synthesize_source_policies(rogue, level=10)
    priest = build_game_ir_slice(class_key='priest', level=10)
    before = synthesize_source_policies(priest, level=10)
    assert before['candidate_count'] == 2
    assert before['auto_attack_fallback_ids'] == []


def test_auto_fallback_fails_closed_when_auto_unavailable():
    source = build_game_ir_slice(class_key='warrior', level=10)
    no_auto = replace(source, auto_attacks=())
    with pytest.raises(ValueError, match='no safe sourced direct-damage fallback or eligible auto attack'):
        synthesize_source_policies(no_auto, level=10, include_auto_resource_fallback=True)
    wrong_mode = replace(source, auto_attacks=(replace(source.auto_attacks[0], required_mode_id='not_active'),))
    with pytest.raises(ValueError, match='no safe sourced direct-damage fallback or eligible auto attack'):
        synthesize_source_policies(wrong_mode, level=10, include_auto_resource_fallback=True)


def test_resource_requirement_invalid_or_unknown_stays_excluded():
    rogue = build_game_ir_slice(class_key='rogue', level=10)
    finisher = rogue.actions[1]
    invalid = replace(finisher, requirements=({'kind': 'resource_min', 'resource_id': 'fake', 'value': 1},))
    ir = replace(rogue, actions=(rogue.actions[0], invalid))
    discovery = discover_source_combat_buttons(ir, level=10, include_resource_actions=True)
    assert {'id': invalid.id, 'reason': 'invalid_resource_min'} in discovery['excluded']
    assert invalid.id not in synthesize_source_policies(
        ir, level=10, include_auto_resource_fallback=True)['eligible_buttons']


def test_zero_cooldown_resource_only_generator_not_spammed():
    warrior = build_game_ir_slice(class_key='warrior', level=10)
    bloodrage = next(a for a in warrior.actions if a.id == 'bloodrage:2687')
    unlimited = replace(bloodrage, cooldown_s=0)
    ir = replace(warrior, actions=tuple(unlimited if a.id == bloodrage.id else a for a in warrior.actions))
    envelope = synthesize_source_policies(ir, level=10, include_auto_resource_fallback=True)
    assert {'id': bloodrage.id, 'reason': 'unbounded_resource_only_action'} in envelope['excluded']
    assert all(bloodrage.id not in [r.action_id for r in p.rules] for p in envelope['policies'])


def test_resource_only_without_positive_generation_excluded():
    warrior = build_game_ir_slice(class_key='warrior', level=10)
    bloodrage = next(a for a in warrior.actions if a.id == 'bloodrage:2687')
    bad = replace(bloodrage, effects=(ResourceChangeEffect('resource_change', 'rage', 'actor', 'set', 0),))
    ir = replace(warrior, actions=tuple(bad if a.id == bloodrage.id else a for a in warrior.actions))
    envelope = synthesize_source_policies(ir, level=10, include_auto_resource_fallback=True)
    assert {'id': bad.id, 'reason': 'no_positive_resource_generation'} in envelope['excluded']


def test_explicit_cap_applies_to_auto_policy_space():
    with pytest.raises(ValueError, match='exceeds explicit bound'):
        synthesize_source_policies(build_game_ir_slice(class_key='warrior', level=10), level=10,
                                   include_auto_resource_fallback=True, max_policies=2)


def test_companion_auto_attack_is_not_an_invented_player_fallback():
    warlock = build_game_ir_slice(class_key='warlock', level=10)
    only_pet = replace(warlock, actions=(), policies=())
    with pytest.raises(ValueError, match='no safe sourced direct-damage fallback or eligible auto attack'):
        synthesize_source_policies(only_pet, level=10, include_auto_resource_fallback=True)
