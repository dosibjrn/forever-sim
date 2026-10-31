import math

from src.rulesets.forever.classes.druid import rage
from src.rulesets.forever.classes.druid.server_profile import CURRENT_TARGET_SERVER_PROFILE
from src.rulesets.forever.fidelity import issues_for


def test_default_target_profile_preserves_pinned_classic_reference_values():
    level = 20
    p = CURRENT_TARGET_SERVER_PROFILE
    expected = p.incoming_rage_level2_coeff * level * level + p.incoming_rage_level_coeff * level + p.incoming_rage_constant
    assert math.isclose(rage.rage_conversion(level), expected, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(
        rage.rage_from_damage_taken(level, 100.0),
        100.0 / expected * p.incoming_rage_damage_multiplier * p.incoming_rage_income_rate,
        rel_tol=0,
        abs_tol=1e-12,
    )


def test_target_server_override_changes_rage_without_runtime_code_edit():
    base = rage.rage_from_damage_taken(40, 100.0)
    tuned = CURRENT_TARGET_SERVER_PROFILE.with_overrides(incoming_rage_income_rate=0.5)
    assert math.isclose(rage.rage_from_damage_taken(40, 100.0, tuned), base * 0.5, rel_tol=0, abs_tol=1e-12)


def test_provenance_exposes_profile_and_numeric_parameters():
    meta = rage.provenance()
    assert meta["status"] == "forever_source_backed_fixed_armor_rule"
    assert meta["profile"] == CURRENT_TARGET_SERVER_PROFILE.key
    assert meta["commit"] == rage.CMANGOS_COMMIT
    assert meta["parameters"]["damage_multiplier"] == 2.5


def test_incoming_rage_no_longer_counts_as_material_m46_blocker_after_parameterization():
    row = {x.issue_id: x for x in issues_for("druid")}["druid.incoming_damage_rage"]
    assert row.status == "partial"
    assert row.severity == "low"
    assert "Blizzard states Forever" in row.summary
