"""Ingest only indexed-and-tooltip-matched active-periodic-full-heal grant facts.

The source 70338 spell_index carries a tooltip but does not certify client
version, character level, GCD, or multi-aura priority. Those remain RED facts.
"""
from __future__ import annotations
import argparse,hashlib,json,sqlite3
from pathlib import Path

def ingest(db_path: Path, observations: Path) -> int:
    payload=json.loads(Path(observations).read_text())
    keys=set()
    with sqlite3.connect(db_path) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS sourced_talent_active_periodic_heal_action_facts(
          class_key TEXT NOT NULL,talent_id TEXT NOT NULL,source_build TEXT NOT NULL,
          fact_json TEXT NOT NULL,PRIMARY KEY(class_key,talent_id,source_build))''')
        for fact in payload['records']:
            key=(fact['class_key'],fact['talent_id'],payload['checkpoint_source_build'])
            if key in keys:raise ValueError('DUPLICATE_ACTIVE_PERIODIC_SOURCE_FACT')
            keys.add(key)
            row=db.execute('''SELECT name,source_url,raw_listview_json FROM spell_index
                WHERE class_key=? AND spell_id=? AND kind=?''',(fact['class_key'],
                fact['spell_id'],fact['source_index_kind'])).fetchone()
            if row is None:raise ValueError('SOURCE_ACTIVE_PERIODIC_INDEX_ROW_MISSING')
            raw=json.loads(row[2]);after=raw.get('envChange',{}).get('after',{})
            if (row[0]!=fact['name'] or row[1]!=fact['source_url'] or
                    hashlib.sha256(row[2].encode()).hexdigest()!=fact['indexed_payload_sha256']
                    or after.get('text')!=fact['source_tooltip']
                    or after.get('cost')!='20% of base power'
                    or after.get('cooldown')!='15 sec cooldown'
                    or after.get('cast')!='Instant'
                    or after.get('range')!='40 yd range'
                    or fact['source_index_kind']!='talents'
                    or fact.get('source_build_verified') is not False
                    or fact.get('required_mode_id')!='caster'
                    or fact.get('full_duration_multiplier')!=1.
                    or fact.get('source_families')!=['rejuvenation','regrowth']
                    or fact.get('base_mana_cost_fraction')!=.2
                    or fact.get('cooldown_s')!=15.
                    or fact.get('cast_time_s')!=0.
                    or fact.get('gcd_s')!=1.5
                    or fact.get('talent_effect_target')!='rejuvenation_or_regrowth'
                    or fact.get('source_hot_consumption') is not False
                    or fact.get('multiple_hot_selection_verified') is not False
                    or fact.get('gcd_mechanics_verified') is not False
                    or not str(fact.get('mechanics_source_url','')).startswith('https://')):
                raise ValueError('SOURCE_ACTIVE_PERIODIC_FACT_CONFLICT')
            db.execute('''INSERT INTO sourced_talent_active_periodic_heal_action_facts
              (class_key,talent_id,source_build,fact_json) VALUES(?,?,?,?)
              ON CONFLICT(class_key,talent_id,source_build) DO UPDATE SET fact_json=excluded.fact_json''',
              (*key,json.dumps(fact,sort_keys=True)))
        db.commit()
    return len(keys)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True)
    p.add_argument('--observations',type=Path,required=True)
    a=p.parse_args();print({'ingested':ingest(a.db,a.observations)})
