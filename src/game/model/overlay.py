from __future__ import annotations

"""Reusable field overlays for source-backed executable Game IR.

Raw game facts and dated/live ruleset tuning are deliberately separate inputs.
This module contains no class or spell knowledge: it only applies explicit
numeric operations to named IR field paths while preserving a machine-readable
trace of how each executable value was derived.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


SUPPORTED_NUMERIC_OPERATIONS = frozenset({"multiply", "add", "set"})


@dataclass(frozen=True)
class FieldOverlay:
    id: str
    target_path: str
    operation: str
    value: float
    effective_from: str | None = None
    provenance: tuple[Mapping[str, Any], ...] = ()
    unsupported_semantics: tuple[Mapping[str, Any], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.operation not in SUPPORTED_NUMERIC_OPERATIONS:
            raise ValueError(f"unsupported numeric overlay operation: {self.operation!r}")
        if not str(self.target_path).strip():
            raise ValueError("field overlay target_path must be non-empty")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "target_path": self.target_path,
            "operation": self.operation,
            "value": float(self.value),
            "effective_from": self.effective_from,
            "provenance": [dict(x) for x in self.provenance],
            "unsupported_semantics": [dict(x) for x in self.unsupported_semantics],
            "metadata": dict(self.metadata),
        }


def apply_numeric_field_overlays(
    raw_fields: Mapping[str, float],
    overlays: tuple[FieldOverlay, ...] | list[FieldOverlay],
) -> tuple[dict[str, float], dict[str, tuple[Mapping[str, Any], ...]]]:
    """Apply explicit overlays and return executable values + field traces.

    Unknown targets fail closed instead of silently adding a new semantic.
    Every output field has a raw-source trace entry even when no overlay applies.
    """
    values = {str(k): float(v) for k, v in raw_fields.items()}
    traces: dict[str, list[Mapping[str, Any]]] = {
        path: [{"stage": "raw_source", "value": float(value)}]
        for path, value in values.items()
    }
    for overlay in overlays:
        path = str(overlay.target_path)
        if path not in values:
            raise KeyError(f"overlay target is not a normalized numeric field: {path!r}")
        before = values[path]
        if overlay.operation == "multiply":
            after = before * float(overlay.value)
        elif overlay.operation == "add":
            after = before + float(overlay.value)
        else:
            after = float(overlay.value)
        values[path] = after
        traces[path].append({
            "stage": "overlay",
            "overlay_id": overlay.id,
            "operation": overlay.operation,
            "operand": float(overlay.value),
            "before": before,
            "value": after,
            "effective_from": overlay.effective_from,
            "provenance": [dict(x) for x in overlay.provenance],
        })
    return values, {path: tuple(rows) for path, rows in traces.items()}
