"""Generic, fail-closed source-verified world acquisition state machine.

Models trainer purchases and quest/item teaching as world transactions, not as
inferred buttons. Can only begin at a canonical independently sourced origin;
movement needs independently sourced edges. Current production DB has neither
origin nor edge evidence, so no actual world route can be certified yet.
The trace API is also used by the legality gate and regression tests.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Iterable, Mapping

from .sqlite_talents import DEFAULT_DB
from .source_acquisition import read_acquisition_evidence
from .source_acquisition_entities import _typed_listview
from src.v2.source_sqlite_detail_snapshots import read_verified_spell_detail_snapshot


class UnverifiedWorldEvent(ValueError):
    """A claimed transaction cannot be justified by canonical source data."""


def _table(conn, name: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def _origin(conn, *, anchor: str, class_key: str, level: int) -> dict:
    if not _table(conn,'world_origin_evidence'):
        raise UnverifiedWorldEvent('BLOCKED_NO_CANONICAL_WORLD_ORIGIN')
    row=conn.execute('''SELECT * FROM world_origin_evidence WHERE origin_id=? AND class_key=?''',
                     (anchor,class_key)).fetchone()
    if row is None or int(row['min_level'])>level:
        raise UnverifiedWorldEvent('BLOCKED_WORLD_ORIGIN_NOT_VERIFIED')
    # Must be a separately source-observed origin snapshot: storing a boolean
    # is not independent authority and is intentionally insufficient.
    data=row['source_payload']
    if not data or hashlib.sha256(data.encode()).hexdigest()!=row['source_sha256']:
        raise UnverifiedWorldEvent('BLOCKED_WORLD_ORIGIN_SOURCE_HASH')
    if not row['source_url'] or not row['capture_id']:
        raise UnverifiedWorldEvent('BLOCKED_WORLD_ORIGIN_SOURCE_PROVENANCE')
    return dict(row)


def _travel(conn, from_zone: int, to_zone: int, edge_id: str) -> None:
    if not _table(conn,'world_travel_edges'):
        raise UnverifiedWorldEvent('BLOCKED_NO_SOURCED_TRAVEL_EDGE')
    edge=conn.execute('''SELECT * FROM world_travel_edges WHERE edge_id=?
                 AND from_zone_id=? AND to_zone_id=?''', (edge_id,from_zone,to_zone)).fetchone()
    if not edge or not edge['source_url'] or not edge['source_payload'] or not edge['capture_id']:
        raise UnverifiedWorldEvent('BLOCKED_TRAVEL_EDGE_NOT_VERIFIED')
    if hashlib.sha256(edge['source_payload'].encode()).hexdigest()!=edge['source_sha256']:
        raise UnverifiedWorldEvent('BLOCKED_TRAVEL_EDGE_SOURCE_HASH')


def _entity(conn, *, class_key: str, spell_id: int, method: str,
            entity_id: int, detail_sha: str, index_sha: str) -> dict:
    if not _table(conn,'ability_acquisition_entities'):
        raise UnverifiedWorldEvent('BLOCKED_NO_SOURCED_ACQUISITION_ENTITIES')
    row=conn.execute('''SELECT e.* FROM ability_acquisition_entities e
        WHERE class_key=? AND spell_id=? AND method=? AND entity_id=?''',
        (class_key,spell_id,method,entity_id)).fetchone()
    if not row or row['detail_html_sha256']!=detail_sha or row['source_payload_sha256']!=index_sha:
        raise UnverifiedWorldEvent('BLOCKED_ENTITY_NOT_LINKED_TO_CURRENT_SPELL_SOURCE')
    # Re-read the original, SHA-verified source page and check the *exact*
    # entity's ID, name, zone list and JSON checksum, rather than trusting
    # mutable secondary SQLite columns as evidence.
    raw=read_verified_spell_detail_snapshot(conn,batch_id=row['index_batch_id'],spell_id=spell_id)
    if raw['html_sha256']!=row['detail_html_sha256']:
        raise UnverifiedWorldEvent('BLOCKED_STALE_ENTITY_SOURCE_DETAIL')
    anchor={'taught_by_npc':'taught-by-npc','reward_from_quest':'reward-from-q',
            'taught_by_item':'taught-by-item'}[method]
    entries=_typed_listview(raw['html'],anchor,row['source_entity_type'])
    hits=[x for x in entries if x.get('id')==entity_id]
    if len(hits)!=1:
        raise UnverifiedWorldEvent('BLOCKED_SOURCE_ENTITY_NOT_UNIQUE')
    source_entity=hits[0]
    digest=hashlib.sha256(json.dumps(source_entity,sort_keys=True,
                    separators=(',',':')).encode()).hexdigest()
    if (row['source_entity_json_sha256']!=digest or
            row['entity_name']!=(source_entity.get('displayName') or source_entity.get('name')) or
            row['zone_ids_json']!=json.dumps(sorted(set(source_entity.get('location') or [])))):
        raise UnverifiedWorldEvent('BLOCKED_ENTITY_SOURCE_FIELDS_TAMPERED')
    return dict(row)


def verify_acquisition_trace(*, class_key: str, level: int, anchor_id: str,
                             events: Iterable[Mapping],
                             db_path: str | Path | None = None) -> dict:
    """Replay sourced movement and spell-learning events without trusting claims.

    A trainer purchase is legal only at an independently evidenced origin or
    after verified travel, to a source-linked trainer in that zone, with source
    indexed/cross-checked price and sufficient carried funds. Unverified quest
    completion and item possession are intentionally not minted by event input.
    Unrelated 'learned_spell_ids' supplied by the caller are never admitted.
    """
    path=Path(db_path or DEFAULT_DB)
    if type(level) is not int or level<1 or not isinstance(anchor_id,str):
        raise UnverifiedWorldEvent('INVALID_WORLD_TRACE_IDENTITY')
    with sqlite3.connect(f'file:{path.resolve()}?mode=ro',uri=True) as conn:
        conn.row_factory=sqlite3.Row
        orig=_origin(conn, anchor=anchor_id,class_key=class_key,level=level)
        location=int(orig['zone_id'])
        cash=int(orig['initial_copper'])
        if cash<0:
            raise UnverifiedWorldEvent('INVALID_SOURCED_INITIAL_FUNDS')
        source_index = {int(r['spell_id']):dict(r) for r in conn.execute('''
            SELECT e.*,i.raw_listview_json,i.batch_id AS live_batch_id
            FROM ability_acquisition_evidence e JOIN spell_index i
             ON i.class_key=e.class_key AND i.spell_id=e.spell_id AND i.kind='abilities'
            WHERE e.class_key=?''',(class_key,))}
        learned=set()
        completed=[]
        for n,event in enumerate(events):
            if not isinstance(event,Mapping):
                raise UnverifiedWorldEvent('INVALID_WORLD_EVENT')
            kind=event.get('kind')
            if kind=='travel':
                dest=event.get('destination_zone_id')
                if type(dest) is not int or type(event.get('edge_id')) is not str:
                    raise UnverifiedWorldEvent('INVALID_TRAVEL_EVENT')
                _travel(conn,location,dest,event['edge_id'])
                location=dest
                completed.append({'index':n,'kind':kind,'zone_id':dest})
            elif kind=='trainer_purchase':
                sid=event.get('spell_id');npc=event.get('npc_id')
                if type(sid) is not int or type(npc) is not int:
                    raise UnverifiedWorldEvent('INVALID_TRAINER_EVENT_IDS')
                evidence=source_index.get(sid)
                if not evidence:
                    raise UnverifiedWorldEvent('BLOCKED_TRAINER_SPELL_NOT_IN_SOURCE_INDEX')
                if (evidence['source_payload_sha256'] != hashlib.sha256(
                        evidence['raw_listview_json'].encode()).hexdigest()
                        or evidence['index_batch_id']!=evidence['live_batch_id']):
                    raise UnverifiedWorldEvent('BLOCKED_STALE_TRAINER_SPELL_INDEX')
                proof=read_acquisition_evidence(class_key=class_key,spell_ids=(sid,),db_path=path).get(sid)
                if not proof or proof['status']!='CURRENT_SOURCE_EVIDENCE' or not proof['detail_html_sha256']:
                    raise UnverifiedWorldEvent('BLOCKED_NO_VERIFIED_TRAINER_DETAIL')
                if not proof['methods_observed'].get('taught_by_npc'):
                    raise UnverifiedWorldEvent('BLOCKED_SPELL_NOT_TRAINED_BY_NPC')
                if proof['required_level_hint'] is None or int(proof['required_level_hint'])>level:
                    raise UnverifiedWorldEvent('BLOCKED_TRAINER_RANK_LEVEL')
                entity=_entity(conn,class_key=class_key,spell_id=sid,method='taught_by_npc',
                    entity_id=npc,detail_sha=proof['detail_html_sha256'],
                    index_sha=evidence['source_payload_sha256'])
                # NPC zone is an exact observed source ID, not fuzzy place names.
                zones=json.loads(entity['zone_ids_json'])
                if location not in zones:
                    raise UnverifiedWorldEvent('BLOCKED_NPC_NOT_SOURCED_IN_PLAYER_ZONE')
                price=evidence['training_cost_hint']
                if price is None or float(price)<0 or int(price)!=price:
                    raise UnverifiedWorldEvent('BLOCKED_TRAINING_COST_NOT_SOURCED')
                if cash<int(price):
                    raise UnverifiedWorldEvent('BLOCKED_INSUFFICIENT_SOURCED_FUNDS')
                if sid in learned:
                    raise UnverifiedWorldEvent('BLOCKED_DUPLICATE_RANK_PURCHASE')
                cash-=int(price); learned.add(sid)
                completed.append({'index':n,'kind':kind,'spell_id':sid,'npc_id':npc,
                                  'zone_id':location,'paid_copper':int(price),
                                  'source_url':entity['source_url'],
                                  'source_detail_sha256':proof['detail_html_sha256']})
            else:
                # Crucially: accepting arbitrary 'quest_completed', 'item_grant',
                # 'started_with_spell' would allow a fake route to mint spells.
                raise UnverifiedWorldEvent('BLOCKED_UNSUPPORTED_OR_UNVERIFIED_WORLD_EVENT')
    return {'status':'VERIFIED_SOURCED_ACQUISITION_TRACE', 'class_key':class_key,
            'level':level,'origin_id':anchor_id,'zone_id':location,
            'remaining_copper':cash,'verified_learned_spell_ids':sorted(learned),
            'verified_event_count':len(completed),'verified_events':completed,
            'travel_time_and_xp_verified':False,
            'world_route_complete':False}
