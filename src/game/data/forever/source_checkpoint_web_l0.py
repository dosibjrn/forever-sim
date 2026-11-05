"""Read-only compatibility reader for historical L0 rune flags.

The retired P1 web-observation ingester is intentionally absent. This reader
remains only for the transitional GameIR rune-policy caller until that caller
is retired; native MythicSim owns Warcraft source facts and legality.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3


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
