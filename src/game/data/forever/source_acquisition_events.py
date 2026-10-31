"""Generic source-consistent spell acquisition state transitions (WF291 WIP).

The verified Wowhead related-list establishes a *possible teacher*, not a
visited NPC, learned spell, reachable zone, completed quest, or full route.
This module interprets explicit character state + explicit proposed events,
never creates them from spell names, and never upgrades them to world proofs.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Iterable

from src.game.data.forever.source_acquisition import read_acquisition_evidence
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.v2.source_sqlite_detail_snapshots import read_verified_spell_detail_snapshot
from .source_acquisition_entities import TYPES, _typed_listview


@dataclass(frozen=True)
class AcquisitionCharacterState:
    class_key: str
    level: int
    zone_id: int | None
    copper: int
    learned_spell_ids: frozenset[int] = frozenset()
    inventory_item_ids: frozenset[int] = frozenset()
    completed_quest_ids: frozenset[int] = frozenset()

    def __post_init__(self):
        if not self.class_key or type(self.level) is not int or self.level < 1 or self.level > 60:
            raise ValueError('invalid character identity/level')
        if type(self.copper) is not int or self.copper < 0:
            raise ValueError('invalid character copper')
        if self.zone_id is not None and (type(self.zone_id) is not int or self.zone_id <= 0):
            raise ValueError('invalid character zone')
        for values in (self.learned_spell_ids, self.inventory_item_ids, self.completed_quest_ids):
            if not isinstance(values, frozenset) or any(type(v) is not int or v <= 0 for v in values):
                raise ValueError('invalid character IDs')


@dataclass(frozen=True)
class AcquisitionEvent:
    """A proposed local action. It is not a claim of historical observation."""
    method: str
    spell_id: int
    source_entity_id: int
    # Character zone and currency are read from the state, not trusted from
    # a free-form event string. An explicit witness zone must match both.
    witness_zone_id: int | None = None


def verified_source_acquisition_entities(*, class_key: str, spell_id: int,
        db_path: str | Path | None = None) -> tuple[dict, ...]:
    """Recheck every persisted source entity against original verified HTML.

    The whole method list is compared, preventing a deleted, added or edited
    trainer row from silently making a spell appear easier to acquire.
    """
    path = Path(db_path or DEFAULT_DB)
    evidence = read_acquisition_evidence(class_key=class_key, spell_ids=[spell_id], db_path=path).get(spell_id)
    if not evidence or evidence['status'] != 'CURRENT_SOURCE_EVIDENCE' or not evidence['detail_html_sha256']:
        raise ValueError('missing current verified detail source')
    with sqlite3.connect(f'file:{path.resolve()}?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='ability_acquisition_entities'").fetchone():
            raise ValueError('missing typed acquisition entity ledger')
        rows = [dict(x) for x in db.execute('''SELECT * FROM ability_acquisition_entities
                    WHERE class_key=? AND spell_id=? ORDER BY method,entity_id''',
                    (class_key.strip().lower(), spell_id))]
        if not rows:
            raise ValueError('no typed acquisition entities')
        verified = read_verified_spell_detail_snapshot(db,
            batch_id=evidence['index_batch_id'], spell_id=spell_id)
        if verified['html_sha256'] != evidence['detail_html_sha256']:
            raise ValueError('stale detail source')
        actual = {}
        for method, (entity_type, anchor) in TYPES.items():
            if method not in evidence['methods_observed']:
                continue
            entries = _typed_listview(verified['html'], anchor, entity_type)
            if len(entries) != evidence['methods_observed'][method]:
                raise ValueError('related listview count mismatch')
            for entry in entries:
                eid = entry.get('id')
                if type(eid) is not int or eid <= 0 or (method, eid) in actual:
                    raise ValueError('invalid or duplicate related source entity')
                zones = entry.get('location') or []
                if not isinstance(zones, list) or any(type(z) is not int or z <= 0 for z in zones):
                    raise ValueError('invalid source zone')
                name = entry.get('displayName') or entry.get('name')
                if not isinstance(name, str) or not name.strip():
                    raise ValueError('missing source entity name')
                actual[(method, eid)] = {
                    'class_key':class_key.strip().lower(), 'spell_id':spell_id,
                    'method':method, 'entity_id':eid, 'entity_name':name.strip(),
                    'source_entity_type':entity_type, 'zone_ids_json':json.dumps(sorted(set(zones))),
                    'source_entity_json_sha256':sha256(json.dumps(entry,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
                    'index_batch_id':evidence['index_batch_id'],
                    'detail_html_sha256':verified['html_sha256'],
                    'source_url':evidence['source_url'],
                }
        observed = {(r['method'], r['entity_id']):r for r in rows}
        if actual.keys() != observed.keys():
            raise ValueError('stored acquisition entities differ from source HTML')
        for key, row in observed.items():
            if any(row[field] != actual[key][field] for field in actual[key]):
                raise ValueError('stored acquisition entity/source mismatch')
            if row['source_payload_sha256'] != db.execute('''SELECT source_payload_sha256
                FROM ability_acquisition_evidence WHERE class_key=? AND spell_id=?''',
                (class_key.strip().lower(), spell_id)).fetchone()[0]:
                raise ValueError('stored entity index fingerprint mismatch')
        return tuple(rows)


def apply_source_consistent_acquisition(state: AcquisitionCharacterState,
        event: AcquisitionEvent, *, db_path: str | Path | None = None) -> tuple[AcquisitionCharacterState, dict]:
    """Apply only a source-consistent local event, with explicit prerequisites.

    Does not assert travel, inventory origin, quest completion or actual player
    action was verified; the caller must supply those facts independently.
    """
    if event.method not in TYPES or type(event.spell_id) is not int or event.spell_id <= 0:
        raise ValueError('unsupported acquisition method or spell ID')
    if type(event.source_entity_id) is not int or event.source_entity_id <= 0:
        raise ValueError('invalid source entity ID')
    if event.spell_id in state.learned_spell_ids:
        raise ValueError('spell already learned; duplicate purchase blocked')
    path = Path(db_path or DEFAULT_DB)
    evidence = read_acquisition_evidence(class_key=state.class_key,
        spell_ids=[event.spell_id], db_path=path).get(event.spell_id)
    if not evidence or evidence['status'] != 'CURRENT_SOURCE_EVIDENCE':
        raise ValueError('missing/stale acquisition evidence')
    level_hint = evidence['required_level_hint']
    if level_hint is None or type(level_hint) is not int or state.level < level_hint:
        raise ValueError('source acquisition level unknown or unmet')
    entities = verified_source_acquisition_entities(class_key=state.class_key,
        spell_id=event.spell_id, db_path=path)
    entity = next((x for x in entities if x['method'] == event.method and
                   x['entity_id'] == event.source_entity_id), None)
    if entity is None:
        raise ValueError('requested acquisition method/entity not in verified source')
    cost = 0
    inventory = state.inventory_item_ids
    if event.method == 'taught_by_npc':
        zones = json.loads(entity['zone_ids_json'])
        if (event.witness_zone_id is None or state.zone_id != event.witness_zone_id
                or event.witness_zone_id not in zones):
            raise ValueError('trainer zone not supported by source and character state')
        with sqlite3.connect(f'file:{path.resolve()}?mode=ro', uri=True) as db:
            row = db.execute('''SELECT training_cost_hint FROM ability_acquisition_evidence
                WHERE class_key=? AND spell_id=?''',(state.class_key.lower(),event.spell_id)).fetchone()
        if not row or row[0] is None or float(row[0]) < 0 or not float(row[0]).is_integer():
            raise ValueError('trainer price not source-known')
        cost = int(row[0])
        if state.copper < cost:
            raise ValueError('insufficient currency for source-indexed trainer cost')
    elif event.method == 'reward_from_quest':
        if event.source_entity_id not in state.completed_quest_ids:
            raise ValueError('quest completion not in character state')
    elif event.method == 'taught_by_item':
        if event.source_entity_id not in state.inventory_item_ids:
            raise ValueError('teaching item not in inventory')
        inventory = state.inventory_item_ids - {event.source_entity_id}
    else:
        raise ValueError('unsupported acquisition event')
    updated = replace(state, copper=state.copper-cost,
        inventory_item_ids=inventory,
        learned_spell_ids=state.learned_spell_ids | {event.spell_id})
    return updated, {
        'status':'SOURCE_CONSISTENT_LOCAL_ACQUISITION', 'class_key':state.class_key,
        'spell_id':event.spell_id, 'method':event.method,
        'source_entity_id':event.source_entity_id,
        'source_entity_name':entity['entity_name'],
        'source_detail_sha256':entity['detail_html_sha256'],
        'source_entity_sha256':entity['source_entity_json_sha256'],
        'source_url':entity['source_url'],
        'charged_source_index_copper':cost,
        'local_preconditions_checked':True,
        'character_location_independently_verified':False,
        'currency_origin_independently_verified':False,
        'quest_or_item_origin_independently_verified':False,
        'actual_player_event_observed':False,
        'world_route_proven':False,
    }


def audit_source_consistent_actions(ir, state: AcquisitionCharacterState,
        action_ids: Iterable[str]) -> dict:
    """Use the existing exact source-rank ID mapping, never action names."""
    from src.game.data.forever.source_indexed_action_coverage import _source_spell_ids
    actions = {a.id:a for a in ir.actions}
    blockers=[]
    for aid in action_ids:
        action=actions.get(aid)
        ids = sorted(_source_spell_ids(action)) if action else []
        if len(ids) != 1 or ids[0] not in state.learned_spell_ids:
            blockers.append({'action_id':aid,'source_spell_ids':ids,
                'reason':'SOURCE_RANK_NOT_PROVEN_LEARNED_IN_LOCAL_STATE'})
    return {'source_consistent':not blockers,'world_route_proven':False,
        'audited_actions':len(tuple(action_ids)),'blockers':blockers}
