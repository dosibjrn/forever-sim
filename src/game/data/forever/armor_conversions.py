from __future__ import annotations
"""Class-neutral canonical source → Armor IR conversion, including mode gear bonus."""
from dataclasses import dataclass, replace
from pathlib import Path
import math
import re
import sqlite3

from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.model.ir import GameIRSlice, ModeStatModifier


@dataclass(frozen=True)
class ArmorSourceRule:
    class_key: str
    scope: str
    mode_label: str
    source_stat: str
    target_stat: str
    operation: str
    coefficient: float
    authority: str
    source_url: str
    source_date: str
    evidence: str
    capture_id: str


def load_armor_rules(class_key: str, *, db_path: Path | None = None) -> tuple[ArmorSourceRule, ...]:
    path = Path(db_path or DEFAULT_DB)
    if not path.is_file():
        raise FileNotFoundError(f'canonical armor SQLite missing: {path}')
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute('''SELECT * FROM armor_conversion_source_facts
                WHERE class_key IN ('*', ?) ORDER BY scope, class_key, mode_label, source_stat''',
                (str(class_key).lower(),)).fetchall()
        except sqlite3.OperationalError as exc:
            raise ValueError('canonical armor conversion facts missing') from exc
    result = []
    for r in rows:
        if (not all(r[k] for k in ('class_key','scope','source_stat','target_stat','operation',
                                    'authority','source_url','source_date','evidence','capture_id'))
                or r['scope'] not in ('actor','mode') or r['operation'] != 'add_stat_scaled'
                or r['target_stat'] != 'armor' or (r['scope'] == 'mode' and not r['mode_label'])
                or (r['scope'] == 'actor' and r['mode_label'])
                or not math.isfinite(float(r['coefficient'])) or r['coefficient'] <= 0):
            raise ValueError('invalid canonical armor source fact')
        result.append(ArmorSourceRule(**{key: r[key] for key in ArmorSourceRule.__dataclass_fields__}))
    return tuple(result)


def _label(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', str(value).lower()).strip('_')


def source_enrich_armor(ir: GameIRSlice, *, db_path: Path | None = None) -> GameIRSlice:
    """One-time IR source enrichment, not a Druid/stat hardcoded ruleset.

    Gear is applied separately; it recalculates actor armor from the source
    actor-agility rule and adds mode item-armor extra only to the sourced mode.
    """
    if ir.actor.metadata.get('canonical_armor_source_rules'):
        raise ValueError('armor source facts applied twice')
    key = str(ir.actor.metadata.get('class_key', '')).lower()
    if not key:
        raise ValueError('canonical actor class is required for armor source facts')
    rules = load_armor_rules(key, db_path=db_path)
    if not rules:
        return ir
    base = {str(k): float(v) for k,v in dict(ir.actor.base_stats).items()}
    modes = list(ir.modes)
    by_label = {_label(mode.label): i for i,mode in enumerate(modes)}
    actor_rules = []
    for rule in rules:
        source = {'authority':rule.authority,'source_url':rule.source_url,
                  'source_date':rule.source_date,'capture_id':rule.capture_id,
                  'source_stat':rule.source_stat,'target_stat':rule.target_stat,
                  'coefficient':rule.coefficient,'scope':rule.scope}
        if rule.scope == 'actor':
            if rule.source_stat not in base:
                raise ValueError(f'actor armor source stat absent: {rule.source_stat}')
            if not actor_rules and 'armor' in base:
                raise ValueError('actor armor is already defined; would double count')
            base['armor'] = base.get('armor', 0.0) + base[rule.source_stat]*rule.coefficient
            actor_rules.append(source)
        else:
            idx = by_label.get(_label(rule.mode_label))
            if idx is None:
                # Some modes are not yet learned at a given level.
                continue
            mode = modes[idx]
            modes[idx] = replace(mode, stat_modifiers=mode.stat_modifiers + (
                ModeStatModifier(target_stat=rule.target_stat,kind='add_stat_scaled',
                                 source_stat=rule.source_stat,value=rule.coefficient),),
                provenance=mode.provenance+(source,),
                metadata={**dict(mode.metadata),'item_armor_multiplier':1.0+rule.coefficient})
    metadata = {**dict(ir.actor.metadata),'canonical_armor_source_rules':actor_rules}
    if actor_rules or any(r.scope == 'mode' for r in rules):
        metadata['__equipped_armor_source_stat'] = '__equipped_item_armor'
        base['__equipped_item_armor'] = 0.0
    return replace(ir,actor=replace(ir.actor,base_stats=base,metadata=metadata,
                   provenance=ir.actor.provenance+tuple(actor_rules)),modes=tuple(modes))
