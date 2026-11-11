"""Class-specific native adapters for the ONE shared sampled optimizer.

The search, native-paid receipt ranking and HTML publisher are class-neutral.
An adapter supplies only the class-specific Rust request/prepare/APL proposal
producer; it must not invent combat mechanics or bypass native legality.
A new supported class is added as tools.wf_<class>_native_persistent_optimizer
with PersistentNativeEvaluator and optional DEFAULT_NATIVE_SOURCE.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Callable


FOREVER_CLASSES = frozenset((
    "druid", "hunter", "mage", "paladin", "priest",
    "rogue", "shaman", "warlock", "warrior",
))


class NativeAdapterUnavailable(LookupError):
    """A game class exists but its source-paid native adapter is not ready."""


def normalize_class_name(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("native optimizer class must be a string")
    name = value.strip().lower()
    if name not in FOREVER_CLASSES:
        raise ValueError(
            f"unknown Forever class {value!r}; choose one of: "
            + ", ".join(sorted(FOREVER_CLASSES))
        )
    return name


@dataclass(frozen=True)
class NativeClassAdapter:
    class_name: str
    evaluator_factory: Callable[..., Any]
    default_source: Path | None = None


def resolve_native_class_adapter(class_name: str) -> NativeClassAdapter:
    """Load a class plugin only when performing a real native-paid run.

    The shared optimizer may be exercised using an injected evaluator for any
    class without importing the class's native adapter.
    """
    name = normalize_class_name(class_name)
    module_name = f"tools.wf_{name}_native_persistent_optimizer"
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            raise  # Do not disguise broken dependencies as absent adapters.
        raise NativeAdapterUnavailable(
            f"source-native adapter for {name!r} is not implemented; "
            f"expected {module_name}.PersistentNativeEvaluator"
        ) from exc
    factory = getattr(module, "PersistentNativeEvaluator", None)
    if not callable(factory):
        raise NativeAdapterUnavailable(
            f"source-native adapter for {name!r} lacks PersistentNativeEvaluator"
        )
    default_source = getattr(module, "DEFAULT_NATIVE_SOURCE", None)
    if default_source is not None:
        default_source = Path(default_source)
    return NativeClassAdapter(
        class_name=name,
        evaluator_factory=factory,
        default_source=default_source,
    )
