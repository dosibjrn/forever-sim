"""Fail-closed, version-qualified source-index talent action ingestion."""
from __future__ import annotations
import argparse,hashlib,json,sqlite3
from pathlib import Path

def ingest(db_path:Path, observations:Path):
    payload=json.loads(Path(observations).read_text())
    keys=set()
    with sqlite3.connect(db_path) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS sourced_talent_next_cast_action_facts(
            class_key TEXT NOT NULL,talent_id TEXT NOT NULL,source_build TEXT NOT NULL,
            fact_json TEXT NOT NULL,PRIMARY KEY(class_key,talent_id,source_build))""")
        for fact in payload['records']:
            key=(fact['class_key'],fact['talent_id'],payload['checkpoint_source_build'])
            if key in keys:raise ValueError('DUPLICATE_NEXT_CAST_TALENT_OBSERVATION')
            keys.add(key)
            source=conn.execute("""SELECT name,source_url,raw_listview_json FROM spell_index
                WHERE class_key=? AND spell_id=? AND kind=?""",(
                fact['class_key'],fact['spell_id'],fact['source_index_kind'])).fetchone()
            if (not source or fact['name']!=source[0] or fact['source_url']!=source[1] or
                hashlib.sha256(source[2].encode()).hexdigest()!=fact['indexed_payload_sha256'] or
                fact['source_mechanics_version_verified'] is not False or
                not str(fact['mechanics_source_url']).startswith('https://') or
                not isinstance(fact['mechanics_source_build'],str) or
                fact['mechanics_source_build']==payload['checkpoint_source_build'] or
                fact['mechanics_tooltip']!='When activated, your next Nature spell becomes an instant cast spell.' or
                fact['target_effect_domain']!='instant_next_nature_cast_count' or
                fact['source_talent_target']!='nature_spell' or
                fact['self_cast'] is not True or
                fact['cost_resource_id'] is not None or fact['cost_amount']!=0 or
                fact['required_mode_id']!='caster' or
                fact['gcd_s']!=0 or fact['cooldown_s']!=180 or
                fact['spell_school']!='nature' or fact['next_cast_count']!=1):
                raise ValueError('INVALID_OR_UNVERIFIED_NEXT_CAST_SOURCE_FACT')
            # Build/version bridge is explicitly not certified. Do not claim 70338 exactness.
            conn.execute("""INSERT INTO sourced_talent_next_cast_action_facts
                (class_key,talent_id,source_build,fact_json) VALUES(?,?,?,?)
                ON CONFLICT(class_key,talent_id,source_build) DO UPDATE SET fact_json=excluded.fact_json""",
                (*key,json.dumps(fact,sort_keys=True)))
        conn.commit()
    return len(keys)
if __name__=='__main__':
    q=argparse.ArgumentParser();q.add_argument('--db',type=Path,required=True);q.add_argument('--observations',type=Path,required=True)
    a=q.parse_args();print({'ingested':ingest(a.db,a.observations)})
