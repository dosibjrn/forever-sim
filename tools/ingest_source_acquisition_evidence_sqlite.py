"""Batch-source all indexed spell acquisition hints plus verified detail methods.

No spell IDs, classes, or trainer mechanics are hardcoded. No listview source
code, training cost, or Taught-by count is promoted to a learned spell or a
legal world transition. Re-runnable and atomic; stale snapshots fail closed.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from bs4 import BeautifulSoup

from src.v2.source_sqlite_detail_snapshots import read_verified_spell_detail_snapshot, MissingVerifiedSpellDetail

SCHEMA = '''CREATE TABLE IF NOT EXISTS ability_acquisition_evidence (
 class_key TEXT NOT NULL, spell_id INTEGER NOT NULL,
 index_batch_id TEXT NOT NULL, source_url TEXT NOT NULL,
 source_payload_sha256 TEXT NOT NULL, required_level_hint INTEGER,
 rank_hint INTEGER, training_cost_hint REAL, source_codes_json TEXT NOT NULL,
 detail_html_sha256 TEXT, methods_observed_json TEXT NOT NULL,
 evidence_status TEXT NOT NULL, captured_at TEXT NOT NULL,
 PRIMARY KEY(class_key, spell_id)
)'''
METHODS = {'taught_by_npc': ('Taught by', '#taught-by-npc'),
           'taught_by_item': ('Taught by', '#taught-by-item'),
           'reward_from_quest': ('Reward from', '#reward-from-q'),
           'used_by_item': ('Used by Item', '#used-by-item')}


def _observed_methods(html: str) -> dict:
    soup = BeautifulSoup(html, 'html.parser')
    methods = {}
    for key, (label, anchor) in METHODS.items():
        # "Taught by" may be an item, not an NPC. The tab's typed source
        # anchor, not its ambiguous visible label, establishes method kind.
        tabs = soup.select('button[data-href]')
        matches = [tab for tab in tabs if tab.get('data-href') == anchor]
        if len(matches) > 1:
            raise ValueError('ambiguous acquisition method tab ' + anchor)
        if matches:
            text = matches[0].get_text(' ', strip=True)
            count = re.fullmatch(re.escape(label) + r'\s*\((\d+)\)', text, re.I)
            if not count:
                raise ValueError('malformed acquisition method count ' + anchor)
            methods[key] = int(count.group(1))
    return methods


def ingest(db_path: Path) -> dict:
    db = sqlite3.connect(str(db_path)); db.row_factory = sqlite3.Row
    try:
        indexed = db.execute('''SELECT i.*,b.captured_at FROM spell_index i
            JOIN capture_batches b ON b.batch_id=i.batch_id
            WHERE i.kind='abilities' ORDER BY i.class_key,i.spell_id''').fetchall()
        if not indexed:
            raise ValueError('empty indexed abilities')
        detail_keys = {(r['batch_id'], int(r['spell_id'])) for r in db.execute(
            'SELECT batch_id,spell_id FROM spell_detail_snapshots')}
        prepared = []
        for row in indexed:
            raw = json.loads(row['raw_listview_json'])
            training_cost = raw.get('trainingcost')
            if training_cost is not None:
                try:
                    training_cost = float(training_cost)
                except (TypeError, ValueError) as exc:
                    raise ValueError('invalid source trainingcost') from exc
                if training_cost < 0:
                    raise ValueError('negative source trainingcost')
            source_codes = raw.get('source') or []
            if not isinstance(source_codes, list):
                raise ValueError('invalid listview source codes')
            methods, detail_sha = {}, None
            key = (row['batch_id'], int(row['spell_id']))
            if key in detail_keys:
                verified = read_verified_spell_detail_snapshot(
                    db, batch_id=row['batch_id'], spell_id=int(row['spell_id']))
                detail_sha = verified['html_sha256']
                methods = _observed_methods(verified['html'])
            status = ('VERIFIED_DETAIL_METHOD_OBSERVATION_NOT_WORLD_ACCESS'
                      if methods else 'INDEX_HINTS_ONLY_NO_ACQUISITION_PROOF')
            prepared.append((row['class_key'], int(row['spell_id']), row['batch_id'],
                row['source_url'], hashlib.sha256(row['raw_listview_json'].encode()).hexdigest(),
                row['level_hint'], row['rank_hint'], training_cost,
                json.dumps(source_codes), detail_sha, json.dumps(methods,sort_keys=True),
                status, row['captured_at']))
        db.execute('BEGIN IMMEDIATE')
        db.execute(SCHEMA)
        db.execute('DELETE FROM ability_acquisition_evidence')
        db.executemany('INSERT INTO ability_acquisition_evidence VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', prepared)
        db.commit()
        return {'indexed_abilities':len(prepared),
                'by_class':dict(Counter(x[0] for x in prepared)),
                'by_evidence_status':dict(Counter(x[11] for x in prepared)),
                'verified_method_observations':sum(bool(json.loads(x[10])) for x in prepared),
                'world_acquisition_verified':0,
                'note':'source hints and detail methods only; no trainer visits or quest completion inferred'}
    except Exception:
        db.rollback();raise
    finally:
        db.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--db',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(ingest(args.db),indent=2,sort_keys=True))
