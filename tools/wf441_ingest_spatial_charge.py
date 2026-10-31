"""Source-index crosschecked 70338 talent-granted 2D charge observation."""
import argparse,hashlib,json,sqlite3
from pathlib import Path

def ingest(db_path:Path,observations:Path):
    packet=json.loads(Path(observations).read_text())
    with sqlite3.connect(db_path) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS sourced_talent_spatial_charge_action_facts(
            class_key TEXT NOT NULL,talent_id TEXT NOT NULL,source_build TEXT NOT NULL,
            fact_json TEXT NOT NULL,PRIMARY KEY(class_key,talent_id,source_build))''')
        for fact in packet['records']:
            row=db.execute('''SELECT name,source_url,raw_listview_json FROM spell_index
              WHERE class_key=? AND spell_id=? AND kind='talents' ''',
              (fact['class_key'],fact['spell_id'])).fetchone()
            if not row:raise ValueError('CHARGE_SOURCE_INDEX_MISSING')
            after=json.loads(row[2]).get('envChange',{}).get('after',{})
            forms=fact.get('forms') or []
            if (fact['source_build']!=packet['checkpoint_source_build']
                or fact.get('source_build_verified') is not False
                or fact.get('source_url')!=row[1] or fact.get('name')!=row[0]
                or fact.get('indexed_payload_sha256')!=hashlib.sha256(row[2].encode()).hexdigest()
                or fact.get('source_tooltip')!=after.get('text')
                or after.get('cast')!='Instant' or after.get('cost')!='5 Rage'
                or after.get('cooldown')!='15 sec cooldown'
                or after.get('range')!='25 yd range'
                or fact.get('talent_effect_target')!='feral_charge_talent_grant'
                or fact.get('root_duration_s')!=4.
                or fact.get('required_level')!=20
                or len(forms)!=2 or [f['mode_id'] for f in forms]!=['bear','cat']
                or forms[0]['cost_resource_id']!='rage' or forms[0]['cost_amount']!=5.
                or forms[0]['cooldown_s']!=15. or forms[0]['root_duration_s']!=4.
                or forms[1]['cost_resource_id'] is not None
                or forms[1]['cooldown_s']!=30. or forms[1]['root_duration_s']!=0.
                or forms[1]['minimum_range_yards']!=8.
                or any(f['maximum_range_yards']!=25. or f['gcd_s']!=1.5
                       or f['arrival_distance_yards']!=1.5 for f in forms)
                or any(f.get('source_mechanics_verified') is not False for f in forms)
                or any(not str(f.get('mechanics_source_url','')).startswith('https://') for f in forms)):
                raise ValueError('SOURCE_CHARGE_VERSIONED_INDEX_FACT_CONFLICT')
            db.execute('''INSERT INTO sourced_talent_spatial_charge_action_facts
                (class_key,talent_id,source_build,fact_json) VALUES(?,?,?,?)
                ON CONFLICT(class_key,talent_id,source_build) DO UPDATE SET fact_json=excluded.fact_json''',
                (fact['class_key'],fact['talent_id'],fact['source_build'],json.dumps(fact,sort_keys=True)))
        db.commit()
    return len(packet['records'])

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--observations',type=Path,required=True)
 a=p.parse_args();print({'ingested':ingest(a.db,a.observations)})
