from __future__ import annotations

"""Forever tuning rows adapted into backend-neutral Game IR field overlays."""

from datetime import date

from src.game.model.overlay import FieldOverlay
from src.rulesets.forever.shared.tuning import active_spell_tuning


def direct_damage_overlays(
    *,
    class_key: str,
    family_key: str,
    as_of: date | str | None = None,
) -> tuple[FieldOverlay, ...]:
    """Translate active ruleset tuning into generic direct-damage field paths.

    This adapter is allowed to know the source tuning schema. The overlay model
    and normalizer stay class-neutral.
    """
    out: list[FieldOverlay] = []
    for idx, row in enumerate(active_spell_tuning(class_key, family_key, as_of=as_of)):
        multiplier = float(row.base_damage_multiplier)
        if multiplier == 1.0:
            continue
        provenance = ({
            "provider": "blizzard_forums",
            "source_kind": "dated_forever_beta_tuning",
            "url": row.source_url,
            "note": row.source_note,
            "effective_from": row.effective_from.isoformat(),
            "approximate": bool(row.approximate),
        },)
        for field_name in ("base_min", "base_max"):
            path = f"effects.0.{field_name}"
            unsupported = ()
            if row.approximate:
                unsupported = ({
                    "code": "approximate_tuning_magnitude",
                    "field_path": path,
                    "status": "explicit_approximation",
                    "detail": "Source describes the tuning magnitude approximately; executable IR uses the published approximate multiplier until an exact server value is sourced.",
                    "source_note": row.source_note,
                },)
            out.append(FieldOverlay(
                id=f"forever:{class_key}:{family_key}:{row.effective_from.isoformat()}:{idx}:{field_name}",
                target_path=path,
                operation="multiply",
                value=multiplier,
                effective_from=row.effective_from.isoformat(),
                provenance=provenance,
                unsupported_semantics=unsupported,
                metadata={
                    "class_key": str(class_key),
                    "family_key": str(family_key),
                    "source_override_kind": "base_damage_multiplier",
                },
            ))
    return tuple(out)
