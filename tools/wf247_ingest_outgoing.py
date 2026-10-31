"""Reproducible 2026-10-11 source snapshot -> canonical SQLite (no runtime constants).

CMaNGOS-derived class-1 ordinary target armor is a QUALIFIED CLASSIC PROXY,
not a verified Forever server armor value. Never silently label it authoritative.
"""
import sqlite3
from pathlib import Path
from src.game.data.forever.sqlite_talents import DEFAULT_DB

ARMOR_CLS1 = '8,20,33,68,111,165,230,306,387,463,528,562,596,630,665,700,734,768,802,836,872,906,940,975,1008,1043,1078,1111,1145,1179,1213,1249,1281,1317,1349,1456,1568,1684,1808,1938,2074,2218,2369,2528,2695,2750,2804,2857,2912,2966,3018,3060,3128,3180,3234,3289,3342,3396,3449,3750'
ARMOR_URL='https://github.com/mangoszero/database/blob/325948a78015794e6cc626212bc19fee70c805b2/World/Setup/FullDB/creature_template_classlevelstats.sql'
FAERIE_URL='https://foreverdb.net/spell/770'
RANKS=((770,1,18,55,175),(778,2,30,75,285),(9749,3,42,95,395),(9907,4,54,115,505))
CAPTURE='wf247_outgoing_defense_20261011'

def ingest(path=DEFAULT_DB):
    armor=[int(x) for x in ARMOR_CLS1.split(',')]
    assert len(armor)==60 and armor[19]==836
    with sqlite3.connect(Path(path)) as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS outgoing_combat_profile_source_facts (
          scenario_key TEXT NOT NULL, level INTEGER NOT NULL, target_armor REAL NOT NULL,
          melee_hit REAL NOT NULL, spell_hit REAL NOT NULL,
          armor_constant REAL NOT NULL, reduction_cap REAL NOT NULL,
          target_armor_source TEXT NOT NULL, hit_source TEXT NOT NULL,
          mitigation_source TEXT NOT NULL, source_status TEXT NOT NULL,
          capture_id TEXT NOT NULL, PRIMARY KEY(scenario_key,level));
        CREATE TABLE IF NOT EXISTS target_armor_debuff_source_facts (
          class_key TEXT NOT NULL, spell_id INTEGER NOT NULL, family_key TEXT NOT NULL,
          rank INTEGER NOT NULL, required_level INTEGER NOT NULL,
          mana_cost REAL NOT NULL, armor_delta REAL NOT NULL,
          duration_s REAL NOT NULL, gcd_s REAL NOT NULL,
          allowed_modes TEXT NOT NULL, source_url TEXT NOT NULL,
          source_build TEXT NOT NULL, capture_id TEXT NOT NULL,
          PRIMARY KEY(class_key,spell_id));
        ''')
        for level, basearmor in enumerate(armor,1):
            c.execute('''INSERT OR REPLACE INTO outgoing_combat_profile_source_facts VALUES
            (?,?,?,?,?,?,?,?,?,?,?,?)''',('ordinary_melee_classic_proxy',level,basearmor,
                0.95,0.96,(400+85*level if level<60 else 467.5*level-22167.5),0.75,ARMOR_URL,
                'https://classic-wow-archive.fandom.com/wiki/Spell_Hit_Chance;https://classic-wow-archive.fandom.com/wiki/Hit',
                'https://wowwiki-archive.fandom.com/wiki/Damage_reduction',
                'classic_proxy_not_forever_server_verified',CAPTURE))
        for sid,rank,level,cost,debuff in RANKS:
            c.execute('''INSERT OR REPLACE INTO target_armor_debuff_source_facts VALUES
            (?,?,?,?,?,?,?,?,?,?,?,?,?)''',('druid',sid,'faerie_fire',rank,level,cost,debuff,
                40.,1.5,'caster,cat,bear',f'https://foreverdb.net/spell/{sid}',
                '1.60.1.70291',CAPTURE))
        assert c.execute('pragma integrity_check').fetchone()[0]=='ok'
    return len(armor),len(RANKS)

if __name__=='__main__': print(ingest())
