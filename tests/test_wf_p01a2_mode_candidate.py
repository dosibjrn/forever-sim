"""WF-P01a2: source-defined generic mode autoattack candidate, real exit/recovery."""
from dataclasses import replace
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.model import ResourceCost
from src.v2 import legal_candidate_enumeration as candidates
from src.v2 import level_evaluation_trace as traces


@pytest.mark.parametrize('level,expected_mode_count', [(10, 4), (11, 10)])
def test_real_mode_candidate_is_evaluated_not_falsely_optimized(level, expected_mode_count):
    result = candidates.evaluate_source_candidate_envelope(class_key='druid', level=level)
    assert result['mode_auto_attack_evaluated_count'] == expected_mode_count
    assert result['evaluated_count'] == result['canonical_combat_evaluated_count'] + expected_mode_count
    assert not result['optimization_ready'] and not result['complete_optimizer']
    assert not result['all_source_actions_evaluated']
    assert result['winner']['candidate_kind'] == 'canonical_combat'
    mode_rows = [row for row in [result['winner'], *result['alternatives']]
                 if row['candidate_kind'] == 'source_mode_auto_attack']
    assert len(mode_rows) == expected_mode_count
    for row in mode_rows:
        trace = row['trace']
        assert trace['status'] == 'EVALUATED'
        assert trace['mode']['mode_id'] == 'bear'
        assert trace['mode']['entry_action_id'] == 'bear_form:5487'
        assert trace['mode']['exit_action_id'] == 'cancel_mode:bear'
        assert trace['mode']['recovery_mode_id'] == 'caster'
        assert trace['mode']['exit_execution'][0]['from_mode'] == 'bear'
        assert trace['mode']['exit_execution'][0]['to_mode'] == 'caster'
        assert trace['combat']['auto_attack_damage'] > 0
        assert trace['combat']['auto_attack_swing_count'] > 0
        assert trace['combat']['mode_change_count'] == 1
        assert trace['combat']['selected_actions'][0]['action_id'] == 'bear_form:5487'
        assert trace['combat']['resources_after']['mana'] < trace['combat']['resources_before']['mana']
        assert trace['next_state']['resources']['mana'] >= trace['combat']['resources_after']['mana']
        assert trace['evaluation']['seconds_per_mob'] == pytest.approx(
            trace['combat']['kill_s'] + trace['recovery']['total_s'])
        assert row['seconds_per_mob'] > result['winner']['seconds_per_mob']


def test_mode_action_not_unlocked_early():
    with pytest.raises(ValueError, match='source-backed level/policy'):
        traces.evaluate_mode_auto_attack_trace(class_key='druid', level=9,
                                              talent_selection={}, entry_action_id='bear_form:5487')
    with pytest.raises(ValueError, match='unavailable'):
        traces.evaluate_mode_auto_attack_trace(class_key='druid', level=10,
                                              talent_selection={}, entry_action_id='cat_form:768')


def test_source_mode_missing_exit_fails_closed(monkeypatch):
    original = candidates.build_game_ir_slice
    def broken(*, class_key, level):
        ir = original(class_key=class_key, level=level)
        modes = tuple(replace(m, enabled_action_ids=tuple(x for x in m.enabled_action_ids
                                                          if x != 'cancel_mode:bear'))
                      for m in ir.modes)
        return replace(ir, modes=modes)
    monkeypatch.setattr(candidates, 'build_game_ir_slice', broken)
    with pytest.raises(ValueError, match='missing unique sourced entry/exit'):
        candidates.enumerate_legal_source_candidates(class_key='druid', level=10)


def test_mode_with_no_sourced_auto_attack_is_not_silently_scored(monkeypatch):
    original = candidates.build_game_ir_slice
    def broken(*, class_key, level):
        ir = original(class_key=class_key, level=level)
        return replace(ir, auto_attacks=())
    monkeypatch.setattr(candidates, 'build_game_ir_slice', broken)
    envelope = candidates.enumerate_legal_source_candidates(class_key='druid', level=10)
    assert envelope['mode_auto_attack_candidates'] == []
    assert 'bear_form:5487' in envelope['not_evaluated_source_actions']


def test_mode_exit_cannot_be_free_if_source_declares_cost(monkeypatch):
    original = traces.build_game_ir_slice
    def broken(*, class_key, level):
        ir = original(class_key=class_key, level=level)
        actions = tuple(replace(a, costs=(ResourceCost(resource_id='mana', amount=10.0),))
                        if a.id == 'cancel_mode:bear' else a for a in ir.actions)
        return replace(ir, actions=actions)
    monkeypatch.setattr(traces, 'build_game_ir_slice', broken)
    with pytest.raises(ValueError, match='not a sourced zero-time transition'):
        traces.evaluate_mode_auto_attack_trace(class_key='druid', level=10,
                                              talent_selection={'improved_wrath': 1},
                                              entry_action_id='bear_form:5487')


def test_mode_entry_without_initial_requirement_is_rejected(monkeypatch):
    original = candidates.build_game_ir_slice
    def broken(*, class_key, level):
        ir = original(class_key=class_key, level=level)
        actions = tuple(replace(a, requirements=()) if a.id == 'bear_form:5487' else a
                        for a in ir.actions)
        return replace(ir, actions=actions)
    monkeypatch.setattr(candidates, 'build_game_ir_slice', broken)
    with pytest.raises(ValueError, match='missing entry mode requirement'):
        candidates.enumerate_legal_source_candidates(class_key='druid', level=10)
