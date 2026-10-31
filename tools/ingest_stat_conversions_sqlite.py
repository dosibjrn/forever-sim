from __future__ import annotations
"""Atomic ingestion of explicit, provenance-labelled stat conversion facts."""
import json
from pathlib import Path
import sqlite3

DEFAULT_CAPTURE = Path('data/forever/source_captures/forever_inherited_stat_conversions_2026-10-10.json')
DEFAULT_DB = Path('data/forever/catalogue/forever_abilities.sqlite')


def ingest(db_path: Path = DEFAULT_DB, capture_path: Path = DEFAULT_CAPTURE) -> int:
    payload = json.loads(Path(capture_path).read_text())
    rows = payload['entries']
    if not rows or len({(r['class_key'], r['source_stat'], r['target_type'],r['target_id'],r['mode_label']) for r in rows}) != len(rows):
        raise ValueError('empty or duplicate stat conversion capture')
    for row in rows:
        if not all(row.get(k) for k in ('class_key','source_stat','target_type','target_id','mode_label','source_url','authority')):
            raise ValueError('stat conversion fact missing authority or identity')
        if row['target_type'] not in ('stat','resource_capacity') or float(row['coefficient']) <= 0:
            raise ValueError('invalid stat conversion fact')
    with sqlite3.connect(db_path) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS stat_conversion_source_facts (
            class_key TEXT NOT NULL, source_stat TEXT NOT NULL, target_type TEXT NOT NULL,
            target_id TEXT NOT NULL, mode_label TEXT NOT NULL, coefficient REAL NOT NULL,
            authority TEXT NOT NULL, source_url TEXT NOT NULL, capture_id TEXT NOT NULL,
            PRIMARY KEY(class_key,source_stat,target_type,target_id,mode_label))''')
        for row in rows:
            conn.execute('''INSERT OR REPLACE INTO stat_conversion_source_facts
                (class_key,source_stat,target_type,target_id,mode_label,coefficient,authority,source_url,capture_id)
                VALUES (?,?,?,?,?,?,?,?,?)''',
                (row['class_key'],row['source_stat'],row['target_type'],row['target_id'],row['mode_label'],
                 float(row['coefficient']),row['authority'],row['source_url'],payload['capture_id']))
    return len(rows)

if __name__ == '__main__':
    print(f'Ingested {ingest()} source stat conversions')
