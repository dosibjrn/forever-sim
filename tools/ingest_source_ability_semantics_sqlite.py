"""Ingest verified per-rank ability execution facts into canonical Forever SQLite.

The capture is the only source of game-specific identity, form, timing and
coefficient values. The shared runtime consumes the resulting rows by source
spell ID and generic effect grammar, never by a built-in spell allowlist.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlparse

SCHEMA = '''CREATE TABLE IF NOT EXISTS ability_semantic_source_facts (
 class_key TEXT NOT NULL, spell_id INTEGER NOT NULL,
 semantic_type TEXT NOT NULL, required_mode_id TEXT NOT NULL,
 gcd_s REAL NOT NULL, tick_interval_s REAL,
 spell_power_coefficient REAL NOT NULL,
 source_url TEXT NOT NULL, mechanics_source_url TEXT NOT NULL,
 source_authority TEXT NOT NULL, capture_id TEXT NOT NULL,
 captured_at TEXT NOT NULL, caveats_json TEXT NOT NULL,
 periodic_power_coefficient_per_tick REAL, positional_requirement TEXT,
 PRIMARY KEY(class_key, spell_id)
)'''


def ingest(db_path:Path,capture_path:Path)->dict:
    data=json.loads(Path(capture_path).read_text())
    if data.get('schema')!='forever_source_ability_semantics_v1':
        raise ValueError('unexpected capture schema')
    entries=data.get('entries') or []
    if not entries:raise ValueError('empty capture')
    conn=sqlite3.connect(str(db_path))
    try:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute(SCHEMA)
        existing_columns={x[1] for x in conn.execute('PRAGMA table_info(ability_semantic_source_facts)')}
        for col,definition in (('periodic_power_coefficient_per_tick','REAL'),('positional_requirement','TEXT')):
            if col not in existing_columns:
                conn.execute(f'ALTER TABLE ability_semantic_source_facts ADD COLUMN {col} {definition}')
        seen=set()
        for row in entries:
            key=str(data['class_key']).lower(); sid=int(row['spell_id'])
            if sid in seen:raise ValueError('duplicate spell id')
            seen.add(sid)
            index=conn.execute('SELECT name,source_url,raw_listview_json FROM spell_index WHERE class_key=? AND kind=? AND spell_id=?',
                               (key,'abilities',sid)).fetchone()
            if index is None or index[0]!=row['name'] or index[1]!=row['source_url']:
                raise ValueError(f'unknown/renamed indexed source ability {sid}')
            after=json.loads(index[2]).get('envChange',{}).get('after') or {}
            if not after.get('text') or not after.get('cost'):
                raise ValueError(f'missing indexed tooltip and cost for {sid}')
            # Optional independently observed public page fields. A search
            # excerpt is NOT an HTML capture: require exact agreement with the
            # older indexed listview before promoting any numeric semantics.
            observed=row.get('public_page_observation')
            if observed is not None:
                required={'tooltip','cost','cast','level','spell_power_coefficient','capture_method'}
                if not required.issubset(observed):
                    raise ValueError(f'incomplete public page observation {sid}')
                index_level=conn.execute('SELECT level_hint FROM spell_index WHERE class_key=? AND spell_id=?',
                    (key,sid)).fetchone()[0]
                for field in ('tooltip','cost','cast'):
                    if str(observed[field]).strip()!=str(after.get('text' if field=='tooltip' else field) or '').strip():
                        raise ValueError(f'public page/index drift for {sid}: {field}')
                if int(observed['level'])!=int(index_level):
                    raise ValueError(f'public page/index drift for {sid}: level')
                if float(observed['spell_power_coefficient'])!=float(row['spell_power_coefficient']):
                    raise ValueError(f'public page/coefficient mismatch for {sid}')
                if observed['capture_method']!='manual_public_search_excerpt':
                    raise ValueError(f'unknown evidence capture method for {sid}')
            if row['semantic_type'] not in ('direct_damage','direct_periodic_combo','weapon_combo_position','periodic_control','direct_periodic_heal','direct_heal'):
                raise ValueError('unknown executable semantic shape')
            if row['required_mode_id'] not in ('caster','cat','bear'):
                raise ValueError('unsupported mode identity')
            for url in (row['source_url'],row['mechanics_source_url']):
                if urlparse(url).scheme!='https' or not urlparse(url).hostname:
                    raise ValueError('invalid provenance URL')
            gcd=float(row['gcd_s']);tick=row.get('tick_interval_s')
            if gcd<0 or gcd>3 or (tick is not None and not 0<float(tick)<=30):
                raise ValueError('invalid timing')
            if row['semantic_type'] in ('direct_periodic_combo','periodic_control','direct_periodic_heal') and tick is None:
                raise ValueError('periodic ability requires sourced tick interval')
            if row['semantic_type'] in ('direct_damage','weapon_combo_position','direct_heal') and tick is not None:
                raise ValueError('direct ability cannot have periodic tick')
            coef=float(row['spell_power_coefficient'])
            if coef<0 or coef>3:raise ValueError('invalid spell coefficient')
            periodic_coef=row.get('periodic_power_coefficient_per_tick')
            if row['semantic_type'] in ('periodic_control','direct_periodic_heal') and periodic_coef is None:
                raise ValueError('sourced periodic coefficient is required')
            if periodic_coef is not None and not 0<=float(periodic_coef)<=3:
                raise ValueError('invalid periodic coefficient')
            position=row.get('positional_requirement')
            if row['semantic_type']=='weapon_combo_position' and position!='behind':
                raise ValueError('sourced positional requirement is required')
            if row['semantic_type']!='weapon_combo_position' and position is not None:
                raise ValueError('unexpected position requirement')
            if conn.execute('SELECT 1 FROM ability_semantic_source_facts WHERE class_key=? AND spell_id=?',(key,sid)).fetchone():
                raise ValueError('existing source row must be reconciled, not overwritten')
            conn.execute('''INSERT INTO ability_semantic_source_facts (class_key,spell_id,semantic_type,required_mode_id,gcd_s,tick_interval_s,spell_power_coefficient,source_url,mechanics_source_url,source_authority,capture_id,captured_at,caveats_json,periodic_power_coefficient_per_tick,positional_requirement) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (key,sid,row['semantic_type'],row['required_mode_id'],gcd,
                 None if tick is None else float(tick),coef,row['source_url'],
                 row['mechanics_source_url'],row['source_authority'],data['capture_id'],
                 data['captured_at'],json.dumps(row.get('caveats') or []),
                 None if periodic_coef is None else float(periodic_coef),position))
        conn.commit()
        return {'capture_id':data['capture_id'],'class_key':data['class_key'],'source_spell_ranks':len(seen)}
    except Exception:
        conn.rollback();raise
    finally:conn.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True)
    p.add_argument('--capture',type=Path,required=True)
    a=p.parse_args();print(json.dumps(ingest(a.db,a.capture),indent=2))
