from __future__ import annotations

import pytest

from src.rulesets.forever.classes import paladin as pala


def _snap(level: int, style: str):
    gear = next(g for g in pala.archetypes(level) if g.name == style)
    return pala.gear_snapshot(gear)


def test_l20_ret_uses_only_real_named_items_and_reports_missing_slots():
    gs = _snap(20, '2h_normal')
    assert gs['body_field_method'] == 'discrete_named_sample_and_hold_v1'
    assert gs['item_field_scope'] == 'named audited items only; no interpolated/extrapolated pseudo-items'
    assert not any(x.get('modeled') for x in gs['items'])
    assert not any(x['name'].startswith('Modeled ') for x in gs['items'])
    assert gs['slots']['waist']['name'] == "Crusader's Chain Belt"
    assert gs['slots']['weapon']['name'] == 'Wolfsbane'
    assert 'wrist' in set(gs['body_field_missing_slots'])
    assert gs['slots']['shoulder']['name'] == 'Silvered Bronze Shoulders'
    assert gs['reconciliation_ok'] is True


def test_l20_protection_uses_literal_protector_items_plus_named_weapon_and_shield():
    gs = _snap(20, '1h_shield_normal')
    assert not any(x.get('modeled') for x in gs['items'])
    assert gs['slots']['waist']['name'] == "Protector's Chain Belt"
    assert gs['slots']['weapon']['name'] == "Pathfinder's Clearway"
    assert gs['slots']['offhand']['name'] == 'Seedcloud Buckler'
    assert gs['slots']['weapon']['model_kind'] == 'carried_forward_real_item'
    assert gs['slots']['offhand']['model_kind'] == 'carried_forward_real_item'
    assert gs['reconciliation_ok'] is True


def test_real_item_is_held_between_replacement_levels_instead_of_scaling():
    w19 = _snap(19, '2h_normal')['slots']['waist']
    w20 = _snap(20, '2h_normal')['slots']['waist']
    assert w19['name'] == w20['name'] == "Crusader's Chain Belt"
    assert w19['strength'] == pytest.approx(w20['strength'])
    assert w19['spell_power'] == pytest.approx(w20['spell_power'])
    assert not w19.get('modeled', False)
    assert not w20.get('modeled', False)


def test_no_paladin_checkpoint_uses_pseudo_items_or_aggregate_remainder():
    for level in (10, 16, 20, 30, 40, 50, 60):
        for style in ('2h_normal', '1h_shield_normal'):
            gs = _snap(level, style)
            assert gs['reconciliation_ok'] is True
            for row in gs['items']:
                assert row.get('source') != 'aggregate normal-leveling remainder'
                assert row.get('model_kind') != 'continuous aggregate slot decomposition'
                assert not row.get('modeled', False)
                assert not row['name'].startswith('Modeled ')
