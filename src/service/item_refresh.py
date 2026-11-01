from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from src.rulesets.forever.items.catalogue import ItemCatalogue
from src.rulesets.forever.items.wowhead_capture_import import import_adaptive_capture
from src.rulesets.forever.items.required_level_model import build_required_level_model, apply_inferred_required_levels, build_availability_floor_model
from .item_operations import catalogue_path, DEFAULT_PROFILE

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / 'state' / 'item_refresh'
_LOCK = threading.Lock()
_TASKS: dict[str, dict[str, Any]] = {}
ACTIVE_STATES = frozenset({'queued','capturing','building','publishing'})


def _write_status(task_id: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    p = STATE_DIR / f'{task_id}.json'
    tmp = p.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(_TASKS[task_id], indent=2, sort_keys=True) + '\n', encoding='utf-8')
    os.replace(tmp, p)


def _set(task_id: str, **updates: Any) -> None:
    with _LOCK:
        _TASKS[task_id].update(updates)
        _TASKS[task_id]['updated_at'] = time.time()
        _write_status(task_id)


def get_refresh(task_id: str) -> dict[str, Any] | None:
    with _LOCK:
        task = _TASKS.get(task_id)
        return dict(task) if task else None


def latest_refresh() -> dict[str, Any] | None:
    with _LOCK:
        if not _TASKS:
            return None
        return dict(max(_TASKS.values(), key=lambda x: float(x.get('created_at', 0))))


def _preserve_verified_details(old_path: Path, new_path: Path) -> int:
    if not old_path.exists():
        return 0
    preserved = 0
    with ItemCatalogue(old_path) as old, ItemCatalogue(new_path) as new:
        rows = [x for x in old.list_items() if x.fetch_status in {'verified', 'cached_fallback'}]
        for item in rows:
            new.upsert_item(item)
            for row in old._conn.execute('SELECT class_id, provenance FROM item_class_eligibility WHERE item_id=?', (item.item_id,)):
                new.add_class_eligibility(item.item_id, int(row[0]), str(row[1] or 'preserved_point_detail'))
            preserved += 1
    return preserved


def _run(task_id: str, classes: list[str]) -> None:
    target = catalogue_path()
    stamp = time.strftime('%Y%m%d_%H%M%S')
    capture_dir = STATE_DIR / f'capture_{stamp}_{task_id[:8]}'
    staging = target.with_name(target.stem + f'.refresh-{task_id[:8]}.sqlite')
    manifest_out = target.with_suffix('.manifest.json')
    log_path = STATE_DIR / f'{task_id}.log'
    try:
        _set(task_id, state='capturing', capture_dir=str(capture_dir), log_file=str(log_path))
        profile = Path(os.environ.get('WOWHEAD_CHROME_PROFILE', DEFAULT_PROFILE))
        channel = os.environ.get('WOWHEAD_BROWSER_CHANNEL', 'chrome')
        cmd = [sys.executable, str(ROOT / 'tools' / 'capture_wowhead_adaptive.py'), *classes,
               '--channel', channel, '--user-data-dir', str(profile), '--output', str(capture_dir)]
        with log_path.open('w', encoding='utf-8') as log:
            proc = subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f'adaptive Wowhead capture failed (exit {proc.returncode}); see {log_path}')

        _set(task_id, state='building')
        if staging.exists(): staging.unlink()
        summary = import_adaptive_capture(capture_dir, staging)
        preserved = _preserve_verified_details(target, staging)
        # Preserved exact-detail rows may refine reqlevel/item facts, so rebuild both
        # availability models after the overlay rather than leaving a stale model hash.
        with ItemCatalogue(staging) as cat:
            build_required_level_model(cat, computed_at=summary.captured_at)
            apply_inferred_required_levels(cat)
            build_availability_floor_model(cat, computed_at=summary.captured_at)
            new_hash = cat.catalogue_hash()
            model = cat.availability_floor_model()
        payload = summary.as_dict()
        payload['catalogue_hash_after_preserved_details'] = new_hash
        payload['preserved_verified_detail_items'] = preserved
        if model is not None:
            payload['availability_floor_model'] = {
                'degree': model.degree, 'quadratic_a': model.quadratic_a, 'linear_b': model.linear_b,
                'intercept_c': model.intercept_c, 'rmse': model.rmse, 'lower_sigma': model.lower_sigma,
                'observed_sample_count': model.observed_sample_count,
                'retained_sample_count': model.retained_sample_count,
                'excluded_low_outliers': model.excluded_low_outliers,
                'source_catalogue_hash': model.source_catalogue_hash,
            }
        temp_manifest = Path(str(manifest_out) + '.tmp')
        temp_manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')

        _set(task_id, state='publishing')
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, target)
        os.replace(temp_manifest, manifest_out)
        _set(task_id, state='completed', result=payload, completed_at=time.time())
    except Exception as exc:
        try:
            if staging.exists(): staging.unlink()
        except Exception:
            pass
        _set(task_id, state='failed', error=f'{type(exc).__name__}: {exc}', completed_at=time.time())


def start_refresh(classes: list[str] | None = None) -> dict[str, Any]:
    classes = [str(x).strip().lower() for x in (classes or ['mage','druid','paladin','hunter'])]
    allowed = {'mage','druid','paladin','hunter'}
    if not classes or any(x not in allowed for x in classes):
        raise ValueError('classes must contain mage, druid, paladin and/or hunter')
    from .capture_admission import ADMISSION_LOCK
    with ADMISSION_LOCK, _LOCK:
        from . import abilities_refresh
        if any(t.get('state') in abilities_refresh.ACTIVE for t in abilities_refresh._TASKS.values()):
            raise RuntimeError('ability/talent Wowhead capture already active (shared Chrome profile)')
        for task in _TASKS.values():
            if task.get('state') in ACTIVE_STATES:
                raise RuntimeError(f"item refresh already running: {task['id']}")
        task_id = uuid.uuid4().hex
        now = time.time()
        _TASKS[task_id] = {'id': task_id, 'state': 'queued', 'classes': classes, 'created_at': now, 'updated_at': now}
        _write_status(task_id)
        t = threading.Thread(target=_run, args=(task_id, classes), name=f'item-refresh-{task_id[:8]}', daemon=True)
        t.start()
        return dict(_TASKS[task_id])
