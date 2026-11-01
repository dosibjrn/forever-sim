from __future__ import annotations
"""Ingest official mode-local equipped weapon DPS semantics; no engine class switches."""
import json
from pathlib import Path
import sqlite3

DEFAULT_DB = Path('data/forever/catalogue/forever_abilities.sqlite')
DEFAULT_CAPTURE = Path('data/forever/source_captures/forever_equipped_weapon_mode_2026-10-10.json')


def ingest(db_path: Path = DEFAULT_DB, capture_path: Path = DEFAULT_CAPTURE) -> int:
    capture = json.loads(Path(capture_path).read_text())
    entries = capture['entries']
    keys = [(x['class_key'], x['mode_label'], x['source_stat'], x['damage_source_kind']) for x in entries]
    if not entries or len(set(keys)) != len(keys):
        raise ValueError('empty or duplicate equipped weapon source facts')
    for row in entries:
        if (not all(row.get(k) for k in ('class_key', 'mode_label', 'source_stat', 'damage_source_kind'))
                or row['operation'] != 'replace_flat_dps'
                or row['applies_to'] != 'auto_and_weapon_actions'):
            raise ValueError('unsupported equipped weapon source fact')
    if not all(capture.get(k) for k in ('capture_id', 'source_url', 'source_date', 'evidence')):
        raise ValueError('equipped weapon source lacks provenance')
    with sqlite3.connect(db_path) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS equipped_weapon_mode_source_facts (
            class_key TEXT NOT NULL, mode_label TEXT NOT NULL, source_stat TEXT NOT NULL,
            damage_source_kind TEXT NOT NULL, operation TEXT NOT NULL, applies_to TEXT NOT NULL,
            authority TEXT NOT NULL, source_url TEXT NOT NULL, source_date TEXT NOT NULL,
            evidence TEXT NOT NULL, capture_id TEXT NOT NULL,
            PRIMARY KEY(class_key, mode_label, source_stat, damage_source_kind))''')
        for row in entries:
            conn.execute('''INSERT OR REPLACE INTO equipped_weapon_mode_source_facts
                (class_key,mode_label,source_stat,damage_source_kind,operation,applies_to,
                 authority,source_url,source_date,evidence,capture_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (row['class_key'], row['mode_label'], row['source_stat'], row['damage_source_kind'],
                 row['operation'], row['applies_to'], 'blizzard_dated_patch_note',
                 capture['source_url'], capture['source_date'], capture['evidence'], capture['capture_id']))
    return len(entries)


if __name__ == '__main__':
    print(f'Ingested {ingest()} equipped weapon mode facts')
