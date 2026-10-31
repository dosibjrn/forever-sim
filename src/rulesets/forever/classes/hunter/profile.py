from __future__ import annotations

from src.rulesets.forever.shared import DataProvenance

RULESET = "forever"
CLASS_NAME = "hunter"
ENGINE_KIND = "experimental_leveling"
FAST_SUPPORTED = True
MC_SUPPORTED = False
EXPERIMENTAL = True
VERIFIED_LEVEL_CAP = 20
PLANNING_LEVEL_CAP = 40

TREE_NAMES = ("beast_mastery", "marksmanship", "survival")
PRIMARY_SCHOOL_ENV = "HUNTER_LEVELING_PROFILE"
PRIMARY_SCHOOLS = ("all", "beast_mastery", "marksmanship", "survival")


HUNTER_CAPABILITY_MATRIX = {
    "beast_mastery": {
        "talent_legality_l21_l40": "source_backed",
        "core_ranged_rotation": "bounded",
        "pet_family_actives": "source_backed_bounded",
        "bestial_discipline_focus": "bounded",
        "bestial_wrath": "source_backed_bounded",
        "summon_hawk_initial_strike": "source_backed",
        "summon_hawk_sustained_attacks": "unpriced",
    },
    "marksmanship": {
        "talent_legality_l21_l40": "source_backed",
        "core_ranged_rotation": "bounded",
        "rapid_fire": "source_backed_bounded",
        "rapid_recuperation": "source_backed_bounded",
        "sniper_shot": "source_backed_bounded",
        "ammo_quiver_haste": "unmodeled",
    },
    "survival": {
        "talent_legality_l21_l40": "source_backed",
        "ranged_policy": "bounded",
        "melee_trap_policy": "source_backed_bounded",
        "raptor_strike": "source_backed",
        "immolation_trap": "source_backed",
        "expose_prey_mongoose": "source_backed_bounded",
        "counterattack_parry_cadence": "unpriced",
        "strider_kick_mana": "unpriced",
    },
    "shared": {
        "single_target_leveling": "bounded",
        "multi_shot_pack_leveling": "unmodeled",
        "pet_stat_inheritance": "source_backed",
        "gear": "canonical_sqlite",
        "stat_weights": "canonical_scorer_sensitivity",
    },
}

DATA_PROVENANCE = DataProvenance(
    build="Forever patch 1.60.1 beta sources, 2026-09-30",
    verified_level_cap=VERIFIED_LEVEL_CAP,
    attribution=(
        "Hunter L10-L20 verified behavioral model plus L21-L40 bounded planning model: "
        "Talents Forever build 1.60.1.70009 talent/spellbook roster and pinned Wowhead Forever spell entities; "
        "capability matrix explicitly marks unpriced/unmodeled post-L20 mechanics"
    ),
)
DATA_BUILD = DATA_PROVENANCE.build
DATA_ATTRIBUTION = DATA_PROVENANCE.attribution
DATA_QUALITY = DATA_PROVENANCE.quality

MODEL_FIDELITY = {
    "backend": "hunter_l10_l20_verified_plus_bm_mm_survival_l21_l40_source_backed_bounded_melee_trap",
    "verified_level_cap": VERIFIED_LEVEL_CAP,
    "planning_level_cap": PLANNING_LEVEL_CAP,
    "capability_matrix": HUNTER_CAPABILITY_MATRIX,
    "pull_model": "single_target_only",
    "resource_continuity": "coarse_mana_cycle",
    "pet_model": "expected_value_pet_family_plus_source_backed_player_stat_inheritance",
    "survival": "ranged_kiting_and_bounded_melee_trap_candidates",
    "gear": "canonical SQLite per-level named gear with ranged and melee weapon facts consumed by scorer",
    "mc_validated": False,
    "rating": "verified_l10_l20_medium_planning_l21_l40_bounded",
    "verified_public_facts": (
        "hunter_tree_names_and_l10_l20_talent_ranks_from_talentsforever_70009",
        "auto_shot_forever_identity",
        "arcane_shot_ranks_l6_l12_l20_cost_damage_cooldown",
        "serpent_sting_ranks_l10_l18_cost_damage_duration",
        "aimed_shot_l20_cost_cast_cooldown_bonus_damage",
        "aspect_of_the_hawk_l10_l18_rap",
        "pet_family_damage_health_armor_modifiers",
        "forever_pet_inherits_2_health_per_player_stamina_30pct_player_armor_10pct_highest_attack_power_and_full_player_crit",
        "post_l20_core_spell_ranks_arcane_serpent_aimed_hawk_through_l40_probe",
        "endurance_training_pet_health_armor_3_percent_per_rank",
        "improved_revive_pet_cast_cost_return_health_ranks",
        "rapid_killing_next_shot_10_20_percent_and_rapid_fire_cooldown_reduction",
        "rapid_fire_l26_100_mana_40pct_attack_speed_15s_5min_cd",
        "lone_wolf_20_percent_no_pet_damage",
        "beast_mastery_l21_l40_tree_legality_build_70009",
        "ferocity_pet_crit_2pct_per_rank",
        "spirit_bond_1pct_health_per_10s_or_5s",
        "frenzy_20pct_proc_per_rank_30pct_pet_attack_speed_8s",
        "bestial_wrath_50pct_pet_damage_18s_120s_cd",
        "summon_hawk_l25_l36_initial_damage_mana_5pct_rap_18s_duration_two_active_6s_arcane_shared_cd",
        "marksmanship_l21_l40_tree_legality_build_70009",
        "trueshot_aura_30_ranged_attack_power",
        "mortal_shots_6pct_crit_damage_bonus_per_rank",
        "rapid_recuperation_25_50pct_sting_and_50_100pct_rapid_killing_mana_regen_while_casting",
        "barrage_3_7_10pct_aimed_multishot_volley_damage",
        "ranged_weapon_specialization_1pct_ranged_weapon_damage_per_rank",
        "sniper_shot_l40_160_bonus_365_mana_4s_cast_15s_cd",
        "survival_l21_l40_tree_legality_build_70009",
        "survival_tactics_trap_feign_hit_5_10pct",
        "predators_edge_melee_crit_damage_6pct_and_offhand_10pct_per_rank",
        "counterattack_50pct_weapon_plus_13_requires_deterrence",
        "resourcefulness_melee_trap_cost_30_60pct_and_crit_proc_mana_regen",
        "expose_prey_5_10pct_hunters_mark_attack_proc_mongoose_bite",
        "survivalists_discipline_trap_deterrence_cd_20_40pct",
        "strider_kick_100pct_weapon_damage_30pct_move_speed_3s",
        "lightning_reflexes_agility_2pct_per_rank",
        "lacerating_strikes_mongoose_bite_bleed_40pct_over_21s",
    ),
    "missing_mechanics": (
        "individual_pet_attack_speed_and_skill_rank/focus state (family attack speed is metadata only)",
        "ammo_and_quiver_haste",
        "multi_shot_pack_leveling",
        "survival_counterattack_reactive_parry_cadence_and_strider_kick_base_mana_pricing",
        "survival_l41_l60_talent_tree_legality/effects",
        "beast_mastery_summon_hawk_spawned_hawk_sustained_attack_table",
        "beast_mastery_pet_focus_skill_rank_state_for_bestial_discipline",
        "beast_mastery_improved_mend_pet_policy_and_cleanse_value",
    ),
}


def normalize_primary_school(value):
    value = str(value or "all").lower()
    return value if value in PRIMARY_SCHOOLS else "all"
