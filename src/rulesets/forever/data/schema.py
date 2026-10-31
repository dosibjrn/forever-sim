from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


SCHEMA_VERSION = 1
PARSER_VERSION = "forever-source-v1"


def _tuple_of_dicts(value: Any) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    return tuple(dict(v) for v in value)


@dataclass(frozen=True)
class SourceRef:
    provider: str
    ruleset: str
    entity_kind: str
    entity_id: int | str
    url: str
    retrieved_at: str
    content_fingerprint: str
    parser_version: str = PARSER_VERSION
    source_patch: str | None = None
    source_build: str | None = None
    confidence: str = "high"
    fingerprint_scope: str = "normalized_capture"
    notes: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "SourceRef":
        data = dict(raw)
        data["notes"] = tuple(data.get("notes") or ())
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EffectRecord:
    source_effect_index: int | None = None
    source_effect_type: str | None = None
    source_aura_type: str | None = None
    base_value: float | None = None
    coefficient: float | None = None
    period_s: float | None = None
    proc_chance: float | None = None
    school: str | None = None
    trigger_spell_id: int | None = None
    radius: float | None = None
    raw_text_summary: str | None = None
    server_side_script: bool = False
    normalized_kind: str | None = None
    normalization_status: str = "unsupported"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "EffectRecord":
        return cls(**dict(raw))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SpellRankRecord:
    spell_id: int
    family_key: str
    name: str
    class_key: str
    source_ref: SourceRef
    rank_label: str | None = None
    required_level: int | None = None
    school: str | None = None
    resource_type: str | None = None
    resource_cost: dict[str, Any] | None = None
    cast_time_s: float | None = None
    channel_time_s: float | None = None
    cooldown_s: float | None = None
    gcd_s: float | None = None
    duration_s: float | None = None
    range_yards: float | None = None
    radius_yards: float | None = None
    effects: tuple[EffectRecord, ...] = ()
    flags: tuple[str, ...] = ()
    icon_key: str | None = None
    relations: tuple[dict[str, Any], ...] = ()
    source_status: str = "resolved"
    entity_role: str = "spell_rank"

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "SpellRankRecord":
        data = dict(raw)
        data["source_ref"] = SourceRef.from_dict(data["source_ref"])
        data["effects"] = tuple(EffectRecord.from_dict(v) for v in data.get("effects") or ())
        data["flags"] = tuple(data.get("flags") or ())
        data["relations"] = _tuple_of_dicts(data.get("relations"))
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TalentRankRecord:
    rank: int
    source_ref: SourceRef
    spell_id: int | None = None
    trait_id: int | None = None
    effects: tuple[EffectRecord, ...] = ()

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "TalentRankRecord":
        data = dict(raw)
        data["source_ref"] = SourceRef.from_dict(data["source_ref"])
        data["effects"] = tuple(EffectRecord.from_dict(v) for v in data.get("effects") or ())
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TalentRecord:
    local_key: str
    name: str
    class_key: str
    tree_key: str
    max_rank: int
    source_refs: tuple[SourceRef, ...]
    rank_records: tuple[TalentRankRecord, ...] = ()
    row: int | None = None
    col: int | None = None
    prerequisite: str | None = None
    icon_key: str | None = None
    source_status: str = "resolved"
    aliases: tuple[str, ...] = ()

    @property
    def canonical_spell_id(self) -> int | None:
        ids = [r.spell_id for r in self.rank_records if r.spell_id is not None]
        if ids:
            return int(ids[-1])
        for ref in self.source_refs:
            if ref.provider == "wowhead" and ref.entity_kind in {"spell", "talent"}:
                try:
                    return int(ref.entity_id)
                except (TypeError, ValueError):
                    return None
        return None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "TalentRecord":
        data = dict(raw)
        data["source_refs"] = tuple(SourceRef.from_dict(v) for v in data.get("source_refs") or ())
        data["rank_records"] = tuple(TalentRankRecord.from_dict(v) for v in data.get("rank_records") or ())
        data["aliases"] = tuple(data.get("aliases") or ())
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
