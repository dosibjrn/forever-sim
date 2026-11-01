"""Nine-class acquisition coverage gate (NOT a playable route validator)."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
import sys

# Direct-file CLI must resolve the same source packages as module invocation.
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.game.data.forever.registry import registered_class_keys, build_game_ir_slice
from src.game.data.forever.source_acquisition import audit_learned_action_legality
from src.game.data.forever.sqlite_talents import DEFAULT_DB


def audit(*, level: int = 20, db_path: Path = DEFAULT_DB) -> dict:
    with sqlite3.connect(f'file:{db_path.resolve()}?mode=ro', uri=True) as db:
        db.row_factory=sqlite3.Row
        rows=db.execute('SELECT class_key,evidence_status,methods_observed_json FROM ability_acquisition_evidence').fetchall()
    classes={}
    for cls in registered_class_keys():
        ir=build_game_ir_slice(class_key=cls,level=level,ability_db_path=db_path)
        if ir is None:
            classes[cls]={'status':'NO_SOURCE_IR_AT_LEVEL'}
            continue
        report=audit_learned_action_legality(ir,level=level,
            action_ids=[a.id for a in ir.actions],db_path=db_path)
        classes[cls]={'indexed_evidence_rows':sum(r['class_key']==cls for r in rows),
                      'ir_actions':len(ir.actions),
                      'verified_world_acquisition_actions':report['verified_world_acquisition_count'],
                      'blocked_reason_counts':dict(Counter(r['status'] for r in report['blockers']))}
    return {'source_indexed_acquisition_rows':len(rows),
            'evidence_status_counts':dict(Counter(r['evidence_status'] for r in rows)),
            'observed_method_counts':dict(Counter(key for r in rows for key in json.loads(r['methods_observed_json']))),
            'source_verified_world_acquisition_actions':0,
            'class_level_fully_validated_checkpoints':0,
            'true_world_routes':0,
            'level':level,'classes':classes,
            'interpretation':'method observations are not acquired spells; no world legality proof'}

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--level',type=int,default=20)
    parser.add_argument('--db',type=Path,default=DEFAULT_DB)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    result=audit(level=args.level,db_path=args.db)
    data=json.dumps(result,indent=2,sort_keys=True)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(data)
    print(data)
