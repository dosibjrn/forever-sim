"""Idempotent versioned source capture -> canonical SQLite companion facts.

No runtime module imports this capture: the compiler reads SQLite only.
"""
from __future__ import annotations
import json,sqlite3
from pathlib import Path
from src.game.data.forever.sqlite_talents import DEFAULT_DB
ROOT=Path(__file__).resolve().parents[1]
CAPTURE=ROOT/'data/forever/source_captures/wf252_hunter_pet_l10_20_20261011.json'

def ingest(*, db_path=DEFAULT_DB, capture_path=CAPTURE):
    c=json.loads(Path(capture_path).read_text())
    with sqlite3.connect(db_path) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS companion_family_source_facts (
            class_key TEXT NOT NULL, family_key TEXT NOT NULL, min_level INTEGER NOT NULL,
            max_level INTEGER NOT NULL, unlock_spell_id INTEGER NOT NULL,
            unlock_url TEXT NOT NULL, family_url TEXT NOT NULL, attack_speed_s REAL NOT NULL,
            base_white_dps REAL NOT NULL, white_dps_per_level REAL NOT NULL,
            damage_multiplier REAL NOT NULL, focus_initial REAL NOT NULL,
            focus_capacity REAL NOT NULL, focus_regen_s REAL NOT NULL,
            ap_link_coefficient REAL NOT NULL, crit_link_coefficient REAL NOT NULL,
            proxy_status TEXT NOT NULL, source_url TEXT NOT NULL,
            capture_id TEXT NOT NULL, captured_at TEXT NOT NULL,
            PRIMARY KEY(class_key,family_key))''')
        db.execute('''CREATE TABLE IF NOT EXISTS companion_skill_source_facts (
            class_key TEXT NOT NULL, family_key TEXT NOT NULL, skill_key TEXT NOT NULL,
            rank INTEGER NOT NULL, min_level INTEGER NOT NULL, spell_id INTEGER NOT NULL,
            damage_min REAL NOT NULL, damage_max REAL NOT NULL,
            focus_cost REAL NOT NULL, cooldown_s REAL NOT NULL, gcd_s REAL NOT NULL,
            school TEXT NOT NULL, source_url TEXT NOT NULL, crosscheck_url TEXT NOT NULL,
            capture_id TEXT NOT NULL, captured_at TEXT NOT NULL,
            PRIMARY KEY(class_key,family_key,skill_key,rank))''')
        for row in c['families']:
            assert db.execute("SELECT 1 FROM spell_index WHERE class_key=? AND spell_id=? AND kind='abilities'",(row['class_key'],row['unlock_spell_id'])).fetchone(), 'pet unlock absent from canonical index'
            if not 0 < row['min_level'] <= row['max_level'] or not 0 < row['attack_speed_s'] or not row['source_url'] or not row['proxy_status'].startswith('qualified_'):
                raise ValueError('invalid companion source scenario')
            cols=[*row,'capture_id','captured_at']
            db.execute(f"INSERT OR REPLACE INTO companion_family_source_facts ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",[*(row.values()),c['capture_id'],c['captured_at']])
        for row in c['skills']:
            if not (row['damage_min']>0 and row['damage_max']>=row['damage_min'] and row['focus_cost']>=0 and row['min_level']>=1 and row['source_url']):
                raise ValueError('invalid companion skill source')
            cols=[*row,'capture_id','captured_at']
            db.execute(f"INSERT OR REPLACE INTO companion_skill_source_facts ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",[*(row.values()),c['capture_id'],c['captured_at']])
        return {'family_rows':db.execute('select count(*) from companion_family_source_facts').fetchone()[0], 'skill_rows':db.execute('select count(*) from companion_skill_source_facts').fetchone()[0]}
if __name__=='__main__': print(ingest())
