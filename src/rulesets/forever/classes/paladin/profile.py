from __future__ import annotations

from src.rulesets.forever.shared import DataProvenance, VERIFIED_LEVEL_CAP

RULESET = "forever"
CLASS_NAME = "paladin"
ENGINE_KIND = "experimental_leveling"
FAST_SUPPORTED = True
MC_SUPPORTED = False
EXPERIMENTAL = True
# Keep a deeper smooth finalist pool for deterministic event validation.  This
# is deliberately separate from the user-visible ``final_k`` and does not add
# stat-weight/envelope probes to the beam search itself.
VALIDATION_CANDIDATE_K = 20

TREE_NAMES = ("holy", "protection", "retribution")
PRIMARY_SCHOOL_ENV = "PALADIN_LEVELING_PROFILE"
PRIMARY_SCHOOLS = ("all", "holy", "protection", "retribution")

DATA_PROVENANCE = DataProvenance(
    build="Forever beta client 1.60.1.69893",
    attribution="Client-derived Paladin talent/spellbook data cross-checked against current Wowhead Forever spell pages; selected level>30 ranks are public-database derived",
    quality={
        "talents": "client-derived tree snapshot; selected modeled effects implemented",
        "core_spells": "69893 client values through the verified beta cap plus current Wowhead Forever modeled ranks where explicitly audited",
        "gear": "normal-quality 2H / 1H+shield per-level curves with visible gear snapshots and gameplay-aware marginal stat guidance; NOT literal item ownership",
        "combat": "deterministic expected-value pack/survival proxy; MC disabled",
    },
)
DATA_BUILD = DATA_PROVENANCE.build
DATA_ATTRIBUTION = DATA_PROVENANCE.attribution
DATA_QUALITY = DATA_PROVENANCE.quality

MODEL_FIDELITY = {
    "backend": "deterministic_expected_value_pack",
    "pull_model": "multi_pull_1_to_4",
    "resource_continuity": "cycle_consistent_hp_mana_proxy",
    "survival": "whole_heal_casts_plus_emergency_windows",
    "gear": "continuous_level_field_plus_per_level_analytic_named_slot_reroll",
    "event_validator": "deterministic_damage_survival_timeline_v2_heals_utility_shield_state",
    "mc_validated": False,
    "rating": "experimental_medium",
}


def normalize_primary_school(value):
    value = str(value or "all").lower()
    return value if value in PRIMARY_SCHOOLS else "all"
