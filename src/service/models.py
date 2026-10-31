from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
import hashlib
import json
from typing import Any

from src.forever_build import canonical_request_as_of
from src.version import SOFTWARE_VERSION


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class JobRequest:
    ruleset: str
    class_name: str
    start_level: int
    end_level: int
    objective: str = "cumulative"
    endpoint_mode: str = "smooth"
    source_snapshot: str = "current"
    engine_semantic_hash: str = "current"
    policy_space_version: str = "current"
    forever_build_as_of: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    validation_modes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.ruleset.strip():
            raise ValueError("ruleset must be non-empty")
        if not self.class_name.strip():
            raise ValueError("class_name must be non-empty")
        if int(self.start_level) < 1:
            raise ValueError("start_level must be >= 1")
        if int(self.end_level) < int(self.start_level):
            raise ValueError("end_level must be >= start_level")
        object.__setattr__(self, "forever_build_as_of", canonical_request_as_of(self.ruleset, self.forever_build_as_of))
        config = dict(self.config or {})
        # Every newly-created durable job is tagged with the code version that
        # will produce its attempts/publications.  Old persisted jobs intentionally
        # remain untagged and are treated as legacy/unknown by thin clients.
        config["producer_version"] = SOFTWARE_VERSION
        object.__setattr__(self, "config", config)

    def canonical_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["validation_modes"] = list(self.validation_modes)
        return out

    def canonical_json(self) -> str:
        return json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":"))

    def dedup_key(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()
