"""Index-bound import of external, web-observed control tooltip facts to staged SQLite.

No game-specific constants: parser uses exact tooltip patterns and provenance.
A web-text observation is NOT an independently fetched/SHA-verified HTML page.
"""
from __future__ import annotations
import argparse,hashlib,json,sqlite3
from src.game.data.forever.source_control_observations import parse_control_observation
from pathlib import Path

_SCHEMA='''CREATE TABLE IF NOT EXISTS source_control_action_observations (
 class_key TEXT NOT NULL, spell_id INTEGER NOT NULL, name TEXT NOT NULL,
 required_level INTEGER NOT NULL, required_mode_id TEXT NOT NULL,
 cost_resource TEXT NOT NULL, cost_amount REAL NOT NULL,
 cast_time_s REAL NOT NULL, gcd_s REAL NOT NULL, cooldown_s REAL NOT NULL,
 effect_kind TEXT NOT NULL, duration_s REAL NOT NULL,
 source_url TEXT NOT NULL, captured_at TEXT NOT NULL,
 index_batch_id TEXT NOT NULL, raw_index_sha256 TEXT NOT NULL,
 observation_sha256 TEXT NOT NULL, observation_json TEXT NOT NULL,
 PRIMARY KEY(class_key,spell_id))'''

def ingest(db_path:Path,observation_file:Path):
    obj=json.loads(observation_file.read_text())
    if obj.get('schema')!='forever_public_control_observation_v1':
        raise ValueError('SOURCE_CONTROL_OBSERVATION_SCHEMA_UNSUPPORTED')
    with sqlite3.connect(db_path) as con:
        con.row_factory=sqlite3.Row
        con.execute(_SCHEMA)
        for obs in obj['observations']:
            sid=int(obs['spell_id']);cl=obs['class_key']
            indexed=con.execute('''SELECT * FROM spell_index WHERE kind='abilities'
                     AND class_key=? AND spell_id=?''',(cl,sid)).fetchone()
            if indexed is None or indexed['batch_id']!=obs['index_batch_id'] or indexed['name']!=obs['name'] or indexed['level_hint']!=obs['learn_level']:
                raise ValueError(f'SOURCE_CONTROL_INDEX_IDENTITY_DRIFT:{sid}')
            if not obs['source_url'].startswith(indexed['source_url']):
                raise ValueError('SOURCE_CONTROL_URL_MISMATCH')
            raw=json.loads(indexed['raw_listview_json'])
            if (raw.get('id')!=sid or raw.get('name')!=obs['name'] or raw.get('level')!=obs['learn_level']
                or (raw.get('envChange') or {}).get('status')=='removed'):
                raise ValueError(f'SOURCE_CONTROL_RANK_INVALID:{sid}')
            fields=parse_control_observation(obs)
            blob=json.dumps(obs,sort_keys=True,separators=(',',':'))
            con.execute('''INSERT OR REPLACE INTO source_control_action_observations VALUES
            (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(
                cl,sid,obs['name'],int(obs['learn_level']),fields['required_mode_id'],
                fields['cost_resource'],fields['cost_amount'],fields['cast_time_s'],fields['gcd_s'],fields['cooldown_s'],
                fields['effect_kind'],fields['duration_s'],obs['source_url'],obs['observed_at'],
                indexed['batch_id'],hashlib.sha256(indexed['raw_listview_json'].encode()).hexdigest(),
                hashlib.sha256(blob.encode()).hexdigest(),blob,
            ))
        con.execute("PRAGMA integrity_check")

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--db',type=Path,required=True);ap.add_argument('--observations',type=Path,required=True)
    a=ap.parse_args();ingest(a.db,a.observations)
