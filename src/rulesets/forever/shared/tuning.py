from __future__ import annotations

"""Dated WoW: Forever beta tuning overrides.

Public spell pages can lag a beta build.  Raw spell/rank facts therefore stay in
class data modules, while build-level tuning changes live here and are applied
at scoring time.  This keeps provenance explicit and avoids rewriting stale
public tooltip rows as if they were current server values.
"""

from dataclasses import dataclass
from datetime import date

from src.forever_build import LEGACY_COMPAT_AS_OF, current as current_forever_build, parse_as_of

# Compatibility alias for callers/tests written before explicit build identity.
# Production calls resolve through src.forever_build.current().
DEFAULT_AS_OF = LEGACY_COMPAT_AS_OF


@dataclass(frozen=True)
class SpellTuningOverride:
    class_name: str
    spell_key: str
    effective_from: date
    base_damage_multiplier: float = 1.0
    source_url: str = ""
    source_note: str = ""
    approximate: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "class_name": self.class_name,
            "spell_key": self.spell_key,
            "effective_from": self.effective_from.isoformat(),
            "base_damage_multiplier": float(self.base_damage_multiplier),
            "source_url": self.source_url,
            "source_note": self.source_note,
            "approximate": bool(self.approximate),
        }


SPELL_TUNING_OVERRIDES = (
    SpellTuningOverride(
        class_name="druid",
        spell_key="wrath",
        effective_from=date(2026, 9, 24),
        base_damage_multiplier=1.50,
        source_url=(
            "https://us.forums.blizzard.com/en/wow/t/"
            "wow-forever-beta-development-notes-%E2%80%93-updated-september-24/2360696"
        ),
        source_note="Wrath base damage increased ~50% in the September 24 beta build.",
        approximate=True,
    ),
)


def _resolve_as_of(as_of: date | str | None) -> date:
    return current_forever_build().as_of if as_of is None else parse_as_of(as_of)


def active_spell_tuning(class_name: str, spell_key: str, *, as_of: date | str | None = None) -> tuple[SpellTuningOverride, ...]:
    cls = str(class_name).strip().lower()
    spell = str(spell_key).strip().lower()
    resolved_as_of = _resolve_as_of(as_of)
    return tuple(
        row for row in SPELL_TUNING_OVERRIDES
        if row.class_name == cls and row.spell_key == spell and row.effective_from <= resolved_as_of
    )


def base_damage_multiplier(class_name: str, spell_key: str, *, as_of: date | str | None = None) -> float:
    value = 1.0
    for row in active_spell_tuning(class_name, spell_key, as_of=as_of):
        value *= float(row.base_damage_multiplier)
    return value


def tuning_provenance(class_name: str, spell_key: str, *, as_of: date | str | None = None) -> list[dict[str, object]]:
    return [row.as_dict() for row in active_spell_tuning(class_name, spell_key, as_of=as_of)]
