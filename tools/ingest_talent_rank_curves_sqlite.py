"""Ingest sourced trait rank curves for *any* indexed talent, without talent-specific code.

Captured raw tooltips are data; normalization/execution happens generically at
runtime. A partial batch never changes the canonical index completeness flag.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlparse


def ingest(db_path: Path, capture_path: Path) -> dict:
    payload = json.loads(Path(capture_path).read_text(encoding='utf-8'))
    if payload.get('schema') != 'wowhead_forever_trait_rank_capture_v1':
        raise ValueError('unsupported trait rank capture schema')
    class_key = str(payload['class_key']).lower()
    batch = str(payload['capture_id'])
    entries = payload.get('entries')
    if not isinstance(entries, list) or not entries:
        raise ValueError('empty trait rank capture')
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('''CREATE TABLE IF NOT EXISTS talent_rank_source_facts (
            class_key TEXT NOT NULL, spell_id INTEGER NOT NULL, rank INTEGER NOT NULL,
            max_rank INTEGER NOT NULL, trait_id INTEGER NOT NULL,
            raw_tooltip TEXT NOT NULL, source_url TEXT NOT NULL,
            tooltip_source_url TEXT NOT NULL,
            source_authority TEXT NOT NULL, capture_id TEXT NOT NULL,
            captured_at TEXT NOT NULL,
            PRIMARY KEY(class_key, spell_id, rank)
        )''')
        indexed = {int(row[0]): str(row[1]) for row in conn.execute(
            'SELECT spell_id,name FROM spell_index WHERE class_key=? AND kind=?',
            (class_key, 'talents'))}
        seen: set[int] = set()
        count = 0
        for entry in entries:
            spell_id = int(entry['spell_id'])
            if spell_id in seen or indexed.get(spell_id) != entry.get('name'):
                raise ValueError(f'unknown, renamed or duplicate indexed talent: {spell_id}')
            seen.add(spell_id)
            url = str(entry['source_url'])
            if (urlparse(url).hostname != 'www.wowhead.com' or
                    f'/forever/spell={spell_id}' not in url):
                raise ValueError(f'noncanonical source URL: {url}')
            tooltip_url = str(entry.get('tooltip_source_url') or '')
            if urlparse(tooltip_url).scheme != 'https' or not urlparse(tooltip_url).hostname:
                raise ValueError(f'missing tooltip transcription source URL: {spell_id}')
            cap = int(entry['max_rank'])
            ranks = entry.get('ranks') or []
            if cap < 1 or len(ranks) != cap or sorted(int(x['rank']) for x in ranks) != list(range(1,cap+1)):
                raise ValueError(f'incomplete or duplicate trait ranks: {spell_id}')
            if int(entry['trait_id']) < 1:
                raise ValueError(f'invalid trait ID: {spell_id}')
            old = conn.execute('SELECT DISTINCT capture_id FROM talent_rank_source_facts WHERE class_key=? AND spell_id=?',
                               (class_key,spell_id)).fetchall()
            if old and any(row[0] != batch for row in old):
                raise ValueError(f'replacing a different capture requires explicit reconciliation: {spell_id}')
            for row in ranks:
                tooltip = str(row['raw_tooltip']).strip()
                if not tooltip:
                    raise ValueError(f'empty tooltip: {spell_id} rank {row["rank"]}')
                conn.execute('''INSERT OR REPLACE INTO talent_rank_source_facts
                    (class_key,spell_id,rank,max_rank,trait_id,raw_tooltip,source_url,
                     tooltip_source_url,source_authority,capture_id,captured_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                    (class_key,spell_id,int(row['rank']),cap,int(entry['trait_id']),tooltip,url,tooltip_url,
                     str(entry['source_authority']),batch,str(payload['captured_at'])))
                count += 1
        conn.commit()
        return {'class_key':class_key,'capture_id':batch,'families':len(seen),'ranks':count,
                'indexed_families':len(indexed),'partial':len(seen)!=len(indexed)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--db',type=Path,default=Path('data/forever/catalogue/forever_abilities.sqlite'))
    parser.add_argument('--capture',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(ingest(args.db,args.capture),indent=2))
