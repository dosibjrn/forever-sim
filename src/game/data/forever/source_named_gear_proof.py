"""Exact pinned-catalogue equipment audit for persistent L2 candidates.

The checkpoint asks whether equipment is legal and obtainable in the selected
ruleset, NOT whether a fictional character already looted it. A listview
identity proves neither an acquisition method nor world access. Keep those
three questions separate, and never score fabricated item stats or slot swaps.
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from collections.abc import Mapping
from math import isclose, isfinite
from src.rulesets.forever.items.runtime_selection import (
    BODY_SLOTS, available_items, catalogue_path, item_payload, item_vector,
    effective_level,
)


def _slot_compatible(slot: str, item) -> bool:
    raw=str(item.slot or '')
    if slot in BODY_SLOTS or slot in ('relic','shirt'): return raw==slot
    if slot in ('ring1','ring2'): return raw=='finger'
    if slot in ('trinket1','trinket2'): return raw=='trinket'
    if slot=='weapon': return raw in ('one_hand','main_hand','two_hand')
    if slot=='offhand': return raw=='off_hand' and item.weapon_hands!=2
    if slot=='wand': return raw=='ranged' and item.weapon_type=='wand'
    if slot=='ranged': return raw=='ranged'
    return False


def _exact_payload(published: Mapping, actual: Mapping) -> bool:
    """Check all simulator-affecting fields plus identity, not only name/ID."""
    for field, value in actual.items():
        if field not in published:
            return False
        supplied=published[field]
        if isinstance(value,float):
            if isinstance(supplied,bool) or not isinstance(supplied,(int,float)) or not isfinite(float(supplied)):
                return False
            if not isclose(float(supplied),value,rel_tol=1e-10,abs_tol=1e-9):
                return False
        elif supplied != value:
            return False
    return True


def audit_named_gear_source(*,class_key: str,level: int,gear: Mapping,
                            db_path: str | Path | None=None) -> dict:
    path=Path(db_path or catalogue_path()).resolve()
    if not path.is_file(): raise ValueError('BLOCKED_MISSING_PINNED_ITEM_CATALOGUE')
    if db_path is not None and path!=Path(catalogue_path()).resolve():
        raise ValueError('BLOCKED_ITEM_CATALOGUE_SNAPSHOT_SCOPE_MISMATCH')
    slots=gear.get('slots')
    if not isinstance(slots,Mapping) or not slots:
        raise ValueError('BLOCKED_MISSING_NAMED_ITEM_SLOTS')
    if gear.get('class_key')!=class_key or int(gear.get('level',-1))!=int(level):
        raise ValueError('BLOCKED_GEAR_ACTOR_IDENTITY')
    eligible={int(x.item_id):x for x in available_items(class_key,level,required_level_policy='observed')}
    rows=[]; used=set(); aggregate={}; seen_two_handed=False
    with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        for slot,published in sorted(slots.items()):
            if not isinstance(published,Mapping) or 'item_id' not in published:
                raise ValueError('BLOCKED_GEAR_WITHOUT_SOURCE_ITEM_ID')
            iid=int(published['item_id']); item=eligible.get(iid)
            refs=[dict(r) for r in db.execute('''SELECT source_type,source_name,source_ref
                FROM item_sources WHERE item_id=? ORDER BY source_type,source_ref''',(iid,))]
            duplicate=iid in used;used.add(iid)
            if item is not None:
                actual=item_payload(item,display_slot=str(slot),effective_level=effective_level(item))
                valid=(not duplicate and _slot_compatible(str(slot),item)
                    and _exact_payload(published,actual) and refs
                    and item.required_level_origin=='observed'
                    and item.required_level is not None and item.required_level<=level)
                if slot=='weapon' and item.weapon_hands==2: seen_two_handed=True
                for stat,value in item_vector(item).items():
                    aggregate[stat]=aggregate.get(stat,0.)+float(value)
            else:
                valid=False
            # Source-listing identity is NOT a documented vendor/drop/quest/craft
            # method. Do not demand a simulated loot transaction either.
            methods=[r for r in refs if r['source_type'] in ('vendor','drop','quest','craft','reputation','pvp','currency')]
            rows.append({'slot':str(slot),'item_id':iid,'name':str(published.get('name','')),
                'source_status':'VERIFIED_PINNED_EQUIPMENT_LEGALITY' if valid else 'BLOCKED_ITEM_ID_SLOT_LEVEL_OR_STATS',
                'source_url':str(item.source_url) if item is not None else None,
                'item_sources':refs,
                'availability_status':'SOURCED_ACQUISITION_METHOD' if methods else 'UNKNOWN_ACQUISITION_METHOD',
                'acquisition_methods':methods})
    from src.rulesets.forever.items.source_equipment_semantics import validate_equipped_item_ids
    try:
        validate_equipped_item_ids(int(x['item_id']) for x in slots.values())
    except ValueError as exc:
        if 'BLOCKED_SOURCE_UNIQUE_EQUIPPED_GROUP' not in str(exc) and 'DUPLICATE_EQUIPPED_ITEM' not in str(exc):
            raise
        for row in rows:
            row['source_status']='BLOCKED_SOURCE_UNIQUE_EQUIPPED_GROUP'
    if seen_two_handed and 'offhand' in slots:
        for r in rows:
            if r['slot'] in ('weapon','offhand'):
                r['source_status']='BLOCKED_TWO_HANDED_WITH_OFFHAND'
    claimed=gear.get('aggregate_stats')
    aggregate_ok=isinstance(claimed,Mapping) and set(claimed)==set(aggregate) and all(
        isinstance(claimed[k],(int,float)) and not isinstance(claimed[k],bool)
        and isfinite(float(claimed[k])) and isclose(float(claimed[k]),v,rel_tol=1e-10,abs_tol=1e-8)
        for k,v in aggregate.items())
    valid_count=sum(r['source_status']=='VERIFIED_PINNED_EQUIPMENT_LEGALITY' for r in rows)
    availability_count=sum(r['availability_status']=='SOURCED_ACQUISITION_METHOD' for r in rows)
    legal=valid_count==len(rows) and aggregate_ok
    return {'class_key':class_key,'level':int(level),'catalogue_path':str(path),
        'catalogue_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'selected_slots':len(rows),'legal_slots':valid_count,
        'aggregate_stats_match_catalogue':aggregate_ok,
        'equipment_legality_complete':legal,
        'sourced_acquisition_methods':availability_count,
        'acquisition_method_coverage_complete':availability_count==len(rows),
        'formal_gear_acceptance':legal and availability_count==len(rows),
        'items':rows,
        'note':'No possession/loot-event requirement. Unknown acquisition method is an availability evidence gap, not proof that an item is unavailable.'}
