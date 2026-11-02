"""Real source-gear snapshot and fail-closed independent P6 comparison tests."""
from copy import deepcopy

import pytest

from src.v2.source_paid_cold_comparison import (
    _winner_gear_effect_gaps,
    compare_saved_cold_winners,
    source_gear_catalogue_snapshot,
)


def _saved_report(budget, gear_snapshot):
    return {
        'class_key': 'druid', 'level': 30,
        'bonus_talent_points': 0, 'pack_size': 2,
        'source_db_sha256': 'pinned-ability-source',
        'search_only': True, 'complete_100mob_candidates': 0,
        'requested_wall_budget_s': budget, 'wall_s': budget - 0.1,
        'validation_shortlist': [{
            'allocation': {}, 'equipped_gear': {'slots': {}},
            'opening_action_ids': [], 'policy_ir': {},
            'policy_signature': 'source-policy', 'recovery': 'always',
        }],
        'validation': {
            'validated_winner_id': '0',
            'rows': [{'id': '0', 'status': 'COMPLETE', 'count': 100,
                      'full_s_per_mob': 12.5}],
        },
        'source_gear_catalogue_snapshot': gear_snapshot,
    }


def test_real_catalogue_and_semantics_are_pinned_separately_from_spell_db():
    snapshot = source_gear_catalogue_snapshot('druid', 30)
    assert snapshot['schema'] == 'source_gear_snapshot_v1'
    assert snapshot['observed_eligible_item_count'] > 0
    assert snapshot['class_key'] == 'druid' and snapshot['level'] == 30
    for key in ('catalogue_sha256', 'equipment_semantics_sha256',
                'observed_eligible_item_ids_sha256'):
        assert len(snapshot[key]) == 64
    assert snapshot == source_gear_catalogue_snapshot('druid', 30)


def test_different_gear_catalogue_fails_before_any_paid_replay():
    original = source_gear_catalogue_snapshot('druid', 30)
    changed = deepcopy(original)
    changed['catalogue_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='COLD_COMPARISON_DIFFERENT_GEAR_SOURCE_SNAPSHOT'):
        compare_saved_cold_winners(_saved_report(30, original),
            _saved_report(300, changed), source_ir=None, seed_stage=None,
            class_key='druid', level=30, source_hash='pinned-ability-source',
            bonus_talent_points=0)


def test_missing_gear_snapshot_cannot_be_compared_to_attested_report():
    original = source_gear_catalogue_snapshot('druid', 30)
    with pytest.raises(ValueError, match='COLD_COMPARISON_DIFFERENT_GEAR_SOURCE_SNAPSHOT'):
        compare_saved_cold_winners(_saved_report(30, original),
            _saved_report(300, None), source_ir=None, seed_stage=None,
            class_key='druid', level=30, source_hash='pinned-ability-source',
            bonus_talent_points=0)


def test_equipped_source_item_unresolved_effects_are_not_silent():
    from src.rulesets.forever.items.runtime_selection import available_items
    from src.game.data.forever.source_checkpoint_p3 import source_item_l0
    items = available_items('druid', 30, required_level_policy='observed')
    item = items[0]
    actual = _winner_gear_effect_gaps(
        {'equipped_gear': {'slots': {'head': {'item_id': item.item_id}}}},
        class_key='druid', level=30)
    unknown = source_item_l0(item)['unresolved_effects']
    assert actual == ({'head': {'item_id': int(item.item_id),
                                'unresolved_effects': unknown}} if unknown else {})
    with pytest.raises(ValueError, match='COLD_COMPARISON_WINNER_ITEM_NOT_IN_SOURCE'):
        _winner_gear_effect_gaps(
            {'equipped_gear': {'slots': {'head': {'item_id': -987654321}}}},
            class_key='druid', level=30)
