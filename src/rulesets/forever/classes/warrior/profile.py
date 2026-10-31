from __future__ import annotations

from src.rulesets.forever.shared import DataProvenance

RULESET = "forever"
CLASS_NAME = "warrior"
ENGINE_KIND = "experimental_leveling"
FAST_SUPPORTED = True
MC_SUPPORTED = False
EXPERIMENTAL = True
VERIFIED_LEVEL_CAP = 20

TREE_NAMES = ("arms", "fury", "protection")
PRIMARY_SCHOOL_ENV = "WARRIOR_LEVELING_PROFILE"
PRIMARY_SCHOOLS = ("all", "arms", "fury", "protection")

DATA_PROVENANCE = DataProvenance(
    build="Forever patch 1.60.1 public source anchors",
    attribution="M45 thin onboarding proof: pinned Wowhead Forever Heroic Strike + Arms talent identities (2026-09-25)",
)
DATA_BUILD = DATA_PROVENANCE.build
DATA_ATTRIBUTION = DATA_PROVENANCE.attribution
DATA_QUALITY = DATA_PROVENANCE.quality

MODEL_FIDELITY = {
    "backend": "thin_onboarding_proof_single_target",
    "pull_model": "single_target_only",
    "resource_continuity": "coarse_rage_budget",
    "survival": "coarse_deflection_exposure_proxy",
    "gear": "level_curve_only_no_item_catalogue",
    "mc_validated": False,
    "rating": "proof_only_low",
    "verified_public_facts": (
        "heroic_strike_rank_1_identity_cost_and_bonus_damage",
        "improved_heroic_strike_identity",
        "improved_rend_identity",
        "deflection_identity",
    ),
    "missing_mechanics": (
        "real_weapon_tables_and_rage_generation",
        "stances",
        "rend_rotation",
        "overpower_revenge_thunder_clap_cleave_and_execute",
        "real_gear_and_multi_pull_survival",
    ),
    "proof_only": True,
}


def normalize_primary_school(value):
    value = str(value or "all").lower()
    return value if value in PRIMARY_SCHOOLS else "all"
