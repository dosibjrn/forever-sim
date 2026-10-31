"""Source-versioned, idempotent staging; reject false build certification."""
import argparse,json,sqlite3
from pathlib import Path

def ingest(db, observations):
    src=json.loads(Path(observations).read_text())
    if src.get('source_build')!='1.60.1.70338' or len(src.get('records',()))!=1:
        raise ValueError('RESOURCE_ACTION_STAGED_SOURCE_SCOPE_MISMATCH')
    with sqlite3.connect(db) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS sourced_talent_resource_action_facts(
            class_key TEXT NOT NULL,talent_id TEXT NOT NULL,family_key TEXT NOT NULL,
            spell_id INTEGER NOT NULL,name TEXT NOT NULL,required_level INTEGER NOT NULL,
            required_mode_id TEXT NOT NULL,resource_id TEXT NOT NULL,resource_gain REAL NOT NULL,
            cost_resource_id TEXT NOT NULL,base_resource_cost_fraction REAL NOT NULL,
            cost_reduction_group TEXT NOT NULL,
            cooldown_s REAL NOT NULL,gcd_s REAL NOT NULL,must_have_room INTEGER NOT NULL,
            source_build TEXT NOT NULL,source_url TEXT NOT NULL,
            mechanics_source_url TEXT NOT NULL,mechanics_source_build TEXT NOT NULL,
            full_resource_rule_source_url TEXT NOT NULL,
            full_resource_rule_source_build TEXT NOT NULL,bridge_verified INTEGER NOT NULL,
            PRIMARY KEY(class_key,talent_id))''')
        for item in src['records']:
            if (item['source_build']!=src['source_build'] or
                    item['bridge_verified']!=0 or
                    item['mechanics_source_build']==src['source_build'] or
                    item['full_resource_rule_source_build']==src['source_build'] or
                    any(not str(item[k]).startswith('https://') for k in
                        ('source_url','mechanics_source_url','full_resource_rule_source_url')) or
                    item['talent_id']!=item['family_key'] or
                    item['cost_reduction_group']!='shapeshift_mana'):
                raise ValueError('UNVERIFIED_SOURCE_RESOURCE_ACTION_BRIDGE')
            match=con.execute('SELECT 1 FROM spell_index WHERE class_key=? AND kind=? AND spell_id=?',
                 (item['class_key'],'talents',item['spell_id'])).fetchone()
            if not match:raise ValueError('SOURCE_RESOURCE_ACTION_INDEX_ID_MISSING')
            keys=tuple(item)
            con.execute('INSERT OR REPLACE INTO sourced_talent_resource_action_facts ('+
                ','.join(keys)+') VALUES ('+','.join('?' for _ in keys)+')',
                tuple(item[k] for k in keys))
        return con.execute('SELECT COUNT(*) FROM sourced_talent_resource_action_facts').fetchone()[0]

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--db',required=True);ap.add_argument('--observations',required=True)
    args=ap.parse_args();print('staged resource actions',ingest(args.db,args.observations))
