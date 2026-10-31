"""Verified class item-listview capture -> isolated canonical SQLite stage.

Source capture validation is shared with Warrior; class eligibility is NEVER
inferred from equipment proficiencies or other classes. A verified export
proves its declared per-band IDs, not upstream Wowhead completeness; a raw
adaptive capture is stronger because it verifies captured HTML/listview bytes.
"""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from src.rulesets.forever.items.wowhead_queries import CANONICAL_CLASS_QUERIES
from src.rulesets.forever.items.source_capture_integrity import (
    verify_class_capture, verify_class_item_export,
)
from src.rulesets.forever.items.wowhead_capture_import import item_record_from_listview
from src.rulesets.forever.items.catalogue import ItemCatalogue
from src.rulesets.forever.items.runtime_selection import _DEFAULT_DB, source_class_item_membership_verified


def _verified_source_membership(class_key: str, source_json: Path | None,
                                capture_dir: Path | None):
    """One provenance envelope for both verified source capture formats."""
    if capture_dir is not None:
        capture_dir=Path(capture_dir)
        capture=verify_class_capture(capture_dir,class_key)
        records=[item_record_from_listview(row,captured_at=capture.captured_at)
                 for row in capture.base_rows.values()]
        return (capture.provenance_by_id,'VERIFIED_CLASS_LISTVIEW_CAPTURE',
                (capture_dir/'manifest.json').read_bytes(),records)
    source_json=Path(source_json)
    return (verify_class_item_export(source_json,class_key),
            'VERIFIED_CLASS_LISTVIEW_EXPORT',source_json.read_bytes(),[])


def stage_class_capture(*, class_key: str, output: Path,
                        source_json: Path | None = None,
                        capture_dir: Path | None = None,
                        canonical: Path = _DEFAULT_DB) -> dict:
    """Create a separate, source-attested SQLite snapshot, never edit canonical."""
    key=class_key.lower()
    if key not in CANONICAL_CLASS_QUERIES:
        raise ValueError('UNKNOWN_SOURCE_CLASS_QUERY')
    if (source_json is None)==(capture_dir is None):
        raise ValueError('SELECT_ONE_VERIFIED_CAPTURE_SOURCE')
    output=Path(output);canonical=Path(canonical)
    if output.resolve()==canonical.resolve() or output.exists():
        raise ValueError('REFUSE_OVERWRITE_SOURCE_OR_STAGED_SQLITE')
    class_id=CANONICAL_CLASS_QUERIES[key].class_id
    memberships,source_kind,source_bytes,new_records=_verified_source_membership(key,source_json,capture_dir)
    if not memberships:
        raise ValueError('EMPTY_SOURCE_CLASS_MEMBERSHIP')
    output.parent.mkdir(parents=True,exist_ok=True)
    try:
        with sqlite3.connect(f'file:{canonical.resolve()}?mode=ro',uri=True) as original,sqlite3.connect(output) as db:
            original.backup(db)
            db.execute('DELETE FROM item_class_eligibility WHERE class_id=?',(class_id,))
            db.commit()
        if new_records:
            with ItemCatalogue(output) as cat:
                cat.upsert_items(new_records)
        with sqlite3.connect(output) as db:
            known={int(row[0]) for row in db.execute('SELECT item_id FROM items')}
            if set(memberships)-known:
                raise ValueError('SOURCE_CLASS_ITEMS_MISSING_CANONICAL_ROWS')
            entries=[(iid,class_id,provenance) for iid,provenance in sorted(memberships.items())]
            db.executemany('INSERT INTO item_class_eligibility(item_id,class_id,provenance) VALUES(?,?,?)',entries)
            db.execute('''CREATE TABLE IF NOT EXISTS class_source_attestation
                (class_id INTEGER PRIMARY KEY,source_kind TEXT NOT NULL,
                 source_sha256 TEXT NOT NULL,member_count INTEGER NOT NULL,
                 verified INTEGER NOT NULL,membership_sha256 TEXT NOT NULL)''')
            membership_bytes=''.join(f'{iid}\t{provenance}\n' for iid,_,provenance in entries).encode()
            db.execute('''INSERT OR REPLACE INTO class_source_attestation
                (class_id,source_kind,source_sha256,member_count,verified,membership_sha256)
                VALUES(?,?,?,?,?,?)''',(class_id,source_kind,sha256(source_bytes).hexdigest(),
                    len(entries),1,sha256(membership_bytes).hexdigest()))
            db.commit()
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                raise ValueError('STAGED_SQLITE_INTEGRITY_FAILURE')
        if not source_class_item_membership_verified(key,output):
            raise ValueError('STAGED_SOURCE_CLASS_ATTESTATION_FAILED')
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    return {'class_key':key,'class_id':class_id,'source_kind':source_kind,
            'source_membership_count':len(memberships),'membership_verified_complete':True,
            'staged_path':str(output),'canonical_sha256':sha256(canonical.read_bytes()).hexdigest(),
            'staged_sha256':sha256(output.read_bytes()).hexdigest(),
            'source_sha256':sha256(source_bytes).hexdigest(),'sqlite_integrity':'ok',
            'p3_pass':False,'reason':'SOURCE_MEMBERSHIP_ONLY_REQUIRES_L0_TOP5_L2_AND_SEARCH'}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--class-key',required=True,choices=sorted(CANONICAL_CLASS_QUERIES))
    parser.add_argument('--output',required=True,type=Path)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--source-json',type=Path)
    group.add_argument('--capture-dir',type=Path)
    args=parser.parse_args()
    print(json.dumps(stage_class_capture(class_key=args.class_key,output=args.output,
        source_json=args.source_json,capture_dir=args.capture_dir),indent=2))
