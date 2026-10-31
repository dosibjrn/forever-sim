from src.rulesets.forever.classes.mage import engine as mage
from src.rulesets.forever.classes.mage.analytic import analytic_stat_gradient
from src.rulesets.forever.classes.mage.server_profile import CURRENT_TARGET_SERVER_PROFILE
from src.rulesets.forever.fidelity import inventory_report
from tools.report_m46_closure import build_report as build_closure_report
from src import game_context
from src.engine_registry import reset_engine_cache


def test_blizzard_strategy_is_explicitly_disabled_and_not_an_m46_blocker():
    profile = CURRENT_TARGET_SERVER_PROFILE
    assert profile.blizzard_aoe_leveling_enabled is False
    fidelity = inventory_report()
    row = next(x for x in fidelity["classes"]["mage"]["issues"] if x["issue_id"] == "mage.blizzard_aoe_leveling")
    assert row["active_for_target_server"] is False
    assert row["blocks_m46_for_target_server"] is False
    try:
        closure = build_closure_report()
        assert "mage.blizzard_aoe_leveling" not in closure["remaining_high_medium"]
    finally:
        game_context.configure("classic", "mage")
        reset_engine_cache()


def test_ice_lance_coefficient_is_profile_scoped_and_frozen_multiplier_is_separate():
    rank = mage.latest(mage.ICE_LANCE, 20)
    assert rank is not None
    p = CURRENT_TARGET_SERVER_PROFILE
    assert mage.spell_power_direct_coeff(rank, p) == 1.0 / 7.0
    assert mage.spell_power_effective_coeff(rank, p, frozen=False) == 1.0 / 7.0
    assert mage.spell_power_effective_coeff(rank, p, frozen=True) == 3.0 / 7.0
    assert "proxy" in p.ice_lance_sp_coefficient_provenance


def test_ice_lance_profile_value_flows_into_player_facing_stat_gradient():
    t = mage.Talents(ice_lance=1)
    baseline = {"total_s": 100.0, "kill_s": 100.0, "recovery_s": 0.0, "casts_ice_lance": 10.0}
    p = CURRENT_TARGET_SERVER_PROFILE
    base = analytic_stat_gradient(20, t, baseline=baseline, cfg=mage.SimConfig(server_profile=p))
    stronger = analytic_stat_gradient(
        20, t, baseline=baseline,
        cfg=mage.SimConfig(server_profile=p.with_overrides(ice_lance_sp_coefficient=0.25)),
    )
    assert abs(stronger["objective_gradient"]["spell_power"]) > abs(base["objective_gradient"]["spell_power"])


def test_fingers_of_frost_charge_count_is_profile_scoped_with_conflict_provenance():
    p = CURRENT_TARGET_SERVER_PROFILE
    assert p.fingers_of_frost_charges == 2
    assert "guide_conflict=1" in p.fingers_of_frost_charges_provenance
    one_charge = p.with_overrides(fingers_of_frost_charges=1)
    assert one_charge.fingers_of_frost_charges == 1
    assert p.fingers_of_frost_charges == 2
