"""Ingest source-index verified direct control facts as opaque typed L0 grammar."""
from __future__ import annotations
import argparse,json,hashlib,sqlite3
from pathlib import Path

def ingest(db_path:Path, observations:Path):
    doc=json.loads(observations.read_text());seen=set()
    with sqlite3.connect(db_path) as db:
        for fact in doc['records']:
            key=(fact['class_key'],fact['spell_id'])
            if key in seen:raise ValueError('DUPLICATE_DIRECT_CONTROL_OBSERVATION')
            seen.add(key)
            row=db.execute('SELECT name,level_hint,source_url,raw_listview_json FROM spell_index WHERE class_key=? AND spell_id=? AND kind=?',
                (fact['class_key'],fact['spell_id'],fact['source_index_kind'])).fetchone()
            if (row is None or row[0]!=fact['name'] or row[1]!=fact['min_level'] or
                row[2]!=fact['source_url'] or
                hashlib.sha256(row[3].encode()).hexdigest()!=fact['indexed_payload_sha256'] or
                fact['build_bridge_verified'] is not False or
                not str(fact['source_mechanics_url']).startswith('https://') or
                fact['mechanics_source_build']==doc['checkpoint_source_build'] or
                fact['source_type']!='direct_control' or
                fact['tooltip_text']!=f"Stuns the target for {int(fact['duration_s'])} sec." or
                fact['required_mode_id'] not in ('bear','cat','caster') or
                fact['cost']!='10 Rage' or fact['cast']!='Instant' or
                not 0<float(fact['duration_s'])<=60 or fact['gcd_s']!=1.5 or
                fact['cooldown_s']!=60 or fact['range']!='5 yd range' or
                fact['control_id']!='stun' or
                fact['prevents_enemy_actions'] is not True or fact['breaks_on_damage'] is not False):
                raise ValueError('INVALID_SOURCE_DIRECT_CONTROL_OBSERVATION')
            # Numeric material is version-qualified; it is never promoted to
            # verified 70338 by storing it in this stage.
            caveats=[{'semantic':'direct_control_source_observation',
                'source_build_verified':False,'source_index_sha256':fact['indexed_payload_sha256'],
                'observation':fact},
                {'semantic':'source_version','status':'bridge_unverified_70374_to_70338'},
                {'semantic':'control_resistance','status':'not_server_verified'}]
            db.execute("""INSERT INTO ability_semantic_source_facts
                (class_key,spell_id,semantic_type,required_mode_id,gcd_s,tick_interval_s,
                spell_power_coefficient,source_url,mechanics_source_url,source_authority,
                capture_id,captured_at,caveats_json,periodic_power_coefficient_per_tick,positional_requirement)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(class_key,spell_id) DO UPDATE SET
                semantic_type=excluded.semantic_type,
                required_mode_id=excluded.required_mode_id,gcd_s=excluded.gcd_s,
                source_url=excluded.source_url,mechanics_source_url=excluded.mechanics_source_url,
                source_authority=excluded.source_authority,capture_id=excluded.capture_id,
                caveats_json=excluded.caveats_json""",(
                fact['class_key'],fact['spell_id'],'direct_control',fact['required_mode_id'],
                fact['gcd_s'],None,0.,fact['source_url'],fact['source_mechanics_url'],
                'source_index_direct_control_unverified_build', 'wf440-direct-control',
                '2026-10-16',json.dumps(caveats),None,None))
        db.commit()
    return len(seen)
if __name__=='__main__':
    q=argparse.ArgumentParser();q.add_argument('--db',type=Path,required=True);q.add_argument('--observations',type=Path,required=True)
    a=q.parse_args();print({'ingested':ingest(a.db,a.observations)})
