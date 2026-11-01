from __future__ import annotations

import math

from src import classic_mage_leveling_optimizer_v10 as eng
from src.v2 import stat_weights as sw
from src.v2.analytic_scorer import AnalyticOptions
from src.v2.path_dp import LevelNode


def test_probe_increment_endpoints_and_midpoint():
    assert sw.probe_increment(10) == 4.0
    assert sw.probe_increment(60) == 40.0
    assert math.isclose(sw.probe_increment(35), 22.0)
    assert sw.probe_increment(1) == 4.0
    assert sw.probe_increment(99) == 40.0


def test_classic_spell_power_coefficients_cover_low_level_penalty_and_frost_slow():
    r1 = eng.FROSTBOLT[0]  # learned at 4, 1.5 s base cast
    r6 = eng.FROSTBOLT[5]  # learned at 32, 3.0 s base cast
    assert math.isclose(eng.spell_power_direct_coeff(r1), (1.5/3.5)*0.40*0.95, rel_tol=1e-12)
    assert math.isclose(eng.spell_power_direct_coeff(r6), (3.0/3.5)*0.95, rel_tol=1e-12)
    assert math.isclose(eng.spell_power_direct_coeff(eng.FIRE_BLAST[3]), 1.5/3.5, rel_tol=1e-12)
    # Fireball ranks scale with their original rank cast time; its attached DoT
    # receives no SP in Classic. Pyroblast is the exception with a 70% DoT.
    fb1 = eng.FIREBALL[0]
    fb5 = eng.FIREBALL[4]
    assert math.isclose(eng.spell_power_direct_coeff(fb1), (1.5/3.5)*0.2875, rel_tol=1e-12)
    assert math.isclose(eng.spell_power_direct_coeff(fb5), 1.0, rel_tol=1e-12)
    assert eng.spell_power_dot_coeff(fb5) == 0.0
    assert math.isclose(eng.spell_power_direct_coeff(eng.PYROBLAST[0]), 1.0, rel_tol=1e-12)
    assert math.isclose(eng.spell_power_dot_coeff(eng.PYROBLAST[0]), 0.70, rel_tol=1e-12)
    # Rank 1 Arcane Missiles is a 3 s / 3 missile channel before the level penalty.
    assert math.isclose(eng.spell_power_direct_coeff(eng.ARCANE_MISSILES[0]), (3.0/3.5)*0.55, rel_tol=1e-12)


def test_configured_player_stats_applies_only_requested_gear_bonuses():
    t = eng.Talents()
    base = eng.player_stats_for_config(34, t, eng.SimConfig())
    cfg = eng.SimConfig(gear_bonus_intellect=10.0, gear_bonus_spirit=7.0, gear_bonus_spell_power=21.0)
    got = eng.player_stats_for_config(34, t, cfg)
    assert math.isclose(got.intellect, base.intellect + 10.0)
    assert math.isclose(got.spirit, base.spirit + 7.0)
    assert math.isclose(got.spell_power, 21.0)
    assert got.max_mana > base.max_mana
    assert got.spell_crit > base.spell_crit


def test_recovery_uses_configured_gear_stats():
    t = eng.Talents()
    base_cfg = eng.SimConfig()
    int_cfg = eng.SimConfig(gear_bonus_intellect=20.0)
    spirit_cfg = eng.SimConfig(gear_bonus_spirit=20.0)

    base_stats = eng.player_stats_for_config(34, t, base_cfg)
    int_stats = eng.player_stats_for_config(34, t, int_cfg)
    spirit_stats = eng.player_stats_for_config(34, t, spirit_cfg)

    # Holding missing mana constant, +Int must not create fake recovery savings
    # just because the perturbed build has a larger maximum mana pool.
    missing = 500.0
    base_t = eng.recovery_time(34, t, base_stats.max_mana - missing, base_cfg, 0.0)
    int_t = eng.recovery_time(34, t, int_stats.max_mana - missing, int_cfg, 0.0)
    assert math.isclose(int_t, base_t, rel_tol=1e-12)

    # Holding missing mana constant, +Spirit should speed recovery.
    spirit_t = eng.recovery_time(34, t, spirit_stats.max_mana - missing, spirit_cfg, 0.0)
    assert spirit_t < base_t


def test_probe_node_reports_per_point_weights_and_sp_normalization(monkeypatch):
    baseline = 100.0
    node = LevelNode(
        34, eng.Talents(), baseline,
        eng.Policy('baseline', 'frostbolt', use_fireblast=False, use_nova=False, use_blink=False),
        'analytic:normal5q', {},
    )

    def fake_opt(level, talents, cfg, *, options, school):
        score = baseline - (
            2.0 * cfg.gear_bonus_intellect
            + 1.0 * cfg.gear_bonus_spirit
            + 3.0 * cfg.gear_bonus_spell_power
        )
        return eng.Policy('reopt', 'frostbolt'), {'total_s': score}

    monkeypatch.setattr(sw, 'optimize_policy_analytic', fake_opt)
    out = sw.probe_node(node, eng.SimConfig(), options=AnalyticOptions(kill_boundary_model='normal5q'))
    d = out.details['stat_weights']
    assert d['method'] == 'symmetric_difference_reoptimized_policy'
    assert math.isclose(d['probe_increment'], sw.probe_increment(34))
    stats = d['stats']
    assert math.isclose(stats['intellect']['seconds_saved_per_100_per_point'], 2.0)
    assert math.isclose(stats['spirit']['seconds_saved_per_100_per_point'], 1.0)
    assert math.isclose(stats['spell_power']['seconds_saved_per_100_per_point'], 3.0)
    assert math.isclose(stats['intellect']['forward_seconds_saved_per_100_per_point'], 2.0)
    assert math.isclose(stats['intellect']['backward_seconds_saved_per_100_per_point'], 2.0)
    assert math.isclose(stats['intellect']['normalized_to_spell_power'], 2.0/3.0)
    assert math.isclose(stats['spirit']['normalized_to_spell_power'], 1.0/3.0)
    assert math.isclose(stats['spell_power']['normalized_to_spell_power'], 1.0)
    assert math.isclose(stats['intellect']['value_in_intellect'], 1.0)
    assert math.isclose(stats['spirit']['value_in_intellect'], 0.5)
    assert math.isclose(stats['spell_power']['value_in_intellect'], 1.5)
    assert math.isclose(stats['intellect']['points_per_one_intellect'], 1.0)
    assert math.isclose(stats['spirit']['points_per_one_intellect'], 2.0)
    assert math.isclose(stats['spell_power']['points_per_one_intellect'], 2.0/3.0)
