"""Explicit source-stage quarantine ledger, never executable authority.

A source detail page with unrecognized structure must not discard the other
2,000+ successfully captured pages. It also must not silently disappear from
coverage or become an L2-legal action. This ledger is stage-only; every row is
bound to the exact source HTML and indexed row hashes.
"""
from __future__ import annotations
from hashlib import sha256
import sqlite3

SCHEMA='''CREATE TABLE IF NOT EXISTS verified_source_ingest_blockers (
 class_key TEXT NOT NULL, spell_id INTEGER NOT NULL, stage TEXT NOT NULL,
 index_batch_id TEXT NOT NULL, index_payload_sha256 TEXT NOT NULL, detail_html_sha256 TEXT,
 reason_code TEXT NOT NULL, PRIMARY KEY(class_key,spell_id,stage))'''


def reason(exc: Exception) -> str:
    # A deterministic bounded code; avoid storing arbitrary exception messages
    # or treating an unexpected parser failure as source evidence.
    value=str(exc).split(':',1)[0].strip()
    return value[:100] if value and value.replace('_','').isalnum() else type(exc).__name__


def read_blocker(conn: sqlite3.Connection, *, class_key: str,
                 spell_id: int, stage: str) -> dict | None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='verified_source_ingest_blockers'").fetchone():
        return None
    row=conn.execute('''SELECT index_batch_id,index_payload_sha256,detail_html_sha256,reason_code
        FROM verified_source_ingest_blockers WHERE class_key=? AND spell_id=? AND stage=?''',
        (class_key,spell_id,stage)).fetchone()
    if row is None:return None
    idx=conn.execute('''SELECT raw_listview_json,batch_id FROM spell_index
        WHERE class_key=? AND spell_id=? AND kind='abilities' ''',(class_key,spell_id)).fetchone()
    if idx is None or idx[1]!=row[0] or sha256(idx[0].encode()).hexdigest()!=row[1]:
        raise ValueError('STALE_VERIFIED_SOURCE_BLOCKER_INDEX_REINGEST_REQUIRED')
    if row[2] is not None:
        # A parser-blocked page was valid source HTML. A data-only update
        # invalidates that blocker just as it invalidates a typed effect row.
        from src.v2.source_sqlite_detail_snapshots import read_verified_spell_detail_snapshot
        batch=conn.execute('''SELECT batch_id FROM spell_index WHERE class_key=?
            AND spell_id=? AND kind='abilities' ''',(class_key,spell_id)).fetchone()
        live=read_verified_spell_detail_snapshot(conn,batch_id=batch[0],spell_id=spell_id)
        if live['html_sha256']!=row[2]:
            raise ValueError('STALE_VERIFIED_SOURCE_BLOCKER_HTML_REINGEST_REQUIRED')
    return {'stage':stage,'reason_code':row[3],
            'detail_html_sha256':row[2],'index_payload_sha256':row[1],
            'index_batch_id':row[0]}
