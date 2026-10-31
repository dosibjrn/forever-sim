"""Ingest independently captured Forever stealth-button source facts to canonical SQLite."""
import argparse, json, sqlite3, hashlib
from pathlib import Path

def ingest(db_path, evidence_path):
    doc=json.loads(Path(evidence_path).read_text())
    assert doc['schema_version']==1
    with sqlite3.connect(db_path) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS source_stealth_action_facts (
            class_key TEXT NOT NULL, spell_id INTEGER NOT NULL, name TEXT NOT NULL,
            source_url TEXT NOT NULL, index_sha256 TEXT NOT NULL,
            facts_json TEXT NOT NULL, PRIMARY KEY(class_key,spell_id))''')
        for facts in doc['records']:
            key=facts['class_key'];sid=int(facts['spell_id'])
            row=db.execute("SELECT name,level_hint,rank_hint,source_url,raw_listview_json FROM spell_index WHERE class_key=? AND spell_id=? AND kind='abilities'",(key,sid)).fetchone()
            if row is None or row[0]!=facts['name'] or row[1]!=facts['minimum_level'] or row[2]!=facts['rank'] or row[3]!=facts['source_url']:
                raise ValueError('STEALTH_INDEX_IDENTITY_OR_RANK_DRIFT')
            if not facts['source_url'].startswith('https://www.wowhead.com/forever/spell='):
                raise ValueError('STEALTH_UNTRUSTED_SOURCE_URL')
            source=facts['source_text'].lower()
            if not (f"reduces your movement speed by {round((1-facts['movement_speed_multiplier'])*100)}%" in source
                    and f"{facts['cooldown_s']} sec cooldown" in source and
                    (facts.get('required_mode_id') is None or 
                     str(facts.get('required_mode_label') or facts['required_mode_id'].replace('_',' ')).lower() in source) and
                    'lasts until cancelled' in source and
                    'cannot be used in combat' in source):
                raise ValueError('STEALTH_SOURCE_FACT_UNSUPPORTED_BY_CAPTURE')
            digest=hashlib.sha256(row[4].encode()).hexdigest()
            db.execute('INSERT OR REPLACE INTO source_stealth_action_facts VALUES (?,?,?,?,?,?)',
                (key,sid,facts['name'],facts['source_url'],digest,json.dumps(facts,sort_keys=True)))
    return len(doc['records'])

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--db',default='data/forever/catalogue/forever_abilities.sqlite')
    p.add_argument('--evidence',default='evidence/wf474_stealth_source_observations.json');a=p.parse_args()
    print('ingested',ingest(a.db,a.evidence),'stealth observations')
