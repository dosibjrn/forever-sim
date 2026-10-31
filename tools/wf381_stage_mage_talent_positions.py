"""Create a version-pinned, isolated canonical SQLite talent-position snapshot.

This stages ONLY positions, rank caps and prerequisites.  The absence of
source tooltip rank curves remains a P2 coverage blocker, not zero benefit.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import shutil
import sqlite3

from src.game.data.forever.sqlite_talents import DEFAULT_DB

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'evidence/wf381/mage_talent_positions_70374.json'
TARGET = ROOT / 'data/forever/staged_mage_l30_talent_positions_70374.sqlite'


def stage(*, source: Path = SOURCE, base: Path = DEFAULT_DB, target: Path = TARGET):
    source, base, target = map(Path, (source, base, target))
    if base.resolve() == target.resolve():
        raise ValueError('STAGED_TALENT_SOURCE_DB_MUST_NOT_BE_OVERWRITTEN')
    data = json.loads(source.read_text())
    if (data.get('schema') != 'forever_source_talent_positions_v1'
            or not data.get('talents') or not data.get('source_build')
            or not data.get('class_key') or not data.get('min_level')):
        raise ValueError('STAGED_TALENT_INVALID_SOURCE_DOCUMENT')
    raw = json.dumps(data, sort_keys=True)
    base_hash = sha256(base.read_bytes()).hexdigest()
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(base, target)
    with sqlite3.connect(target) as db:
        db.execute('''CREATE TABLE checkpoint_talent_source_positions (
            class_key TEXT NOT NULL, source_build TEXT NOT NULL,
            min_level INTEGER NOT NULL, source_sha256 TEXT NOT NULL,
            source_json TEXT NOT NULL,
            PRIMARY KEY(class_key,source_build,min_level))''')
        db.execute('INSERT INTO checkpoint_talent_source_positions VALUES (?,?,?,?,?)',
                   (data['class_key'], data['source_build'], int(data['min_level']),
                    sha256(raw.encode()).hexdigest(), raw))
        integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
        if integrity != 'ok':
            raise ValueError('STAGED_TALENT_SQLITE_INTEGRITY_FAILED')
    if sha256(base.read_bytes()).hexdigest() != base_hash:
        raise ValueError('STAGED_TALENT_CANONICAL_SOURCE_CHANGED')
    return {'positions': len(data['talents']), 'source_build': data['source_build'],
            'source_sha256': sha256(source.read_bytes()).hexdigest(),
            'staged_db_sha256': sha256(target.read_bytes()).hexdigest(),
            'base_sha256': base_hash, 'sqlite_integrity': integrity,
            'staged_db': str(target)}


if __name__ == '__main__':
    print(json.dumps(stage(), indent=2))
