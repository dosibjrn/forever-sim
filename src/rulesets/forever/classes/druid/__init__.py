"""Forever Druid compatibility exports, loaded only when requested.

G50b: source-backed generic IR imports this package's fact submodules.
Importing those facts must NOT eagerly load the historical scorer/engine.
Explicit engine imports and historical package-level exports remain supported.
"""
from __future__ import annotations

from importlib import import_module

__all__ = ('annotations', 'RULESET', 'CLASS_NAME', 'ENGINE_KIND', 'FAST_SUPPORTED', 'MC_SUPPORTED', 'EXPERIMENTAL', 'DATA_PROVENANCE', 'DATA_BUILD', 'DATA_ATTRIBUTION', 'DATA_QUALITY', 'MODEL_FIDELITY', 'VERIFIED_LEVEL_CAP', 'PLANNING_LEVEL_CAP', 'DRUID_CAPABILITY_MATRIX', 'TREE_NAMES', 'PRIMARY_SCHOOL_ENV', 'PRIMARY_SCHOOLS', 'normalize_primary_school', 'Talents', 'TALENT_RULES', 'TALENT_SCHEMA_BUILD', 'TALENT_SCHEMA_SOURCE', 'tree_points', 'legal_add', 'add_point', 'final_allocation', 'talent_preference_key', 'current_schema_errors', 'allocation_schema_errors', 'validate_current_schema', 'expected_points_for_level', 'level_points_complete', 'CAT_FORM_LEVEL', 'MANGLE_MODEL_LEVEL', 'experimental_level_score', 'marginal_stat_weights', 'score_external_build')


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    engine = import_module(".engine", __name__)
    value = getattr(engine, name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
