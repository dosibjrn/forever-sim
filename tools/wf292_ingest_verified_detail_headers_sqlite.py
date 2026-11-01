#!/usr/bin/env python3
"""Batch materialize typed spell headers from SHA-verified canonical Wowhead HTML.

This recovers source-observed resource costs and required levels when listview
is incomplete. It deliberately does NOT assert coefficients, effect mechanics,
rank acquisition, executable actions or source-complete checkpoints.
All classes and all verified snapshots are handled without spell allowlists.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

# Direct CLI execution starts with tools/ on sys.path, not the repository root.
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import re
import sqlite3

from src.v2.source_sqlite_detail_snapshots import read_verified_spell_detail_snapshot
from src.v2.source_sqlite_typed_spell_facts import extract_header_facts
from src.game.data.forever.source_ingest_blockers import SCHEMA as BLOCKER_SCHEMA, reason as blocker_reason

SCHEMA='''CREATE TABLE IF NOT EXISTS verified_spell_detail_header_facts (
 class_key TEXT NOT NULL, spell_id INTEGER NOT NULL, index_batch_id TEXT NOT NULL,
 source_url TEXT NOT NULL, source_payload_sha256 TEXT NOT NULL,
 detail_html_sha256 TEXT NOT NULL, name TEXT NOT NULL,
 required_level INTEGER NOT NULL, cost_resource TEXT, cost_amount REAL,
 range_text TEXT, unparsed_effect_text TEXT NOT NULL,
 effect_execution_status TEXT NOT NULL,
 PRIMARY KEY(class_key,spell_id)
)'''
_COST=re.compile(r'(\d+(?:\.\d+)?)\s+(Mana|Energy|Rage|Focus)',re.I)


def ingest(db_path:Path, *, quarantine_structural_errors:bool=False)->dict:
    db=sqlite3.connect(db_path);db.row_factory=sqlite3.Row
    try:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise ValueError('CORRUPT_SOURCE_SQLITE')
        rows=db.execute('''SELECT i.* FROM spell_index i
            JOIN spell_detail_snapshots d ON d.batch_id=i.batch_id AND d.spell_id=i.spell_id
            WHERE i.kind='abilities' ORDER BY i.class_key,i.spell_id''').fetchall()
        if not rows:
            raise ValueError('NO_SOURCE_VERIFIED_DETAILS')
        prepared=[];recovered_cost=0;blocked=[]
        for row in rows:
            evidence=None
            try:
                sid=int(row['spell_id'])
                evidence=read_verified_spell_detail_snapshot(db,batch_id=row['batch_id'],spell_id=sid)
                facts=extract_header_facts({'html':evidence['html'],
                    'lineage':{'source_url':evidence['source_url'],
                               'html_sha256':evidence['html_sha256']}},spell_id=sid)
                if facts['name']!=row['name'] or facts['required_level']!=row['level_hint']:
                    raise ValueError(f'DETAIL_INDEX_IDENTITY_OR_LEVEL_DRIFT:{sid}')
                if evidence['source_url']!=row['source_url']:
                    raise ValueError(f'DETAIL_INDEX_URL_DRIFT:{sid}')
                raw=json.loads(row['raw_listview_json']); after=(raw.get('envChange') or {}).get('after') or {}
                indexed_cost=str(after.get('cost') or '').strip()
                parsed=_COST.fullmatch(indexed_cost) if indexed_cost else None
                if indexed_cost and not parsed:
                    raise ValueError(f'INDEX_COST_GRAMMAR_UNKNOWN:{sid}')
                cost=facts['resource_cost']
                if parsed and (cost is None or float(parsed.group(1))!=float(cost['amount'])
                        or parsed.group(2).lower()!=cost['resource']):
                    raise ValueError(f'INDEX_AND_VERIFIED_DETAIL_COST_CONFLICT:{sid}')
                if not parsed and cost:recovered_cost+=1
                prepared.append((row['class_key'],sid,row['batch_id'],row['source_url'],
                    sha256(row['raw_listview_json'].encode()).hexdigest(),evidence['html_sha256'],
                    facts['name'],int(facts['required_level']),
                    cost['resource'] if cost else None,float(cost['amount']) if cost else None,
                    facts['range_text'],facts['unparsed_effect_text'],
                    'SOURCE_VERIFIED_HEADER_ONLY_UNPARSED_EFFECT_NOT_EXECUTABLE'))
            except (ValueError,KeyError,TypeError) as exc:
                if not quarantine_structural_errors:raise
                blocked.append((row['class_key'],int(row['spell_id']),'headers',row['batch_id'],
                    sha256(row['raw_listview_json'].encode()).hexdigest(),
                    evidence['html_sha256'] if evidence is not None else None,blocker_reason(exc)))
                continue
        db.execute('BEGIN IMMEDIATE')
        db.execute(SCHEMA);db.execute(BLOCKER_SCHEMA)
        db.execute("DELETE FROM verified_source_ingest_blockers WHERE stage='headers'")
        db.executemany('INSERT INTO verified_source_ingest_blockers VALUES (?,?,?,?,?,?,?)',blocked)
        db.execute('DELETE FROM verified_spell_detail_header_facts')
        db.executemany('''INSERT INTO verified_spell_detail_header_facts VALUES
            (?,?,?,?,?,?,?,?,?,?,?,?,?)''',prepared)
        db.commit()
        return {'indexed_source_verified_headers':len(prepared),
            'by_class':dict(Counter(r[0] for r in prepared)),
            'costs_recovered_where_index_missing':recovered_cost,
            'quarantined_source_pages':len(blocked),'quarantine_reasons':dict(Counter(x[-1] for x in blocked)),
            'executable_promotions':0,'accepted_checkpoints':0,
            'source':'independent SHA-verified canonical spell detail HTML',
            'effect_execution_status':'BLOCKED_UNPARSED_EFFECT_OR_INCOMPLETE_MECHANICS'}
    except Exception:
        db.rollback();raise
    finally:db.close()




if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,required=True)
    a=p.parse_args()
    print(json.dumps(ingest(a.db),indent=2,sort_keys=True))
