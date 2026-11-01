"""Warrior source membership staging into a copy of the canonical item SQLite.

Source profile (armor/weapon skills) is separate from *per-item* eligibility.
Provisional membership from other classes is explicitly non-authoritative and
cannot certify P3. Verified source mode requires a complete class-1 item-ID
listview export with per-page provenance and a source-count checksum.
"""
from __future__ import annotations
import argparse, json, sqlite3, hashlib
from pathlib import Path
from src.rulesets.forever.items.runtime_selection import catalogue_path, _source_class_profile
from src.rulesets.forever.items.catalogue import ItemCatalogue
from src.rulesets.forever.items.wowhead_capture_import import canonical_base_rows,item_record_from_listview

ROOT=Path(__file__).resolve().parents[1]
PROVISIONAL='PROVISIONAL_CROSS_CLASS_INTERSECTION_NOT_WARRIOR_SOURCE'


def stage(*,output:Path,source_json:Path|None=None,provisional:bool=False,
          capture_dir:Path|None=None)->dict:
    if sum((source_json is not None,provisional,capture_dir is not None))!=1:
        raise ValueError('SELECT_EXACTLY_ONE_OF_SOURCE_CAPTURE_OR_PROVISIONAL')
    profile=_source_class_profile('warrior')
    if not profile or profile['class_id']!=1:raise ValueError('MISSING_WARRIOR_SOURCE_PROFILE')
    canonical=ROOT/'data/forever/catalogue/items_2026-09-29.sqlite'
    if output.resolve()==canonical.resolve():raise ValueError('REFUSE_TO_MUTATE_CANONICAL')
    output.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(f'file:{canonical.resolve()}?mode=ro',uri=True) as original,sqlite3.connect(output) as db:
        original.backup(db)
        db.execute('DELETE FROM item_class_eligibility WHERE class_id=1')
        if provisional:
            # Intersection across at least two independently verified source
            # class listviews is a useful engineering smoke set, not evidence
            # of Warrior eligibility. It may miss Warrior-only equipment and
            # include another class's exclusive items. Paladin-source shields
            # are provisional Warrior candidates because both classes have
            # shield proficiency; they do NOT establish class-1 membership.
            # Never count as PASS.
            ids=[int(row[0]) for row in db.execute('''
                SELECT item_id FROM item_class_eligibility
                WHERE class_id IN (2,3,8,11)
                GROUP BY item_id HAVING COUNT(DISTINCT class_id)>=2
                UNION
                SELECT e.item_id FROM item_class_eligibility e
                JOIN items i ON i.item_id=e.item_id
                WHERE i.slot IN ('ranged','thrown') AND i.weapon_type IN ('bow','crossbow','gun','thrown')
                UNION
                SELECT e.item_id FROM item_class_eligibility e
                JOIN items i ON i.item_id=e.item_id
                WHERE e.class_id=2 AND i.slot='off_hand' AND i.armor_type='shield' ''')]
            entries=[(iid,1,PROVISIONAL) for iid in ids]
            complete=False
            evidence='OTHER_CLASS_SOURCE_INTERSECTION_NOT_A_WARRIOR_LISTVIEW'
        elif capture_dir is not None:
            from src.rulesets.forever.items.source_capture_integrity import verify_class_capture
            verified = verify_class_capture(capture_dir, 'warrior')
            base = verified.base_rows
            records = [item_record_from_listview(r, captured_at=verified.captured_at)
                       for r in base.values()]
            db.commit()  # Existing catalogue writer needs the SQLite lock released.
            with ItemCatalogue(output) as cat:
                cat.upsert_items(records)
            entries = [(iid, 1, verified.provenance_by_id[iid]) for iid in sorted(base)]
            complete = True
            evidence = 'VERIFIED_WARRIOR_ADAPTIVE_CAPTURE_FULL_BAND_AND_BYTE_INTEGRITY'
        else:
            from src.rulesets.forever.items.source_capture_integrity import verify_class_item_export
            membership = verify_class_item_export(source_json, 'warrior')
            existing = {int(row[0]) for row in db.execute('SELECT item_id FROM items')}
            if set(membership) - existing:
                raise ValueError('SOURCE_WARRIOR_ITEMS_MISSING_CANONICAL_ITEM_ROWS')
            entries = [(iid, 1, provenance) for iid, provenance in sorted(membership.items())]
            complete = True
            evidence = 'VERIFIED_CLASS_1_EXPORT_BAND_COVERAGE_WITH_ITEM_ROWS'
        db.executemany('INSERT INTO item_class_eligibility(item_id,class_id,provenance) VALUES(?,?,?)',entries)
        db.execute('CREATE TABLE IF NOT EXISTS class_source_attestation (class_id INTEGER PRIMARY KEY, source_kind TEXT NOT NULL, source_sha256 TEXT NOT NULL, member_count INTEGER NOT NULL, verified INTEGER NOT NULL, membership_sha256 TEXT NOT NULL)')
        source_kind=('VERIFIED_CLASS_LISTVIEW_CAPTURE' if capture_dir is not None else
            'VERIFIED_CLASS_LISTVIEW_EXPORT' if source_json is not None else 'PROVISIONAL')
        source_bytes=((capture_dir/'manifest.json').read_bytes() if capture_dir is not None else
            source_json.read_bytes() if source_json is not None else PROVISIONAL.encode())
        membership_bytes=''.join(f'{iid}\t{provenance}\n' for iid,_,provenance in sorted(entries)).encode('utf-8')
        db.execute('INSERT OR REPLACE INTO class_source_attestation (class_id,source_kind,source_sha256,member_count,verified,membership_sha256) VALUES(?,?,?,?,?,?)',
            (1,source_kind,hashlib.sha256(source_bytes).hexdigest(),len(entries),int(complete),hashlib.sha256(membership_bytes).hexdigest()))
        db.commit()
        integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
        if integrity!='ok':raise ValueError('STAGED_SQLITE_INTEGRITY_FAILURE')
        source_count=db.execute('SELECT COUNT(*) FROM item_class_eligibility WHERE class_id=1').fetchone()[0]
        assert source_count==len(entries)
    return {'class_key':'warrior','level':30,'profile':'unrestricted',
        'staged_path':str(output),'canonical_sha256':hashlib.sha256(canonical.read_bytes()).hexdigest(),
        'staged_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
        'source_membership_count':len(entries),'membership_verified_complete':complete,
        'provenance':evidence,'source_json':str(source_json) if source_json else None,
        'p3_pass':False,'reason':'PROVISIONAL_ONLY' if not complete else 'RUN_CHECKPOINT_P3_AND_CONTEXTUAL_TOP5',
        'sqlite_integrity':'ok'}


def warrior_source_membership_verified(path:Path)->bool:
    from src.rulesets.forever.items.runtime_selection import source_class_item_membership_verified
    return source_class_item_membership_verified('warrior',path)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--source-json',type=Path)
    group.add_argument('--capture-dir',type=Path)
    group.add_argument('--provisional',action='store_true')
    args=parser.parse_args()
    print(json.dumps(stage(output=args.output,source_json=args.source_json,provisional=args.provisional,
        capture_dir=args.capture_dir),indent=2))
