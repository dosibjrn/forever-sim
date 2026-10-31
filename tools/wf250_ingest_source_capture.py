"""Idempotent ingestion of verified, URL-attributed source capture JSON.

No game facts are in this script. Data lives in a versioned capture and the
canonical SQLite; consumers never import the capture or script.
"""
from pathlib import Path
import json
import sqlite3
from src.game.data.forever.sqlite_talents import DEFAULT_DB

CAPTURE = Path(__file__).resolve().parents[1] / 'data/forever/source_captures/wf250_mage_verified_2026-10-11.json'


def ingest(db=DEFAULT_DB, capture=CAPTURE):
    data = json.loads(Path(capture).read_text())
    with sqlite3.connect(db) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS verified_spell_rank_facts (
            class_key TEXT NOT NULL, spell_id INTEGER NOT NULL,
            cast_time_s REAL NOT NULL, mana_cost REAL NOT NULL,
            cooldown_s REAL NOT NULL, tooltip_text TEXT NOT NULL,
            source_url TEXT NOT NULL, source_build TEXT NOT NULL,
            captured_at TEXT NOT NULL, capture_id TEXT NOT NULL,
            spell_power_coefficient REAL,
            PRIMARY KEY(class_key,spell_id))''')
        conn.execute('''CREATE TABLE IF NOT EXISTS verified_talent_rank_facts (
            class_key TEXT NOT NULL, spell_id INTEGER NOT NULL,
            talent_name TEXT NOT NULL, tree_key TEXT NOT NULL,
            tree_row INTEGER NOT NULL, tree_col INTEGER NOT NULL,
            rank INTEGER NOT NULL, max_rank INTEGER NOT NULL,
            trait_id INTEGER NOT NULL, modifier_json TEXT NOT NULL,
            rank_source_url TEXT NOT NULL, tree_source_url TEXT NOT NULL,
            captured_at TEXT NOT NULL, capture_id TEXT NOT NULL,
            PRIMARY KEY(class_key,spell_id,rank))''')
        conn.execute('''CREATE TABLE IF NOT EXISTS verified_talent_granted_action_facts (
            class_key TEXT NOT NULL, spell_id INTEGER NOT NULL,
            action_json TEXT NOT NULL, source_url TEXT NOT NULL,
            captured_at TEXT NOT NULL, capture_id TEXT NOT NULL,
            PRIMARY KEY(class_key,spell_id))''')
        cols = {r[1] for r in conn.execute('PRAGMA table_info(verified_spell_rank_facts)')}
        if 'spell_power_coefficient' not in cols:
            conn.execute('ALTER TABLE verified_spell_rank_facts ADD COLUMN spell_power_coefficient REAL')
        for row in data.get('granted_actions', []):
            conn.execute('''INSERT OR REPLACE INTO verified_talent_granted_action_facts VALUES (?,?,?,?,?,?)''',
                (row['class_key'],row['spell_id'],json.dumps(row,sort_keys=True),
                 row['source_url'],data['captured_at'],data['capture_id']))
        for row in data['spell_ranks']:
            conn.execute('''INSERT OR REPLACE INTO verified_spell_rank_facts VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (row['class_key'],row['spell_id'],row['cast_time_s'],row['mana_cost'],
                 row['cooldown_s'],row['tooltip_text'],row['source_url'],row['source_build'],
                 data['captured_at'],data['capture_id'],row.get('spell_power_coefficient')))
        for row in data['talents']:
            if len(row['rank_values']) != row['max_rank']:
                raise ValueError('talent capture rank curve incomplete')
            for rank,value in enumerate(row['rank_values'],1):
                modifiers = [{**mod, 'value': value} for mod in row['modifiers']]
                conn.execute('''INSERT OR REPLACE INTO verified_talent_rank_facts VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (row['class_key'],row['spell_id'],row['name'],row['tree_key'],
                     row['row'],row['col'],rank,row['max_rank'],row['trait_id'],
                     json.dumps(modifiers,sort_keys=True),row['rank_source_url'],
                     row['tree_source_url'],data['captured_at'],data['capture_id']))
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('source SQLite integrity check failed')

if __name__ == '__main__':
    ingest()
