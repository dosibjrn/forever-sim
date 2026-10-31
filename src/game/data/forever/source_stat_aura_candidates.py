"""Nine-class, source-hash-bound typed stat-aura *candidate* ingestion.

This batch recognizes complete literal primary-stat buff tooltips without
inventing character starting attributes, acquisition or target legality. A
candidate is NEVER a legal L2 action. It becomes a generic runtime aura only
when an independently sourced actor baseline and acquisition are available.
The compiler is spell-ID/name/class independent.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3

from .sqlite_talents import DEFAULT_DB

# Entire tooltip must match one of the exact source-observed phrasings.
_TEXT = re.compile(
    r"^(?:Increases the target's|(?:Power|Holy power) infuses the target, increasing their) "
    r"(?P<stat>Strength|Agility|Stamina|Intellect|Spirit) by (?P<amount>\d+) "
    r"for (?P<duration>\d+) hour(?:s)?\.$", re.I)
_COST = re.compile(r'^(?P<amount>\d+(?:\.\d+)?) Mana$', re.I)
_SCHEMA = '''CREATE TABLE IF NOT EXISTS source_index_stat_aura_candidates (
 class_key TEXT NOT NULL, spell_id INTEGER NOT NULL,
 batch_id TEXT NOT NULL, source_url TEXT NOT NULL,
 required_level_hint INTEGER NOT NULL,
 stat_id TEXT NOT NULL, stat_amount REAL NOT NULL,
 duration_s REAL NOT NULL, mana_cost REAL NOT NULL,
 index_payload_sha256 TEXT NOT NULL,
 execution_status TEXT NOT NULL,
 PRIMARY KEY(class_key,spell_id))'''
_BLOCKED = 'BLOCKED_ACTOR_PRIMARY_BASELINE_AND_ACQUISITION_UNVERIFIED'


def _extract(row):
    raw=json.loads(row['raw_listview_json'])
    if raw.get('id')!=row['spell_id'] or raw.get('name')!=row['name'] or raw.get('level')!=row['level_hint']:
        raise ValueError('SOURCE_STAT_AURA_INDEX_IDENTITY_MISMATCH')
    env=raw.get('envChange') or {}
    if env.get('status')=='removed':
        return None
    after=env.get('after') or {}
    m=_TEXT.fullmatch(str(after.get('text') or '').strip())
    if m is None:
        return None
    cost=_COST.fullmatch(str(after.get('cost') or '').strip())
    if (cost is None or str(after.get('cast'))!='Instant' or
            after.get('cooldown') not in ('',None) or after.get('name')!=row['name'] or
            row['level_hint'] is None or int(row['level_hint'])<1 or
            int(m['amount'])<=0 or int(m['duration'])<=0):
        # A matching stat effect with missing cost or timing is a typed blocker,
        # not a free or executable aura.
        return None
    return (row['class_key'],row['spell_id'],row['batch_id'],row['source_url'],
            int(row['level_hint']),m['stat'].lower(),float(m['amount']),
            float(m['duration'])*3600,float(cost['amount']),
            sha256(row['raw_listview_json'].encode()).hexdigest(),_BLOCKED)


def ingest(db_path: Path | str = DEFAULT_DB)->dict:
    with sqlite3.connect(str(db_path)) as db:
        db.row_factory=sqlite3.Row
        rows=db.execute('''SELECT i.class_key,i.spell_id,i.batch_id,i.name,i.level_hint,
            i.source_url,i.raw_listview_json FROM spell_index i JOIN capture_lists l
            ON i.batch_id=l.batch_id AND i.class_key=l.class_key AND i.kind=l.kind
            JOIN capture_batches b ON b.batch_id=i.batch_id
            WHERE i.kind='abilities' AND l.complete=1 AND b.status='complete'
            ORDER BY i.class_key,i.spell_id''').fetchall()
        if len({r['class_key'] for r in rows})!=9:
            raise ValueError('SOURCE_STAT_AURA_REQUIRES_NINE_COMPLETE_CLASS_INDEXES')
        candidates=[r for row in rows if (r:=_extract(row)) is not None]
        db.execute('BEGIN IMMEDIATE')
        db.execute(_SCHEMA)
        db.execute('DELETE FROM source_index_stat_aura_candidates')
        db.executemany('INSERT INTO source_index_stat_aura_candidates VALUES (?,?,?,?,?,?,?,?,?,?,?)',candidates)
        return {'indexed':len(rows),'classes_scanned':9,'typed_candidates':len(candidates),
            'by_class':dict(Counter(r[0] for r in candidates)),
            'by_stat':dict(Counter(r[5] for r in candidates)),
            'executable_promotions':0,'accepted_checkpoints':0,
            'status':'TYPED_SOURCE_EVIDENCE_NOT_EXECUTABLE'}


def read_current_candidates(db_path: Path | str, *, class_key: str)->tuple[dict,...]:
    with sqlite3.connect(f'file:{Path(db_path).resolve()}?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_index_stat_aura_candidates'").fetchone():
            return ()
        rows=db.execute('''SELECT a.*,i.name,i.level_hint AS live_level,i.level_hint,i.raw_listview_json,
            i.source_url AS live_url,i.batch_id AS live_batch FROM source_index_stat_aura_candidates a
            JOIN spell_index i ON i.class_key=a.class_key AND i.spell_id=a.spell_id
            AND i.kind='abilities' WHERE a.class_key=? ORDER BY a.required_level_hint,a.spell_id''',
            (str(class_key).lower(),)).fetchall()
        out=[]
        for row in rows:
            if (row['index_payload_sha256']!=sha256(row['raw_listview_json'].encode()).hexdigest()
                or row['batch_id']!=row['live_batch'] or row['source_url']!=row['live_url']
                or row['required_level_hint']!=row['live_level']):
                raise ValueError('STALE_SOURCE_STAT_AURA_REINGEST_REQUIRED')
            fresh=_extract(row)
            if fresh is None or tuple(fresh)!=tuple(row[k] for k in (
                'class_key','spell_id','batch_id','source_url','required_level_hint',
                'stat_id','stat_amount','duration_s','mana_cost','index_payload_sha256','execution_status')):
                raise ValueError('TAMPERED_SOURCE_STAT_AURA_REINGEST_REQUIRED')
            out.append({k:row[k] for k in ('class_key','spell_id','source_url','required_level_hint',
                'stat_id','stat_amount','duration_s','mana_cost','execution_status')})
        return tuple(out)
