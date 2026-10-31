"""Stage source-observed flat resource awards independently from talent rank chance.

This does NOT bridge source builds: a later web spell tooltip supplies numeric
observations, and the gate retains a visible build-bridge failure until a
client-build-specific source attests the resource award.
"""
from __future__ import annotations
import json,sqlite3
from pathlib import Path

_SCHEMA='''CREATE TABLE IF NOT EXISTS sourced_critical_resource_talent_facts (
 class_key TEXT NOT NULL, talent_id TEXT NOT NULL, target_build TEXT NOT NULL,
 source_url TEXT NOT NULL, resource_amount_source_url TEXT NOT NULL,
 resource_amount_source_build TEXT NOT NULL, resource_bridge_verified INTEGER NOT NULL,
 bear_resource TEXT NOT NULL, bear_amount REAL NOT NULL,
 cat_resource TEXT NOT NULL, cat_amount REAL NOT NULL,
 PRIMARY KEY (class_key,talent_id))'''


def ingest(db_path:Path,obs_path:Path):
    obs=json.loads(Path(obs_path).read_text())
    if obs.get('schema')!='forever_dual_critical_resource_observation_v1':
        raise ValueError('CRITICAL_RESOURCE_SOURCE_SCHEMA_UNSUPPORTED')
    with sqlite3.connect(db_path) as db:
        db.row_factory=sqlite3.Row
        db.execute(_SCHEMA)
        for row in obs['records']:
            if any(not isinstance(row.get(k),str) or not row[k] for k in (
                'class_key','talent_id','target_build','source_url',
                'resource_amount_source_url','resource_amount_source_build',
                'bear_resource','cat_resource')):
                raise ValueError('CRITICAL_RESOURCE_SOURCE_MISSING_FIELD')
            if not (row['source_url'].startswith('https://') and
                    row['resource_amount_source_url'].startswith('https://')):
                raise ValueError('CRITICAL_RESOURCE_SOURCE_URL_INVALID')
            # Cross-build evidence MUST be explicitly uncertified. This tool
            # may not manufacture a source bridge from a later tooltip.
            if row['resource_amount_source_build']!=row['target_build'] and row.get('resource_bridge_verified'):
                raise ValueError('CRITICAL_RESOURCE_UNVERIFIED_CROSS_BUILD_ASSERTED_VERIFIED')
            for k in ('bear_amount','cat_amount'):
                if type(row.get(k)) not in (int,float) or not 0<row[k]<=100:
                    raise ValueError('CRITICAL_RESOURCE_AMOUNT_INVALID')
            src=db.execute('SELECT source_json FROM checkpoint_talent_source_catalogue WHERE class_key=? AND source_build=?',
                           (row['class_key'],row['target_build'])).fetchone()
            if src is None:raise ValueError('CRITICAL_RESOURCE_TARGET_BUILD_ABSENT')
            captures=[x for x in json.loads(src['source_json'])['observations']
                      if x['talent_id']==row['talent_id']]
            if (len(captures)!=1 or captures[0].get('source_url')!=row['source_url'] or
                    captures[0].get('effect_domain')!='critical_bear_rage_proc_probability' or
                    captures[0].get('additional_effect_domain')!=
                        'critical_cat_bonus_combo_point_proc_probability'):
                raise ValueError('CRITICAL_RESOURCE_TALENT_SOURCE_NOT_MATCHED')
            # Talent observations own probability; this sidecar owns amounts.
            db.execute('INSERT OR REPLACE INTO sourced_critical_resource_talent_facts VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (row['class_key'],row['talent_id'],row['target_build'],row['source_url'],
                        row['resource_amount_source_url'],row['resource_amount_source_build'],
                        int(bool(row.get('resource_bridge_verified',False))),row['bear_resource'],
                        float(row['bear_amount']),row['cat_resource'],float(row['cat_amount'])))
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True)
    p.add_argument('--observations',type=Path,required=True)
    a=p.parse_args();ingest(a.db,a.observations)
