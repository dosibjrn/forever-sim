"""Source-validated timed-aura/trigger spell capture into canonical SQLite.

Source text and version are persisted; the generic executor never imports this
module and never contains spell/class/rank identities.
"""
from __future__ import annotations
import json,sqlite3
from pathlib import Path
from src.game.data.forever.sqlite_talents import DEFAULT_DB

CAPTURE=Path(__file__).resolve().parents[1]/'data/forever/source_captures/wf253_paladin_seal_20261011.json'

def ingest(db_path=DEFAULT_DB,capture_path=CAPTURE):
    p=json.loads(Path(capture_path).read_text())
    if not p['source_url'].startswith('https://foreverdiff.com/') or not p['client_build'].startswith('1.60.1.'):
        raise ValueError('missing exact-build source authority')
    with sqlite3.connect(db_path) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS sourced_timed_aura_actions (
            class_key TEXT NOT NULL,spell_id INTEGER NOT NULL,family_key TEXT NOT NULL,
            min_level INTEGER NOT NULL,mana_cost REAL NOT NULL,duration_s REAL NOT NULL,gcd_s REAL NOT NULL,
            aura_id TEXT NOT NULL,school TEXT NOT NULL,swing_min REAL NOT NULL,swing_max REAL NOT NULL,
            judgement_min REAL,judgement_max REAL,proc_sp_coefficient REAL NOT NULL,
            judge_sp_coefficient REAL NOT NULL,proc_reference_speed_s REAL NOT NULL,
            source_url TEXT NOT NULL,crosscheck_url TEXT NOT NULL,client_build TEXT NOT NULL,
            capture_id TEXT NOT NULL,caveats_json TEXT NOT NULL,
            PRIMARY KEY(class_key,spell_id))''')
        db.execute('''CREATE TABLE IF NOT EXISTS sourced_aura_consumers (
            class_key TEXT NOT NULL,spell_id INTEGER NOT NULL,family_key TEXT NOT NULL,
            min_level INTEGER NOT NULL,cost_kind TEXT NOT NULL,cost_value REAL NOT NULL,
            cooldown_s REAL NOT NULL,gcd_s REAL NOT NULL,required_aura_id TEXT NOT NULL,
            event_kind TEXT NOT NULL,consumes_aura INTEGER NOT NULL,source_url TEXT NOT NULL,
            client_build TEXT NOT NULL,capture_id TEXT NOT NULL,
            PRIMARY KEY(class_key,spell_id))''')
        columns={x[1] for x in db.execute('PRAGMA table_info(sourced_timed_aura_actions)')}
        if 'school' not in columns:
            db.execute("ALTER TABLE sourced_timed_aura_actions ADD COLUMN school TEXT NOT NULL DEFAULT 'holy'")
        # Later source captures may qualify a mutual-exclusion group.
        # Re-ingesting the older rank batch must not erase that provenance.
        prior_groups = {}
        if 'exclusive_group' in columns:
            prior_groups = {int(row[0]):row[1] for row in db.execute(
                'SELECT spell_id,exclusive_group FROM sourced_timed_aura_actions WHERE class_key=?',
                (p['class_key'],)) if row[1]}
        for r in p['ranks']:
            idx=db.execute('''SELECT level_hint FROM spell_index WHERE class_key=? AND kind='abilities'
                              AND spell_id=?''',(p['class_key'],r['spell_id'])).fetchone()
            if idx is None or int(idx[0])!=int(r['min_level']):
                raise ValueError(f'canonical spell index rank mismatch: {r["spell_id"]}')
            if (r['swing_min']<=0 or r['swing_max']<r['swing_min'] or r['mana_cost']<0 or
                (r['judgement_min'] is None)!=(r['judgement_max'] is None)):
                raise ValueError('invalid sourced aura rank')
            db.execute('''INSERT OR IGNORE INTO sourced_timed_aura_actions
                         (class_key,spell_id,family_key,min_level,mana_cost,duration_s,gcd_s,aura_id,school,
                          swing_min,swing_max,judgement_min,judgement_max,proc_sp_coefficient,judge_sp_coefficient,
                          proc_reference_speed_s,source_url,crosscheck_url,client_build,capture_id,caveats_json)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(
                p['class_key'],r['spell_id'],p['family_key'],r['min_level'],r['mana_cost'],
                p['duration_s'],p['gcd_s'],p['aura_id'],p['school'],r['swing_min'],r['swing_max'],
                r['judgement_min'],r['judgement_max'],p['on_swing_spell_power_coefficient'],
                p['judgement_spell_power_coefficient'],p['proc_reference_weapon_speed_s'],
                p['source_url'],p['crosscheck_url'],p['client_build'],p['capture_id'],
                json.dumps({'proc_speed_formula_status':p['proc_speed_formula_status'],
                  'judgement_coefficient_status':p['judgement_coefficient_status']})))
        if prior_groups:
            for spell_id, group in prior_groups.items():
                db.execute('UPDATE sourced_timed_aura_actions SET exclusive_group=? WHERE class_key=? AND spell_id=?',
                           (group,p['class_key'],spell_id))
        if 'judge_exclusive_group' not in {x[1] for x in db.execute('PRAGMA table_info(sourced_aura_consumers)')}:
            db.execute('ALTER TABLE sourced_aura_consumers ADD COLUMN judge_exclusive_group TEXT')
        j=p['judgement']
        idx=db.execute('''SELECT level_hint FROM spell_index WHERE class_key=? AND kind='abilities'
                          AND spell_id=?''',(p['class_key'],j['spell_id'])).fetchone()
        if idx is None or int(idx[0])!=int(j['min_level']):
            raise ValueError('canonical Judgement spell index mismatch')
        if j['cost_kind']!='base_mana_fraction' or not 0<j['cost_value']<1 or j['consumes_seal']:
            raise ValueError('unverified Judgement cost or seal consumption')
        db.execute('''INSERT OR IGNORE INTO sourced_aura_consumers
                     (class_key,spell_id,family_key,min_level,cost_kind,cost_value,cooldown_s,gcd_s,required_aura_id,
                      event_kind,consumes_aura,source_url,client_build,capture_id,judge_exclusive_group)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(
            p['class_key'],j['spell_id'],'judgement',j['min_level'],j['cost_kind'],
            j['cost_value'],j['cooldown_s'],j['gcd_s'],p['aura_id'],
            'judgement_seal',0,p['mechanic_source_url'],p['client_build'],p['capture_id'],'paladin_judgement'))
        return {'aura_rank_rows':len(p['ranks']),'consumer_rows':1,'capture_id':p['capture_id']}

if __name__=='__main__':print(ingest())
