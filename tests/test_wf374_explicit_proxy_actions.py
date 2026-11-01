"""Explicit typed-effect approximations remain searchable, not silently erased."""

from dataclasses import replace

import pytest

from src.game.data.forever import build_game_ir_slice
from src.game.policy_evolution import from_source_rules, scratch_policies


def test_sourced_swipe_with_known_base_damage_and_explicit_ap_gap_is_searchable():
    ir = build_game_ir_slice(class_key='druid', level=30)
    swipe = next(a for a in ir.actions if a.family_key == 'swipe')
    assert swipe.effects[0].unsupported_semantics[0]['status'] == 'explicit_gap'
    policy = from_source_rules(ir, ((swipe.id, ()),))
    assert policy.rules[0].action_id == swipe.id
    assert any(swipe.id in {r.action_id for r in p.rules}
               for p in scratch_policies(ir, max_candidates=128))


def test_unclassified_unsupported_source_effect_remains_fail_closed():
    ir = build_game_ir_slice(class_key='druid', level=30)
    swipe = next(a for a in ir.actions if a.family_key == 'swipe')
    bad = replace(swipe, effects=(replace(swipe.effects[0], unsupported_semantics=(
        {'status': 'unknown', 'semantic': 'unknown_unmodeled_effect'},)),))
    bad_ir = replace(ir, actions=tuple(bad if a.id == swipe.id else a for a in ir.actions))
    with pytest.raises(ValueError, match='POLICY_REFERENCES_UNEXECUTABLE_SOURCE_EFFECT'):
        from_source_rules(bad_ir, ((bad.id, ()),))
