"""Historical source-acquisition evidence reader for still-live legacy consumers.

This is source provenance only, never a Warcraft spell-legality verdict.
The selected MythicSim Rust engine owns acquisition and legal learned ranks.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Iterable

from .source_db_scope import DEFAULT_DB


def read_acquisition_evidence(*, class_key: str, spell_ids: Iterable[int],
                              db_path: str | Path | None = None) -> dict[int, dict]:
    ids = sorted(set(int(x) for x in spell_ids))
    if not ids:
        return {}
    path = Path(db_path or DEFAULT_DB)
    with sqlite3.connect(f'file:{path.resolve()}?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ability_acquisition_evidence'").fetchone():
            return {}
        rows = db.execute('''SELECT e.*, i.raw_listview_json, i.batch_id AS live_batch,
                                  i.level_hint AS live_level, i.source_url AS live_url,
                                  s.html_sha256 AS live_detail_sha,
                                  d.details_verified AS live_detail_verified,
                                  b.status AS live_batch_status
            FROM ability_acquisition_evidence e JOIN spell_index i
              ON e.class_key=i.class_key AND e.spell_id=i.spell_id AND i.kind='abilities'
            LEFT JOIN spell_detail_snapshots s ON s.batch_id=e.index_batch_id AND s.spell_id=e.spell_id
            LEFT JOIN spell_details d ON d.batch_id=e.index_batch_id AND d.spell_id=e.spell_id
            LEFT JOIN capture_batches b ON b.batch_id=e.index_batch_id
            WHERE e.class_key=?''', (class_key.strip().lower(),)).fetchall()
    results = {}
    for r in rows:
        sid = int(r['spell_id'])
        if sid not in ids:
            continue
        if (r['source_payload_sha256'] != hashlib.sha256(r['raw_listview_json'].encode()).hexdigest()
                or r['index_batch_id'] != r['live_batch'] or r['source_url'] != r['live_url']
                or r['required_level_hint'] != r['live_level']):
            results[sid] = {'status': 'STALE_INDEX_EVIDENCE', 'spell_id': sid}
            continue
        if r['detail_html_sha256'] is not None and (
                r['detail_html_sha256'] != r['live_detail_sha']
                or r['live_detail_verified'] != 1 or r['live_batch_status'] != 'complete'):
            results[sid] = {'status': 'STALE_DETAIL_EVIDENCE', 'spell_id': sid}
            continue
        results[sid] = {
            'spell_id': sid, 'class_key': r['class_key'],
            'required_level_hint': r['required_level_hint'],
            'methods_observed': json.loads(r['methods_observed_json']),
            'evidence_status': r['evidence_status'],
            'index_batch_id': r['index_batch_id'],
            'detail_html_sha256': r['detail_html_sha256'],
            'source_url': r['source_url'], 'status': 'CURRENT_SOURCE_EVIDENCE',
        }
    return results

