"""Strict versioned client-tooltip ranks -> canonical timed-aura SQLite.

Only captures are spell-specific; runtime is class-neutral. Re-running is idempotent.
"""
from __future__ import annotations
import json,sqlite3
from pathlib import Path
from src.game.data.forever.sqlite_talents import DEFAULT_DB
CAPTURE=Path(__file__).resolve().parents[1]/'data/forever/source_captures/wf256_paladin_crusader_fury_20261011.json'
COLUMNS={
    'mechanic_kind':'TEXT NOT NULL DEFAULT \'swing_damage\'',
    'actor_attack_power_delta':'REAL', 'attack_rate_multiplier':'REAL',
    'judge_school_power_bonus':'REAL', 'judge_duration_s':'REAL',
    'judge_exclusive_group':'TEXT', 'swing_speed_scaled':'INTEGER NOT NULL DEFAULT 1',
    'swing_absorb_fraction':'REAL','swing_absorb_requires_stat':'TEXT','swing_absorb_id':'TEXT',
}

def ingest(db_path=DEFAULT_DB,capture_path=CAPTURE):
    p=json.loads(Path(capture_path).read_text())
    if not p['client_build'].startswith('1.60.1.') or not p['source_authority'].startswith('current_beta_client_'):
        raise ValueError('invalid capture version or authority')
    with sqlite3.connect(db_path) as db:
        db.execute('BEGIN IMMEDIATE')
        columns={row[1] for row in db.execute('PRAGMA table_info(sourced_timed_aura_actions)')}
        for name,typ in COLUMNS.items():
            if name not in columns:db.execute(f'ALTER TABLE sourced_timed_aura_actions ADD COLUMN {name} {typ}')
        rows=0
        for family in p['families']:
            if (not family['source_url'].startswith('https://theforeverera.com/en/spells/') or
                not family['crosscheck_url'].startswith('https://') or
                family['exclusive_group']!='paladin_seal' or
                family['mechanic_kind'] not in ('swing_damage','attack_rate_buff')):
                raise ValueError('invalid source family authority or mechanic')
            if family['mechanic_kind']=='attack_rate_buff' and not (family['attack_rate_multiplier']>1 and family['judge_duration_s']>0):
                raise ValueError('invalid source attack speed/judgement')
            if family['mechanic_kind']=='swing_damage' and not 0<=family['swing_absorb_fraction']<=1:
                raise ValueError('invalid source absorb fraction')
            for r in family['ranks']:
                idx=db.execute("SELECT level_hint,name FROM spell_index WHERE class_key=? AND kind='abilities' AND spell_id=?",
                    (p['class_key'],r['spell_id'])).fetchone()
                if idx is None or int(idx[0])!=int(r['min_level']) or idx[1].lower()!=family['family_key'].replace('_',' '):
                    raise ValueError(f'canonical spell identity/rank mismatch: {r["spell_id"]}')
                if r['mana_cost']<0 or r['min_level']<1:
                    raise ValueError('invalid source cost/level')
                old=db.execute('SELECT capture_id FROM sourced_timed_aura_actions WHERE class_key=? AND spell_id=?',
                    (p['class_key'],r['spell_id'])).fetchone()
                if old and old[0]!=p['capture_id']:raise ValueError('conflicting canonical source rank')
                damage=family['mechanic_kind']=='swing_damage'
                caveats={'source_authority':p['source_authority'],
                    'damage_formula':family.get('damage_per_swing_interpretation'),
                    'judgement_school_power_interpretation':family.get('judge_school_power_interpretation'),
                    'absorb_semantics':family.get('absorb_semantics'),
                    'coefficient_source_url':family.get('coefficient_source_url'),
                    'coefficient_provenance':family.get('coefficient_provenance'),
                    'taunt_status':family.get('judgement_taunt_status')}
                data=dict(class_key=p['class_key'],spell_id=r['spell_id'],family_key=family['family_key'],
                    min_level=r['min_level'],mana_cost=r['mana_cost'],duration_s=family['duration_s'],gcd_s=family['gcd_s'],
                    aura_id=family['aura_id'],school=family['school'],swing_min=r.get('swing_min',0),swing_max=r.get('swing_max',0),
                    judgement_min=r.get('judgement_min'),judgement_max=r.get('judgement_max'),
                    proc_sp_coefficient=float(family.get('proc_sp_coefficient',0.0)),
                    judge_sp_coefficient=float(family.get('judge_sp_coefficient',0.0)),proc_reference_speed_s=1.0,
                    source_url=family['source_url'],crosscheck_url=family['crosscheck_url'],client_build=p['client_build'],
                    capture_id=p['capture_id'],caveats_json=json.dumps(caveats),exclusive_group=family['exclusive_group'],
                    mechanic_kind=family['mechanic_kind'],actor_attack_power_delta=r.get('actor_attack_power_delta'),
                    attack_rate_multiplier=family.get('attack_rate_multiplier'),
                    judge_school_power_bonus=r.get('judge_school_power_bonus'),judge_duration_s=family.get('judge_duration_s'),
                    judge_exclusive_group=family.get('judge_exclusive_group'),
                    swing_speed_scaled=int(family.get('swing_speed_scaled',True)),
                    swing_absorb_fraction=family.get('swing_absorb_fraction'),
                    swing_absorb_requires_stat=family.get('swing_absorb_requires_stat'),swing_absorb_id=family.get('swing_absorb_id'))
                cols=list(data)
                db.execute(f'INSERT OR REPLACE INTO sourced_timed_aura_actions ({",".join(cols)}) VALUES ({",".join("?" for _ in cols)})',
                    [data[k] for k in cols]);rows+=1
        # The consumer is a shared sourced Judgement: one target judgement
        # active at a time, not a separate button per seal.
        cols={x[1] for x in db.execute('PRAGMA table_info(sourced_aura_consumers)')}
        if 'judge_exclusive_group' not in cols:
            db.execute('ALTER TABLE sourced_aura_consumers ADD COLUMN judge_exclusive_group TEXT')
        db.execute("UPDATE sourced_aura_consumers SET judge_exclusive_group='paladin_judgement' WHERE class_key=? AND family_key='judgement'",(p['class_key'],))
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('SQLite integrity failure')
        return {'sourced_aura_ranks':rows,'families':len(p['families']),'capture_id':p['capture_id']}
if __name__=='__main__':print(ingest())
