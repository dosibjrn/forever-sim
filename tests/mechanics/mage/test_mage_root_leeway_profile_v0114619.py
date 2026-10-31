from src.rulesets.forever.classes.mage import engine as mage
from src.rulesets.forever.classes.mage.server_profile import CURRENT_TARGET_SERVER_PROFILE
from src.rulesets.forever.fidelity import inventory_report


def test_default_config_inherits_root_and_leeway_from_server_profile():
    p = CURRENT_TARGET_SERVER_PROFILE.with_overrides(
        root_break_mode="never",
        root_break_base=0.77,
        root_break_damage_scale=1.23,
        root_break_fire_bonus=0.42,
        moving_melee_leeway=2.75,
    )
    cfg = mage.SimConfig(server_profile=p)
    assert cfg.root_break_mode == "never"
    assert cfg.root_break_base == 0.77
    assert cfg.root_break_damage_scale == 1.23
    assert cfg.root_break_fire_bonus == 0.42
    assert cfg.moving_leeway == 2.75


def test_explicit_sensitivity_override_beats_profile_without_mutating_it():
    p = CURRENT_TARGET_SERVER_PROFILE.with_overrides(root_break_mode="never", moving_melee_leeway=2.5)
    cfg = mage.SimConfig(server_profile=p, root_break_mode="first", moving_leeway=1.0)
    assert cfg.root_break_mode == "first"
    assert cfg.moving_leeway == 1.0
    assert p.root_break_mode == "never"
    assert p.moving_melee_leeway == 2.5


def test_root_break_and_leeway_are_no_longer_medium_m46_blocker():
    report = inventory_report()
    row = next(x for x in report["classes"]["mage"]["issues"] if x["issue_id"] == "mage.root_break_and_melee_leeway")
    assert row["status"] == "partial"
    assert row["severity"] == "low"
    assert row["blocks_m46_for_target_server"] is False
    assert "server-profile" in row["summary"]
