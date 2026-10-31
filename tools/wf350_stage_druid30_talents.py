"""Build an isolated canonical SQLite source stage from versioned Forever evidence.

The generic IR loader reads the staged table; this script does not modify the
original catalogue or add class-specific branches to the optimizer.
"""
from __future__ import annotations
import hashlib, json, shutil, sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'data/forever/catalogue/forever_abilities.sqlite'
SOURCE=ROOT/'evidence/wf350/druid_l30_source_talent_catalogue_70338.json'
TARGET=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite'

def stage():
    raw=SOURCE.read_bytes();data=json.loads(raw)
    assert data['source_build']=='1.60.1.70338' and data['class_key']=='druid'
    shutil.copyfile(BASE,TARGET)
    with sqlite3.connect(TARGET) as db:
        db.execute('''CREATE TABLE checkpoint_talent_source_catalogue (
            class_key TEXT NOT NULL, source_build TEXT NOT NULL,
            min_level INTEGER NOT NULL, source_sha256 TEXT NOT NULL,
            source_json TEXT NOT NULL,
            PRIMARY KEY(class_key,source_build,min_level))''')
        db.execute('INSERT INTO checkpoint_talent_source_catalogue VALUES(?,?,?,?,?)',(
            data['class_key'],data['source_build'],data['min_level'],hashlib.sha256(raw).hexdigest(),raw.decode()))
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    return {'stage':str(TARGET),'source_sha256':hashlib.sha256(raw).hexdigest(),
            'stage_sha256':hashlib.sha256(TARGET.read_bytes()).hexdigest(),
            'source_catalogue_size':len(data['catalogue']), 'source_observations':len(data['observations'])}
if __name__=='__main__':print(json.dumps(stage(),indent=2))
