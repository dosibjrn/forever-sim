#!/usr/bin/env python3
"""Produce exact source repair IDs and safe preexisting-fetcher commands.

This is an audit/repair PLAN, not a successful fetch or semantic ingestion.
The existing capture script is deliberately run out-of-band, with an isolated
SQLite copy and explicit --details-only --spell-ids; no silent fallback.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from src.game.data.forever.source_ability_repair import repair_queue
from src.game.data.forever.sqlite_talents import DEFAULT_DB


def plan(*,class_key:str,level:int,db_path:Path=DEFAULT_DB)->dict:
    result=repair_queue(class_key=class_key,level=level,db_path=db_path)
    # Spells indexed but missing *parsed executable facts* need source evidence.
    # Details cannot repair malformed LISTVIEW data: refetch the full listing.
    ids=[x['spell_id'] for x in result['repairs'] if x['stage']=='SEMANTIC_FACTS_MISSING']
    result['detail_capture_spell_ids']=ids
    result['existing_fetcher']={
        'script':'tools/capture_forever_abilities_sqlite.py',
        'batch_id':result['batch_id'],
        'details_only':True,
        'spell_ids':ids,
        'command_argv':(['python','tools/capture_forever_abilities_sqlite.py',
            '--db',str(db_path),'--batch-id',result['batch_id'],
            '--details-only','--spell-ids']+[str(x) for x in ids]) if ids else [],
        'safety':'Run only on a staging SQLite copy; then validate source facts and IR before promoting.'}
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--class-key',required=True)
    p.add_argument('--level',type=int,required=True)
    p.add_argument('--db',type=Path,default=DEFAULT_DB)
    p.add_argument('--output',type=Path)
    a=p.parse_args()
    report=plan(class_key=a.class_key,level=a.level,db_path=a.db)
    result=json.dumps(report,ensure_ascii=False,indent=2)
    if a.output:a.output.write_text(result+'\n',encoding='utf-8')
    else:print(result)
    raise SystemExit(1 if report['repair_count'] else 0)
