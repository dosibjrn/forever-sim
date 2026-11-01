"""Migrate *all* pinned source talent records to the canonical abilities SQLite.

This is a one-time source snapshot migration, not a runtime fallback or a
hand-selected list of talents. Existing Wowhead spell_index remains the
identity inventory; this table holds previously normalized rank facts with
explicit legacy-snapshot provenance. No inferred ranks are generated.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3


def ingest(db_path: Path, fixture_root: Path, snapshot: str, class_key: str) -> dict:
    path = fixture_root / snapshot / class_key / 'talents.json'
    records = json.loads(path.read_text(encoding='utf-8'))
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS talent_normalized_records (
            class_key TEXT NOT NULL, spell_id INTEGER NOT NULL,
            snapshot_id TEXT NOT NULL, source_record_json TEXT NOT NULL,
            PRIMARY KEY (class_key, spell_id)
        )''')
        indexed = {int(id): name for id, name in conn.execute(
            'SELECT spell_id,name FROM spell_index WHERE class_key=? AND kind=?',
            (class_key, 'talents'))}
        imported = 0
        unresolved = []
        for row in records:
            matches = [int(ref['entity_id']) for ref in row.get('source_refs', [])
                       if ref.get('provider') == 'wowhead' and int(ref.get('entity_id', -1)) in indexed
                       and indexed[int(ref['entity_id'])].casefold() == row['name'].casefold()]
            if len(set(matches)) != 1:
                unresolved.append(row['local_key'])
                continue
            conn.execute('INSERT OR REPLACE INTO talent_normalized_records VALUES (?,?,?,?)',
                         (class_key, matches[0], snapshot, json.dumps(row, sort_keys=True)))
            imported += 1
        conn.commit()
        return {'indexed': len(indexed), 'snapshot_records': len(records),
                'imported': imported, 'unmatched': unresolved}
    finally:
        conn.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--db', type=Path, default=Path('data/forever/catalogue/forever_abilities.sqlite'))
    p.add_argument('--fixtures', type=Path, default=Path('src/rulesets/forever/data/fixtures'))
    p.add_argument('--snapshot', default='forever_2026_09_26')
    p.add_argument('--class-key', default='druid')
    args = p.parse_args()
    print(json.dumps(ingest(args.db, args.fixtures, args.snapshot, args.class_key), indent=2))
