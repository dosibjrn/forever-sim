#!/usr/bin/env python3
"""Migrate an already source-captured resource-scaled periodic family to typed SQLite.

All rank values are parsed from the canonical captured tooltip. Mechanics that
are not in the tooltip (tick cadence, resource binding, crit/AP semantics) must
be supplied as explicitly attributed evidence; unknown coefficients remain
blockers rather than invented numbers. Run on a staging SQLite first.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from src.game.data.forever.source_ability_semantics import parse_resource_scaled_periodic_ladder


def ingest(db_path: Path, *, class_key: str, family: str, required_mode: str,
           resource_id: str, tick_interval_s: float, mechanics_url: str,
           mechanics_evidence: str, capture_id: str | None = None) -> dict:
    if not (0 < tick_interval_s <= 30) or not mechanics_url.startswith('https://') or not mechanics_evidence.strip():
        raise ValueError('mechanics source URL, evidence and positive tick interval required')
    conn=sqlite3.connect(db_path)
    try:
        conn.row_factory=sqlite3.Row
        conn.execute('BEGIN IMMEDIATE')
        rows=conn.execute('''SELECT i.* FROM spell_index i JOIN capture_lists l
           ON l.batch_id=i.batch_id AND l.class_key=i.class_key AND l.kind=i.kind
           JOIN capture_batches b ON b.batch_id=i.batch_id
           WHERE lower(i.class_key)=? AND lower(i.name)=? AND i.kind='abilities'
           AND l.complete=1 AND b.status='complete' ORDER BY i.level_hint''',
           (class_key.lower(),family.lower())).fetchall()
        if not rows:raise ValueError('no complete canonical source rank family')
        batch_ids={r['batch_id'] for r in rows}
        if len(batch_ids)!=1:raise ValueError('ambiguous capture batches')
        if capture_id is not None and capture_id not in batch_ids:raise ValueError('capture ID mismatch')
        # Fail the *entire* transaction for any missing/invalid rank; no partial family.
        parsed=[]
        for r in rows:
            after=(json.loads(r['raw_listview_json']).get('envChange') or {}).get('after') or {}
            ladder,duration=parse_resource_scaled_periodic_ladder(str(after.get('text') or ''))
            if r['level_hint'] is None or r['rank_hint'] is None:
                raise ValueError(f'unverified rank/level {r["spell_id"]}')
            if after.get('cast')!='Instant' or not str(after.get('cost') or '').strip():
                raise ValueError(f'unverified cost/cast {r["spell_id"]}')
            if duration/tick_interval_s != int(duration/tick_interval_s):
                raise ValueError(f'invalid periodic tick schedule {r["spell_id"]}')
            parsed.append((r,ladder,duration))
        captured_at=datetime.now(timezone.utc).isoformat(timespec='seconds')
        for r,ladder,duration in parsed:
            sid=int(r['spell_id'])
            existing=conn.execute('''SELECT semantic_type FROM ability_semantic_source_facts
                  WHERE class_key=? AND spell_id=?''',(class_key.lower(),sid)).fetchone()
            if existing and existing[0]!='resource_scaled_periodic':
                raise ValueError(f'conflicting semantic shape {sid}')
            caveats=[{'semantic':'attack_power_scaling','status':'explicit_gap'},
                     {'semantic':'periodic_can_crit','status':'explicit_gap'},
                     {'semantic':'tick_interval','status':'legacy_transcription_pending_independent_verification',
                      'evidence':mechanics_evidence},
                     {'semantic':'resource_binding','resource_id':resource_id,'scope':'target'},
                     {'semantic':'damage_ladder','status':'parsed_from_canonical_indexed_tooltip'}]
            conn.execute('''INSERT INTO ability_semantic_source_facts
             (class_key,spell_id,semantic_type,required_mode_id,gcd_s,tick_interval_s,
              spell_power_coefficient,source_url,mechanics_source_url,source_authority,
              capture_id,captured_at,caveats_json)
             VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
             ON CONFLICT(class_key,spell_id) DO UPDATE SET
             tick_interval_s=excluded.tick_interval_s,source_url=excluded.source_url,
             mechanics_source_url=excluded.mechanics_source_url,
             source_authority=excluded.source_authority,capture_id=excluded.capture_id,
             captured_at=excluded.captured_at,caveats_json=excluded.caveats_json''',
             (class_key.lower(),sid,'resource_scaled_periodic',required_mode,1.0,
              float(tick_interval_s),0.0,r['source_url'],mechanics_url,
              'canonical_index_plus_attributed_legacy_mechanics',r['batch_id'],captured_at,
              json.dumps(caveats,sort_keys=True)))
        conn.commit()
        return {'family':family,'class_key':class_key,'ranks':len(parsed),
                'spell_ids':[int(r['spell_id']) for r,_,_ in parsed],
                'damage_ladders':{str(r['spell_id']):ladder for r,ladder,_ in parsed},
                'mechanics_status':'INCOMPLETE_AP_CRIT_AND_TICK_PROOF',
                'source':'canonical_spell_index_tooltip',
                'complete_source_action_coverage':False}
    except Exception:
        conn.rollback();raise
    finally:conn.close()

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--db',required=True,type=Path)
    p.add_argument('--class-key',required=True);p.add_argument('--family',required=True)
    p.add_argument('--required-mode',required=True);p.add_argument('--resource-id',required=True)
    p.add_argument('--tick-interval-s',type=float,required=True)
    p.add_argument('--mechanics-url',required=True);p.add_argument('--mechanics-evidence',required=True)
    a=p.parse_args()
    print(json.dumps(ingest(a.db,class_key=a.class_key,family=a.family,
          required_mode=a.required_mode,resource_id=a.resource_id,
          tick_interval_s=a.tick_interval_s,mechanics_url=a.mechanics_url,
          mechanics_evidence=a.mechanics_evidence),indent=2))
