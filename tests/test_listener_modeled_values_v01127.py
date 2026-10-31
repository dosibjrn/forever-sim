from __future__ import annotations

import pytest

from src.rulesets.forever.classes import paladin as pala
from src.listener import DECISIONS_HTML


def _spend(names):
    t = pala.Talents()
    for name in names:
        assert pala.legal_add(t, name)
        t = pala.add_point(t, name)
    return t


def test_paladin_real_slots_publish_explicit_numeric_stat_summaries_and_reconcile():
    t = _spend(['improved_holy_strike'] * 2 + ['benediction'] * 5 +
               ['improved_judgement'] * 2 + ['deflection'] * 2)
    row = pala.experimental_level_score(20, t, 'auto')
    gs = row['gear_stats']

    assert gs['items']
    assert not any(x.get('modeled') for x in gs['items'])
    for item in gs['items']:
        assert item.get('stat_summary')
        assert item['stat_summary'] != 'no numeric contribution', item

    assert gs['reconciliation_ok'] is True
    assert gs['reconciliation_max_abs_delta'] == pytest.approx(0.0, abs=1e-8)
    for stat in ('strength', 'stamina', 'intellect', 'spirit', 'spell_power',
                 'healing', 'defense', 'body_armor', 'shield_armor',
                 'block_value', 'weapon_dps', 'weapon_speed'):
        assert gs['slot_totals'][stat] == pytest.approx(gs['combat_totals'][stat], abs=1e-8)


def test_listener_labels_explicit_modeled_stats_and_reconciliation():
    assert 'explicit stats used by model' in DECISIONS_HTML
    assert 'combat aggregate' in DECISIONS_HTML
    assert 'displayed slot sum' in DECISIONS_HTML
    assert 'reconciliation' in DECISIONS_HTML
    assert 'gearStatSummary' in DECISIONS_HTML
