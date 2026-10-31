"""Type source-observed WF345 Rune of Battle equip effects, generically executed.

Only the one-time source ingestion refers to specific item IDs. Effects carry
source-signed magnitudes and context. No invented item numbers in the runtime.
"""
from pathlib import Path
from hashlib import sha256
import json, sqlite3

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/forever/source_equipment_semantics_70338.sqlite'

def migrate(db_path=DB):
    with sqlite3.connect(db_path) as db:
        for iid,stat in ((21566,'spell_penetration'),(21568,'resistance_all')):
            row=db.execute('''SELECT evidence_excerpt,evidence_sha256,equip_semantics
                FROM source_item_equipment_semantics WHERE item_id=?''',(iid,)).fetchone()
            if not row or row[2]!='EQUIPPABLE_UNTYPED_EFFECT' or sha256(row[0].encode()).hexdigest()!=row[1]:
                raise ValueError('SOURCE_ITEM_EVIDENCE_NOT_PRESENT_OR_CHANGED')
            entries=[{'type':'add_actor_stat','stat':stat,'amount':2,'source':'equip_tooltip'},
                {'type':'add_actor_stat_if_environment','stat':stat,'amount':4,
                 'environments':['forest','grassland'],'source':'equip_tooltip'}]
            db.execute('''UPDATE source_item_equipment_semantics SET
                equip_semantics='EQUIPPABLE_TYPED_PASSIVE',typed_effects_json=? WHERE item_id=?''',
                (json.dumps(entries,sort_keys=True),iid))
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    return sha256(Path(db_path).read_bytes()).hexdigest()

if __name__=='__main__':print(migrate())
