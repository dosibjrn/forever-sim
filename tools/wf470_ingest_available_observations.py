#!/usr/bin/env python3
"""Source-ID-anchored import of independently captured effect observations.

The ingest tool is class-neutral. Its input files carry all spell-specific facts.
The runtime and optimizer always consume typed, canonical SQLite records.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import json
import sqlite3
from hashlib import sha256
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from src.game.data.forever.source_queued_swing import ingest as ingest_queued
from tools.wf321_ingest_control_observations import ingest as ingest_control

_SCHEMA='''CREATE TABLE IF NOT EXISTS p1_source_effect_role_facts (
 class_key TEXT NOT NULL, spell_id INTEGER NOT NULL, name TEXT NOT NULL,
 roles_json TEXT NOT NULL, source_index_url TEXT NOT NULL,
 source_index_sha256 TEXT NOT NULL,
 evidence_url TEXT NOT NULL, evidence_text TEXT NOT NULL,
 PRIMARY KEY(class_key,spell_id))'''

_ALLOWED=frozenset({'damage','buff','debuff','cc','healing','utility','threat'})

def ingest_roles(db_path:Path, src:Path):
    raw=json.loads(src.read_text())
    if raw.get('schema')!='p1_source_effect_roles_v1':
        raise ValueError('P1_SCOPE_SOURCE_SCHEMA_UNSUPPORTED')
    with sqlite3.connect(db_path) as conn:
        conn.row_factory=sqlite3.Row
        conn.execute(_SCHEMA)
        for fact in raw['records']:
            sid=int(fact['spell_id']);cls=str(fact['class_key']);name=str(fact['name'])
            row=conn.execute('SELECT * FROM spell_index WHERE class_key=? AND spell_id=? AND kind=?',
                             (cls,sid,'abilities')).fetchone()
            if row is None or row['name']!=name or row['source_url']!=fact['source_index_url']:
                raise ValueError('P1_SCOPE_SOURCE_INDEX_ID_NAME_URL_MISMATCH:'+str(sid))
            roles=fact['roles']
            if (not isinstance(roles,list) or not roles or len(roles)!=len(set(roles))
                    or not set(roles)<=_ALLOWED or not str(fact['source_url']).startswith('https://')
                    or not str(fact.get('evidence') or '')):
                raise ValueError('P1_SCOPE_INVALID_ROLE_OR_PROVENANCE:'+str(sid))
            conn.execute('INSERT OR REPLACE INTO p1_source_effect_role_facts VALUES (?,?,?,?,?,?,?,?)',
                         (cls,sid,name,json.dumps(sorted(roles)),row['source_url'],
                          sha256(row['raw_listview_json'].encode()).hexdigest(),
                          fact['source_url'],fact['evidence']))
        if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise ValueError('P1_SCOPE_DATABASE_INTEGRITY_FAILED')


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument('--db',required=True,type=Path)
    p.add_argument('--queued',action='append',default=[],type=Path)
    p.add_argument('--control',action='append',default=[],type=Path)
    p.add_argument('--scope-roles',action='append',default=[],type=Path)
    a=p.parse_args()
    if not (a.queued or a.control or a.scope_roles):
        p.error('specify at least one source observation file')
    if not a.db.is_file():p.error('--db does not exist')
    for src in a.queued:
        ingest_queued(a.db,src)
        print('INGESTED queued',src)
    for src in a.control:
        ingest_control(a.db,src)
        print('INGESTED control',src)
    for src in a.scope_roles:
        ingest_roles(a.db,src)
        print('INGESTED sourced effect roles',src)
    return 0

if __name__=='__main__':
    raise SystemExit(main())
