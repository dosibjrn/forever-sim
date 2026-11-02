"""Real source-gear snapshot and fail-closed independent P6 comparison tests."""
from copy import deepcopy

import pytest

from src.v2.source_paid_cold_comparison import (
    _winner_gear_effect_gaps,
    _verify_winner_gear_legality,
    compare_saved_cold_winners,
    _same_executed_source_search_space,
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


def test_different_source_slot_offsets_fail_before_any_paid_replay():
    # The 30s and 300s source candidate universes must be identical, even
    # when both use the same real source SQLite and equipment catalogue.
    snapshot = source_gear_catalogue_snapshot('druid', 30)
    thirty, three_hundred = _saved_report(30, snapshot), _saved_report(300, snapshot)
    common = {'gear_slot_sampling_version': 'stratified_source_slots_v1',
              'max_gear_moves': 16, 'gear_slot_offset': 0}
    thirty['source_search_space'] = common
    three_hundred['source_search_space'] = {**common, 'gear_slot_offset': 1}
    with pytest.raises(ValueError, match='COLD_COMPARISON_DIFFERENT_SOURCE_SEARCH_SPACE'):
        compare_saved_cold_winners(thirty, three_hundred,
            source_ir=None, seed_stage=None, class_key='druid', level=30,
            source_hash='pinned-ability-source', bonus_talent_points=0)
    # A missing space attestation must also fail closed, not replay at cost.
    del three_hundred['source_search_space']
    with pytest.raises(ValueError, match='COLD_COMPARISON_DIFFERENT_SOURCE_SEARCH_SPACE'):
        compare_saved_cold_winners(thirty, three_hundred,
            source_ir=None, seed_stage=None, class_key='druid', level=30,
            source_hash='pinned-ability-source', bonus_talent_points=0)


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


def _actual_source_winner():
    """Use the real pinned item catalogue, not fabricated item payloads."""
    from src.rulesets.forever.items.runtime_selection import select_gear
    from src.v2.source_bounded_joint_frontier import _cold_source_equipment_payload

    selected = select_gear('druid', 30, 'druid_feral', weights={},
        required_level_policy='observed', exclude_unknown_item_effects=True)
    assert len(selected) >= 2
    gear = _cold_source_equipment_payload(class_key='druid', level=30,
        gear_role='druid_feral', selected=selected)
    return {'equipped_gear': gear}


def test_cold_bootstrap_retains_full_pinned_item_vector_for_paid_replay():
    """Real Druid item SQLite must agree with the source gear audit before combat.

    This caught the previous hand-written aggregate dropping crit/hit/dodge.
    Neither missing stats nor forged extra stats may bypass the source audit.
    """
    from src.game.data.forever.registry import build_game_ir_slice
    from src.v2.source_bounded_joint_frontier import source_cold_start_stage
    from src.game.data.forever.source_named_gear_proof import audit_named_gear_source

    for level in (20, 30):
        ir = build_game_ir_slice(class_key="druid", level=level)
        stage = source_cold_start_stage(
            class_key="druid", level=level, source_ir=ir, gear_role="druid_feral")
        gear = stage["gear_policy_result"]["winner"]["gear"]
        assert {"crit", "hit", "dodge"} <= set(gear["aggregate_stats"])
        audit = audit_named_gear_source(class_key="druid", level=level, gear=gear)
        assert audit["equipment_legality_complete"], audit
        altered = deepcopy(gear)
        altered["aggregate_stats"]["crit"] += 5.0
        assert not audit_named_gear_source(
            class_key="druid", level=level, gear=altered
        )["equipment_legality_complete"]


def test_real_sourced_cold_finalist_has_full_equipment_legality():
    winner = _actual_source_winner()
    audit = _verify_winner_gear_legality(winner, class_key='druid', level=30)
    assert audit['equipment_legality_complete']
    assert audit['selected_slots'] == len(winner['equipped_gear']['slots'])


def test_saved_winner_forged_stats_rejected_before_paid_100mob_replay():
    snapshot = source_gear_catalogue_snapshot('druid', 30)
    original = _actual_source_winner()
    thirty, three_hundred = _saved_report(30, snapshot), _saved_report(300, snapshot)
    thirty['validation_shortlist'][0]['equipped_gear'] = deepcopy(original['equipped_gear'])
    three_hundred['validation_shortlist'][0]['equipped_gear'] = deepcopy(original['equipped_gear'])
    slot = next(iter(three_hundred['validation_shortlist'][0]['equipped_gear']['slots']))
    three_hundred['validation_shortlist'][0]['equipped_gear']['slots'][slot]['spell_power'] += 100
    with pytest.raises(ValueError, match='COLD_COMPARISON_WINNER_GEAR_NOT_SOURCE_LEGAL'):
        compare_saved_cold_winners(thirty, three_hundred, source_ir=None, seed_stage=None,
            class_key='druid', level=30, source_hash='pinned-ability-source',
            bonus_talent_points=0)


def test_real_source_slot_swap_and_duplicate_rejected():
    actual = _actual_source_winner()
    slots = list(actual['equipped_gear']['slots'])
    a, b = slots[:2]
    forged_slot = deepcopy(actual)
    forged_slot['equipped_gear']['slots'][a] = deepcopy(
        forged_slot['equipped_gear']['slots'][b])
    with pytest.raises(ValueError, match='COLD_COMPARISON_WINNER_GEAR_NOT_SOURCE_LEGAL'):
        _verify_winner_gear_legality(forged_slot, class_key='druid', level=30)
    duplicated = deepcopy(actual)
    duplicated['equipped_gear']['slots'][a]['item_id'] = (
        duplicated['equipped_gear']['slots'][b]['item_id'])
    with pytest.raises(ValueError, match='COLD_COMPARISON_WINNER_GEAR_NOT_SOURCE_LEGAL'):
        _verify_winner_gear_legality(duplicated, class_key='druid', level=30)


def test_p6_source_space_requires_executed_proposer_not_two_matching_labels():
    # The actual source search emits these fields in its result. A saved
    # literal alone is not a witness that the paid proposer executed it.
    from src.v2.source_bounded_joint_frontier import _SOURCE_GEAR_SAMPLING_VERSION
    current = _SOURCE_GEAR_SAMPLING_VERSION
    def report(declared, executed, *, offset=0, executed_offset=0):
        return {
            'source_search_space': {
                'gear_slot_sampling_version': declared, 'gear_slot_offset': offset,
                'max_gear_moves': 16},
            'source_slot_proposal_coverage': {
                'strategy': executed, 'slot_offset': executed_offset},
        }

    good30 = report(current, current)
    good300 = deepcopy(good30)
    assert _same_executed_source_search_space(good30, good300) is True

    # Previously two matching stale saved versions could claim source-space
    # parity, despite the real source proposer having moved to v10.
    stale = report('stratified_source_slots_v1', current)
    with pytest.raises(ValueError,
                       match='COLD_COMPARISON_SEARCH_SPACE_STRATEGY_ATTESTATION_MISMATCH'):
        _same_executed_source_search_space(stale, deepcopy(stale))

    # Two reports from the same *old* executable may be replayed as numeric
    # diagnostics, but are not proof of the current paid candidate universe.
    old = report('stratified_source_slots_v1', 'stratified_source_slots_v1')
    assert _same_executed_source_search_space(old, deepcopy(old)) is False

    # A matching strategy but different actually executed slot rotation
    # is a different source candidate universe, not an interchangeable run.
    wrong_offset = report(current, current, executed_offset=1)
    with pytest.raises(ValueError,
                       match='COLD_COMPARISON_SEARCH_SPACE_STRATEGY_ATTESTATION_MISMATCH'):
        _same_executed_source_search_space(wrong_offset, deepcopy(wrong_offset))

    # Old reports without runtime-produced metadata are non-certifying.
    legacy = {'source_search_space': deepcopy(good30['source_search_space'])}
    assert _same_executed_source_search_space(legacy, deepcopy(legacy)) is False
    with pytest.raises(ValueError,
                       match='COLD_COMPARISON_DIFFERENT_SOURCE_SEARCH_SPACE'):
        _same_executed_source_search_space(good30,
            report(current, current, offset=1))


def test_independent_paid_p6_replay_receipts_fail_closed_without_losing_other_leg():
    from src.v2.source_paid_cold_comparison import _summarize_independent_paid_replay

    missing = _summarize_independent_paid_replay(
        {'rows': [], 'wall_s_outside_search_budget': 0.2}, budget=30)
    assert missing['status'] == 'MISSING_SINGLE_PAID_REPLAY_ROW'
    assert missing['mob_completed'] == 0 and missing['s_per_mob'] is None
    assert missing['replay_wall_s'] == 0.2
    duplicate = _summarize_independent_paid_replay(
        {'rows': [{'status': 'COMPLETE', 'count': 100, 'full_s_per_mob': 10.}] * 2},
        budget=30)
    assert duplicate['status'] == 'MISSING_SINGLE_PAID_REPLAY_ROW'

    for bad in (0., -2., float('nan'), float('inf')):
        result = _summarize_independent_paid_replay(
            {'rows': [{'status': 'COMPLETE', 'count': 100,
                       'mob_completed': 100, 'full_s_per_mob': bad}]}, budget=300)
        assert result['status'] == 'INVALID_COMPLETE_PAID_REPLAY'
        assert result['mob_completed'] == 0 and result['s_per_mob'] is None

    # Real partial paid kills from a failed pull remain observable, never
    # silently promoted to a complete independent 100-mob leg.
    interrupted = _summarize_independent_paid_replay(
        {'rows': [{'status': 'BLOCKED_ACTOR_DIED', 'mob_completed': 42,
                   'failed_pull_index': 21, 'events': 987}]}, budget=30)
    assert interrupted['mob_completed'] == 42
    assert interrupted['status'] == 'BLOCKED_ACTOR_DIED'
    assert interrupted['failed_pull_index'] == 21

    completed = _summarize_independent_paid_replay(
        {'rows': [{'status': 'COMPLETE', 'count': 100,
                   'mob_completed': 100, 'full_s_per_mob': 12.5, 'events': 5200}],
         'wall_s_outside_search_budget': 2.}, budget=300)
    assert completed['status'] == 'COMPLETE'
    assert completed['mob_completed'] == completed['count'] == 100
    assert completed['s_per_mob'] == 12.5


@pytest.mark.parametrize('first_rows, expected_mobs', [
    ([], 0),
    ([{'status': 'BLOCKED_ACTOR_DIED', 'count': 42,
       'failed_pull_index': 21, 'events': 987}], 42),
    ('RAISE', 0),
])
def test_p6_independent_comparison_keeps_both_paid_legs_on_first_failure(
        monkeypatch, first_rows, expected_mobs):
    """Exercise the real comparison caller, not just the receipt helper.

    Source legality and actual combat remain separately validated by the
    hydrated production regressions; this focused negative control checks
    that a failed 30s replay cannot erase the independent paid 300s result.
    """
    from src.v2 import source_paid_cold_comparison as comparison
    from src.v2 import source_bounded_joint_frontier as frontier

    snapshot = {'schema': 'test-source-snapshot',
                'class_membership_verified': False}
    thirty = _saved_report(30, snapshot)
    three_hundred = _saved_report(300, snapshot)
    monkeypatch.setattr(comparison, 'source_gear_catalogue_snapshot',
                        lambda class_key, level: snapshot)
    monkeypatch.setattr(comparison, '_verify_winner_gear_legality',
                        lambda winner, **kwargs: {
                            'equipment_legality_complete': True,
                            'sourced_acquisition_methods': []})
    monkeypatch.setattr(comparison, '_winner_gear_effect_gaps',
                        lambda winner, **kwargs: {})

    calls = []
    def paid_replay(search_report, **kwargs):
        calls.append((search_report, kwargs))
        if len(calls) == 1:
            if first_rows == 'RAISE':
                raise RuntimeError('source preparation failed before paid combat')
            return {'rows': first_rows, 'wall_s_outside_search_budget': 1.0}
        return {'rows': [{'status': 'COMPLETE', 'count': 100,
                          'full_s_per_mob': 12.5, 'events': 5000}],
                'wall_s_outside_search_budget': 2.0}

    monkeypatch.setattr(frontier, 'replay_joint_shortlist_100mob', paid_replay)
    result = compare_saved_cold_winners(
        thirty, three_hundred, source_ir=None, seed_stage=None,
        class_key='druid', level=30,
        source_hash='pinned-ability-source', bonus_talent_points=0)

    assert len(calls) == 2
    assert [r['budget_s'] for r in result['replays']] == [30, 300]
    assert result['status'] == 'INCOMPLETE_INDEPENDENT_100MOB_REPLAY'
    assert result['replays'][0]['mob_completed'] == expected_mobs
    if first_rows == 'RAISE':
        assert result['replays'][0]['status'] == 'PAID_REPLAY_EXECUTOR_EXCEPTION'
        assert 'RuntimeError: source preparation failed' in result['replays'][0]['reason']
        assert result['replays'][0]['replay_wall_s'] >= 0
    assert result['replays'][1]['status'] == 'COMPLETE'
    assert result['replays'][1]['mob_completed'] == 100
    assert result['replays'][1]['s_per_mob'] == 12.5
    assert result['ratio_T30_T300'] is None
    assert result['numeric_p6_within_1pct'] is False
    assert result['eligible_for_checkpoint_acceptance'] is False
