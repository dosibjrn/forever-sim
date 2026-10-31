"""Staged, source-identity-bound WEB-INDEXED text for checkpoint L0.

These observations are deliberately NOT authenticated HTML snapshots and do not
prove trainer/rune acquisition, spell rank availability, or L2 executability.
They can supplement an empty canonical listview tooltip *only* for contextual
L0 search triage.  Never modify the canonical source database in place.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlparse

_SOURCE_KINDS = frozenset({
    'forever_wowhead_search_indexed',
    'forever_wowhead_quest_search_indexed',
    'secondary_forever_client_description',
})


def _check_observation(entry: dict, indexed: dict) -> None:
    sid = int(indexed['spell_id'])
    if (int(entry['spell_id']) != sid or entry['class_key'] != indexed['class_key']
            or entry['name'] != indexed['name']
            or entry['source_url'] != indexed['source_url']
            or entry['source_index_sha256'] != hashlib.sha256(
                indexed['raw_listview_json'].encode()).hexdigest()):
        raise ValueError('SOURCE_WEB_L0_INDEX_IDENTITY_MISMATCH')
    if entry['capture_kind'] not in _SOURCE_KINDS:
        raise ValueError('SOURCE_WEB_L0_UNSUPPORTED_CAPTURE_KIND')
    if (not entry['observed_text'].strip() or len(entry['observed_text']) > 1600
            or not entry['observed_at'] or not entry['observed_url'].startswith('https://')):
        raise ValueError('SOURCE_WEB_L0_INVALID_OBSERVATION')
    url = urlparse(entry['observed_url'])
    if entry['capture_kind'] == 'forever_wowhead_quest_search_indexed':
        if url.hostname != 'www.wowhead.com' or '/forever/quest=' not in url.path:
            raise ValueError('SOURCE_WEB_L0_QUEST_URL_MISMATCH')
    elif entry['capture_kind'] == 'forever_wowhead_search_indexed':
        if url.hostname != 'www.wowhead.com' or '/forever/' not in url.path or f'spell={sid}' not in url.path:
            raise ValueError('SOURCE_WEB_L0_SPELL_URL_MISMATCH')
    else:
        if url.hostname != 'foreverdb.net' or url.path != f'/spell/{sid}':
            raise ValueError('SOURCE_WEB_L0_SECONDARY_URL_MISMATCH')
    if not isinstance(entry.get('source_flags', []), list) or any(
            not isinstance(v,str) for v in entry.get('source_flags', [])):
        raise ValueError('SOURCE_WEB_L0_FLAGS_INVALID')


def ingest_observations(stage_db: str | Path, observation_json: str | Path) -> dict:
    """Write to a caller-created isolated SQLite stage; atomic and fail-closed."""
    path = Path(stage_db)
    doc = json.loads(Path(observation_json).read_text())
    if doc.get('schema') != 'checkpoint_web_l0_v1':
        raise ValueError('SOURCE_WEB_L0_SCHEMA_MISMATCH')
    observations = doc['observations']
    if not isinstance(observations,list) or not observations:
        raise ValueError('SOURCE_WEB_L0_EMPTY')
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN IMMEDIATE')
        try:
            indexed = {int(r['spell_id']):dict(r) for r in db.execute(
                "SELECT class_key,spell_id,name,source_url,raw_listview_json FROM spell_index "
                "WHERE class_key=? AND kind='abilities'",(doc['class_key'],))}
            if not indexed:
                raise ValueError('SOURCE_WEB_L0_NO_INDEX')
            seen=set()
            for entry in observations:
                sid=int(entry['spell_id'])
                if sid in seen:
                    raise ValueError('SOURCE_WEB_L0_DUPLICATE_ID')
                seen.add(sid)
                if sid not in indexed:
                    raise ValueError('SOURCE_WEB_L0_UNKNOWN_ID')
                _check_observation(entry,indexed[sid])
            db.execute('''CREATE TABLE IF NOT EXISTS checkpoint_source_l0_web_observations (
                class_key TEXT NOT NULL, spell_id INTEGER NOT NULL,
                name TEXT NOT NULL, source_url TEXT NOT NULL,
                source_index_sha256 TEXT NOT NULL,
                capture_kind TEXT NOT NULL, observed_url TEXT NOT NULL,
                observed_at TEXT NOT NULL, observed_text TEXT NOT NULL,
                source_flags_json TEXT NOT NULL,
                PRIMARY KEY(class_key,spell_id))''')
            for entry in observations:
                db.execute('''INSERT OR REPLACE INTO checkpoint_source_l0_web_observations
                    VALUES(?,?,?,?,?,?,?,?,?,?)''',(
                    entry['class_key'],int(entry['spell_id']),entry['name'],entry['source_url'],
                    entry['source_index_sha256'],entry['capture_kind'],entry['observed_url'],
                    entry['observed_at'],entry['observed_text'],
                    json.dumps(entry.get('source_flags',[]),sort_keys=True)))
            db.commit()
        except Exception:
            db.rollback()
            raise
    return {'observations_ingested':len(seen),'capture_kind_counts':{
        kind:sum(x['capture_kind']==kind for x in observations) for kind in sorted(_SOURCE_KINDS)},
        'L2_legal_action_promotion':0,'canonical_database_mutated':False}


def load_observations(db: sqlite3.Connection, class_key: str) -> dict[int,dict]:
    """Reject stale rows; do not silently use a mismatched source snapshot."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                      "AND name='checkpoint_source_l0_web_observations'").fetchone():
        return {}
    rows=db.execute('''SELECT o.*,i.raw_listview_json,i.name AS current_name,
        i.source_url AS current_source_url FROM checkpoint_source_l0_web_observations o
        LEFT JOIN spell_index i ON i.class_key=o.class_key AND i.spell_id=o.spell_id
        WHERE o.class_key=? ''',(class_key,)).fetchall()
    found={}
    for raw in rows:
        r=dict(raw)
        if (r['raw_listview_json'] is None
                or hashlib.sha256(r['raw_listview_json'].encode()).hexdigest()!=r['source_index_sha256']
                or r['name']!=r['current_name'] or r['source_url']!=r['current_source_url']):
            raise ValueError('SOURCE_WEB_L0_STALE_INDEX_OBSERVATION')
        r['source_flags']=json.loads(r.pop('source_flags_json'))
        r.pop('raw_listview_json');r.pop('current_name');r.pop('current_source_url')
        found[int(r['spell_id'])]=r
    return found
