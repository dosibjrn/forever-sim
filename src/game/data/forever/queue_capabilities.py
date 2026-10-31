"""G50h: narrowly *proven* source-only queued Decision capabilities.

Independent of both full-leveling/default eligibility and route planning. Exact
levels are admission declarations; unknown/missing providers fail closed.
Keep this separate from route snapshot fingerprints and the gameplay IR.
"""
from __future__ import annotations

from pathlib import Path

from .registry import registered_class_keys, generic_source_level_bounds

# Individually smoke-executed with the native generic Decision builder.
# Do NOT infer a continuous corridor from these observations.
_DECLARED_QUEUE_LEVELS = {
    "druid": (10, 11),
    "warrior": (10,), "rogue": (10,), "priest": (10,),
    "shaman": (10,), "warlock": (10,), "mage": (10,),
}
PINNED_FOREVER_AS_OF = "2026-10-08"


def native_generic_queue_levels(class_key: str) -> tuple[int, ...]:
    key = str(class_key).strip().lower()
    if key not in registered_class_keys():
        return ()
    bounds = generic_source_level_bounds(key)
    if bounds is None:
        return ()
    declared = _DECLARED_QUEUE_LEVELS.get(key, ())
    # Misconfigured declarations are rejected wholesale, not clipped.
    if len(set(declared)) != len(declared) or any(
        not isinstance(n, int) or n < bounds[0] or n > bounds[1]
        for n in declared
    ):
        return ()
    return tuple(sorted(declared))


def native_generic_queue_supported(class_key: str, level: int) -> bool:
    return type(level) is int and level in native_generic_queue_levels(class_key)


def require_native_generic_queue(class_key: str, level: int) -> str:
    key = str(class_key).strip().lower()
    if not native_generic_queue_supported(key, level) or key != class_key:
        raise ValueError("native generic queue scope not declared for class/level")
    return key


def native_generic_queue_artifact(class_key: str, level: int) -> Path:
    key = require_native_generic_queue(class_key, level)
    return Path("generic") / "decisions" / f"forever-{key}-L{level}.json"
