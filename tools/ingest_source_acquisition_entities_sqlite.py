"""Batch-normalize verified Wowhead spell detail acquisition *entities*.

Only typed related-list entries (`npc`, `quest`, `item`) are accepted; unknown
JS/HTML formats block the snapshot, not silently turn into source evidence.
All entries are method affordances, never character acquisition/route proofs.
"""
from __future__ import annotations

from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from tools.ingest_source_acquisition_evidence_sqlite import METHODS, _observed_methods
from src.v2.source_sqlite_detail_snapshots import read_verified_spell_detail_snapshot
from src.game.data.forever.source_acquisition_entities import _typed_listview, TYPES

SCHEMA = '''CREATE TABLE IF NOT EXISTS ability_acquisition_entities (
 class_key TEXT NOT NULL, spell_id INTEGER NOT NULL, method TEXT NOT NULL,
 entity_id INTEGER NOT NULL, entity_name TEXT NOT NULL, source_entity_type TEXT NOT NULL,
 zone_ids_json TEXT NOT NULL, source_entity_json_sha256 TEXT NOT NULL,
 index_batch_id TEXT NOT NULL, detail_html_sha256 TEXT NOT NULL,
 source_url TEXT NOT NULL, source_payload_sha256 TEXT NOT NULL,
 PRIMARY KEY(class_key, spell_id, method, entity_id)
)'''


def ingest(db_path: Path) -> dict:
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute('''SELECT e.*,i.raw_listview_json,i.source_url AS live_url,
            i.batch_id AS live_batch FROM ability_acquisition_evidence e
            JOIN spell_index i ON i.class_key=e.class_key AND i.spell_id=e.spell_id
              AND i.kind='abilities' ORDER BY e.class_key,e.spell_id''').fetchall()
        if not rows:
            raise ValueError('missing source acquisition evidence; run primary batch first')
        prepared = []
        by_method = Counter()
        verified_details = 0
        for row in rows:
            if not row['detail_html_sha256']:
                continue
            if (row['index_batch_id'] != row['live_batch'] or row['source_url'] != row['live_url']
                or row['source_payload_sha256'] != hashlib.sha256(row['raw_listview_json'].encode()).hexdigest()):
                raise ValueError('index evidence stale: rerun acquisition batch first')
            verified = read_verified_spell_detail_snapshot(db, batch_id=row['index_batch_id'],
                                                            spell_id=int(row['spell_id']))
            if row['detail_html_sha256'] != verified['html_sha256']:
                raise ValueError('detail evidence stale: rerun acquisition batch first')
            methods = _observed_methods(verified['html'])
            if methods != json.loads(row['methods_observed_json']):
                raise ValueError('typed method count stale')
            verified_details += 1
            for method, (etype, anchor) in TYPES.items():
                if method not in methods:
                    continue
                entries = _typed_listview(verified['html'], anchor, etype)
                if len(entries) != methods[method]:
                    raise ValueError(f'{method} count inconsistent for spell {row["spell_id"]}')
                ids = []
                for entry in entries:
                    entity_id = entry.get('id')
                    if type(entity_id) is not int or entity_id <= 0:
                        raise ValueError('related listview lacks positive entity ID')
                    name = entry.get('displayName') or entry.get('name')
                    if not isinstance(name, str) or not name.strip():
                        raise ValueError('source entity unnamed')
                    zones = entry.get('location') or []
                    if not isinstance(zones, list) or any(type(v) is not int or v <= 0 for v in zones):
                        raise ValueError('invalid source zone IDs')
                    ids.append(entity_id)
                    prepared.append((row['class_key'], row['spell_id'],method,entity_id,
                        name.strip(),etype,json.dumps(sorted(set(zones))),
                        hashlib.sha256(json.dumps(entry,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
                        row['index_batch_id'],verified['html_sha256'],row['source_url'],
                        row['source_payload_sha256']))
                    by_method[method] += 1
                if len(ids) != len(set(ids)):
                    raise ValueError('duplicate source entity in one method list')
        db.execute('BEGIN IMMEDIATE')
        db.execute(SCHEMA)
        db.execute('DELETE FROM ability_acquisition_entities')
        db.executemany('''INSERT INTO ability_acquisition_entities VALUES
                            (?,?,?,?,?,?,?,?,?,?,?,?)''',prepared)
        db.commit()
    return {'verified_detail_snapshots':verified_details,'source_entity_links':len(prepared),
            'source_entity_links_by_method':dict(by_method),
            'unique_source_entities':len(set((x[2],x[3]) for x in prepared)),
            'verified_world_events':0,
            'interpretation':'related acquisition entity IDs and zones, NOT witnessed player visits'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--db',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(ingest(args.db),sort_keys=True,indent=2))
