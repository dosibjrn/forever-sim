"""Stage source-backed Warrior L30 stat and weapon gear execution facts.

The source is copied; the canonical SQLite is never modified. This is a P3
measurement prerequisite, NOT source membership attestation or P3 acceptance.
"""
from __future__ import annotations
import hashlib,json,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'data/forever/staged_warrior_l30_talents_70338.sqlite'
DST=ROOT/'data/forever/staged_warrior_l30_gear_runtime_wf368.sqlite'
SOURCE='https://foreverdb.net/stats/warrior'
SOURCE_GEAR='https://www.wowhead.com/forever/items/finder'


def stage(source:Path=SRC,destination:Path=DST)->dict:
    if source.resolve()==destination.resolve():raise ValueError('REFUSE_SOURCE_OVERWRITE')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(f'file:{source.resolve()}?mode=ro',uri=True) as original,sqlite3.connect(destination) as db:
        original.backup(db)
        facts=[
            ('strength','stat','attack_power',2.0,'total','linear',None,None,
             'Forever client Warrior Strength grants +2 melee attack power.'),
            ('stamina','resource_capacity','health',10.0,'delta_only','linear',None,None,
             'Forever client +10 HP per Stamina after first 20; naked HP remains proxy, only equipment delta applied.'),
            ('agility','stat','melee_crit_chance',0.01/10.4,'total','linear',None,None,
             'Forever beta L30 Warrior 10.4 Agility = 1% melee crit.'),
            ('agility','stat','armor',2.0,'total','linear',None,None,
             'Forever client Agility gives 2 Armor per point.'),
        ]
        for stat,kind,target,coef,baseline,operation,threshold,below,evidence in facts:
            db.execute('''INSERT OR REPLACE INTO actor_stat_conversion_source_facts
                (class_key,source_stat,target_type,target_id,coefficient,baseline,
                authority,source_url,source_date,evidence,capture_id,operation,threshold,below_coefficient)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                ('warrior',stat,kind,target,coef,baseline,'foreverdb_beta_client_70291',
                 SOURCE,'2026-10-14',evidence,'wf368_warrior_l30_gear_primary',operation,threshold,below))
        db.execute('''INSERT OR REPLACE INTO equipped_weapon_mode_source_facts
            (class_key,mode_label,source_stat,damage_source_kind,operation,applies_to,
            authority,source_url,source_date,evidence,capture_id,source_item_slot,
            weapon_speed_semantics,weapon_speed_source_url)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(
            'warrior','*','weapon_dps','scenario_ordinary_mainhand','replace_flat_dps',
            'auto_and_weapon_actions','qualified_equipped_weapon_item_tooltip',
            SOURCE_GEAR,'2026-10-14',
            'Ordinary Warrior main-hand autoattack takes its damage and speed from the equipped source item; no second scenario weapon DPS.',
            'wf368_warrior_mainhand_gear_bridge','weapon','equipped',SOURCE_GEAR))
        db.commit()
        integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
        if integrity!='ok':raise ValueError('SQLITE_INTEGRITY:'+integrity)
    return {'source':str(source),'destination':str(destination),'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),
        'conversion_rows':len(facts),'weapon_rows':1,'integrity':'ok',
        'membership_proven':False,'p3_status':'FAIL_PENDING_LEGAL_DENOMINATOR_AND_MEASURED_TOP5'}

if __name__=='__main__':print(json.dumps(stage(),indent=2))
