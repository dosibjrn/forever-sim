from __future__ import annotations
"""Ingest source-recorded Armor stat and mode coefficients into canonical SQLite."""
import json
import math
from pathlib import Path
import sqlite3

DEFAULT_DB = Path('data/forever/catalogue/forever_abilities.sqlite')
DEFAULT_CAPTURE = Path('data/forever/source_captures/forever_armor_conversions_2026-10-10.json')


def ingest(db_path: Path = DEFAULT_DB, capture_path: Path = DEFAULT_CAPTURE) -> int:
    payload = json.loads(Path(capture_path).read_text(encoding='utf8'))
    rows = payload['entries']
    keys = [(r['class_key'], r['scope'], r['mode_label'], r['source_stat'], r['target_stat']) for r in rows]
    if not payload.get('capture_id') or not rows or len(set(keys)) != len(keys):
        raise ValueError('missing capture identity, empty data or duplicate armor source rules')
    for row in rows:
        if any(not row.get(k) for k in ('class_key', 'scope', 'source_stat', 'target_stat',
                                         'operation', 'authority', 'source_url', 'source_date', 'evidence')):
            raise ValueError('armor rule missing source facts')
        if (row['scope'] not in ('actor', 'mode') or row['operation'] != 'add_stat_scaled'
                or row['target_stat'] != 'armor' or (row['scope'] == 'mode' and not row['mode_label'])
                or (row['scope'] == 'actor' and row['mode_label'])
                or not math.isfinite(float(row['coefficient'])) or float(row['coefficient']) <= 0):
            raise ValueError('unexecutable armor source rule')
    with sqlite3.connect(db_path) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS armor_conversion_source_facts (
            class_key TEXT NOT NULL, scope TEXT NOT NULL, mode_label TEXT NOT NULL,
            source_stat TEXT NOT NULL, target_stat TEXT NOT NULL, operation TEXT NOT NULL,
            coefficient REAL NOT NULL, authority TEXT NOT NULL, source_url TEXT NOT NULL,
            source_date TEXT NOT NULL, evidence TEXT NOT NULL, capture_id TEXT NOT NULL,
            PRIMARY KEY(class_key,scope,mode_label,source_stat,target_stat))''')
        for r in rows:
            conn.execute('''INSERT OR REPLACE INTO armor_conversion_source_facts
                (class_key,scope,mode_label,source_stat,target_stat,operation,coefficient,
                 authority,source_url,source_date,evidence,capture_id)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                (r['class_key'],r['scope'],r['mode_label'],r['source_stat'],r['target_stat'],
                 r['operation'],float(r['coefficient']),r['authority'],r['source_url'],
                 r['source_date'],r['evidence'],payload['capture_id']))
    return len(rows)


if __name__ == '__main__':
    print(f'Ingested {ingest()} armor source rules')
