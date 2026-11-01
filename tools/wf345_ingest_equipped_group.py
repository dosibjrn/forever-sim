"""One-time source-evidence migration for Forever unique-equipped item groups.

Facts are ingested into the existing immutable item-semantics SQLite ledger;
no item IDs or group names are placed in the runtime algorithms.
"""
from hashlib import sha256
from pathlib import Path
import sqlite3

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/forever/source_equipment_semantics_70338.sqlite'
OBSERVED='2026-10-13'
SOURCE='FOREVER_WEB_TEXT_BUILD_UNCONFIRMED'
EVIDENCE=(
    (21566,'Rune of Perfection','trinket','rune-of-perfection',
     'Item Level 25; Unique-Equipped: Rune of Battle (1); Trinket; +4 Stamina; Requires Level 20; Equip: Your spells pierce 2 Magical Resistances. Gain an additional 4 Spell Piercing in Forest and Grassland areas.',
     'Rune of Battle',1),
    (21568,'Rune of Duty','trinket','rune-of-duty',
     'Item Level 25; Unique-Equipped: Rune of Battle (1); Trinket; +4 Stamina; Requires Level 20; Equip: Increases all Resistances by 2. Gain an additional 4 to all Resistances in Forest and Grassland areas.',
     'Rune of Battle',1),
    (273298,"Lookie's Spyglass",'trinket','lookies-spyglass',
     'Item Level 23; Unique-Equipped; Trinket; +1 Spirit; Requires Level 18; Use: Allows you to look far into the distance. Community note: moving cancels the visual effect; cannot be done in combat.',
     'Unique item:273298',1),
)

def migrate(path=DB):
    with sqlite3.connect(path) as db:
        cols={r[1] for r in db.execute('PRAGMA table_info(source_item_equipment_semantics)')}
        if 'equip_group' not in cols:
            db.execute('ALTER TABLE source_item_equipment_semantics RENAME TO old_semantics')
            db.execute('''CREATE TABLE source_item_equipment_semantics (
                item_id INTEGER PRIMARY KEY, item_name TEXT NOT NULL, catalogue_slot TEXT NOT NULL,
                source_url TEXT NOT NULL, source_observed_at TEXT NOT NULL, source_scope TEXT NOT NULL,
                evidence_excerpt TEXT NOT NULL, evidence_sha256 TEXT NOT NULL,
                equip_semantics TEXT NOT NULL CHECK(equip_semantics IN
                ('NON_EQUIPPABLE_RUNE_LEARNING_ITEM','EQUIPPABLE_TYPED_PASSIVE','EQUIPPABLE_UNTYPED_EFFECT','EQUIPPABLE_NONCOMBAT_USE')),
                typed_effects_json TEXT NOT NULL,
                equip_group TEXT, equip_limit INTEGER,
                CHECK(length(evidence_sha256)=64),
                CHECK((equip_group IS NULL AND equip_limit IS NULL) OR
                      (length(equip_group)>0 AND equip_limit>=1)))''')
            db.execute('''INSERT INTO source_item_equipment_semantics
                (item_id,item_name,catalogue_slot,source_url,source_observed_at,source_scope,
                 evidence_excerpt,evidence_sha256,equip_semantics,typed_effects_json)
                SELECT item_id,item_name,catalogue_slot,source_url,source_observed_at,source_scope,
                       evidence_excerpt,evidence_sha256,equip_semantics,typed_effects_json FROM old_semantics''')
            db.execute('DROP TABLE old_semantics')
        for iid,name,slot,slug,excerpt,group,limit in EVIDENCE:
            db.execute('''INSERT OR REPLACE INTO source_item_equipment_semantics
                (item_id,item_name,catalogue_slot,source_url,source_observed_at,source_scope,
                 evidence_excerpt,evidence_sha256,equip_semantics,typed_effects_json,equip_group,equip_limit)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                (iid,name,slot,f'https://www.wowhead.com/forever/item={iid}/{slug}',OBSERVED,SOURCE,
                 excerpt,sha256(excerpt.encode()).hexdigest(),
                 'EQUIPPABLE_NONCOMBAT_USE' if iid==273298 else 'EQUIPPABLE_UNTYPED_EFFECT',
                 '[]',group,limit))
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('SELECT COUNT(*) FROM source_item_equipment_semantics').fetchone()[0]==8
    return sha256(Path(path).read_bytes()).hexdigest()

if __name__=='__main__':print(migrate())
