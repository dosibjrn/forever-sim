"""Real combat/recovery, source gear, held-out replay and fail-closed search."""
import pytest

import src.v2.source_staged_joint_search as staged
from src.game.data.forever.registry import build_game_ir_slice


LEGACY_FERAL = {'ferocity': 5, 'heart_of_the_wild': 3,
                'thick_hide': 2, 'savage_fury': 1}


def test_source_roles_are_included_before_diversity():
    ir = build_game_ir_slice(class_key='druid', level=20)
    gears = staged._gear_envelope('druid', 20, max_gear_candidates=64,
                                   required_level_policy='observed',
                                   include_melee_gear=True, ir_slice=ir)
    anchors = staged._diverse_gear_indices(gears, 2)
    assert len({gears[i]['gear_role'] for i in anchors}) == 2
    assert len({gears[i]['id'] for i in anchors}) == 2


def test_real_search_and_held_out_replay_never_seed_discovery(monkeypatch):
    independent = ({}, {'improved_wrath': 1}, {'ferocity': 1})
    monkeypatch.setattr(staged, 'enumerate_legal_talent_allocations',
                        lambda *a, **k: (independent, False))
    result = staged.evaluate_staged_joint_search(
        class_key='druid', level=20, screening_gear_count=2,
        finalist_talent_count=2, max_policies_per_path=16,
        max_caster_policies=16, held_out_allocation=LEGACY_FERAL)
    assert result['incoming_attacks_scored'] is True
    assert set(result['neutral_branch_gear_anchors']) == {'caster', 'mode'}
    assert len(set(result['screening_gear_indices'])) == 2
    assert result['talent_allocations_enumerated'] == 3
    assert result['talent_allocations_screened'] == 3
    assert result['winner']['seconds_per_mob'] > 0
    assert result['winner']['best_policy']['selected_actions']
    assert result['held_out']['legal'] is True
    assert result['held_out']['evaluated_gear_count'] == result['gear_envelope_count']
    assert result['held_out']['best']['seconds_per_mob'] > 0
    assert result['held_out']['used_to_seed_discovery'] is False
    assert result['held_out_in_independent_allocation_universe'] is False
    assert result['global_optimum_claim'] is False
    assert result['source_talent_families'] > result['executable_talent_families']
    # Held-out candidate is deliberately absent from independent universe.
    assert all(row['talent_id'] != staged.talent_candidate_id(LEGACY_FERAL)
               for row in result['finalists'])


def test_invalid_held_out_is_explicit_not_a_noop(monkeypatch):
    monkeypatch.setattr(staged, 'enumerate_legal_talent_allocations',
                        lambda *a, **k: (({},), False))
    result = staged.evaluate_staged_joint_search(
        class_key='druid', level=20, screening_gear_count=1,
        finalist_talent_count=1, max_policies_per_path=16,
        max_caster_policies=16, held_out_allocation={'nonexistent_talent': 1})
    assert result['held_out']['legal'] is False
    assert 'unknown talent' in result['held_out']['reason']
    assert result['talent_allocations_screened'] == 1


def test_truncated_talent_envelope_rejected(monkeypatch):
    monkeypatch.setattr(staged, 'enumerate_legal_talent_allocations',
                        lambda *a, **k: (({},), True))
    with pytest.raises(ValueError, match='talent candidate envelope'):
        staged.evaluate_staged_joint_search(class_key='druid', level=20)


def test_cross_class_mage_fails_closed_when_no_source_policy_executes(monkeypatch):
    monkeypatch.setattr(staged, 'enumerate_legal_talent_allocations',
                        lambda *a, **k: (({},), False))
    with pytest.raises(ValueError, match='no executable legal talent candidate'):
        staged.evaluate_staged_joint_search(
            class_key='mage', level=20, screening_gear_count=1,
            finalist_talent_count=1, max_policies_per_path=16,
            max_caster_policies=16, schedule_incoming_attacks=False)
