"""Real-executor canary for resource-mutating offensive actions.

No external source facts are created here. Rogue IR has an unresolved Eviscerate
AP coefficient, which must stay a typed coverage blocker.
"""
from dataclasses import replace

from src.game.data.forever.registry import build_game_ir_slice
from src.v2.generic_backend import _policy_combat_evaluation
from src.v2.source_budgeted_prefix import PrefixCandidate, source_prefix_envelope
from src.v2.source_stateful_budgeted import (
    _l0_proxy, _make_policy, _resource_flow_proxy, run_source_stateful_budgeted,
)


def test_source_discovery_keeps_damage_with_resource_change_but_not_unrelated_actions():
    ir = build_game_ir_slice(class_key='rogue', level=20)
    envelope = source_prefix_envelope(ir, level=20)
    assert 'sinister_strike:1758' in envelope['actions']
    assert 'eviscerate:6761' in envelope['actions']
    assert 'sinister_strike:1758' in envelope['fillers']
    assert all('stealth' not in x for x in envelope['actions'])


def test_unresolved_source_effect_blocks_finisher_but_not_generic_builder():
    result = run_source_stateful_budgeted(class_key='rogue', level=20,
        max_l2_attempts=12, max_event_transitions=700, use_l1=False)
    assert result['status'] == 'BEST_KNOWN_BOUNDED'
    assert result['source_actions'] == ['sinister_strike:1758']
    assert result['source_fillers'] == ['sinister_strike:1758']
    assert result['blocked_source_semantics'] == [{
        'id': 'eviscerate:6761', 'reason': 'BLOCKED_UNMODELED_SOURCE_SEMANTICS',
        'effects': [{'semantic': 'eviscerate_attack_power_scaling',
                     'status': 'current_forever_server_formula_not_yet_normalized'}]}]
    assert result['winner']['score_s_per_mob'] > 0
    assert result['winner']['survived']
    assert result['event_transitions'] <= 700
    assert result['l2_attempts'] <= 12
    assert result['verification_complete']
    assert result['verification_completed'] == result['verification_required'] == 2
    ir = build_game_ir_slice(class_key='rogue', level=20)
    winner = result['winner']
    scratch, execution, details = _policy_combat_evaluation(
        ir, level=20, policy_override=_make_policy(ir, winner['fallback']),
        opening_action_ids=tuple(winner['prefix']), schedule_incoming_attacks=True)
    assert execution.timeline.target_defeated
    assert scratch.seconds_per_mob == winner['score_s_per_mob']
    assert details['event_transitions_new'] > 0


def test_generic_action_rename_has_same_full_objective():
    ir = build_game_ir_slice(class_key='rogue', level=20)
    old = 'sinister_strike:1758'
    new = 'generic_source_resource_hit'
    renamed = replace(ir, actions=tuple(
        replace(a, id=new, name='Neutral resource hit') if a.id == old else a
        for a in ir.actions))
    result = run_source_stateful_budgeted(class_key='rogue', level=20,
        ir_slice=renamed, max_l2_attempts=7, max_event_transitions=500,
        use_l1=False)
    assert result['source_actions'] == [new]
    assert result['winner']['fallback'] == new
    assert result['winner']['score_s_per_mob'] == 22.523478260869574
    assert result['verification_complete']


def test_l0_weapon_damage_and_net_energy_regeneration_are_generic_ir_features():
    ir = build_game_ir_slice(class_key='rogue', level=20)
    amap = {a.id: a for a in ir.actions}
    c = PrefixCandidate(('sinister_strike:1758',), 'sinister_strike:1758')
    proxy = _l0_proxy(c, amap, ir, 20)
    assert proxy['estimated_damage'] > 0  # real expected_weapon_damage primitive
    assert proxy['resource_flow']['net_resource_wait_s'] > 0
    assert not proxy['resource_flow']['uncovered_resource_deficit']
    no_regen = replace(ir, resources=tuple(
        replace(r, regeneration_per_s=0.) if r.id == 'energy' else r
        for r in ir.resources))
    without = _resource_flow_proxy(c, amap, no_regen, 5)
    with_regen = _resource_flow_proxy(c, amap, ir, 5)
    assert without['uncovered_resource_deficit']['energy'] > 0
    assert not with_regen['uncovered_resource_deficit']


def test_druid_l10_ordered_prefix_and_mage_l20_regression():
    for cls, level, expected in [('druid', 10, 16.111809753559438),
                                 ('mage', 20, 27.960992907801415)]:
        result = run_source_stateful_budgeted(class_key=cls, level=level,
            max_l2_attempts=12, max_event_transitions=700, use_l1=False)
        assert result['winner']['score_s_per_mob'] == expected
        assert result['verification_complete']


def test_all_unresolved_effect_statuses_are_fail_closed():
    from src.v2.source_stateful_budgeted import _unsafe_semantics
    ir = build_game_ir_slice(class_key='rogue', level=20)
    action = next(a for a in ir.actions if a.id == 'eviscerate:6761')
    effect = action.effects[0]
    for status in ('not_yet_modeled', 'explicit_gap', 'not_verified',
                   'not_resolved', 'legacy_transcription_pending_independent_verification',
                   'current_forever_server_formula_not_yet_normalized', 'new_unrecognized_status'):
        mutated = replace(action, effects=(replace(effect,
            unsupported_semantics=({'status': status, 'semantic': 'missing_source_rule'},)),
            *action.effects[1:]))
        assert _unsafe_semantics(mutated) == [{'status': status, 'semantic': 'missing_source_rule'}]
    approximated = replace(action, effects=(replace(effect,
        unsupported_semantics=({'status': 'explicit_approximation'},)), *action.effects[1:]))
    assert _unsafe_semantics(approximated) == []
