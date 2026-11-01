"""Request-scoped authority for an explicit canonical-source SQLite snapshot.

The registry builds a single Game IR from one abilities database. Previously
only the late generic compiler saw an `ability_db_path` override; provider
spells, maintenance, talents and rank promotion silently read DEFAULT_DB.
ContextVar keeps parallel builds isolated and restores the default even when a
source parser raises. This scope is source selection, NOT source verification.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

_active_ability_source: ContextVar[Path | None] = ContextVar(
    "forever_ability_source_sqlite", default=None
)


def active_ability_db(default: Path | str) -> Path:
    """Return the explicit snapshot for this IR build, or the normal default."""
    selected = _active_ability_source.get()
    return selected if selected is not None else Path(default)


@contextmanager
def ability_source_scope(path: Path | str | None):
    """Bind one SQLite for all nested provider and enrichment reads."""
    if path is None:
        yield
        return
    source = Path(path).resolve(strict=True)
    if not source.is_file():
        raise FileNotFoundError(f"ability SQLite snapshot is not a file: {source}")
    token = _active_ability_source.set(source)
    try:
        yield
    finally:
        _active_ability_source.reset(token)
