"""Registry↔executor↔search fail-closed contracts, no game identity hints."""
from dataclasses import replace
from pathlib import Path
import re

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.runtime import ActorState, TargetState, execute_action
from src.game.runtime.effect_capabilities import (
    effect_execution_kind, effect_role, registered_effect_types,
)
from src.v2.source_button_discovery import discover_source_combat_buttons
from src.v2.source_policy_search import synthesize_source_policies
from src.v2.source_action_coverage import audit_source_action_coverage


class UnmodeledEffect:
    pass


def test_every_registered_effect_kind_is_handled_by_action_executor():
    """A registry change without a matching executor dispatch is a release failure."""
    source = (Path(__file__).resolve().parents[1] / 'src/game/runtime/simulator.py').read_text()
    segment = source.split('if event.kind == "ActionCompleted":', 1)[1].split('if event.kind == "ControlApplied":', 1)[0]
    kinds = set(re.findall(r'(?:if|elif) kind == "([^"]+)"', segment))
    for group in re.findall(r'kind in \(([^)]+)\)', segment):
        kinds.update(re.findall(r'"([^"]+)"', group))
    registered = {effect_execution_kind(effect_type.__new__(effect_type)) for effect_type in registered_effect_types()}
    assert kinds == registered
    assert len(registered) == len(registered_effect_types())


def test_unknown_effect_is_never_searchable_or_silently_dropped_from_audit():
    ir = build_game_ir_slice(class_key='mage', level=10)
    known = next(a for a in ir.actions if a.id == 'fireball:133')
    unknown = replace(known, id='synthetic:unknown', effects=(UnmodeledEffect(),))
    source = replace(ir, actions=(unknown,))
    assert effect_role(unknown.effects[0]) is None
    with pytest.raises(NotImplementedError, match='UnmodeledEffect'):
        effect_execution_kind(unknown.effects[0])
    discovery = discover_source_combat_buttons(source, level=10)
    assert discovery['action_ids'] == []
    assert discovery['excluded'] == [{'id': unknown.id, 'reason': 'unexecutable_effect'}]
    audit = audit_source_action_coverage(source, level=10)
    assert audit['status'] == 'INCOMPLETE'
    assert audit['blockers'][0]['unexecutable_effects'] == [{'effect_index': 0, 'effect_type': 'UnmodeledEffect'}]


def test_missing_source_provenance_is_a_blocker_not_a_missing_record():
    ir = build_game_ir_slice(class_key='mage', level=10)
    known = next(a for a in ir.actions if a.id == 'fireball:133')
    unknown_source = replace(known, id='synthetic:no-source', provenance={})
    audit = audit_source_action_coverage(replace(ir, actions=(unknown_source,)), level=10)
    assert audit['audited_action_count'] == 1
    assert audit['blockers'][0]['missing_provenance']
    assert not audit['complete_optimizer']


def test_cross_class_search_and_effect_roles_share_runtime_contract():
    for cls, level, mode in [('mage', 10, None), ('druid', 20, 'cat')]:
        ir = build_game_ir_slice(class_key=cls, level=level)
        envelope = synthesize_source_policies(
            ir, level=level, mode_id=mode,
            include_auto_resource_fallback=(mode is not None), max_policies=1024)
        assert envelope['candidate_count'] > 0
        actions = {a.id: a for a in ir.actions}
        assert all(effect_role(e) is not None
                   for action_id in envelope['eligible_buttons'] for e in actions[action_id].effects)
        audit = audit_source_action_coverage(ir, level=level, search_envelopes=(envelope,))
        assert not audit['complete_optimizer']


def test_unknown_effect_fails_before_any_resource_or_clock_mutation():
    ir = build_game_ir_slice(class_key='mage', level=10)
    action = next(a for a in ir.actions if a.id == 'fireball:133')
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    target = TargetState.with_health('target', 1000.0)
    before = (dict(actor.resources), actor.current_time_s, actor.gcd_ready_s,
              dict(actor.cooldown_ready_s), target.health)
    bad = replace(action, effects=(UnmodeledEffect(),))
    with pytest.raises(NotImplementedError, match='UnmodeledEffect'):
        execute_action(action=bad, actor=actor, target=target)
    assert (dict(actor.resources), actor.current_time_s, actor.gcd_ready_s,
            dict(actor.cooldown_ready_s), target.health) == before
    with pytest.raises(NotImplementedError, match='UnmodeledEffect'):
        execute_action(action=replace(bad, metadata={**bad.metadata, 'channel': True}),
                       actor=actor, target=target)
    assert (dict(actor.resources), actor.current_time_s, actor.gcd_ready_s,
            dict(actor.cooldown_ready_s), target.health) == before


def test_invalid_channel_envelope_fails_before_resource_spend():
    ir = build_game_ir_slice(class_key='mage', level=10)
    action = next(a for a in ir.actions if a.id == 'fireball:133')
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    before = dict(actor.resources)
    with pytest.raises(ValueError, match='channel effects must be periodic'):
        execute_action(action=replace(action, metadata={**action.metadata, 'channel': True}),
                       actor=actor, target=TargetState.with_health('target', 1000.0))
    assert dict(actor.resources) == before
