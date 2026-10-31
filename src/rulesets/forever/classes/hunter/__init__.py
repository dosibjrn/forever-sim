"""Forever Hunter compatibility exports, loaded only when requested.

G50b: source-backed generic IR imports this package's fact submodules.
Importing those facts must NOT eagerly load the historical scorer/engine.
Explicit engine imports and historical package-level exports remain supported.
"""
from __future__ import annotations

from importlib import import_module

__all__ = ('annotations', 'RULESET', 'CLASS_NAME', 'ENGINE_KIND', 'FAST_SUPPORTED', 'MC_SUPPORTED', 'EXPERIMENTAL', 'VERIFIED_LEVEL_CAP', 'PLANNING_LEVEL_CAP', 'HUNTER_CAPABILITY_MATRIX', 'DATA_PROVENANCE', 'DATA_BUILD', 'DATA_ATTRIBUTION', 'DATA_QUALITY', 'MODEL_FIDELITY', 'TREE_NAMES', 'PRIMARY_SCHOOL_ENV', 'PRIMARY_SCHOOLS', 'normalize_primary_school', 'Talents', 'TALENT_RULES', 'tree_points', 'legal_add', 'add_point', 'final_allocation', 'talent_preference_key', 'experimental_level_score', 'marginal_stat_weights')


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    engine = import_module(".engine", __name__)
    value = getattr(engine, name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
