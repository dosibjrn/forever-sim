#!/usr/bin/env python3
"""Run exact-ID Forever detail recapture on an isolated SQLite copy.

This gate NEVER promotes evidence to canonical data: raw HTML is not typed
semantics. It fails closed until the downstream semantic/IR/executor gate exists.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.plan_forever_ability_repair import plan
from tools.parse_verified_detail_to_staging import (
    SourceRepairBlocked, parse_into_staging)
from tools.compare_staged_ability_search import compare
from tools.capture_forever_abilities_sqlite import (read_verified_spell_detail_snapshot,
    MissingVerifiedSpellDetail)


def _verify_existing_staging_lineage(canonical: Path, staging: Path) -> None:
    """A fetched stage must still match current canonical outside detail evidence.

    A standalone stage from another machine/agent must never silently become
    a new base. The capture tool's details-only mode edits only the two detail
    tables; any other changed row or schema requires explicit rebase.
    """
    excluded={'spell_details','spell_detail_snapshots'}
    paths=(f'file:{canonical}?mode=ro',f'file:{staging}?mode=ro')
    with sqlite3.connect(paths[0],uri=True) as source,sqlite3.connect(paths[1],uri=True) as stage:
        for db in (source,stage):
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                raise ValueError('STAGING_LINEAGE_INVALID_SQLITE')
            if db.execute('PRAGMA foreign_key_check').fetchone() is not None:
                raise ValueError('STAGING_LINEAGE_FOREIGN_KEYS_INVALID')
        schema_query="SELECT type,name,sql FROM sqlite_master WHERE type IN ('table','index','trigger','view') AND name NOT LIKE 'sqlite_%' ORDER BY type,name"
        if source.execute(schema_query).fetchall()!=stage.execute(schema_query).fetchall():
            raise ValueError('STAGING_LINEAGE_SCHEMA_DRIFT')
        names=[r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for name in names:
            if name in excluded:
                continue
            # All identifiers come from canonical sqlite_master, never user input.
            quoted='"'+name.replace('"','""')+'"'
            sql=f'SELECT * FROM {quoted} ORDER BY rowid'
            if source.execute(sql).fetchall()!=stage.execute(sql).fetchall():
                raise ValueError(f'STAGING_LINEAGE_DATA_DRIFT:{name}')


def execute(*, class_key: str, level: int, canonical: Path, staging: Path,
            runner=subprocess.run, spell_ids: tuple[int,...] | None = None,
            runtime_scenario: dict | None = None,
            offline: bool = False,
            reuse_staging: bool = False) -> dict:
    canonical, staging = Path(canonical).resolve(), Path(staging).resolve()
    if canonical == staging:
        raise ValueError('staging database must differ from canonical database')
    if reuse_staging and not offline:
        raise ValueError('reuse_staging requires offline=True; never fetch into an existing stage')
    if reuse_staging:
        if not staging.is_file():
            raise FileNotFoundError(f'offline staging SQLite not found: {staging}')
    elif staging.exists():
        raise FileExistsError(f'refuse to overwrite staging database: {staging}')
    proposed = plan(class_key=class_key, level=level, db_path=canonical)
    ids = proposed['detail_capture_spell_ids'] if spell_ids is None else list(spell_ids)
    if spell_ids is not None:
        if not ids or len(set(ids))!=len(ids) or any(int(x)<=0 for x in ids):
            raise ValueError('invalid explicitly requested spell IDs')
        with sqlite3.connect(f'file:{canonical}?mode=ro',uri=True) as db:
            available={int(x[0]) for x in db.execute('''SELECT spell_id FROM spell_index
                WHERE batch_id=? AND class_key=? AND kind='abilities'
                  AND level_hint<=?''',(proposed['batch_id'],class_key.lower(),level))}
        if set(ids)-available:
            raise ValueError(f'not source-indexed and level-legal: {sorted(set(ids)-available)}')
    result = {'class_key':class_key, 'level':level, 'requested_ids':ids,
              'staging':str(staging), 'canonical':str(canonical),
              'promoted':False, 'status':'NOT_RUN'}
    if not ids:
        result['status']='NO_DETAIL_REPAIRS_PLANNED'
        return result
    staging.parent.mkdir(parents=True, exist_ok=True)
    if reuse_staging:
        try:
            _verify_existing_staging_lineage(canonical,staging)
        except (ValueError,sqlite3.Error) as exc:
            result['status']='STAGING_LINEAGE_MISMATCH'
            result['blocker']=str(exc)
            return result
    else:
        # SQLite online backup, rather than file-copy, respects WAL and live pages.
        with sqlite3.connect(f'file:{canonical}?mode=ro',uri=True) as source, sqlite3.connect(staging) as target:
            source.backup(target)
    result['offline']=bool(offline)
    result['reused_staging']=bool(reuse_staging)
    if offline:
        # Reuse snapshots already present in the SQLite backup. In particular,
        # never call a capture subprocess or treat unavailable evidence as a
        # best-effort source of made-up mechanics.
        result['command']=None
        result['fetch_exit_code']=None
    else:
        command = [sys.executable,str(Path(__file__).resolve().parent/'capture_forever_abilities_sqlite.py'),
                   '--db',str(staging),'--batch-id',proposed['batch_id'],
                   '--details-only','--spell-ids',*[str(x) for x in ids]]
        result['command']=command
        try:
            completed=runner(command, capture_output=True, text=True, timeout=180)
            result['fetch_exit_code']=completed.returncode
            result['fetch_stdout_tail']=completed.stdout[-2000:]
            result['fetch_stderr_tail']=completed.stderr[-2000:]
        except (OSError,subprocess.TimeoutExpired) as exc:
            result['status']='SOURCE_FETCH_FAILED'
            result['error']=str(exc)
            return result
        if completed.returncode:
            result['status']='SOURCE_FETCH_FAILED'
            return result
    verified=[]; missing=[]
    with sqlite3.connect(f'file:{staging}?mode=ro',uri=True) as db:
        integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
        if integrity != 'ok':
            result['status']='STAGING_SQLITE_CORRUPT'; result['integrity']=integrity
            return result
        for sid in ids:
            try:
                read_verified_spell_detail_snapshot(db,batch_id=proposed['batch_id'],spell_id=sid)
                verified.append(sid)
            except MissingVerifiedSpellDetail:
                missing.append(sid)
    result.update(verified_ids=verified,missing_ids=missing)
    result['status']=('OFFLINE_VERIFIED_HTML_MISSING' if offline else 'SOURCE_INCOMPLETE') if missing else 'EVIDENCE_CAPTURED_SEMANTICS_NOT_VALIDATED'
    if not missing and runtime_scenario is not None:
        try:
            repairs=parse_into_staging(staging,spell_ids=tuple(ids))
            result['typed_repairs']=repairs
            result['runtime_gate']=compare(canonical_db=canonical,staged_db=staging,
                class_key=class_key,level=level,**runtime_scenario)
            result['status']='STAGING_REAL_POLICY_SEARCH_VALIDATED_NOT_PROMOTED'
        except (SourceRepairBlocked,ValueError) as exc:
            result['status']='STAGING_SEMANTIC_OR_RUNTIME_BLOCKED'
            result['blocker']=str(exc)
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--class-key',required=True)
    p.add_argument('--level',type=int,required=True)
    p.add_argument('--db',type=Path,required=True)
    p.add_argument('--staging',type=Path,required=True)
    p.add_argument('--spell-ids',type=int,nargs='+')
    p.add_argument('--offline',action='store_true',help='Never fetch: use only previously captured and verified HTML snapshots')
    p.add_argument('--reuse-staging',action='store_true',help='Offline only: process an existing fetched stage after checking canonical lineage; never overwrite')
    p.add_argument('--runtime-scenario-json',type=Path,
                   help='Explicit bounded real policy-search scenario; does not promote to canonical')
    a=p.parse_args(argv)
    scenario=(json.loads(a.runtime_scenario_json.read_text())
              if a.runtime_scenario_json else None)
    r=execute(class_key=a.class_key,level=a.level,canonical=a.db,staging=a.staging,
        spell_ids=tuple(a.spell_ids) if a.spell_ids else None,
        runtime_scenario=scenario,offline=a.offline,reuse_staging=a.reuse_staging)
    print(json.dumps(r,indent=2,ensure_ascii=False))
    return 0 if r['status'] in ('EVIDENCE_CAPTURED_SEMANTICS_NOT_VALIDATED','STAGING_REAL_POLICY_SEARCH_VALIDATED_NOT_PROMOTED') else 2

if __name__=='__main__':
    raise SystemExit(main())
