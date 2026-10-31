from __future__ import annotations

"""Forever Warrior M45 onboarding-proof engine facade."""

from .profile import (
    RULESET, CLASS_NAME, ENGINE_KIND, FAST_SUPPORTED, MC_SUPPORTED, EXPERIMENTAL,
    VERIFIED_LEVEL_CAP, DATA_PROVENANCE, DATA_BUILD, DATA_ATTRIBUTION, DATA_QUALITY,
    MODEL_FIDELITY, TREE_NAMES, PRIMARY_SCHOOL_ENV, PRIMARY_SCHOOLS,
    normalize_primary_school,
)
from .talents import (
    Talents, TALENT_RULES, tree_points, legal_add, add_point,
    final_allocation, talent_preference_key,
)
from .mechanics import experimental_level_score, marginal_stat_weights

__all__ = [name for name in globals() if not name.startswith("_")]
