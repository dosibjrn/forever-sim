"""External beta-client rank observations for an *explicit staged* source snapshot.

This is not a replacement for independently SHA-verified Forever spell-detail
HTML.  It is a fail-closed, source-identified alternative to stale canonical
listview numeric facts, preserving the original index bytes and hashes.
Nothing here authorizes checkpoint acceptance or asserts server-side tuning.
"""
from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlparse

SCHEMA = '''CREATE TABLE IF NOT EXISTS source_external_rank_observations (
 class_key TEXT NOT NULL, spell_id INTEGER NOT NULL, source_build TEXT NOT NULL,
 source_build_date TEXT NOT NULL, observed_at TEXT NOT NULL,
 index_batch_id TEXT NOT NULL, index_sha256 TEXT NOT NULL,
 after_json TEXT NOT NULL, source_urls_json TEXT NOT NULL,
 observation_sha256 TEXT NOT NULL, observation_json TEXT NOT NULL,
 source_quality TEXT NOT NULL,
 PRIMARY KEY(class_key,spell_id)
)'''
QUALITY='EXTERNAL_WEB_TEXT_NOT_SHA_VERIFIED_HTML'

class ExternalRankObservationError(ValueError):
    pass


def _identity(conn, class_key, spell_id):
    conn.row_factory=sqlite3.Row
    row=conn.execute('''SELECT i.*,b.captured_at,b.status AS batch_status,
       l.complete AS list_complete FROM spell_index i
       JOIN capture_batches b ON b.batch_id=i.batch_id
       JOIN capture_lists l ON l.batch_id=i.batch_id AND l.class_key=i.class_key AND l.kind=i.kind
       WHERE i.class_key=? AND i.kind='abilities' AND i.spell_id=?''',
       (class_key,spell_id)).fetchone()
    if row is None or row['batch_status']!='complete' or row['list_complete']!=1:
        raise ExternalRankObservationError('NO_COMPLETE_CANONICAL_INDEX_RANK')
    raw=json.loads(row['raw_listview_json'])
    if raw.get('id')!=spell_id or raw.get('name')!=row['name'] or raw.get('level')!=row['level_hint']:
        raise ExternalRankObservationError('CANONICAL_INDEX_RANK_DRIFT')
    if (raw.get('envChange') or {}).get('status')=='removed':
        raise ExternalRankObservationError('SOURCE_RANK_REMOVED')
    return row


def ingest_observations(stage:Path, observations:Path):
    """Import explicit source observations into a *separate* SQLite stage.

    No guessing of source identity, no unverified values in canonical rows,
    and no partial import on a single invalid observation. Duplicate entries
    and single-source claims are rejected. This is NOT a live HTML fetcher.
    """
    stage=Path(stage)
    doc=json.loads(Path(observations).read_text(encoding='utf-8'))
    if doc.get('schema')!='forever_external_rank_observations_v1':
        raise ExternalRankObservationError('BAD_OBSERVATION_SCHEMA')
    observations=doc.get('observations')
    if not isinstance(observations,list) or not observations:
        raise ExternalRankObservationError('NO_OBSERVATIONS')
    from .source_index_rank_parity import parse_index_after
    seen=set();inserted=[]
    with sqlite3.connect(stage) as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute(SCHEMA)
        for obs in observations:
            class_key=str(obs['class_key']).lower()
            spell_id=int(obs['spell_id'])
            key=(class_key,spell_id)
            if key in seen:
                raise ExternalRankObservationError('DUPLICATE_OBSERVATION')
            seen.add(key)
            row=_identity(conn,class_key,spell_id)
            if (row['name']!=obs['name'] or int(row['level_hint'])!=int(obs['required_level'])
                    or row['batch_id']!=obs['index_batch_id']):
                raise ExternalRankObservationError('OBSERVATION_INDEX_IDENTITY_MISMATCH')
            build_date=date.fromisoformat(obs['source_build_date'])
            observed=date.fromisoformat(obs['observed_at'])
            index_capture=date.fromisoformat(row['captured_at'][:10])
            if not index_capture<build_date<=observed:
                raise ExternalRankObservationError('NOT_NEWER_THAN_INDEX_OR_FUTURE_OBSERVATION')
            urls=obs['source_urls']
            if (not isinstance(urls,list) or len(urls)<2
                    or len({urlparse(x).netloc.lower() for x in urls})<2
                    or any(urlparse(x).scheme!='https' or not urlparse(x).netloc for x in urls)):
                raise ExternalRankObservationError('NEEDS_TWO_DISTINCT_HTTPS_SOURCE_DOMAINS')
            after=obs['after']
            if not isinstance(after,dict) or after.get('name')!=row['name']:
                raise ExternalRankObservationError('OBSERVATION_TOOLTIP_NAME_MISMATCH')
            # Same fail-closed grammar as the production source-index adapter.
            parsed=parse_index_after(after,obs['effect_kind'])
            if parsed['kind']!=obs['effect_kind']:
                raise ExternalRankObservationError('EFFECT_KIND_MISMATCH')
            canonical_hash=sha256(row['raw_listview_json'].encode()).hexdigest()
            if obs['index_sha256']!=canonical_hash:
                raise ExternalRankObservationError('OBSERVATION_STALE_INDEX_HASH')
            payload=json.dumps(obs,sort_keys=True,separators=(',',':'))
            conn.execute('''INSERT OR REPLACE INTO source_external_rank_observations
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',(
                class_key,spell_id,obs['source_build'],obs['source_build_date'],
                obs['observed_at'],row['batch_id'],canonical_hash,
                json.dumps(after,sort_keys=True),json.dumps(urls,sort_keys=True),
                sha256(payload.encode()).hexdigest(),payload,QUALITY))
            inserted.append({'spell_id':spell_id,'class_key':class_key,'parsed':parsed,
                             'source_build':obs['source_build'],'sources':urls})
        if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise ExternalRankObservationError('STAGE_INTEGRITY_FAILED')
    return {'status':'WEB_TEXT_OBSERVATIONS_ONLY_NOT_SHA_VERIFIED',
            'inserted':inserted,'count':len(inserted),'checkpoint_eligible':False}


def external_rank_fact(conn, row, *, effect_kind, as_of):
    """Return a newer, identity-bound staged observation or None.

    Presence of a stale/malformed observation is an error, never a fallback.
    """
    table=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_external_rank_observations'").fetchone()
    if not table:
        return None
    obs=conn.execute('''SELECT * FROM source_external_rank_observations
        WHERE class_key=? AND spell_id=?''',(row['class_key'],row['spell_id'])).fetchone()
    if obs is None:
        return None
    if obs['source_quality']!=QUALITY or obs['index_batch_id']!=row['batch_id']:
        raise ExternalRankObservationError('OBSERVATION_SOURCE_IDENTITY_DRIFT')
    raw_observation=obs['observation_json']
    if sha256(raw_observation.encode()).hexdigest()!=obs['observation_sha256']:
        raise ExternalRankObservationError('OBSERVATION_CONTENT_HASH_DRIFT')
    document=json.loads(raw_observation)
    if (document['class_key']!=row['class_key'] or document['spell_id']!=row['spell_id']
            or document['name']!=row['name'] or document['required_level']!=row['level_hint']
            or document['source_build']!=obs['source_build']
            or document['source_build_date']!=obs['source_build_date']
            or document['observed_at']!=obs['observed_at']
            or document['index_batch_id']!=obs['index_batch_id']
            or document['index_sha256']!=obs['index_sha256']
            or json.dumps(document['after'],sort_keys=True)!=obs['after_json']
            or json.dumps(document['source_urls'],sort_keys=True)!=obs['source_urls_json']
            or document['effect_kind']!=effect_kind):
        raise ExternalRankObservationError('OBSERVATION_STORED_FIELDS_DRIFT')
    if obs['index_sha256']!=sha256(row['raw_listview_json'].encode()).hexdigest():
        raise ExternalRankObservationError('OBSERVATION_STALE_INDEX_HASH')
    build_date=date.fromisoformat(obs['source_build_date'])
    observed_at=date.fromisoformat(obs['observed_at'])
    if build_date>as_of:
        return None  # Explicit historical time travel; never use future values.
    if build_date<=date.fromisoformat(row['captured_at'][:10]) or observed_at<build_date:
        raise ExternalRankObservationError('OBSERVATION_BUILD_ORDER_INVALID')
    urls=json.loads(obs['source_urls_json'])
    if len({urlparse(x).netloc.lower() for x in urls})<2:
        raise ExternalRankObservationError('OBSERVATION_SOURCES_INVALID')
    from .source_index_rank_parity import parse_index_after
    parsed=parse_index_after(json.loads(obs['after_json']),effect_kind)
    return {**parsed,'raw_observed_after':json.loads(obs['after_json']),
        'source_authority':'external_beta_client_web_text_observation',
        'external_source_urls':urls,'source_build':obs['source_build'],
        'source_build_date':obs['source_build_date'],'observed_at':obs['observed_at'],
        'observation_sha256':obs['observation_sha256'],
        'detail_html_independently_verified':False,
        'checkpoint_eligibility':'BLOCKED_EXTERNAL_WEB_TEXT_NOT_SHA_VERIFIED_DETAIL'}
