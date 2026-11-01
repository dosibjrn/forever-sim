from __future__ import annotations

import math

from src.v2.stat_weight_model import compute_for_engine, normalize_objective_gradient
from src.rulesets.forever.classes.mage import engine as mage


def test_normalize_objective_gradient_uses_common_reference_schema():
    out = normalize_objective_gradient(
        baseline_s_per_100=1000.0,
        objective_gradient={"intellect": -2.0, "spirit": -1.0, "spell_power": -4.0},
        method="analytic_test",
        reference_stat="spell_power",
    )
    assert out["analytical"] is True
    assert out["reference_stat"] == "spell_power"
    assert out["stats"]["intellect"]["seconds_saved_per_100_per_point"] == 2.0
    assert out["stats"]["intellect"]["normalized_to_reference"] == 0.5
    assert out["stats"]["spell_power"]["points_per_one_intellect"] == 0.5
    assert out["stats"]["spirit"]["points_per_one_intellect"] == 2.0


def test_common_dispatch_prefers_analytic_provider_over_legacy_fd():
    calls = []

    class Fake:
        @staticmethod
        def analytic_stat_gradient(level, talents, **kwargs):
            calls.append("analytic")
            return {
                "objective_gradient": {"strength": -3.0, "weapon_dps": -6.0},
                "baseline_s_per_100": 900.0,
                "reference_stat": "weapon_dps",
                "method": "fake_analytic",
            }

        @staticmethod
        def marginal_stat_weights(level, talents, profile, baseline=None):
            calls.append("legacy")
            return {"weights": {}}

    out = compute_for_engine(Fake, 30, object(), baseline={"total_s": 900.0})
    assert calls == ["analytic"]
    assert out["method"] == "fake_analytic"
    assert out["stats"]["strength"]["normalized_to_reference"] == 0.5


def test_forever_mage_analytic_gradient_values_int_from_crit_without_step_probe():
    level = 34
    talents = mage.Talents()
    cfg = mage.SimConfig(use_best_water=True)
    policy = mage.Policy("gradient test", "frostbolt", use_fireblast=False, use_nova=False, use_blink=False)
    # Deliberately continuous fake baseline: the provider consumes the actual cast
    # mix and timing, not +/- gear probes or integer cast-boundary transitions.
    baseline = {
        "total_s": 1200.0,
        "kill_s": 900.0,
        "recovery_s": 300.0,
        "casts_frostbolt": 350.0,
        "casts_wand_expected_s": 40.0,
    }
    raw = mage.analytic_stat_gradient(level, talents, baseline=baseline, policy=policy, cfg=cfg)
    grad = raw["objective_gradient"]
    assert grad["intellect"] < 0.0
    assert grad["spell_power"] < 0.0
    assert grad["spirit"] < 0.0
    assert raw["components"]["intellect"]["kill_time_via_spell_crit"] < 0.0
    expected = 1.0 / (100.0 * (14.77 + .65 * level))
    assert math.isclose(raw["components"]["intellect"]["dcrit_per_int"], expected, rel_tol=1e-12)

    out = compute_for_engine(
        mage, level, talents, baseline=baseline, policy=policy, cfg=cfg
    )
    assert out["analytical"] is True
    assert out["method"] == "analytic_continuous_gearing_surrogate_v1"
    assert out["stats"]["intellect"]["seconds_saved_per_100_per_point"] > 0.0
    assert out["stats"]["spell_power"]["normalized_to_reference"] == 1.0
