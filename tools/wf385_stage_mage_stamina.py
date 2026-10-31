"""Reproducibly stage the ForeverDB Mage stamina marginal in canonical SQLite.

The naked Mage Stamina remains unknown. The 20-point threshold is an explicit
assumption for *marginal gear Stamina only*, not a character base-stat claim.
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'data/forever/staged_mage_l30_talent_positions_70374.sqlite'
TARGET=ROOT/'data/forever/staged_mage_l30_stamina_70374.sqlite'


def stage(source:Path=SOURCE,target:Path=TARGET)->dict:
    if source.resolve()==target.resolve():
        raise ValueError('source database must not be overwritten')
    target.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(f'file:{source.resolve()}?mode=ro',uri=True) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
        dst.execute('''INSERT INTO actor_stat_conversion_source_facts
            (class_key,source_stat,target_type,target_id,coefficient,baseline,authority,
             source_url,source_date,evidence,capture_id,operation,threshold,below_coefficient)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            ('mage','stamina','resource_capacity','health',10.,'delta_only',
             'foreverdb_forever_client_character_sheet','https://foreverdb.net/stats/mage',
             '2026-10-14','Forever client tooltip: 1 HP for first 20 Stamina, 10 HP thereafter. Naked Mage Stamina is unknown. Gear delta assumes naked Stamina >=20; actual total Stamina is NOT synthesized.',
             'wf385_mage_stamina_70374','threshold_linear',20.,1.))
        assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert dst.execute("SELECT count(*) FROM actor_stat_conversion_source_facts WHERE class_key='mage' AND source_stat='stamina'").fetchone()[0]==1
    return {'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'target':str(target),'target_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
            'source_url':'https://foreverdb.net/stats/mage',
            'marginal_assumption':'UNKNOWN_NAKED_STAMINA_AT_LEAST_20',
            'sqlite_integrity':'ok'}

if __name__=='__main__':
    print(json.dumps(stage(),indent=2))
