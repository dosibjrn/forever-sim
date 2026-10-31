"""Service-owned Wowhead Forever ability/talent catalogue refresh.

Uses the existing tools.capture_forever_abilities_sqlite parser unchanged for
collection. Subprocess capture operates on an SQLite backup; only verified,
complete batches are atomically published to the canonical ability catalogue.
The canonical item database and optimizer publications are never changed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / 'state' / 'abilities_refresh'
CATALOGUE = ROOT / 'data' / 'forever' / 'catalogue' / 'forever_abilities.sqlite'
CLASSES = ('warrior', 'paladin', 'hunter', 'rogue', 'priest', 'shaman', 'mage', 'warlock', 'druid')
KINDS = ('abilities', 'talents')
ACTIVE = frozenset({'queued', 'capturing', 'verifying', 'publishing'})
_LOCK = threading.RLock()
_TASKS: dict[str, dict[str, Any]] = {}


def catalogue_status(db_path: Path | None = None) -> dict[str, Any]:
    """Read-only factual coverage; index != tooltip != engine modeling."""
    path = Path(db_path or CATALOGUE)
    if not path.is_file():
        return {'present': False, 'path': str(path), 'index_complete': False,
                'details_verified': 0, 'rows': 0, 'lists': 0}
    try:
        uri = path.resolve().as_uri() + '?mode=ro'
        # sqlite3's connection context manager does NOT close the handle.
        # Close explicitly: Windows cannot os.replace an open target SQLite.
        with closing(sqlite3.connect(uri, uri=True, timeout=1)) as db:
            db.row_factory = sqlite3.Row
            latest = db.execute('SELECT batch_id,captured_at,status FROM capture_batches '
                                'ORDER BY captured_at DESC,batch_id DESC LIMIT 1').fetchone()
            if latest is None:
                return {'present': True, 'path': str(path), 'index_complete': False,
                        'details_verified': 0, 'rows': 0, 'lists': 0}
            batch_id = str(latest['batch_id'])
            lists = [dict(row) for row in db.execute(
                'SELECT class_key,kind,expected_count,captured_count,complete '
                'FROM capture_lists WHERE batch_id=? ORDER BY class_key,kind', (batch_id,))]
            rows = db.execute('SELECT COUNT(*) FROM spell_index WHERE batch_id=?', (batch_id,)).fetchone()[0]
            total_ids = db.execute('SELECT COUNT(DISTINCT spell_id) FROM spell_index WHERE batch_id=?', (batch_id,)).fetchone()[0]
            has_snapshots = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='spell_detail_snapshots'").fetchone() is not None
            verified = db.execute('''SELECT COUNT(*) FROM spell_details d
                JOIN spell_detail_snapshots s ON s.batch_id=d.batch_id AND s.spell_id=d.spell_id
                WHERE d.batch_id=? AND d.details_verified=1''', (batch_id,)).fetchone()[0] if has_snapshots else 0
            legacy_details = db.execute('SELECT COUNT(*) FROM spell_details WHERE batch_id=? AND details_verified=1',
                                        (batch_id,)).fetchone()[0] - verified
            coverage = all(x['complete'] and int(x['captured_count']) == int(x['expected_count'])
                           for x in lists) if len(lists) == len(CLASSES) * len(KINDS) else False
            return {'present': True, 'path': str(path), 'batch_id': batch_id,
                    'captured_at': latest['captured_at'], 'status': latest['status'],
                    'index_complete': bool(coverage and latest['status'] == 'complete'),
                    'lists': len(lists), 'expected_lists': len(CLASSES)*len(KINDS),
                    'rows': int(rows), 'unique_spells': int(total_ids),
                    'details_verified': int(verified), 'details_remaining': int(total_ids - verified),
                    'legacy_details_without_snapshot': int(legacy_details),
                    'per_class': lists, 'engine_modeled': False,
                    'warning': 'Raw source index. Talent-tree geometry and executable effects NOT asserted.'}
    except (sqlite3.Error, OSError, ValueError) as exc:
        return {'present': True, 'path': str(path), 'error': f'{type(exc).__name__}: {exc}',
                'index_complete': False, 'rows': 0, 'lists': 0, 'details_verified': 0}


def _status_file(task_id: str) -> Path:
    return STATE_DIR / f'{task_id}.json'


def _write(task_id: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_DIR / f'{task_id}.json.tmp'
    tmp.write_text(json.dumps(_TASKS[task_id], indent=2, sort_keys=True) + '\n', encoding='utf-8')
    os.replace(tmp, _status_file(task_id))


def _set(task_id: str, **fields: Any) -> None:
    with _LOCK:
        _TASKS[task_id].update(fields)
        _TASKS[task_id]['updated_at'] = time.time()
        _write(task_id)


def _historical(task_id: str) -> dict[str, Any] | None:
    path = _status_file(task_id)
    try:
        obj = json.loads(path.read_text(encoding='utf-8'))
        if obj.get('state') in ACTIVE:
            obj['state'] = 'interrupted'
            obj['error'] = 'Service restarted before refresh finished; canonical catalogue unchanged.'
        return obj
    except (OSError, ValueError):
        return None


def _progress(task: dict[str, Any]) -> dict[str, Any] | None:
    if task.get('state') not in ACTIVE:
        return None
    log = task.get('log_file')
    if not log:
        return {'done': 0, 'total': 20 if task.get('mode') == 'details' else 18}
    try:
        # Read only a bounded tail of the capture log, not an entire large detail run.
        with open(log, 'rb') as inp:
            inp.seek(0, os.SEEK_END)
            length = inp.tell()
            inp.seek(max(0, length - 32768))
            lines = inp.read().decode('utf-8', errors='replace').splitlines()
    except OSError:
        return None
    if task.get('mode') == 'index':
        done = sum(1 for line in lines if line.lstrip().startswith('{"class":'))
        phase = next((x.strip() for x in reversed(lines) if x.startswith('FETCH ')), None)
        return {'done': min(done, 18), 'total': 18, 'last_step': phase}
    detail_lines = [x.strip() for x in lines if re.search(r'\bdetail\s+\d+/\d+', x)]
    last = detail_lines[-1] if detail_lines else None
    match = re.search(r'\bdetail\s+(\d+)/(\d+)', last or '')
    return {'done': int(match.group(1)) if match else 0,
            'total': int(match.group(2)) if match else int(task.get('max_details') or 0),
            'last_step': last}


def _public_task(task: dict[str, Any] | None) -> dict[str, Any] | None:
    if task is None:
        return None
    result = dict(task)
    progress = _progress(result)
    if progress is not None:
        result['progress'] = progress
    return result


def get_refresh(task_id: str) -> dict[str, Any] | None:
    with _LOCK:
        return _public_task(_TASKS[task_id] if task_id in _TASKS else _historical(task_id))


def latest_refresh() -> dict[str, Any] | None:
    with _LOCK:
        live = max(_TASKS.values(), key=lambda x: float(x.get('created_at', 0)), default=None)
        historical = []
        if STATE_DIR.exists():
            historical = [p for p in STATE_DIR.glob('*.json') if p.is_file()]
        disk = _historical(max(historical, key=lambda p: p.stat().st_mtime).stem) if historical else None
        if disk and (not live or float(disk.get('created_at', 0)) > float(live.get('created_at', 0))):
            return _public_task(disk)
        return _public_task(live)


def _backup_db(target: Path, staging: Path) -> None:
    if staging.exists():
        staging.unlink()
    if target.is_file():
        with closing(sqlite3.connect(f'{target.resolve().as_uri()}?mode=ro', uri=True)) as source:
            with closing(sqlite3.connect(staging)) as dest:
                source.backup(dest)
    else:
        # The canonical fetcher initializes the schema on first capture.
        staging.parent.mkdir(parents=True, exist_ok=True)


def _check_staging(staging: Path, batch_id: str, mode: str, *, previous_details: int) -> dict[str, Any]:
    """Validate exact batch and all class lists before publishing any bytes."""
    with closing(sqlite3.connect(staging)) as db:
        if db.execute('PRAGMA quick_check').fetchone() != ('ok',):
            raise ValueError('staging SQLite quick_check failed')
        batch = db.execute('SELECT status FROM capture_batches WHERE batch_id=?', (batch_id,)).fetchone()
        if batch != ('complete',):
            raise ValueError(f'capture batch {batch_id} not complete')
        rows = db.execute('SELECT class_key,kind,expected_count,captured_count,complete '
                          'FROM capture_lists WHERE batch_id=?', (batch_id,)).fetchall()
        if len(rows) != len(CLASSES)*len(KINDS) or any(
                not complete or expected is None or expected != captured or captured <= 0
                for _, _, expected, captured, complete in rows):
            raise ValueError('incomplete class list coverage; active catalogue protected')
        indexed = db.execute('SELECT COUNT(*) FROM spell_index WHERE batch_id=?', (batch_id,)).fetchone()[0]
        has_snapshots = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='spell_detail_snapshots'").fetchone() is not None
        verified = db.execute('''SELECT COUNT(*) FROM spell_details d
            JOIN spell_detail_snapshots s ON s.batch_id=d.batch_id AND s.spell_id=d.spell_id
            WHERE d.batch_id=? AND d.details_verified=1''', (batch_id,)).fetchone()[0] if has_snapshots else 0
        if mode == 'details' and not has_snapshots:
            raise ValueError('detail capture did not provide independently verifiable HTML snapshots')
        if mode == 'details' and db.execute('''SELECT COUNT(*) FROM spell_detail_snapshots s
            LEFT JOIN spell_details d ON d.batch_id=s.batch_id AND d.spell_id=s.spell_id
            WHERE s.batch_id=? AND (d.spell_id IS NULL OR d.details_verified!=1)''',
            (batch_id,)).fetchone()[0]:
            raise ValueError('detail snapshots contain unverified or orphan rows')
        if indexed < len(rows):
            raise ValueError('no source spell rows in staging')
        if mode == 'details' and verified < previous_details:
            raise ValueError('detail capture regressed verified coverage')
        if mode == 'details':
            # Verify the actual bytes, not merely presence of a flag/row.
            from src.v2.source_sqlite_detail_snapshots import (
                materialize_spell_detail_snapshot, MissingVerifiedSpellDetail,
            )
            spell_ids = [int(r[0]) for r in db.execute(
                'SELECT spell_id FROM spell_detail_snapshots WHERE batch_id=?', (batch_id,))]
            for spell_id in spell_ids:
                try:
                    materialize_spell_detail_snapshot(staging, batch_id=batch_id, spell_id=spell_id)
                except MissingVerifiedSpellDetail as exc:
                    raise ValueError(f'HTML snapshot {spell_id} failed independent verification: {exc}') from exc
    return {'batch_id': batch_id, 'lists': len(rows), 'rows': indexed,
            'details_verified': verified, 'new_details': verified - previous_details}


def _run(task_id: str, mode: str, max_details: int | None) -> None:
    CAT = CATALOGUE
    stage = STATE_DIR / f'{task_id}.sqlite'
    log_path = STATE_DIR / f'{task_id}.log'
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        old = catalogue_status(CAT)
        if mode == 'details' and not old.get('index_complete'):
            raise ValueError('complete index required before fetching details')
        _backup_db(CAT, stage)
        batch_id = str(old.get('batch_id')) if mode == 'details' else (
            datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+task_id[:6])
        command = [sys.executable, str(ROOT / 'tools' / 'capture_forever_abilities_sqlite.py'),
                   '--db', str(stage), '--batch-id', batch_id,
                   '--channel', os.environ.get('WOWHEAD_BROWSER_CHANNEL','chrome'),
                   '--user-data-dir', str(Path(os.environ.get('WOWHEAD_CHROME_PROFILE',
                                                str(ROOT/'.wowhead-chrome-profile'))))]
        if mode == 'details':
            command += ['--resume', '--details']
            if max_details is not None:
                command += ['--max-details', str(max_details)]
        _set(task_id, state='capturing', log_file=str(log_path), batch_id=batch_id)
        with log_path.open('w', encoding='utf-8') as log:
            run = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                 text=True, check=False)
        # The fetcher returns 1 if some individual tooltip pages failed. A
        # verified subset is still useful and resumable; reject any such run
        # that did not produce a valid manifest or did not improve coverage.
        if run.returncode and mode != 'details':
            raise RuntimeError(f'Wowhead capture exited {run.returncode}; see log {log_path}')
        _set(task_id, state='verifying')
        validation = _check_staging(stage, batch_id, mode,
                                    previous_details=int(old.get('details_verified') or 0) if mode=='details' else 0)
        raw_manifest = STATE_DIR / f'wowhead_abilities_manifest_{batch_id}.json'
        if not raw_manifest.exists():
            raise ValueError('fetcher did not produce a manifest')
        manifest = json.loads(raw_manifest.read_text(encoding='utf-8'))
        if not manifest.get('index_complete'):
            raise ValueError('fetcher manifest reports incomplete index')
        detail_failures = int((manifest.get('detail_stats') or {}).get('failed') or 0)
        if run.returncode and (not detail_failures or validation['new_details'] <= 0):
            raise RuntimeError(f'detail capture exited {run.returncode} without verified progress; see {log_path}')
        if mode == 'details' and max_details and validation['new_details'] > max_details:
            raise ValueError('details captured beyond requested limit')
        manifest['sqlite'] = str(CAT)
        CAT.parent.mkdir(parents=True, exist_ok=True)
        manifest_dest = CAT.parent / f'wowhead_abilities_manifest_{batch_id}.json'
        manifest_tmp = manifest_dest.with_suffix('.json.tmp')
        manifest_tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
        _set(task_id, state='publishing')
        # No concurrent writer uses this DB; capture only writes a private staging DB.
        os.replace(stage, CAT)
        os.replace(manifest_tmp, manifest_dest)
        validation['detail_failures'] = detail_failures
        _set(task_id, state='completed_with_warnings' if detail_failures else 'completed',
             result=validation, completed_at=time.time())
    except Exception as exc:
        _set(task_id, state='failed', error=f'{type(exc).__name__}: {exc}', completed_at=time.time())
    finally:
        # Preserve log and task state; throw away failed capture bytes, not the catalogue.
        try:
            if stage.exists(): stage.unlink()
        except OSError:
            pass


def start_refresh(mode: str = 'index', max_details: int | None = None) -> dict[str, Any]:
    if mode not in {'index', 'details'}:
        raise ValueError('mode must be index or details')
    if max_details is not None:
        if mode != 'details' or not isinstance(max_details, int) or isinstance(max_details, bool) or not 1 <= max_details <= 200:
            raise ValueError('max_details must be 1..200 for details mode')
    if mode == 'details' and not catalogue_status().get('index_complete'):
        raise ValueError('complete spell/talent index needed before details')
    # Share admission with the existing item capture; both use the same Chrome profile.
    from .capture_admission import ADMISSION_LOCK
    with ADMISSION_LOCK, _LOCK:
        from . import item_refresh
        if any(x.get('state') in item_refresh.ACTIVE_STATES for x in item_refresh._TASKS.values()):
            raise RuntimeError('item Wowhead capture already active (shared Chrome profile)')
        if any(x.get('state') in ACTIVE for x in _TASKS.values()):
            raise RuntimeError('ability/talent capture already active')
        task_id = uuid.uuid4().hex
        now = time.time()
        _TASKS[task_id] = {'id': task_id, 'state': 'queued', 'mode': mode,
                           'max_details': max_details, 'created_at': now, 'updated_at': now}
        _write(task_id)
        thread = threading.Thread(target=_run, args=(task_id,mode,max_details),
                                  name=f'abilities-refresh-{task_id[:8]}', daemon=True)
        thread.start()
        return dict(_TASKS[task_id])
