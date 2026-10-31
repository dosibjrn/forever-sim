"""Versioned, source-observed item EQUIP semantics (not generic item-level lore).

The Forever list-view calls rune-learning *consumables* 'Relic Idol'. A slot
label alone does not prove they can be worn. Data live in an immutable SQLite
source ledger; no item IDs or spell facts are encoded in the optimizer.

Only explicitly observed item effects are executable. Source text is a dated
Forever observation, not a verified client-70338 binary dump.
"""
from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from json import loads
from pathlib import Path
from math import isfinite
import re
import os
import sqlite3

_DEFAULT = Path(__file__).resolve().parents[4] / 'data/forever/source_equipment_semantics_70338.sqlite'

@dataclass(frozen=True)
class EquipmentSemantic:
    item_id: int
    item_name: str
    slot: str
    source_url: str
    observed_at: str
    source_scope: str
    equip_semantics: str
    typed_effects: tuple[tuple[str,str,float], ...]
    equip_group: str | None = None
    equip_limit: int | None = None
    conditional_effects: tuple[tuple[str,str,float,tuple[str,...]], ...] = ()


def ledger_path() -> Path:
    return Path(os.environ.get('FOREVER_ITEM_EQUIPMENT_SEMANTICS', _DEFAULT))


@lru_cache(maxsize=8)
def _load(path: str, mtime_ns: int, size: int) -> dict[int, EquipmentSemantic]:
    uri=Path(path).resolve().as_uri()+'?mode=ro'
    with sqlite3.connect(uri,uri=True) as con:
        if con.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('ITEM_EQUIPMENT_SEMANTICS_DB_CORRUPT')
        rows=con.execute('SELECT item_id,item_name,catalogue_slot,source_url,source_observed_at,source_scope,evidence_excerpt,evidence_sha256,equip_semantics,typed_effects_json,equip_group,equip_limit FROM source_item_equipment_semantics').fetchall()
    result={}
    for iid,name,slot,url,observed,scope,excerpt,digest,sem,effects_json,group,limit in rows:
        if (not str(url).startswith('https://www.wowhead.com/forever/item=')
            or sha256(str(excerpt).encode()).hexdigest()!=digest
            or str(iid) != url.split('/item=',1)[1].split('/',1)[0]
            or sem not in ('NON_EQUIPPABLE_RUNE_LEARNING_ITEM','EQUIPPABLE_TYPED_PASSIVE','EQUIPPABLE_UNTYPED_EFFECT','EQUIPPABLE_NONCOMBAT_USE')):
            raise ValueError('ITEM_EQUIPMENT_SEMANTICS_PROVENANCE_INVALID')
        effects=loads(effects_json)
        if sem=='NON_EQUIPPABLE_RUNE_LEARNING_ITEM' and effects:
            raise ValueError('NON_EQUIPPABLE_ITEM_HAS_EQUIP_EFFECTS')
        if (group is None) != (limit is None):
            raise ValueError('ITEM_EQUIPMENT_GROUP_INCOMPLETE')
        if group is not None:
            if not isinstance(group,str) or not group.strip() or not isinstance(limit,int) or limit<1:
                raise ValueError('ITEM_EQUIPMENT_GROUP_INVALID')
            # Do not let a forged group silently constrain builds: the source
            # observation itself must contain the Unique-Equipped wording.
            if 'Unique-Equipped' not in excerpt:
                raise ValueError('ITEM_EQUIPMENT_GROUP_SOURCE_MISSING')
            if group.startswith('Unique item:'):
                if group != f'Unique item:{iid}':
                    raise ValueError('ITEM_EQUIPMENT_GROUP_IDENTITY_MISMATCH')
            elif f'Unique-Equipped: {group} ({limit})' not in excerpt:
                raise ValueError('ITEM_EQUIPMENT_GROUP_SOURCE_MISMATCH')
        if sem in ('EQUIPPABLE_UNTYPED_EFFECT','EQUIPPABLE_NONCOMBAT_USE') and effects:
            raise ValueError('UNTYPED_ITEM_HAS_TYPED_EFFECTS')
        if sem=='EQUIPPABLE_NONCOMBAT_USE' and not (
            'Use:' in excerpt and 'cannot be done in combat' in excerpt.lower()
        ):
            raise ValueError('NONCOMBAT_USE_SOURCE_UNSUPPORTED')
        parsed=[]; conditional=[]
        for effect in effects:
            kind=effect.get('type')
            if kind=='multiply_actor_stat':
                if (set(effect)!={'type','stat','multiplier','source'}
                    or effect.get('source')!='equip_tooltip'
                    or effect.get('stat') not in {'strength','agility','stamina','intellect','spirit'}
                    or not isfinite(float(effect['multiplier']))
                    or float(effect['multiplier'])<=0):
                    raise ValueError('UNKNOWN_SOURCED_ITEM_EFFECT')
                parsed.append((kind,effect['stat'],float(effect['multiplier'])))
            elif kind in ('add_actor_stat','add_actor_stat_if_environment'):
                allowed={'type','stat','amount','source'}
                if kind=='add_actor_stat_if_environment':allowed.add('environments')
                if (set(effect)!=allowed or effect.get('source')!='equip_tooltip'
                    or effect.get('stat') not in {'spell_penetration','resistance_all'}
                    or not isfinite(float(effect['amount'])) or float(effect['amount'])<=0):
                    raise ValueError('UNKNOWN_SOURCED_ITEM_EFFECT')
                # Prove each magnitude, channel and conditional biome by the
                # immutable source excerpt, not by a hand-authored ID switch.
                stat=effect['stat'];amount=float(effect['amount'])
                if stat=='spell_penetration':
                    base=re.search(r'Your spells pierce (\d+) Magical Resistances',excerpt)
                    area=re.search(r'additional (\d+) Spell Piercing in Forest and Grassland areas',excerpt)
                else:
                    base=re.search(r'Increases all Resistances by (\d+)',excerpt)
                    area=re.search(r'additional (\d+) to all Resistances in Forest and Grassland areas',excerpt)
                matched=area if kind=='add_actor_stat_if_environment' else base
                if matched is None or int(matched.group(1))!=amount:
                    raise ValueError('SOURCE_ITEM_EFFECT_MAGNITUDE_NOT_PROVEN')
                if kind=='add_actor_stat_if_environment':
                    env=effect['environments']
                    if not isinstance(env,list) or sorted(env)!=['forest','grassland']:
                        raise ValueError('SOURCE_ITEM_ENVIRONMENT_NOT_PROVEN')
                    conditional.append((kind,stat,amount,tuple(env)))
                else:parsed.append((kind,stat,amount))
            else:raise ValueError('UNKNOWN_SOURCED_ITEM_EFFECT')
        if iid in result:raise ValueError('DUPLICATE_ITEM_EQUIPMENT_SEMANTICS')
        result[iid]=EquipmentSemantic(iid,name,slot,url,observed,scope,sem,tuple(parsed),group,limit,tuple(conditional))
    return result


def source_equipment_semantics() -> dict[int, EquipmentSemantic]:
    path=ledger_path()
    if not path.is_file():raise ValueError('MISSING_SOURCE_EQUIPMENT_SEMANTICS_LEDGER')
    stat=path.stat()
    return _load(str(path.resolve()),stat.st_mtime_ns,stat.st_size)


def semantic_for_item(item) -> EquipmentSemantic | None:
    sem=source_equipment_semantics().get(int(item.item_id))
    if sem is not None and (sem.item_name != item.name or sem.slot != item.slot
                             or sem.source_url.split('/item=',1)[1].split('/',1)[0]
                                != item.source_url.split('/item=',1)[1].split('/',1)[0]):
        raise ValueError('SOURCED_ITEM_EQUIPMENT_IDENTITY_MISMATCH')
    return sem


def validate_equipped_item_ids(item_ids) -> None:
    """Fail closed for source-verified Unique-Equipped groups, across slots.

    Unknown groups are not fabricated. This check is independent of stat
    modeling and must run even when the item effect is not executable in L2.
    """
    ids=tuple(int(i) for i in item_ids)
    if len(ids)!=len(set(ids)):
        raise ValueError('DUPLICATE_EQUIPPED_ITEM')
    evidence=source_equipment_semantics()
    counts={}
    limits={}
    for iid in ids:
        sem=evidence.get(iid)
        if sem is None or sem.equip_group is None:continue
        group=sem.equip_group
        counts[group]=counts.get(group,0)+1
        if group in limits and limits[group]!=sem.equip_limit:
            raise ValueError('SOURCE_EQUIP_GROUP_CONFLICTING_LIMITS')
        limits[group]=sem.equip_limit
        if counts[group]>limits[group]:
            raise ValueError(f'BLOCKED_SOURCE_UNIQUE_EQUIPPED_GROUP:{group}')


def apply_equipped_source_effects(ir, *, class_key: str, level: int, item_ids,
                                  environment_tags=()):
    """Execute only source-typed passive effects, after canonical additive gear.

    Applied to actor stats consumed by the existing CombatRuntime/recovery;
    no new combat engine or item-specific formulas.
    """
    from dataclasses import replace
    from .runtime_selection import available_items
    by_id={int(x.item_id):x for x in available_items(class_key,level,required_level_policy='observed')}
    ids=tuple(map(int,item_ids))
    validate_equipped_item_ids(ids)
    stats=dict(ir.actor.base_stats)
    environments=frozenset(str(x).lower() for x in environment_tags)
    if not environments.issubset({'forest','grassland'}):
        raise ValueError('SOURCE_ITEM_UNKNOWN_ENVIRONMENT_TAG')
    provenance=[]; contingent=[]
    for iid in ids:
        if iid not in by_id:raise ValueError('EQUIPPED_ITEM_NOT_SOURCE_LEGAL')
        sem=semantic_for_item(by_id[iid])
        if sem is None:continue
        if sem.equip_semantics in ('EQUIPPABLE_UNTYPED_EFFECT','EQUIPPABLE_NONCOMBAT_USE'):
            continue  # Strict L2 admission checks unknown effects before this adapter.
        if sem.equip_semantics!='EQUIPPABLE_TYPED_PASSIVE':
            raise ValueError('NON_EQUIPPABLE_RUNE_LEARNING_ITEM')
        for kind,stat,multiplier in sem.typed_effects:
            if kind=='multiply_actor_stat':
                if stat not in stats:raise ValueError('ITEM_PASSIVE_UNSUPPORTED_ACTOR_STAT')
                before=float(stats[stat]);stats[stat]=before*multiplier
            elif kind=='add_actor_stat':
                before=float(stats.get(stat,0.));stats[stat]=before+multiplier
            else:raise ValueError('ITEM_PASSIVE_UNSUPPORTED_KIND')
            provenance.append({'item_id':iid,'effect':kind,'stat':stat,'multiplier':multiplier,
                               'before':before,'after':stats[stat],
                               'source_url':sem.source_url,'source_scope':sem.source_scope})
        for kind,stat,amount,areas in sem.conditional_effects:
            enabled=bool(environments.intersection(areas))
            contingent.append({'item_id':iid,'effect':kind,'stat':stat,'amount':amount,
                'environment_tags':list(environments),'qualifying_environments':list(areas),
                'activated':enabled,'environment_status':
                    'SCENARIO_EXPLICIT' if environments else 'UNSPECIFIED_NO_CONDITIONAL_BONUS',
                'source_url':sem.source_url})
            if enabled:
                before=float(stats.get(stat,0.));stats[stat]=before+amount
                provenance.append({'item_id':iid,'effect':kind,'stat':stat,
                    'amount':amount,'before':before,'after':stats[stat],
                    'source_url':sem.source_url,'source_scope':sem.source_scope})
    if not provenance and not contingent:return ir
    return replace(ir,actor=replace(ir.actor,base_stats=stats),
                   provenance={**dict(ir.provenance),'source_equipped_passives':provenance,
                               'source_environment_conditional_passives':contingent})
