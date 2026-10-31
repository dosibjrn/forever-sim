"""Reproducible, hash-guarded L30 70338 dual-source rank ingestion.

A pinned 70338 catalogue can receive rank curves backed by later client facts,
but every cross-build mismatch remains an explicit P2 blocker. No overwrites.
"""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def ingest(db_path:Path, observation_path:Path)->str:
    evidence=json.loads(observation_path.read_text())
    if (evidence['source_build']!='1.60.1.70338' or evidence['class_key']!='druid'
            or evidence['min_level']!=30):
        raise ValueError('WF442_SOURCE_SCOPE_MISMATCH')
    captures=evidence['observations']
    ids=[entry['talent_id'] for entry in captures]
    if len(ids)!=len(set(ids)) or set(ids)!={'natural_reaction','improved_regrowth'}:
        raise ValueError('WF442_SOURCE_RANK_SCOPE_MISMATCH')
    with sqlite3.connect(db_path) as conn:
        row=conn.execute('SELECT source_json,source_sha256 FROM checkpoint_talent_source_catalogue '
                         'WHERE class_key=? AND source_build=? AND min_level=?',
                         ('druid','1.60.1.70338',30)).fetchone()
        if row is None:raise ValueError('WF442_SOURCE_CATALOGUE_MISSING')
        raw,existing_sha=row
        if hashlib.sha256(raw.encode()).hexdigest()!=existing_sha:
            raise ValueError('WF442_SOURCE_CATALOGUE_TAMPERED')
        data=json.loads(raw)
        observations={x['talent_id']:x for x in data['observations']}
        # Either wholly unchanged parent or the identical already-applied row;
        # never silently update a different catalogue or a changed fact.
        if set(ids)<=set(observations):
            if any(observations[x['talent_id']]!=x for x in captures):
                raise ValueError('WF442_SOURCE_CAPTURE_CONFLICT')
            return existing_sha
        if existing_sha!=evidence['parent_source_sha256']:
            raise ValueError('WF442_PARENT_SOURCE_SHA_MISMATCH')
        if set(ids)&set(observations):
            raise ValueError('WF442_PARTIAL_SOURCE_INGEST')
        data['observations']+=captures
        data['observed_unreachable_talent_positions']=[x for x in
            data['observed_unreachable_talent_positions'] if
            x['indexed_talent_id'] not in ids]
        serialized=json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':'))
        sha=hashlib.sha256(serialized.encode()).hexdigest()
        conn.execute('UPDATE checkpoint_talent_source_catalogue SET source_json=?,source_sha256=? '
                     'WHERE class_key=? AND source_build=? AND min_level=?',
                     (serialized,sha,'druid','1.60.1.70338',30))
        assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        return sha

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--source-db',type=Path,default=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite')
    ap.add_argument('--observations',type=Path,default=ROOT/'evidence/wf442/WF442_SOURCE_RANK_OBSERVATIONS.json')
    args=ap.parse_args()
    print(ingest(args.source_db,args.observations))

if __name__=='__main__':main()
