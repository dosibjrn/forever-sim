from __future__ import annotations

import pytest

from src.rulesets.forever.shared.crafted_itemization import CRAFTED_ITEMS
from src.rulesets.forever.shared.item_budget import peer_exchange_budget_units
from src.rulesets.forever.classes import paladin as pala
from src.rulesets.forever.classes.paladin.gear import archetypes, gear_snapshot, reroll_body_items
from src.v2.stat_weight_model import compute_for_engine


def _spend(names):
    t = pala.Talents()
    for name in names:
        assert pala.legal_add(t, name)
        t = pala.add_point(t, name)
    return t


def test_peer_exchange_budget_units_are_level_local_and_cover_core_hybrid_stats():
    l20 = peer_exchange_budget_units(
        CRAFTED_ITEMS, 20,
        stats=("strength", "intellect", "spirit", "spell_power"),
    )
    l40 = peer_exchange_budget_units(
        CRAFTED_ITEMS, 40,
        stats=("strength", "intellect", "spirit", "spell_power"),
    )
    assert l20["method"] == "forever_peer_item_exchange_v1"
    for stat in ("strength", "intellect", "spirit", "spell_power"):
        assert l20["units_per_budget"][stat] > 0
        assert l40["units_per_budget"][stat] > 0
        assert l20["confidence"][stat]["peer_samples"] >= 1
    # Amounts scale with tier instead of freezing one low-level exchange chunk.
    assert l40["units_per_budget"]["intellect"] > l20["units_per_budget"]["intellect"]


def test_paladin_analytic_weights_publish_equal_budget_projection_without_erasing_raw_gradient():
    t = _spend(['improved_holy_strike'] * 2 + ['benediction'] * 5 +
               ['improved_judgement'] * 2 + ['deflection'] * 2)
    row = pala.experimental_level_score(20, t, 'auto')
    sw = compute_for_engine(pala, 20, t, baseline=row, profile='all')

    assert sw['analytical'] is True
    assert sw['equal_item_budget']['method'] == 'forever_peer_item_exchange_v1'
    assert sw['stat_mix_guidance_rank'] == sw['equal_item_budget']['rank']
    for stat in ('strength', 'intellect', 'spirit', 'spell_power'):
        r = sw['stats'][stat]
        assert r['seconds_saved_per_100_per_point'] >= 0
        assert r['empirical_units_per_equal_budget'] > 0
        assert r['seconds_saved_per_100_per_equal_budget'] == pytest.approx(
            r['seconds_saved_per_100_per_point'] * r['empirical_units_per_equal_budget']
        )
    # Weapon DPS remains a native-unit derivative: the peer-item body estimator
    # does not fabricate a weapon-DPS exchange rate.
    assert 'empirical_units_per_equal_budget' not in sw['stats']['weapon_dps']


def test_paladin_named_body_reroll_replaces_same_slots_and_reconciles_to_combat_totals():
    level = 40
    base = next(g for g in archetypes(level) if g.name == '2h_normal')
    # Deliberately Int-heavy local value to force Holy peer pieces where the
    # baseline Ret family has comparable named slot anchors.
    rerolled = reroll_body_items(base, level, {'intellect': 1.0})
    assert rerolled.selected_body_items
    # Canonical SQLite slot reroll may choose different real Int-heavy peers as
    # the pinned catalogue refreshes; the contract is literal named items, not
    # one historical Prefect fixture.
    assert rerolled.gear_selection_method == 'per_level_analytic_sqlite_slot_reroll_v2'
    gs = gear_snapshot(rerolled)
    assert gs['gear_selection_method'] == 'per_level_analytic_sqlite_slot_reroll_v2'
    assert gs['inventory_continuity'] is False

    rows = list(gs['items'])
    mapped = {
        'strength': rerolled.strength_bonus,
        'stamina': rerolled.stamina_bonus,
        'intellect': rerolled.intellect_bonus,
        'spirit': rerolled.spirit_bonus,
        'spell_power': rerolled.spell_damage_bonus,
        'healing': rerolled.healing_bonus,
        'defense': rerolled.defense_bonus,
    }
    for stat, target in mapped.items():
        got = sum(float(x.get(stat, 0.0) or 0.0) for x in rows)
        assert got == pytest.approx(target, abs=1e-8), (stat, got, target)


def test_paladin_level_score_can_accept_per_level_reroll_but_keeps_baseline_as_safety_net():
    t = _spend(['improved_holy_strike'] * 2 + ['benediction'] * 5 +
               ['improved_judgement'] * 2 + ['deflection'] * 2)
    row20 = pala.experimental_level_score(20, t, 'auto')
    gs20 = row20['gear_stats']
    assert gs20['modeled_level'] == 20
    assert gs20['inventory_continuity'] is False
    assert gs20['gear_selection_method'] in ('baseline_family', 'per_level_analytic_named_slot_reroll_v1', 'per_level_analytic_sqlite_slot_reroll_v2')
