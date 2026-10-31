from __future__ import annotations

"""Source-backed, class-neutral conversion facts for executable gear deltas.

The canonical database owns class/mode/stat identities and coefficients.  This
module only supports the generic `source stat -> mode stat` primitive; other
conversion types remain explicit coverage gaps, not guessed fallbacks.
"""

from dataclasses import dataclass
from pathlib import Path
import sqlite3

from src.game.data.forever.sqlite_talents import DEFAULT_DB


@dataclass(frozen=True)
class ModeStatConversion:
    source_stat: str
    target_stat: str
    mode_label: str
    coefficient: float
    authority: str
    source_url: str
    capture_id: str


def _load_conversions(class_key: str, target_type: str, *, db_path: Path | None = None) -> tuple[ModeStatConversion, ...]:
    path = Path(db_path or DEFAULT_DB)
    if not path.is_file():
        raise FileNotFoundError(f'canonical Forever abilities SQLite missing: {path}')
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute('''SELECT * FROM stat_conversion_source_facts
                WHERE class_key=? AND target_type=?
                ORDER BY source_stat, mode_label, target_id''', (str(class_key).lower(), target_type)).fetchall()
        except sqlite3.OperationalError as exc:
            raise ValueError('canonical stat conversion source facts missing') from exc
    result = []
    for row in rows:
        if (not row['source_stat'] or not row['target_id'] or not row['mode_label']
                or not row['source_url'] or not row['authority'] or float(row['coefficient']) <= 0):
            raise ValueError('invalid canonical stat conversion fact')
        result.append(ModeStatConversion(
            source_stat=str(row['source_stat']), target_stat=str(row['target_id']),
            mode_label=str(row['mode_label']), coefficient=float(row['coefficient']),
            authority=str(row['authority']), source_url=str(row['source_url']),
            capture_id=str(row['capture_id'])))
    return tuple(result)


def load_mode_stat_conversions(class_key: str, *, db_path: Path | None = None) -> tuple[ModeStatConversion, ...]:
    """Source-backed mode-local stat conversions."""
    return _load_conversions(class_key, 'stat', db_path=db_path)


def load_mode_resource_capacity_conversions(class_key: str, *, db_path: Path | None = None) -> tuple[ModeStatConversion, ...]:
    """Source-backed mode-local gear stat -> resource capacity conversions."""
    return _load_conversions(class_key, 'resource_capacity', db_path=db_path)
