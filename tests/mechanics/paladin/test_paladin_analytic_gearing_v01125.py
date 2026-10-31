from __future__ import annotations

import math
import pytest

from src.rulesets.forever.classes import paladin as pala
from src.v2.stat_weight_model import compute_for_engine


def _spend(names):
    t = pala.Talents()
    for name in names:
        assert pala.legal_add(t, name), (name, t.points())
        t = pala.add_point(t, name)
    return t


CHECKPOINT_BUILDS = {
    16: ['improved_holy_strike'] * 2 + ['benediction'] * 5,
    20: ['improved_holy_strike'] * 2 + ['benediction'] * 5 + ['improved_judgement'] * 2 + ['deflection'] * 2,
    30: (['benediction'] * 5 + ['improved_judgement'] * 2 + ['conviction'] * 5 +
         ['sanctified_judgement'] * 3 + ['seal_of_command'] + ['pursuit_of_justice'] * 2 +
         ['sacred_arbiter'] + ['crusade'] * 2),
}


@pytest.mark.parametrize('level', [16, 20, 30])
def test_paladin_checkpoint_analytic_weights_are_positive_and_listener_ready(level):
    t = _spend(CHECKPOINT_BUILDS[level])
    row = pala.experimental_level_score(level, t, 'auto')
    sw = compute_for_engine(pala, level, t, baseline=row, profile='all')

    assert sw['analytical'] is True
    assert sw['method'] == 'analytic_paladin_continuous_gearing_surrogate_v1'
    assert sw['reference_stat'] == 'spell_power'
    assert sw['baseline_s_per_100'] == pytest.approx(row['total_s'])
    for stat in ('strength', 'weapon_dps', 'spell_power', 'intellect', 'spirit'):
        value = sw['stats'][stat]['seconds_saved_per_100_per_point']
        assert math.isfinite(value)
        assert value >= 0.0
    assert sw['stats']['strength']['seconds_saved_per_100_per_point'] > 0
    assert sw['stats']['weapon_dps']['seconds_saved_per_100_per_point'] > 0
    assert sw['stats']['spell_power']['seconds_saved_per_100_per_point'] > 0
    assert sw['stats']['intellect']['components']['dcrit_per_int'] > 0

    # Listener contract: rate + kill/recovery + per-slot field all exist on the
    # same selected baseline that produced the weights.
    assert row['mobs_per_hour'] > 0
    assert row['kill_s'] > 0
    assert row['recovery_s'] >= 0
    gs = row['gear_stats']
    assert gs['slots']['weapon']['weapon_dps'] == pytest.approx(row['gear_stats']['weapon_dps'])
    assert gs['hand_setup'] in ('2H', '1H + shield')


def test_paladin_low_level_weapon_field_uses_current_forever_frontier_samples():
    g16 = next(g for g in pala.archetypes(16) if g.name == '2h_normal')
    g20 = next(g for g in pala.archetypes(20) if g.name == '2h_normal')
    g30 = next(g for g in pala.archetypes(30) if g.name == '2h_normal')

    # L16 carries the last real named weapon forward; there is no synthetic
    # interpolation toward a future drop/quest reward.
    assert g16.weapon_dps == pytest.approx(20.50, abs=0.02)
    assert g16.weapon_speed == pytest.approx(3.0)
    assert 'Forsaken Greataxe' in g16.weapon_anchor
    # L20 locks to the Horde/Alliance class-quest frontier (~25.6 DPS).
    assert g20.weapon_dps == pytest.approx(25.59, abs=0.02)
    assert 'Wolfsbane' in g20.weapon_anchor
    # L30 no longer sits on the old 27.2-DPS handoff; Corpsemaker anchors it.
    assert g30.weapon_dps == pytest.approx(28.95, abs=0.02)
    assert 'Corpsemaker' in g30.weapon_anchor


def test_paladin_listener_slot_decomposition_matches_combat_aggregate_totals():
    for level in (16, 20, 30):
        for gear in pala.archetypes(level):
            gs = pala.gear_snapshot(gear)
            rows = list(gs['items'])
            mapped = {
                'strength': gear.strength_bonus,
                'stamina': gear.stamina_bonus,
                'intellect': gear.intellect_bonus,
                'spirit': gear.spirit_bonus,
                'mp5': gear.mp5_bonus,
                'spell_power': gear.spell_damage_bonus,
                'healing': gear.healing_bonus,
                'defense': gear.defense_bonus,
            }
            for stat, target in mapped.items():
                got = sum(float(x.get(stat, 0.0) or 0.0) for x in rows)
                assert got == pytest.approx(target, abs=1e-8), (level, gear.name, stat, got, target)

            body_armor = sum(float(x.get('armor', 0.0) or 0.0) for x in rows if x.get('slot') != 'offhand')
            assert body_armor == pytest.approx(gear.item_armor, abs=1e-8)
            if gear.weapon_style == '2h':
                assert 'offhand' in gs['blocked_slots']
                assert 'offhand' not in gs['slots']
            else:
                assert gs['slots']['offhand']['armor'] == pytest.approx(gear.shield_armor)
                assert gs['slots']['offhand']['block_value'] == pytest.approx(gear.shield_block_value)


def test_paladin_mana_plan_cadence_scales_analytic_holy_strike_and_judgement_derivatives():
    level = 20
    t = _spend(CHECKPOINT_BUILDS[level])
    gear = next(g for g in pala.archetypes(level) if g.name == '2h_normal')
    focus = pala.mechanics._base_damage(level, t, gear, 'retribution')
    d = pala.mechanics._focus_damage_derivatives(level, t, gear, 'retribution', focus)

    assert d['holy_strike_spell_power'] > 0
    assert d['judgement_spell_power'] > 0
    assert d['spell_power'] == pytest.approx(
        d['holy_strike_spell_power'] + d['seal_spell_power'] + d['judgement_spell_power']
    )


def test_level20_protection_stat_weights_publish_mp5_and_spell_power():
    t = _spend(['redoubt']*5 + ['precision']*3 + ['anticipation']*2 + ['improved_seal_of_fury'])
    row = pala.experimental_level_score(20, t, 'protection')
    sw = compute_for_engine(pala, 20, t, baseline=row, profile='protection')
    assert 'spell_power' in sw['stats']
    assert 'mp5' in sw['stats']
    assert math.isfinite(sw['stats']['mp5']['seconds_saved_per_100_per_point'])
    assert sw['stats']['mp5']['seconds_saved_per_100_per_point'] >= 0.0
    assert sw['stats']['mp5']['components']['dregen_mps_per_mp5'] == pytest.approx(0.2)
