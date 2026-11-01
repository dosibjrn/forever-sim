from __future__ import annotations

"""Source-versioned, class-neutral primary stat -> combat/resource conversion.

These facts are additive transformations of an existing source Actor IR. The
provider supplies the actual base attributes and the canonical SQLite supplies
the conversion coefficients. A resource with an explicitly qualified proxy
baseline can opt into *delta_only* conversion: gear changes are executable,
while its unverifiable naked base health is never silently asserted as truth.
"""

from dataclasses import dataclass, replace
from math import isfinite
from pathlib import Path
import sqlite3

from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.model.ir import GameIRSlice


@dataclass(frozen=True)
class PrimaryStatConversion:
    class_key: str
    source_stat: str
    target_type: str
    target_id: str
    coefficient: float
    baseline: str
    operation: str
    threshold: float | None
    below_coefficient: float | None
    authority: str
    source_url: str
    source_date: str
    evidence: str
    capture_id: str

    def as_dict(self) -> dict:
        return {key: getattr(self, key) for key in self.__dataclass_fields__}


def load_primary_stat_conversions(class_key: str, *, db_path: Path | None = None) -> tuple[PrimaryStatConversion, ...]:
    path = Path(db_path or DEFAULT_DB)
    if not path.is_file():
        raise FileNotFoundError(f'canonical primary-stat SQLite missing: {path}')
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute('''SELECT * FROM actor_stat_conversion_source_facts
                WHERE class_key IN ('*', ?) ORDER BY source_stat,target_type,target_id''',
                (str(class_key).lower(),)).fetchall()
        except sqlite3.OperationalError as exc:
            raise ValueError('canonical actor stat conversion table missing') from exc
    facts = []
    targets = set()
    for row in rows:
        fact = PrimaryStatConversion(**{key: row[key] for key in PrimaryStatConversion.__dataclass_fields__})
        key = (fact.source_stat, fact.target_type, fact.target_id)
        if (key in targets or not all((fact.source_stat, fact.target_id, fact.class_key,
                                       fact.authority, fact.source_url, fact.source_date,
                                       fact.evidence, fact.capture_id))
                or fact.target_type not in ('stat', 'resource_capacity')
                or fact.baseline not in ('total', 'delta_only')
                or (fact.target_type == 'stat' and fact.baseline != 'total')
                or (fact.target_type == 'resource_capacity' and fact.baseline != 'delta_only')
                or fact.operation not in ('linear', 'threshold_linear')
                or (fact.operation == 'linear' and
                    (fact.threshold is not None or fact.below_coefficient is not None))
                or (fact.operation == 'threshold_linear' and
                    (fact.threshold is None or fact.below_coefficient is None or
                     not isfinite(float(fact.threshold)) or float(fact.threshold) < 0 or
                     not isfinite(float(fact.below_coefficient)) or
                     float(fact.below_coefficient) <= 0))
                or not isfinite(float(fact.coefficient)) or float(fact.coefficient) <= 0):
            raise ValueError('invalid or conflicting canonical primary stat conversion')
        targets.add(key)
        facts.append(fact)
    return tuple(facts)


def source_enrich_primary_stats(ir: GameIRSlice, *, db_path: Path | None = None) -> GameIRSlice:
    """Compile canonical total-stat conversions into the Actor once.

    Gear delta and talent deltas subsequently use the *same* attached facts.
    The health proxy baseline is retained; only sourced gear Stamina deltas
    modify its capacity. This does not claim authoritative naked HP.
    """
    if 'canonical_primary_stat_conversions' in ir.actor.metadata:
        raise ValueError('canonical primary stat conversions applied twice')
    key = str(ir.actor.metadata.get('class_key', '')).lower()
    if not key:
        raise ValueError('source actor class key missing')
    facts = load_primary_stat_conversions(key, db_path=db_path)
    if not facts:
        return ir
    stats = {str(k): float(v) for k, v in ir.actor.base_stats.items()}
    resources = {r.id for r in ir.resources if r.owner_actor_id == ir.actor.id}
    missing_base = {}
    for fact in facts:
        if fact.source_stat not in stats:
            # A delta-only resource rule can act on sourced *gear changes*
            # without inventing an unknown naked primary stat. The threshold
            # is an explicit marginal assumption, not a fabricated actor stat.
            if (fact.target_type == 'resource_capacity' and fact.baseline == 'delta_only'
                    and fact.target_id in resources and fact.class_key != '*'):
                missing_base[fact.source_stat] = {
                    'assumed_at_least': float(fact.threshold or 0.),
                    'status': 'UNKNOWN_NAKED_STAT_GEAR_MARGINAL_ONLY',
                    'source_url': fact.source_url, 'capture_id': fact.capture_id,
                }
                continue
            if fact.class_key == '*':
                continue
            raise ValueError(f'canonical primary stat source absent: {fact.source_stat}')
        if fact.target_type == 'stat':
            stats[fact.target_id] = float(stats.get(fact.target_id, 0.0)) + (
                float(stats[fact.source_stat]) * float(fact.coefficient))
        elif fact.target_id not in resources:
            # Global rules may target a resource this actor does not possess
            # (e.g. mana conversion on a non-mana actor). Such a rule is not
            # applicable, never an instruction to manufacture that resource.
            if fact.class_key == '*':
                continue
            raise ValueError(f'canonical primary resource target absent: {fact.target_id}')
    source = tuple(f.as_dict() for f in facts if
        (f.source_stat in stats or f.source_stat in missing_base) and
        (f.target_type != 'resource_capacity' or f.target_id in resources))
    actor = replace(ir.actor, base_stats=stats,
        metadata={**dict(ir.actor.metadata), 'canonical_primary_stat_conversions': source,
                  'canonical_missing_base_stat_proxies': missing_base},
        provenance=ir.actor.provenance + ({'stage': 'canonical_primary_stat_conversions',
            'source_facts': source, 'health_baseline': 'qualified_proxy_delta_only'},))
    return replace(ir, actor=actor,
        provenance={**dict(ir.provenance), 'canonical_primary_stat_conversions': source})


# Public compatibility alias; executor uses the same class-neutral arithmetic.
from src.game.stat_math import converted_stat_amount
