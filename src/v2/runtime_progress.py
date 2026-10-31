from __future__ import annotations

"""Tiny optimizer-owned runtime progress side channel.

Unlike ``viewer.json`` this file is intentionally small and cheap to rewrite.
The service polls it once per second and turns it into durable runtime_progress
job events.  Search correctness never depends on this file.
"""

from contextlib import contextmanager
from contextvars import ContextVar
import os
import time
from typing import Any, Iterator

from .runtime_state import STATE_DIR, atomic_write_json

_CONTEXT: ContextVar[dict[str, Any]] = ContextVar("v2_runtime_progress_context", default={})
_LAST_WRITE_AT = 0.0
_MIN_WRITE_INTERVAL_S = 0.10


@contextmanager
def progress_scope(**fields: Any) -> Iterator[None]:
    base = dict(_CONTEXT.get() or {})
    base.update({k: v for k, v in fields.items() if v is not None})
    token = _CONTEXT.set(base)
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def _overall_progress(ctx: dict[str, Any]) -> dict[str, Any]:
    try:
        total = max(1, int(ctx.get("levels_total") or 1))
        done = max(0, int(ctx.get("levels_done") or 0))
        cand_total = max(0, int(ctx.get("candidate_total") or 0))
        cand_current = max(0, int(ctx.get("candidate_current") or 0))
    except (TypeError, ValueError):
        return {"mode": "indeterminate"}

    partial = 0.0
    if cand_total > 0 and cand_current > 0:
        # Candidate N is in progress. Count completed candidates exactly and a
        # small midpoint allowance for the current candidate so the bar moves
        # during long levels without pretending fixed-point iterations are equal.
        partial = min(1.0, max(0.0, (cand_current - 0.5) / cand_total))
    fraction = min(1.0, max(0.0, (done + partial) / total))
    return {
        "mode": "determinate",
        "current": done,
        "total": total,
        "fraction": fraction,
        "unit": "levels",
    }


def _format_duration(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    sec = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}m {sec:02d}s"
    hours = minutes // 60
    return f"{hours}h {minutes % 60:02d}m"


def emit_runtime_progress(*, force: bool = False, **fields: Any) -> dict[str, Any] | None:
    """Write one bounded status snapshot; failures are deliberately non-fatal.

    Candidate process-pool workers set WOW_SIM_SUPPRESS_RUNTIME_PROGRESS=1 so
    only the parent owns the shared status side-channel.
    """
    global _LAST_WRITE_AT
    if os.environ.get("WOW_SIM_SUPPRESS_RUNTIME_PROGRESS") == "1":
        return None
    now_mono = time.monotonic()
    if not force and now_mono - _LAST_WRITE_AT < _MIN_WRITE_INTERVAL_S:
        return None

    ctx = dict(_CONTEXT.get() or {})
    ctx.update({k: v for k, v in fields.items() if v is not None})
    now = time.time()
    started_at = float(ctx.get("started_at") or now)
    elapsed = max(0.0, now - started_at)
    progress = dict(ctx.get("progress") or _overall_progress(ctx))
    fraction = progress.get("fraction")
    eta = None
    try:
        f = float(fraction)
        if 0.01 < f < 1.0:
            eta = max(0.0, elapsed * (1.0 - f) / f)
    except (TypeError, ValueError):
        pass

    parts = []
    level = ctx.get("level")
    if level is not None:
        parts.append(f"L{level}")
    ci, ct = ctx.get("candidate_current"), ctx.get("candidate_total")
    if ci is not None and ct is not None:
        parts.append(f"candidate {ci}/{ct}")
    profile = ctx.get("profile")
    if profile:
        parts.append(str(profile))
    fi, fm = ctx.get("fixed_point_iteration"), ctx.get("fixed_point_max_iters")
    if fi is not None and fm is not None:
        parts.append(f"fixed-point {fi}/{fm}")
    parts.append(f"elapsed {_format_duration(elapsed)}")
    if eta is not None:
        parts.append(f"ETA ~{_format_duration(eta)}")

    payload = {
        "state": "running",
        "phase": ctx.get("phase") or "searching",
        "outer_stage": ctx.get("stage") or "search",
        "level": level,
        "progress": progress,
        "message": ctx.get("message") or " · ".join(parts),
        "elapsed_seconds": elapsed,
        "eta_seconds": eta,
        "updated_at": now,
    }
    for key in (
        "candidate_current", "candidate_total", "profile",
        "fixed_point_iteration", "fixed_point_max_iters", "talent_added",
    ):
        if ctx.get(key) is not None:
            payload[key] = ctx[key]
    try:
        path = STATE_DIR / "runtime" / "status.json"
        atomic_write_json(path, payload)
        _LAST_WRITE_AT = now_mono
        return payload
    except OSError:
        return None
