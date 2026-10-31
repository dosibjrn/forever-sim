from __future__ import annotations

"""Active mechanics-engine registry.

Production modules import ``eng`` from here instead of importing a concrete
class/ruleset module.  The proxy resolves attributes lazily, which keeps the
existing engine-shaped API intact while allowing CLI selection before worker
processes and state paths are created.
"""

import importlib
from types import ModuleType
from typing import Any

from src import game_context
from src.class_registry import definitions, get_definition

# Backward-compatible read-only-ish mapping for architecture/tests and older
# callers. The authoritative source is ClassDefinition; this view is derived
# once from the registry and contains no independently maintained class list.
_ENGINE_MODULES = {(d.ruleset, d.class_name): d.engine_module for d in definitions()}

# Parse selection as early as possible.  Spawned workers inherit the environment
# and therefore resolve the exact same module even when their argv differs.
game_context.configure_from_argv()

_cached_key: tuple[str, str] | None = None
_cached_module: ModuleType | None = None


def get_engine() -> ModuleType:
    global _cached_key, _cached_module
    spec = game_context.current()
    key = (spec.ruleset, spec.class_name)
    if key != _cached_key or _cached_module is None:
        definition = get_definition(*key)
        _cached_module = importlib.import_module(definition.engine_module)
        _cached_key = key
    return _cached_module


def reset_engine_cache() -> None:
    global _cached_key, _cached_module
    _cached_key = None
    _cached_module = None


class _EngineProxy:
    def __getattr__(self, name: str) -> Any:
        return getattr(get_engine(), name)

    def __dir__(self):
        return sorted(set(dir(type(self))) | set(dir(get_engine())))

    def __repr__(self) -> str:
        return f"<EngineProxy -> {get_engine().__name__}>"


eng = _EngineProxy()
