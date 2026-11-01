#!/usr/bin/env python3
"""Resume-safe nine-class bulk source capture, using the EXISTING Wowhead fetcher.

A browser/source-capture utility, never part of combat runtime. The input
canonical database is immutable; only a separate stage gets HTML snapshots.
Every row is selected by source spell ID from the complete canonical index.
The stage is rebase-checked before resuming, including all non-detail tables.
Partial successes survive failed browser runs; nothing becomes executable.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time

# A direct `python tools/wf292_batch_verified_source_recovery.py` starts with
# tools/ on sys.path. Resolve the canonical source packages without PYTHONPATH.
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.run_forever_ability_repair import _verify_existing_staging_lineage
from src.v2.source_sqlite_detail_snapshots import (
    MissingVerifiedSpellDetail, read_verified_spell_detail_snapshot)

FETCHER = Path(__file__).with_name('capture_forever_abilities_sqlite.py')


def _index(db: sqlite3.Connection) -> list[dict]:
    db.row_factory=sqlite3.Row
    batches=db.execute('''SELECT l.class_key,l.batch_id FROM capture_lists l
        JOIN capture_batches b ON b.batch_id=l.batch_id
        WHERE l.kind='abilities' AND l.complete=1 AND b.status='complete'
        ORDER BY l.class_key''').fetchall()
    if len(batches)!=9 or len({r['class_key'] for r in batches})!=9:
        raise ValueError('REQUIRES_NINE_INDEPENDENT_COMPLETE_CLASS_INDEXES')
    rows=[dict(r) for r in db.execute('''SELECT i.class_key,i.batch_id,i.spell_id,i.level_hint,
        i.source_url FROM spell_index i JOIN capture_lists l ON
        l.batch_id=i.batch_id AND l.class_key=i.class_key AND l.kind=i.kind
        WHERE i.kind='abilities' AND l.complete=1 ORDER BY i.class_key,i.spell_id''')]
    if not rows or len(rows)!=len({(r['class_key'],r['spell_id']) for r in rows}):
        raise ValueError('MISSING_OR_AMBIGUOUS_SOURCE_INDEX')
    return rows


def inventory(db_path:Path, *, chunk_size:int=100, max_level:int=60) -> dict:
    if chunk_size<1 or chunk_size>250 or max_level<1 or max_level>60:
        raise ValueError('INVALID_BATCH_LIMIT')
    with sqlite3.connect(f'file:{db_path.resolve()}?mode=ro',uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise ValueError('SOURCE_SQLITE_CORRUPT')
        indexed=_index(db)
        verified=set()
        verified_pages=set()
        for row in indexed:
            try:
                read_verified_spell_detail_snapshot(db,batch_id=row['batch_id'],spell_id=row['spell_id'])
                verified.add((row['class_key'],row['spell_id']))
                verified_pages.add((row['batch_id'],row['spell_id']))
            except MissingVerifiedSpellDetail:
                pass
        pending=[r for r in indexed if (r['class_key'],r['spell_id']) not in verified
                 and (r['level_hint'] is None or r['level_hint']<=max_level)]
        # Source-index priority: early-level coverage across ALL classes before
        # later ranks; no fixed spell/rank/class priority list.
        pending.sort(key=lambda r:(r['level_hint'] if r['level_hint'] is not None else 61,
                                   r['class_key'],r['spell_id']))
        # Multiple classes share some source spell IDs. The HTML evidence is
        # keyed by (batch_id, spell_id), NOT by class. Fetch each unique page
        # exactly once; the source coverage ledger still counts every class
        # row independently. This removes 61 redundant page fetches here.
        seen_pages=set();unique_pending=[]
        for row in pending:
            key=(row['batch_id'],row['spell_id'])
            if key not in seen_pages:
                seen_pages.add(key);unique_pending.append(row)
        chunks=[]
        # The canonical fetcher uses a batch ID for all selected source spell IDs.
        # Partition into bounded browser sessions to preserve successes on failure.
        for i in range(0,len(unique_pending),chunk_size):
            part=unique_pending[i:i+chunk_size]
            for batch in sorted({r['batch_id'] for r in part}):
                rows=[r for r in part if r['batch_id']==batch]
                chunks.append({'batch_id':batch,'spell_ids':[r['spell_id'] for r in rows],
                    'class_counts':dict(Counter(r['class_key'] for r in rows))})
        return {'indexed':len(indexed),'verified_detail_before':len(verified),
                'verified_unique_pages_before':len(verified_pages),
                'pending':len(pending),'pending_unique_pages':len(unique_pending),
                'max_level':max_level,
                'by_class_pending':dict(Counter(r['class_key'] for r in pending)),
                'chunks':chunks,'source_database_sha256':sha256(db_path.read_bytes()).hexdigest(),
                'executable_promotions':0,'accepted_checkpoints':0,
                'note':'Verified HTML source evidence only, never executable mechanics.'}


def stage_from_canonical(canonical:Path,stage:Path, *,resume:bool) -> None:
    if canonical.resolve()==stage.resolve():
        raise ValueError('CANONICAL_MUST_NEVER_BE_CAPTURE_STAGE')
    if resume:
        if not stage.is_file():
            raise FileNotFoundError('NO_EXISTING_STAGE_TO_RESUME')
        _verify_existing_staging_lineage(canonical,stage)
    else:
        if stage.exists():
            raise FileExistsError('REFUSE_TO_OVERWRITE_EXISTING_STAGE')
        stage.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(f'file:{canonical.resolve()}?mode=ro',uri=True) as src,sqlite3.connect(stage) as dest:
            src.backup(dest)



def typed_ingest_stage(*,source_stage:Path,typed_stage:Path)->dict:
    """Materialize verified HTML -> typed source facts in a DIFFERENT stage.

    The original fetch stage remains clean and resumable. No runtime or
    canonical database is mutated. Existing ingestion modules own their data.
    """
    from tools.wf292_ingest_verified_detail_headers_sqlite import ingest as headers
    from tools.ingest_source_acquisition_evidence_sqlite import ingest as acquisition
    from tools.ingest_source_acquisition_entities_sqlite import ingest as entities
    from tools.ingest_source_index_effect_candidates_sqlite import ingest as effects
    from src.game.data.forever.source_effect_atoms import ingest as effect_atoms
    from src.game.data.forever.source_stat_aura_candidates import ingest as stat_auras
    from src.game.data.forever.source_verified_detail_effects import ingest as verified_detail_effects
    source_stage,typed_stage=Path(source_stage),Path(typed_stage)
    if typed_stage.resolve()==source_stage.resolve():
        raise ValueError('TYPED_STAGE_MUST_DIFFER_FROM_FETCH_STAGE')
    if typed_stage.exists():
        raise FileExistsError('REFUSE_TO_OVERWRITE_TYPED_STAGE')
    typed_stage.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(f'file:{source_stage.resolve()}?mode=ro',uri=True) as src,sqlite3.connect(typed_stage) as dest:
        src.backup(dest)
    # A failure leaves an explicitly incomplete, never-promoted typed stage;
    # all individual ingesters are transactional. It can be deleted and rerun.
    results={'verified_headers':headers(typed_stage,quarantine_structural_errors=True),
             'acquisition':acquisition(typed_stage),
             'entities':entities(typed_stage),
             'effect_candidates':effects(typed_stage),
             'source_effect_atoms':effect_atoms(typed_stage),
             'source_stat_aura_candidates':stat_auras(typed_stage),
             'verified_detail_effect_slots':verified_detail_effects(typed_stage,quarantine_structural_errors=True)}
    with sqlite3.connect(typed_stage) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise ValueError('TYPED_STAGE_SQLITE_CORRUPT')
    return {'status':'TYPED_SOURCE_EVIDENCE_NOT_EXECUTABLE',
            'typed_stage':str(typed_stage),'ingested':results,
            'executable_promotions':0,'accepted_checkpoints':0}


def execute(*,canonical:Path,stage:Path,chunk_size:int=100,max_level:int=60,
            max_chunks:int|None=None,resume:bool=False,offline:bool=False,
            runner=subprocess.run,timeout_s:int=1800,session_chunks:int=4,detail_workers:int=4) -> dict:
    if max_chunks is not None and max_chunks<0:
        raise ValueError('INVALID_MAX_CHUNKS')
    if session_chunks < 1 or session_chunks > 12:
        raise ValueError('INVALID_SESSION_CHUNKS')
    if detail_workers < 1 or detail_workers > 8:
        raise ValueError('INVALID_DETAIL_WORKERS')
    canonical,stage=Path(canonical),Path(stage)
    stage_from_canonical(canonical,stage,resume=resume)
    before=inventory(stage,chunk_size=chunk_size,max_level=max_level)
    if offline:
        return {'status':'OFFLINE_SOURCE_INVENTORY_ONLY','before':before,
                'stage':str(stage),'attempted_chunks':0,'verified_new':0}
    completed=[]; sessions=[]
    selected=before['chunks'][:max_chunks]
    # One persistent authenticated browser per bounded session, not one launch
    # per batch/class. The existing fetcher's per-spell transactions preserve
    # successfully captured HTML if a later page or entire session fails.
    for offset in range(0,len(selected),session_chunks):
        group=selected[offset:offset+session_chunks]
        plan={'schema':'forever_detail_session_v1',
              'chunks':[{'batch_id':c['batch_id'],'spell_ids':c['spell_ids']}
                        for c in group]}
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',suffix='.json',
                 prefix='.forever_detail_session_',dir=stage.parent,delete=False) as fh:
            json.dump(plan,fh,sort_keys=True)
            plan_path=Path(fh.name)
        argv=[sys.executable,str(FETCHER),'--db',str(stage),
              '--details-only','--detail-plan',str(plan_path),
              '--detail-workers',str(detail_workers)]
        start=time.monotonic()
        try:
            result=runner(argv,capture_output=True,text=True,
                          timeout=timeout_s*len(group))
            status='FETCH_OK' if result.returncode==0 else 'FETCH_NONZERO'
            stdout=result.stdout[-2000:];stderr=result.stderr[-2000:]
        except (OSError,subprocess.TimeoutExpired) as exc:
            status='FETCH_FAILED_OR_TIMED_OUT';stdout='';stderr=str(exc)
        finally:
            plan_path.unlink(missing_ok=True)
        elapsed=round(time.monotonic()-start,3)
        # Regardless of subprocess exit, independently verify every page. A
        # browser crash after 99 pages must not discard those 99 snapshots.
        with sqlite3.connect(f'file:{stage.resolve()}?mode=ro',uri=True) as db:
            for chunk in group:
                successes=[]
                for sid in chunk['spell_ids']:
                    try:read_verified_spell_detail_snapshot(db,batch_id=chunk['batch_id'],spell_id=sid)
                    except MissingVerifiedSpellDetail:pass
                    else:successes.append(sid)
                completed.append({'status':status,'batch_id':chunk['batch_id'],
                    'requested':len(chunk['spell_ids']), 'verified':len(successes),
                    'spell_ids_verified':successes, 'session_index':len(sessions),
                    'elapsed_session_wall_s':elapsed})
        sessions.append({'status':status,'chunks':len(group),
            'requested':sum(len(c['spell_ids']) for c in group),
            'elapsed_wall_s':elapsed,'stdout_tail':stdout,'stderr_tail':stderr})
    after=inventory(stage,chunk_size=chunk_size,max_level=max_level)
    _verify_existing_staging_lineage(canonical,stage)
    return {'status':'SOURCE_HTML_CAPTURE_WIP_NOT_EXECUTABLE',
            'before':{k:v for k,v in before.items() if k!='chunks'},
            'after':{k:v for k,v in after.items() if k!='chunks'},
            'chunks':completed,'sessions':sessions,'attempted_chunks':len(completed),
            'browser_sessions':len(sessions),'detail_workers':detail_workers,
            'verified_new':after['verified_detail_before']-before['verified_detail_before'],
            'verified_new_unique_pages':after['verified_unique_pages_before']-before['verified_unique_pages_before'],
            'source_db_unchanged_sha256':sha256(canonical.read_bytes()).hexdigest(),
            'stage':str(stage),'accepted_checkpoints':0,'executable_promotions':0}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,required=True)
    p.add_argument('--staging',type=Path,required=True)
    p.add_argument('--chunk-size',type=int,default=100)
    p.add_argument('--max-level',type=int,default=60)
    p.add_argument('--max-chunks',type=int)
    p.add_argument('--detail-workers',type=int,default=4,
                   help='Independent source pages per persistent browser, 1-8')
    p.add_argument('--session-chunks',type=int,default=4,
                   help='Bounded source-index chunks per authenticated browser session')
    p.add_argument('--resume',action='store_true')
    p.add_argument('--offline',action='store_true')
    p.add_argument('--typed-staging',type=Path,help='New separate SQLite for typed source ingest; never canonical')
    p.add_argument('--output',type=Path)
    a=p.parse_args()
    result=execute(canonical=a.db,stage=a.staging,chunk_size=a.chunk_size,
        max_level=a.max_level,max_chunks=a.max_chunks,resume=a.resume,offline=a.offline,
        session_chunks=a.session_chunks,detail_workers=a.detail_workers)
    if a.typed_staging:
        result['typed_ingestion']=typed_ingest_stage(source_stage=a.staging,
            typed_stage=a.typed_staging)
    s=json.dumps(result,indent=2,sort_keys=True)
    if a.output:
        a.output.parent.mkdir(parents=True,exist_ok=True)
        a.output.write_text(s+'\n')
    print(s)

if __name__=='__main__':main()
