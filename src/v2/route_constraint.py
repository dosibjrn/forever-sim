from __future__ import annotations

"""Generic constraints for canonical route solving.

Constraints operate only on the shared candidate/DP contracts. They never score
combat and contain no class-specific talent semantics; those remain behind
``ClassModel.route_matches`` / opaque build keys.
"""

from dataclasses import dataclass, field
from typing import Any, Mapping

from .class_model import ClassModel
from .path_dp import LevelNode


def _canonical_key(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_canonical_key(v) for v in value)
    if isinstance(value, tuple):
        return tuple(_canonical_key(v) for v in value)
    if isinstance(value, dict):
        return tuple(sorted((str(k), _canonical_key(v)) for k, v in value.items()))
    return value


@dataclass(frozen=True)
class RouteConstraint:
    """A declarative restriction over an otherwise canonical route search.

    ``endpoint_definition`` uses the registry/ClassModel route-definition DSL
    and is ideal for a pinned spec/archetype. ``endpoint_build_key`` pins one
    exact target build. ``path_build_keys`` can pin any subset of level states
    (including a complete reference/talent progression). ``metadata_equals``
    constrains candidate metadata without teaching the solver class semantics.
    """

    name: str
    endpoint_definition: Mapping[str, Any] = field(default_factory=dict)
    endpoint_build_key: Any = None
    path_build_keys: Mapping[int, Any] = field(default_factory=dict)
    metadata_equals: Mapping[str, Any] = field(default_factory=dict)
    metadata_scope: str = "endpoint"  # endpoint | all_levels
    source: str = "user_constraint"

    def __post_init__(self) -> None:
        if not str(self.name).strip():
            raise ValueError("constraint name must be non-empty")
        if self.metadata_scope not in {"endpoint", "all_levels"}:
            raise ValueError("metadata_scope must be 'endpoint' or 'all_levels'")
        if not (self.endpoint_definition or self.endpoint_build_key is not None or self.path_build_keys or self.metadata_equals):
            raise ValueError("constraint must restrict at least one route property")
        if any(int(level) < 1 for level in self.path_build_keys):
            raise ValueError("path_build_keys levels must be positive")

    @classmethod
    def from_mapping(cls, name: str, raw: Mapping[str, Any]) -> "RouteConstraint":
        allowed = {"endpoint_definition", "endpoint_build_key", "path_build_keys", "metadata_equals", "metadata_scope", "source"}
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError("unknown route constraint key(s): " + ", ".join(sorted(unknown)))
        path = {int(k): _canonical_key(v) for k, v in dict(raw.get("path_build_keys") or {}).items()}
        metadata = dict(raw.get("metadata_equals") or {})
        definition = dict(raw.get("endpoint_definition") or {})
        return cls(
            name=str(name),
            endpoint_definition=definition,
            endpoint_build_key=_canonical_key(raw.get("endpoint_build_key")) if raw.get("endpoint_build_key") is not None else None,
            path_build_keys=path,
            metadata_equals=metadata,
            metadata_scope=str(raw.get("metadata_scope") or "endpoint"),
            source=str(raw.get("source") or "user_constraint"),
        )

    def definition(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": "generic_constraint", "source": self.source}
        if self.endpoint_definition:
            out["endpoint_definition"] = dict(self.endpoint_definition)
        if self.endpoint_build_key is not None:
            out["endpoint_build_key"] = self.endpoint_build_key
        if self.path_build_keys:
            out["path_build_keys"] = {str(k): v for k, v in sorted(self.path_build_keys.items())}
        if self.metadata_equals:
            out["metadata_equals"] = dict(self.metadata_equals)
            out["metadata_scope"] = self.metadata_scope
        return out

    def allows(self, node: LevelNode, *, level: int, target_level: int, model: ClassModel) -> bool:
        level = int(level); target_level = int(target_level)
        if level in self.path_build_keys and model.build_key(node.talents) != self.path_build_keys[level]:
            return False
        if level == target_level:
            if self.endpoint_build_key is not None and model.build_key(node.talents) != self.endpoint_build_key:
                return False
            if self.endpoint_definition and not model.route_matches(node.talents, self.endpoint_definition):
                return False
        if self.metadata_equals and (self.metadata_scope == "all_levels" or level == target_level):
            details = dict(node.details or {})
            candidate = details.get("candidate_result")
            metadata = dict(getattr(candidate, "metadata", {}) or {}) if candidate is not None else details
            for key, expected in self.metadata_equals.items():
                actual = metadata.get(key)
                if actual is None and candidate is not None:
                    actual = getattr(candidate, key, None)
                if actual != expected:
                    return False
        return True
