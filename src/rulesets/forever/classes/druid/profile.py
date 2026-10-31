from __future__ import annotations

from src.rulesets.forever.shared import DataProvenance

VERIFIED_LEVEL_CAP = 30
PLANNING_LEVEL_CAP = 40

RULESET = "forever"
CLASS_NAME = "druid"
ENGINE_KIND = "experimental_leveling"
FAST_SUPPORTED = True
MC_SUPPORTED = False
EXPERIMENTAL = True

TREE_NAMES = ("balance", "feral", "restoration")
PRIMARY_SCHOOL_ENV = "DRUID_LEVELING_PROFILE"
PRIMARY_SCHOOLS = ("all", "balance", "feral", "bear", "restoration")

DATA_PROVENANCE = DataProvenance(
    build="Forever beta client 1.60.1.70170",
    attribution="TalentsForever current Druid tree build 1.60.1.70170 + audited Forever spell/item sources (2026-10-03)",
)
DATA_BUILD = DATA_PROVENANCE.build
DATA_ATTRIBUTION = DATA_PROVENANCE.attribution
DATA_QUALITY = DATA_PROVENANCE.quality

DRUID_CAPABILITY_MATRIX = {
    "balance": {
        "talent_legality_l10_l40": "source_backed",
        "single_target_rotation": "source_backed_bounded",
        "mana_recovery": "stateful_shared_recovery",
        "moonkin_and_core_nukes": "source_backed",
        "aoe_leveling": "unmodeled",
    },
    "cat": {
        "talent_legality_l10_l40": "source_backed",
        "energy_combo_points": "finite_target_stateful",
        "between_mob_energy_carry": "stateful",
        "rake_rip_ferocious_bite": "source_backed_bounded",
        "omen_clearcasting_proc_state": "unpriced",
        "solo_shred_uptime": "unpriced",
        "cat_swipe": "unverified_fail_closed",
    },
    "bear": {
        "talent_legality_l10_l40": "source_backed",
        "pack_model_1_to_3": "source_backed_bounded",
        "survival_pressure": "stateful",
        "between_pull_hp_recovery": "stateful_shared_recovery",
        "incoming_damage_to_rage": "explicit_server_profile_proxy",
        "multi_pull_without_swipe": "fail_closed",
    },
    "shared": {
        "gear": "canonical_sqlite_runtime_selection",
        "stat_weights": "canonical_scorer_sensitivity",
        "form_exit_heal_drink_reentry": "shared_recovery_authority",
        "verified_level_cap": "L30",
        "planning_level_cap": "L40",
    },
}

MODEL_FIDELITY = {
    "backend": "deterministic_balance_cat_bear_leveling_cycles",
    "verified_level_cap": VERIFIED_LEVEL_CAP,
    "planning_level_cap": PLANNING_LEVEL_CAP,
    "capability_matrix": DRUID_CAPABILITY_MATRIX,
    "pull_model": "cat_single_target_plus_balance_single_target_plus_bear_1_to_3_pack",
    "resource_continuity": "stateful_cat_energy_combo_plus_balance_mana_plus_shared_form_recovery",
    "survival": "stateful_hp_chain; bear_pack_pressure; cat_balance_single_target",
    "gear": "canonical_sqlite_per_level_role_selection",
    "mc_validated": False,
    "rating": "verified_l10_l30_medium_planning_l31_l40_bounded",
    "verified_public_facts": (
        "cat_form", "claw_r1", "shred_r1", "rake_l34",
        "ferocious_bite_l40", "wrath_l38", "moonfire_l28",
        "omen_of_clarity", "clearcasting", "moonkin_form",
        "brawler_leatherworking_family", "totemic_leatherworking_family",
        "swipe_bear_3_target_cap", "primal_bite_rank_ladder", "maul_15_rage",
        "shifting_power_70170", "improved_shifting_power_70170",
    ),
    "missing_mechanics": (
        "target_server_cat_bear_fixed_form_swing_constants",
        "omen_clearcasting_proc_rate_and_state",
        "solo_shred_behind_target_uptime",
        "cat_swipe_forever_acquisition_and_scaling",
        "forever_specific_incoming_damage_to_rage_formula",
        "forever_specific_ooc_health_regen_formula",
        "balance_aoe_leveling_policy",
        "l41_l60_full_fidelity_audit",
    ),
}



def normalize_primary_school(value):
    value = str(value or "all").lower()
    return value if value in PRIMARY_SCHOOLS else "all"
