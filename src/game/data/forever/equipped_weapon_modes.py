from __future__ import annotations
"""Read source-authorized equipped-weapon mode semantics from canonical SQLite."""
from dataclasses import dataclass
from pathlib import Path
import sqlite3
from src.game.data.forever.sqlite_talents import DEFAULT_DB


@dataclass(frozen=True)
class EquippedWeaponModeFact:
    class_key: str
    mode_label: str
    source_stat: str
    damage_source_kind: str
    operation: str
    applies_to: str
    authority: str
    source_url: str
    source_date: str
    capture_id: str
    source_item_slot: str = "weapon"
    weapon_speed_semantics: str | None = None
    weapon_speed_source_url: str | None = None


def load_equipped_weapon_mode_facts(class_key: str, *, db_path: Path | None = None) -> tuple[EquippedWeaponModeFact, ...]:
    path = Path(db_path or DEFAULT_DB)
    if not path.is_file():
        raise FileNotFoundError(f'canonical Forever abilities SQLite missing: {path}')
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute('''SELECT * FROM equipped_weapon_mode_source_facts
                WHERE class_key=? ORDER BY mode_label,source_stat,damage_source_kind''',
                (str(class_key).lower(),)).fetchall()
        except sqlite3.OperationalError as exc:
            raise ValueError('canonical equipped weapon mode source facts missing') from exc
    facts = []
    for row in rows:
        if (not all(row[k] for k in ('class_key','mode_label','source_stat','damage_source_kind',
                                    'authority','source_url','source_date','evidence','capture_id'))
                or row['operation'] != 'replace_flat_dps'
                or row['applies_to'] != 'auto_and_weapon_actions'):
            raise ValueError('invalid canonical equipped weapon mode source fact')
        if 'weapon_speed_semantics' in row.keys() and row['weapon_speed_semantics'] not in (None,'equipped','form_fixed'):
            raise ValueError('unsupported canonical equipped weapon speed semantics')
        facts.append(EquippedWeaponModeFact(**{k: row[k] for k in EquippedWeaponModeFact.__dataclass_fields__
                                              if k in row.keys()}))
    return tuple(facts)
