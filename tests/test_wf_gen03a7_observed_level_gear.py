"""Real sourced item-level provenance gating in the existing gear optimizer.

An observed requirement is not proof of item acquisition. The selector must
never promote listview presence or an inferred level to an attainable item.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from src.game.data.forever.registry import build_game_ir_slice

from src.game.data.forever.gear import select_named_gear
from src.rulesets.forever.items.catalogue import ItemCatalogue, ItemRecord
from src.rulesets.forever.items.runtime_selection import (
    available_items, clear_runtime_item_cache, gear_overrides,
)
from src.v2.source_joint_discovery import _gear_envelope, evaluate_bounded_joint_discovery


def test_default_candidate_envelope_unchanged():
    old = _gear_envelope('druid', 20, max_gear_candidates=32,
                         gear_weight_order=2, gear_weight_ratios=(.5, 1., 2.))
    explicit = _gear_envelope('druid', 20, max_gear_candidates=32,
                              gear_weight_order=2, gear_weight_ratios=(.5, 1., 2.),
                              required_level_policy='catalogue')
    assert [row['id'] for row in old] == [row['id'] for row in explicit]
    assert len(old) == 18


def test_observed_level_gate_removes_unobserved_trinket_from_actual_search():
    catalogue = _gear_envelope('druid', 20, max_gear_candidates=32,
                               gear_weight_order=2, gear_weight_ratios=(.5, 1., 2.))
    observed = _gear_envelope('druid', 20, max_gear_candidates=32,
                              gear_weight_order=2, gear_weight_ratios=(.5, 1., 2.),
                              required_level_policy='observed')
    assert any(7506 in [i['item_id'] for i in row['selection'].slots.values()] for row in catalogue)
    assert observed
    assert all(7506 not in [i['item_id'] for i in row['selection'].slots.values()] for row in observed)
    assert all(i['required_level_origin'] == 'observed'
               and i['fetch_status'] == 'verified_listview'
               for row in observed for i in row['selection'].slots.values())
    assert all(row['selection'].slots for row in observed)


def test_observed_level_gate_is_generic_across_classes():
    for class_key in ('mage', 'druid'):
        selected = select_named_gear(class_key=class_key, level=20,
                                     stat_weights={'spell_power': 1., 'spirit': .5},
                                     required_level_policy='observed')
        assert selected.slots
        assert all(i['required_level_origin'] == 'observed' for i in selected.slots.values())


def test_strict_provenance_filters_missing_and_unverified_source(tmp_path, monkeypatch):
    db = tmp_path / 'items.sqlite'
    with ItemCatalogue(db) as cat:
        for iid, origin, status, identity in (
            (101, 'observed', 'verified_listview', 'wowhead_listview'),
            (102, 'inferred_median', 'verified_listview', 'wowhead_listview'),
            (103, 'observed', 'legacy_cached', 'wowhead_listview'),
            (104, 'observed', 'verified_listview', 'legacy_unknown'),
            (105, 'observed', 'verified', 'wowhead_item'),
        ):
            cat.upsert_item(ItemRecord(item_id=iid, name=f'Item {iid}', slot='head',
                                       item_level=10, required_level=10,
                                       required_level_origin=origin,
                                       source_type=('wowhead_detail' if iid == 105 else 'wowhead_listview'),
                                       identity_origin=identity, fetch_status=status))
            cat.add_class_eligibility(iid, 11)
            cat.add_class_eligibility(iid, 8)
    monkeypatch.setenv('FOREVER_ITEM_CATALOGUE', str(db))
    clear_runtime_item_cache()
    try:
        for class_key in ('druid', 'mage'):
            assert {i.item_id for i in available_items(class_key, 20)} == {101, 102, 103, 104, 105}
            assert {i.item_id for i in available_items(class_key, 20,
                     required_level_policy='observed')} == {101, 105}
            assert {i.item_id for i in available_items(class_key, 20)} == {101, 102, 103, 104, 105}
        with gear_overrides({'head': 102}):
            with pytest.raises(ValueError, match='not legal/available'):
                select_named_gear(class_key='druid', level=20, stat_weights={'spirit': 1.},
                                  required_level_policy='observed')
    finally:
        clear_runtime_item_cache()


@pytest.mark.parametrize('policy', ('', 'source_only', 'verified_acquisition', None, 42))
def test_unknown_level_policy_rejected_before_search(policy):
    with pytest.raises(ValueError, match='required_level_policy'):
        _gear_envelope('druid', 20, max_gear_candidates=32,
                       required_level_policy=policy)


def test_druid_l20_real_joint_search_with_observed_level_only():
    """Reoptimize actual gear/talents/policies; OG is read only after search."""
    # Frozen historical Improved-Wrath-only regression; current talent search is larger.
    source=build_game_ir_slice(class_key='druid',level=20)
    frozen=replace(source,talents=tuple(t for t in source.talents if t.id == 'improved_wrath'))
    new = evaluate_bounded_joint_discovery(
        class_key='druid', level=20, ir_slice=frozen, gear_weight_order=2,
        gear_weight_ratios=(.5, 1., 2.), max_gear_candidates=32,
        max_states=256, required_level_policy='observed')
    old = json.loads((Path(__file__).resolve().parents[1] /
        'WF_GEN03A6_DRUID_L20_RATIO_RUN_v0.11.48.220.json').read_text())
    assert new['required_level_policy'] == 'observed'
    assert new['gear_required_level_observed']
    assert not new['gear_acquisition_verified']
    assert len(new['winner_gear_acquisition_blockers']) == len(new['winner']['gear_slots'])
    assert all(row['reason'] == 'acquisition_method_and_prerequisites_not_in_catalogue'
               for row in new['winner_gear_acquisition_blockers'])
    assert new['winner']['best_policy']['selected_actions']
    assert new['evaluated_state_count'] > 0
    assert all(i['required_level_origin'] == 'observed'
               for state in (new['winner'], *new['alternatives'])
               for i in state['gear_slots'].values())
    assert not any(i['item_id'] == 7506
                   for state in (new['winner'], *new['alternatives'])
                   for i in state['gear_slots'].values())
    assert new['winner']['score_s_per_mob'] >= old['winner']['score_s_per_mob'] - 1e-9
    assert new['status'] == 'EVALUATED_BOUNDED_JOINT_GRID'


def test_observed_level_search_fails_closed_when_no_sourced_legal_item(tmp_path, monkeypatch):
    db = tmp_path / 'inferred_only.sqlite'
    with ItemCatalogue(db) as cat:
        cat.upsert_item(ItemRecord(item_id=991, name='Inferred Head', slot='head',
                                   item_level=12, required_level=10,
                                   required_level_origin='inferred_median',
                                   source_type='wowhead_listview',
                                   identity_origin='wowhead_listview',
                                   fetch_status='verified_listview'))
        cat.add_class_eligibility(991, 11)
    monkeypatch.setenv('FOREVER_ITEM_CATALOGUE', str(db))
    clear_runtime_item_cache()
    try:
        with pytest.raises(ValueError, match='no legal named equipment'):
            _gear_envelope('druid', 20, max_gear_candidates=32,
                           required_level_policy='observed')
    finally:
        clear_runtime_item_cache()
