from __future__ import annotations

"""Normalize canonical Forever talent facts into backend-neutral Talent IR."""

from typing import Any

from src.game.model.ir import TalentDefinition, TalentModifier, TalentRankDefinition
from src.rulesets.forever.data.schema import TalentRecord


_SUPPORTED_ACTION_MODIFIERS = {"cast_time_delta_s", "resource_cost_pct"}


def normalize_talent_definition(record: TalentRecord) -> TalentDefinition:
    ranks: list[TalentRankDefinition] = []
    for rank_record in record.rank_records:
        modifiers: list[TalentModifier] = []
        for effect in rank_record.effects:
            kind = str(effect.normalized_kind or "")
            target = str((effect.metadata or {}).get("target") or "")
            if effect.normalization_status != "supported" or kind not in _SUPPORTED_ACTION_MODIFIERS or not target:
                continue
            value = effect.base_value
            if value is None:
                value = effect.coefficient
            if value is None:
                continue
            modifiers.append(TalentModifier(
                kind=kind,
                target_type="action_family",
                target_id=target,
                value=float(value),
                provenance={
                    "source": rank_record.source_ref.to_dict(),
                    "raw_text_summary": effect.raw_text_summary,
                    "normalization_status": effect.normalization_status,
                    "source_effect_type": effect.source_effect_type,
                },
            ))
        ranks.append(TalentRankDefinition(
            rank=int(rank_record.rank),
            modifiers=tuple(modifiers),
            provenance={
                "source": rank_record.source_ref.to_dict(),
                "spell_id": rank_record.spell_id,
                "trait_id": rank_record.trait_id,
            },
        ))
    return TalentDefinition(
        id=str(record.local_key),
        name=str(record.name),
        tree_key=str(record.tree_key),
        max_rank=int(record.max_rank),
        prerequisite=(None if record.prerequisite is None else {
            "talent_id": str(record.prerequisite),
            "required_rank": None,
            "status": "canonical_prerequisite_present_rank_not_normalized",
        }),
        ranks=tuple(ranks),
        provenance=tuple(ref.to_dict() for ref in record.source_refs),
        metadata={
            "class_key": str(record.class_key),
            "row": record.row,
            "col": record.col,
            "source_status": record.source_status,
            "canonical_prerequisite": record.prerequisite,
        },
    )
