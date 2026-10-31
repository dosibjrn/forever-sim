from __future__ import annotations

"""Generic interpreter for normalized Forever source effects.

M43 deliberately keeps this small and explicit: the source snapshot owns numeric
facts, while class engines ask for normalized effects by semantic kind. Unknown
or server-scripted behavior remains outside this interpreter unless a source
record explicitly marks the normalized effect as supported.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

from .catalogue import ForeverSourceCatalogue, default_catalogue
from .schema import EffectRecord


class SourceRuleError(ValueError):
    pass


def _matches(effect: EffectRecord, *, kind: str, target: str | None = None,
             school: str | None = None) -> bool:
    if effect.normalization_status != "supported":
        return False
    if effect.normalized_kind != kind:
        return False
    if school is not None and str(effect.school or "").lower() != str(school).lower():
        return False
    if target is not None:
        actual = effect.metadata.get("target")
        if actual != target:
            return False
    return True


@dataclass(frozen=True)
class SourceRuleInterpreter:
    catalogue: ForeverSourceCatalogue

    def talent_effects(self, class_key: str, talent_key: str, rank: int) -> tuple[EffectRecord, ...]:
        rank = int(rank)
        if rank <= 0:
            return ()
        talent = self.catalogue.talent(class_key, talent_key)
        for row in talent.rank_records:
            if int(row.rank) == rank:
                return tuple(row.effects)
        raise SourceRuleError(f"no normalized rank record for {class_key}:{talent_key} rank {rank}")

    def talent_value(self, class_key: str, talent_key: str, rank: int, kind: str, *,
                     target: str | None = None, school: str | None = None) -> float:
        if int(rank) <= 0:
            return 0.0
        matches = [e for e in self.talent_effects(class_key, talent_key, rank)
                   if _matches(e, kind=kind, target=target, school=school)]
        if len(matches) != 1:
            raise SourceRuleError(
                f"expected one supported {kind} effect for {class_key}:{talent_key} rank {rank}, got {len(matches)}"
            )
        value = matches[0].base_value
        if value is None:
            value = matches[0].coefficient
        if value is None:
            value = matches[0].proc_chance
        if value is None:
            raise SourceRuleError(f"normalized effect has no numeric value: {class_key}:{talent_key}:{kind}")
        return float(value)

    def spell_value(self, class_key: str, family_key: str, level: int, kind: str, *,
                    target: str | None = None, school: str | None = None) -> float:
        row = self.catalogue.spell_rank(class_key, family_key, level=int(level))
        matches = [e for e in row.effects if _matches(e, kind=kind, target=target, school=school)]
        if len(matches) != 1:
            raise SourceRuleError(
                f"expected one supported {kind} effect for {class_key}:{family_key}@{level}, got {len(matches)}"
            )
        value = matches[0].base_value
        if value is None:
            value = matches[0].coefficient
        if value is None:
            value = matches[0].proc_chance
        if value is None:
            raise SourceRuleError(f"normalized spell effect has no numeric value: {class_key}:{family_key}:{kind}")
        return float(value)

    def spell_family_value(self, class_key: str, family_key: str, kind: str, *,
                           target: str | None = None, school: str | None = None) -> float:
        """Return one rank-invariant normalized value anchored by the canonical family.

        This is for mechanics such as spell-power coefficients that are identical
        across ranks but where the source snapshot intentionally carries only a
        representative rank/helper anchor.  If multiple captured ranks expose the
        effect they must agree exactly; otherwise the source is ambiguous and the
        interpreter fails closed.
        """
        matches=[]
        for row in self.catalogue.spell_family(class_key, family_key):
            matches.extend(e for e in row.effects if _matches(e, kind=kind, target=target, school=school))
        if not matches:
            raise SourceRuleError(
                f"expected at least one supported family {kind} effect for {class_key}:{family_key}, got 0"
            )
        values=[]
        for effect in matches:
            value=effect.base_value
            if value is None:
                value=effect.coefficient
            if value is None:
                value=effect.proc_chance
            if value is None:
                raise SourceRuleError(f"normalized family effect has no numeric value: {class_key}:{family_key}:{kind}")
            values.append(float(value))
        first=values[0]
        if any(abs(v-first) > 1e-12 for v in values[1:]):
            raise SourceRuleError(
                f"inconsistent supported family {kind} effects for {class_key}:{family_key}: {values}"
            )
        return first


@lru_cache(maxsize=4)
def default_rules(snapshot_id: str | None = None) -> SourceRuleInterpreter:
    cat = default_catalogue() if snapshot_id is None else ForeverSourceCatalogue(snapshot_id=snapshot_id)
    return SourceRuleInterpreter(cat)
