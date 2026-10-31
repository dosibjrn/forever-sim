from __future__ import annotations

import json, os, sys, time, uuid
from pathlib import Path
from typing import Any

from src import game_context

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = game_context.v2_state_root(ROOT)
SNAPSHOT = STATE_DIR / 'viewer.json'

# Windows readers (browser/listener, AV, indexers) can briefly hold a file handle
# without FILE_SHARE_DELETE. os.replace() then raises WinError 5 even though the
# file is otherwise perfectly usable. Keep the normal atomic path, but tolerate
# that transient contention instead of killing the optimizer.
_REPLACE_RETRY_DELAYS = (0.0, 0.005, 0.010, 0.020, 0.040, 0.080, 0.160)
_LAST_PUBLISH_WARNING_AT = 0.0


def _tmp(path: Path) -> Path:
    return path.with_name(path.name + f'.{os.getpid()}.{uuid.uuid4().hex}.tmp')


def atomic_write_json(path: Path, obj: Any) -> None:
    """Write JSON atomically when possible, with a Windows lock fallback.

    The common path is temp-file + os.replace(). On Windows a concurrent reader
    may deny delete/rename sharing for a few milliseconds, causing WinError 5.
    Retry that operation briefly. If the destination remains rename-locked but
    is writable, fall back to replacing its contents in-place. Readers already
    treat a transient partial/invalid snapshot as unavailable and retry, so the
    fallback is preferable to aborting the optimizer for a UI-only artifact.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, ensure_ascii=False, indent=2)
    tmp = _tmp(path)
    try:
        tmp.write_text(data, encoding='utf-8')
        last_exc: PermissionError | None = None
        for delay in _REPLACE_RETRY_DELAYS:
            if delay:
                time.sleep(delay)
            try:
                os.replace(tmp, path)
                return
            except PermissionError as exc:
                last_exc = exc

        # Some Windows handles permit write sharing but not delete/rename
        # sharing. This loses atomicity only on the exceptional lock path, but
        # keeps the optimizer alive and the listener self-heals on its next poll.
        try:
            path.write_text(data, encoding='utf-8')
            return
        except PermissionError:
            if last_exc is not None:
                raise last_exc
            raise
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def read_snapshot() -> dict:
    try:
        return json.loads(SNAPSHOT.read_text(encoding='utf-8'))
    except Exception:
        return {
            'version': 1,
            'running': False,
            'phase': 'idle',
            'message': 'No v2 run yet.',
            'views': {},
        }


def publish(obj: dict) -> dict:
    """Best-effort publication of live UI state.

    Snapshot publication must never be a correctness dependency of the search.
    If Windows keeps the UI file exclusively locked even after retry + direct
    fallback, skip that refresh and let a later publish attempt recover.
    """
    global _LAST_PUBLISH_WARNING_AT
    out = dict(obj)
    out['updated_at'] = time.time()
    try:
        atomic_write_json(SNAPSHOT, out)
    except PermissionError as exc:
        now = time.monotonic()
        if now - _LAST_PUBLISH_WARNING_AT >= 5.0:
            print(
                f'[v2] warning: viewer snapshot busy; skipping this refresh: {exc}',
                file=sys.stderr,
                flush=True,
            )
            _LAST_PUBLISH_WARNING_AT = now
    return out
