from __future__ import annotations

"""Forever Druid compatibility facade for the optimizer registry."""

from .profile import (
    RULESET, CLASS_NAME, ENGINE_KIND, FAST_SUPPORTED, MC_SUPPORTED, EXPERIMENTAL,
    DATA_PROVENANCE, DATA_BUILD, DATA_ATTRIBUTION, DATA_QUALITY, MODEL_FIDELITY,
    VERIFIED_LEVEL_CAP, PLANNING_LEVEL_CAP, DRUID_CAPABILITY_MATRIX,
    TREE_NAMES, PRIMARY_SCHOOL_ENV, PRIMARY_SCHOOLS, normalize_primary_school,
)
from .talents import (
    Talents, TALENT_RULES, TALENT_SCHEMA_BUILD, TALENT_SCHEMA_SOURCE,
    tree_points, legal_add, add_point, final_allocation, talent_preference_key,
    current_schema_errors, allocation_schema_errors, validate_current_schema,
    expected_points_for_level, level_points_complete,
)
from .spells import CAT_FORM_LEVEL, MANGLE_MODEL_LEVEL
from .mechanics import experimental_level_score, marginal_stat_weights, score_external_build

__all__ = [name for name in globals() if not name.startswith("_")]
