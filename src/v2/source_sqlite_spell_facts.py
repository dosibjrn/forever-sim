"""Strict spell-index materialization from the canonical Forever SQLite capture.

Only explicit structured listview fields are eligible. This module does not
interpret tooltip text as verified executable combat semantics.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class MissingVerifiedSpellFact(ValueError):
    pass


def materialize_spell_index_fact(database: str | Path, *, batch_id: str,
                                 class_key: str, kind: str, spell_id: int,
                                 field: str) -> dict:
    """Return a fact and independently checkable field-level database lineage.

    Allowed fields describe spell *identity/discovery*, not combat behavior.
    Every other field fails closed until verified detail ingestion exists.
    """
    allowed = {'name', 'level_hint', 'rank_hint', 'source_url'}
    if field not in allowed:
        raise MissingVerifiedSpellFact(f'{field}: not a verified structured spell-index field')
    with sqlite3.connect(f'file:{Path(database).resolve()}?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        row = db.execute('''SELECT s.*, b.status AS batch_status, l.complete AS list_complete
            FROM spell_index s JOIN capture_batches b ON b.batch_id=s.batch_id
            JOIN capture_lists l ON (l.batch_id=s.batch_id AND l.class_key=s.class_key AND l.kind=s.kind)
            WHERE s.batch_id=? AND s.class_key=? AND s.kind=? AND s.spell_id=?''',
            (batch_id, class_key, kind, spell_id)).fetchone()
        if row is None or row['batch_status'] != 'complete' or row['list_complete'] != 1:
            raise MissingVerifiedSpellFact('missing spell or incomplete capture/list')
        value = row[field]
        if value is None or value == '':
            raise MissingVerifiedSpellFact(f'{field}: NULL/empty in SQLite')
        raw = json.loads(row['raw_listview_json'])
        # Cross-check the structured index against the raw capture where possible.
        raw_key = {'name': 'name', 'level_hint': 'level', 'rank_hint': 'rank', 'source_url': None}[field]
        if raw_key is not None and raw_key in raw and str(raw[raw_key]) != str(value):
            raise MissingVerifiedSpellFact(f'{field}: indexed value disagrees with raw capture')
        lineage = {'authority': 'canonical_sqlite', 'database': str(Path(database).resolve()),
                   'table': 'spell_index', 'capture_batch': batch_id,
                   'row_key': {'batch_id': batch_id, 'class_key': class_key, 'kind': kind, 'spell_id': spell_id},
                   'field_lineage': {field: f'spell_index.{field}'}, 'source_url': row['source_url']}
        return {'value': value, 'lineage': lineage,
                'scope': 'identity_only_not_verified_executable_semantics'}
