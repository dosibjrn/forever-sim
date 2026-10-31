"""Stage ForeverDB-client Warrior L30 per-item witnesses into existing item SQLite.

Source data is versioned JSON, never embedded game facts in optimizer logic.
Per-item membership is *not* a complete Warrior class-1 denominator.  In
particular, the 2,951 cross-class rows remain provisional and P3 stays FAIL.
"""
from __future__ import annotations
import hashlib,json,sqlite3
from pathlib import Path
from src.rulesets.forever.items.catalogue import ItemCatalogue,ItemRecord

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'data/forever/source_captures/WF370_WARRIOR_L30_FOREVERDB_BIS_70338.json'
PARENT=ROOT/'data/forever/staged_warrior_l30_gear_provisional_wf365.sqlite'
STAGE=ROOT/'data/forever/staged_warrior_l30_bis_witness_wf370.sqlite'


def stage(output:Path=STAGE)->dict:
    source=json.loads(SOURCE.read_text())
    assert source['class_key']=='warrior' and source['level']==30 and source['source_build']=='1.60.1.70338'
    ids=[int(x['item_id']) for x in source['items']]
    assert len(ids)==len(set(ids))
    assert all(x['source_url']==f'https://foreverdb.net/item/{x["item_id"]}' and x['bis_profiles'] for x in source['items'])
    assert output.resolve()!=PARENT.resolve()
    output.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(f'file:{PARENT.resolve()}?mode=ro',uri=True) as src,sqlite3.connect(output) as db:
        src.backup(db)
    with ItemCatalogue(output) as cat:
        for row in source['items']:
            old=cat.get_item(int(row['item_id']))
            if old is None:
                facts=row.get('new_item')
                if facts is None:raise ValueError('SOURCE_WITNESS_MISSING_ITEM_FACTS:'+str(row['item_id']))
                rec=ItemRecord(item_id=int(row['item_id']),name=row['name'],
                    source_type='foreverdb_client',source_name='ForeverDB client 70338',
                    source_url=row['source_url'],identity_origin='foreverdb_client',
                    fetch_status='verified_detail',last_verified_at=source['checked_at'],
                    upstream_fingerprint=hashlib.sha256(json.dumps(row,sort_keys=True).encode()).hexdigest(),
                    **facts)
                cat.upsert_items([rec])
            elif old.name!=row['name']:
                raise ValueError('SOURCE_WITNESS_ID_NAME_MISMATCH:'+str(row['item_id']))
    with sqlite3.connect(output) as db:
        db.execute('CREATE TABLE IF NOT EXISTS item_acquisition_min_level (item_id INTEGER PRIMARY KEY REFERENCES items(item_id), min_level INTEGER NOT NULL CHECK(min_level>=1), source_url TEXT NOT NULL)')
        for row in source['items']:
            if 'acquisition_min_level' in row:
                if not row.get('acquisition_source_url','').startswith('https://'):
                    raise ValueError('UNSOURCED_ACQUISITION_FLOOR')
                db.execute('INSERT OR REPLACE INTO item_acquisition_min_level(item_id,min_level,source_url) VALUES(?,?,?)',
                    (int(row['item_id']),int(row['acquisition_min_level']),row['acquisition_source_url']))
        for row in source['items']:
            db.execute('INSERT OR REPLACE INTO item_class_eligibility(item_id,class_id,provenance) VALUES(?,?,?)',
                (int(row['item_id']),1,row['source_url']))
            db.execute('INSERT OR IGNORE INTO item_sources(item_id,source_type,source_name,source_ref) VALUES(?,?,?,?)',
                (int(row['item_id']),'foreverdb_client','Warrior L30 BIS witness',row['source_url']))
        memberships=db.execute('SELECT item_id,provenance FROM item_class_eligibility WHERE class_id=1 ORDER BY item_id,provenance').fetchall()
        digest=hashlib.sha256(''.join(f'{iid}\t{p}\n' for iid,p in memberships).encode()).hexdigest()
        db.execute('UPDATE class_source_attestation SET source_kind=?,source_sha256=?,member_count=?,verified=0,membership_sha256=? WHERE class_id=1',
            ('PROVISIONAL_WITH_PER_ITEM_FOREVERDB_WITNESSES',hashlib.sha256(SOURCE.read_bytes()).hexdigest(),len(memberships),digest))
        db.commit()
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('SELECT verified FROM class_source_attestation WHERE class_id=1').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM item_class_eligibility WHERE class_id=1 AND provenance LIKE "https://foreverdb.net/item/%"').fetchone()[0]==len(ids)
    return {'source_item_witnesses':len(ids),'new_catalogue_items':sum('new_item' in x for x in source['items']),
        'global_membership_verified':False,'p3_pass':False,'staged_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
        'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest()}

if __name__=='__main__':print(json.dumps(stage(),indent=2))
