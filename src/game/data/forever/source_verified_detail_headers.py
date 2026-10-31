"""Read typed source detail headers, rechecking original immutable evidence.

This is a provenance and coverage accessor, not an executable spell compiler.
"""
from __future__ import annotations
from hashlib import sha256
import sqlite3
from src.v2.source_sqlite_detail_snapshots import read_verified_spell_detail_snapshot
from src.v2.source_sqlite_typed_spell_facts import extract_header_facts
from .source_ingest_blockers import read_blocker

def read_current_header(db:sqlite3.Connection, *,class_key:str,spell_id:int)->dict|None:
    """Recheck immutable source hashes on every read; stale rows cannot legalize action."""
    db.row_factory=sqlite3.Row
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='verified_spell_detail_header_facts'").fetchone():
        return None
    row=db.execute('''SELECT h.*,i.raw_listview_json,i.batch_id AS live_batch_id,
        i.source_url AS live_source_url FROM verified_spell_detail_header_facts h
        JOIN spell_index i ON i.class_key=h.class_key AND i.spell_id=h.spell_id
        AND i.kind='abilities' WHERE h.class_key=? AND h.spell_id=?''',
        (class_key,spell_id)).fetchone()
    if not row:
        blocker=read_blocker(db,class_key=class_key,spell_id=spell_id,stage='headers')
        if blocker:raise ValueError('SOURCE_VERIFIED_HEADERS_QUARANTINED:'+blocker['reason_code'])
        return None
    if (row['index_batch_id']!=row['live_batch_id'] or
        row['source_url']!=row['live_source_url'] or
        row['source_payload_sha256']!=sha256(row['raw_listview_json'].encode()).hexdigest()):
        raise ValueError('STALE_SOURCE_INDEX_HEADER_REINGEST_REQUIRED')
    evidence=read_verified_spell_detail_snapshot(db,batch_id=row['index_batch_id'],spell_id=spell_id)
    if evidence['html_sha256']!=row['detail_html_sha256']:
        raise ValueError('STALE_VERIFIED_DETAIL_HEADER_REINGEST_REQUIRED')
    facts=extract_header_facts({'html':evidence['html'],
        'lineage':{'source_url':evidence['source_url'],
                   'html_sha256':evidence['html_sha256']}},spell_id=spell_id)
    cost=facts['resource_cost']
    if (row['name']!=facts['name'] or row['required_level']!=facts['required_level']
        or row['cost_resource']!=(cost['resource'] if cost else None)
        or row['cost_amount']!=(float(cost['amount']) if cost else None)
        or row['range_text']!=facts['range_text']
        or row['unparsed_effect_text']!=facts['unparsed_effect_text']
        or row['effect_execution_status']!='SOURCE_VERIFIED_HEADER_ONLY_UNPARSED_EFFECT_NOT_EXECUTABLE'):
        raise ValueError('TAMPERED_VERIFIED_DETAIL_HEADER_REINGEST_REQUIRED')
    return dict(row)


# Re-parse expensive verified HTML once per exact SQLite content identity,
# not on every class-level policy candidate. SHA includes a live SQLite WAL
# if one exists. No cached value can survive a data-only SQLite mutation.
from functools import lru_cache
from pathlib import Path


def verified_headers_for_class(db_path: str|Path, class_key:str) -> dict[int,dict]:
    path=Path(db_path).resolve()
    h=sha256(path.read_bytes())
    wal=Path(str(path)+'-wal')
    if wal.exists():h.update(wal.read_bytes())
    return _verified_headers_for_class_cached(str(path),h.hexdigest(),class_key)


@lru_cache(maxsize=64)
def _verified_headers_for_class_cached(path:str,source_content_sha256:str,class_key:str)->dict[int,dict]:
    with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='verified_spell_detail_header_facts'").fetchone():
            return {}
        ids=[int(r[0]) for r in db.execute(
            'SELECT spell_id FROM verified_spell_detail_header_facts WHERE class_key=?',
            (class_key,))]
        return {sid:read_current_header(db,class_key=class_key,spell_id=sid)
                for sid in ids}
