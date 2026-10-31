"""Idempotent source-URL-verified Hunter/Paladin L10-20 action capture.

Source facts are *not* class defaults in Python. A canonical spell_index row
must corroborate every captured class/spell/level before it can execute.
"""
from __future__ import annotations
import json, sqlite3
from pathlib import Path
from src.game.data.forever.sqlite_talents import DEFAULT_DB

CAPTURE = Path(__file__).resolve().parents[1] / 'data/forever/source_captures/wf251_two_classes_2026-10-11.json'

def ingest(db_path=DEFAULT_DB, capture_path=CAPTURE):
    payload=json.loads(Path(capture_path).read_text())
    if payload['capture_id']!='wf251_two_classes_2026-10-11':
        raise ValueError('unexpected source capture ID')
    with sqlite3.connect(db_path) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS verified_native_class_scenarios (
          class_key TEXT PRIMARY KEY, min_level INTEGER NOT NULL, max_level INTEGER NOT NULL,
          mana_scenario_json TEXT NOT NULL, auto_json TEXT NOT NULL,
          capture_id TEXT NOT NULL, provenance_json TEXT NOT NULL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS verified_native_class_actions (
          class_key TEXT NOT NULL, spell_id INTEGER NOT NULL, family_key TEXT NOT NULL,
          min_level INTEGER NOT NULL, resource_id TEXT NOT NULL, cost REAL NOT NULL,
          cast_s REAL NOT NULL, gcd_s REAL NOT NULL, cooldown_s REAL NOT NULL,
          effect_json TEXT NOT NULL, source_url TEXT NOT NULL, capture_id TEXT NOT NULL,
          caveats_json TEXT NOT NULL, PRIMARY KEY(class_key,spell_id))''')
        for c in payload['classes']:
            if c['min_level']>c['max_level'] or not c['provenance']:
                raise ValueError('invalid class scenario')
            conn.execute('''INSERT OR IGNORE INTO verified_native_class_scenarios VALUES (?,?,?,?,?,?,?)''',
                (c['class_key'],c['min_level'],c['max_level'],json.dumps(c['mana_scenario']),
                 json.dumps(c['auto']),payload['capture_id'],json.dumps(c['provenance'])))
            for a in c['actions']:
                if not a['source_url'].startswith('https://www.wowhead.com/forever/spell='):
                    raise ValueError('unverified source domain')
                if not a['effects'] or a['cost']<0 or a['min_level']<1:
                    raise ValueError('invalid source action')
                indexed=conn.execute('''SELECT name,level_hint FROM spell_index
                   WHERE class_key=? AND spell_id=? AND kind='abilities' ''',
                   (c['class_key'],a['spell_id'])).fetchone()
                if indexed is None or int(indexed[1])!=a['min_level']:
                    raise ValueError(f"source index does not corroborate {c['class_key']}:{a['spell_id']}")
                conn.execute('''INSERT OR IGNORE INTO verified_native_class_actions VALUES
                   (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                   (c['class_key'],a['spell_id'],a['family_key'],a['min_level'],'mana',a['cost'],
                    a['cast_s'],a['gcd_s'],a['cooldown_s'],json.dumps(a['effects']),
                    a['source_url'],payload['capture_id'],json.dumps(a.get('caveats',[]))))
        columns=[r[1] for r in conn.execute('PRAGMA table_info(equipped_weapon_mode_source_facts)')]
        if 'source_item_slot' not in columns:
            conn.execute("ALTER TABLE equipped_weapon_mode_source_facts ADD COLUMN source_item_slot TEXT NOT NULL DEFAULT 'weapon'")
        for c in payload['classes']:
            a=c['auto']
            conn.execute('''INSERT OR IGNORE INTO equipped_weapon_mode_source_facts
               (class_key,mode_label,source_stat,damage_source_kind,operation,applies_to,authority,source_url,source_date,evidence,capture_id,source_item_slot)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',(
                c['class_key'],'Ordinary Weapon','weapon_dps',
                'equipped_weapon_dps_plus_attack_power','replace_flat_dps',
                'auto_and_weapon_actions','qualified_weapon_source_tooltip',
                a['source_url'],payload['captured_at'],
                'Auto/weapon attacks use equipped weapon damage; exact weapon speed and base stats are separate scenario proxies',
                payload['capture_id'],'ranged' if a['kind']=='ranged' else 'weapon'))
        # Qualified inherited-Classic stat conversions, never claimed
        # target-server verified. The generic gear engine consumes these rows.
        source_rows=(
            ('hunter','agility','stat','attack_power',2.0,
             'https://www.wowhead.com/classic/guide/classes/hunter/dps-new-player',
             'Hunter Agility contributes 2 ranged AP; this actor models ranged combat only'),
            ('paladin','strength','stat','attack_power',2.0,
             'https://www.warcrafttavern.com/wow-classic/guides/pve-retribution-paladin-stat-priority/',
             'Paladin Strength contributes 2 melee AP'),
        )
        source_rows+=tuple((cls,'stamina','resource_capacity','health',10.0,
            'https://www.wowhead.com/classic/guide/classes/hunter/dps-stat-priority-attributes-pve',
            'Qualified +10 HP per equipped Stamina; naked baseline and first-20 Stamina threshold remain unresolved')
            for cls in ('hunter','paladin'))
        source_rows+=tuple((cls,'agility','stat','armor',2.0,
            'https://www.wowhead.com/classic/guide/classes/hunter/dps-new-player',
            'Inherited Classic 2 Armor per Agility; target-server unverified')
            for cls in ('hunter','paladin'))
        for cls,stat,target_type,target,coef,url,evidence in source_rows:
            conn.execute('''INSERT OR IGNORE INTO actor_stat_conversion_source_facts
              (class_key,source_stat,target_type,target_id,coefficient,baseline,
               authority,source_url,source_date,evidence,capture_id,operation,threshold,below_coefficient)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
               (cls,stat,target_type,target,coef,
                'delta_only' if target_type=='resource_capacity' else 'total','qualified_inherited_classic',
                url,payload['captured_at'],evidence,payload['capture_id'],'linear',None,None))
        conn.execute('''CREATE TABLE IF NOT EXISTS world_incoming_scenario_facts (
          level INTEGER PRIMARY KEY, attacker_level INTEGER NOT NULL,
          swing_s REAL NOT NULL, raw_damage REAL NOT NULL,
          armor_constant REAL NOT NULL, reduction_cap REAL NOT NULL,
          authority TEXT NOT NULL, source_url TEXT NOT NULL, capture_id TEXT NOT NULL)''')
        from src.rulesets.forever.shared.mobs import normal_world_raw_dps
        from src.rulesets.forever.shared.defense import armor_constant
        for lvl in range(1,61):
            attacker=lvl+2
            conn.execute('''INSERT OR IGNORE INTO world_incoming_scenario_facts VALUES (?,?,?,?,?,?,?,?,?)''',
                (lvl,attacker,2.0,2.0*float(normal_world_raw_dps(attacker)),
                 float(armor_constant(attacker)),0.75,
                 'existing_forever_qualified_classic_world_mob_fixture',
                 'https://wowwiki-archive.fandom.com/wiki/Damage_reduction',payload['capture_id']))
        return {c['class_key']:len(c['actions']) for c in payload['classes']}

if __name__=='__main__': print(ingest())
