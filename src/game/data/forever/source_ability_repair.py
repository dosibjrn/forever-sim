"""Source-data repair queue for canonical Forever ability rows.

No spell lists, effect defaults, or claimed acquisition gates. This reports
exactly which stage is missing so the existing browser capture can be retried;
a fetched page is *evidence*, not automatically an executable ability.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from .sqlite_talents import DEFAULT_DB


def repair_queue(*, class_key: str, level: int, db_path: Path | None = None) -> dict:
    key = class_key.strip().lower()
    path = Path(db_path or DEFAULT_DB)
    if not path.is_file():
        raise FileNotFoundError(f'canonical source SQLite missing: {path}')
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        try:
            batches = conn.execute('''SELECT l.batch_id,l.complete,l.blocked_reason,
                b.status AS batch_status,l.expected_count,l.captured_count
                FROM capture_lists l JOIN capture_batches b ON b.batch_id=l.batch_id
                WHERE l.class_key=? AND l.kind='abilities' ORDER BY b.captured_at DESC''',
                (key,)).fetchall()
        except sqlite3.Error as exc:
            raise ValueError(f'canonical capture schema unavailable: {exc}') from exc
        if len(batches) != 1 or not batches[0]['complete'] or batches[0]['batch_status'] != 'complete':
            raise ValueError(f'{key}: no unambiguous complete source-index batch; refresh/validate the capture first')
        batch = batches[0]['batch_id']
        try:
            rows = conn.execute('''SELECT i.spell_id,i.name,i.rank_hint,i.level_hint,
                i.source_url,i.raw_listview_json, s.semantic_type,
                s.required_mode_id,s.gcd_s
                FROM spell_index i LEFT JOIN ability_semantic_source_facts s
                  ON s.spell_id=i.spell_id AND s.class_key=i.class_key
                WHERE i.batch_id=? AND i.class_key=? AND i.kind='abilities'
                  AND (i.level_hint IS NULL OR i.level_hint <= ?)
                ORDER BY i.spell_id''', (batch, key, int(level))).fetchall()
        except sqlite3.Error as exc:
            raise ValueError(f'canonical ability index/semantics schema unavailable: {exc}') from exc
    if not rows:
        raise ValueError(f'{key}: empty source-index window; do not claim complete coverage')
    repairs = []
    verified = 0
    for row in rows:
        sid = int(row['spell_id'])
        base = {'spell_id':sid,'name':row['name'],'rank':row['rank_hint'],
                'level_hint':row['level_hint'],'source_url':row['source_url']}
        if row['level_hint'] is None or int(row['level_hint']) <= 0:
            repairs.append({**base,'stage':'ACQUISITION_UNVERIFIED',
                            'action':'source the level/trainer/quest/rune acquisition gate'});
            continue
        try:
            record = json.loads(row['raw_listview_json'])
            after = (record.get('envChange') or {}).get('after') or {}
            tooltip = after.get('text'); cost = after.get('cost'); cast = after.get('cast')
            if not isinstance(tooltip,str) or not tooltip.strip() or not isinstance(cost,str) or not cost.strip() or not isinstance(cast,str) or not cast.strip():
                raise ValueError('incomplete cost/cast/tooltip from listview')
        except (ValueError,TypeError,AttributeError) as exc:
            repairs.append({**base,'stage':'SOURCE_LISTVIEW_PARSE_FAILED',
                            'action':'recapture complete Wowhead ability listing, then fix listview parser',
                            'detail':str(exc)})
            continue
        if row['semantic_type'] is None:
            repairs.append({**base,'stage':'SEMANTIC_FACTS_MISSING',
                            'action':'capture verified spell detail and parse typed source effects/requirements'})
            continue
        verified += 1
    return {'class_key':key,'level':int(level),'batch_id':batch,
            'indexed_below_or_unknown_level':len(rows),
            'source_rows_ready_for_compiler':verified,
            'repairs':repairs,'repair_count':len(repairs),
            'status':'SOURCE_REPAIR_REQUIRED' if repairs else 'SOURCE_ROWS_PRESENT_COMPILER_STILL_REQUIRES_VALIDATION',
            'complete_action_coverage':False,
            'note':'Ready rows still require generic IR compilation, acquisition validation and full executor checks.'}
