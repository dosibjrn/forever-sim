"""Source-backed acquisition evidence and fail-closed learned-action legality.

A listview level, source code or training price is NOT evidence that a character
learned an action.  Verified spell detail pages can establish an acquisition
*method*, but not trainer reachability, purchase, quest completion or possession.
The explicit learned-state contract below is shared by all nine class providers.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Iterable

from .source_indexed_action_coverage import _source_spell_ids
from .sqlite_talents import DEFAULT_DB


def read_acquisition_evidence(*, class_key: str, spell_ids: Iterable[int],
                              db_path: str | Path | None = None) -> dict[int, dict]:
    ids = sorted(set(int(x) for x in spell_ids))
    if not ids:
        return {}
    path = Path(db_path or DEFAULT_DB)
    with sqlite3.connect(f'file:{path.resolve()}?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ability_acquisition_evidence'").fetchone():
            return {}
        rows = db.execute('''SELECT e.*, i.raw_listview_json, i.batch_id AS live_batch,
                                  i.level_hint AS live_level, i.source_url AS live_url,
                                  s.html_sha256 AS live_detail_sha,
                                  d.details_verified AS live_detail_verified,
                                  b.status AS live_batch_status
            FROM ability_acquisition_evidence e JOIN spell_index i
              ON e.class_key=i.class_key AND e.spell_id=i.spell_id AND i.kind='abilities'
            LEFT JOIN spell_detail_snapshots s ON s.batch_id=e.index_batch_id AND s.spell_id=e.spell_id
            LEFT JOIN spell_details d ON d.batch_id=e.index_batch_id AND d.spell_id=e.spell_id
            LEFT JOIN capture_batches b ON b.batch_id=e.index_batch_id
            WHERE e.class_key=?''', (class_key.strip().lower(),)).fetchall()
    results = {}
    for r in rows:
        sid = int(r['spell_id'])
        if sid not in ids:
            continue
        if (r['source_payload_sha256'] != hashlib.sha256(r['raw_listview_json'].encode()).hexdigest()
                or r['index_batch_id'] != r['live_batch'] or r['source_url'] != r['live_url']
                or r['required_level_hint'] != r['live_level']):
            results[sid] = {'status': 'STALE_INDEX_EVIDENCE', 'spell_id': sid}
            continue
        if r['detail_html_sha256'] is not None and (
                r['detail_html_sha256'] != r['live_detail_sha']
                or r['live_detail_verified'] != 1 or r['live_batch_status'] != 'complete'):
            results[sid] = {'status': 'STALE_DETAIL_EVIDENCE', 'spell_id': sid}
            continue
        results[sid] = {
            'spell_id': sid, 'class_key': r['class_key'],
            'required_level_hint': r['required_level_hint'],
            'methods_observed': json.loads(r['methods_observed_json']),
            'evidence_status': r['evidence_status'],
            'index_batch_id': r['index_batch_id'],
            'detail_html_sha256': r['detail_html_sha256'],
            'source_url': r['source_url'], 'status': 'CURRENT_SOURCE_EVIDENCE',
        }
    return results


def audit_learned_action_legality(ir, *, level: int, action_ids: Iterable[str],
                                  acquired_spell_ids: Iterable[int] = (),
                                  db_path: str | Path | None = None,
                                  world_anchor_id: str | None = None,
                                  world_events: Iterable[dict] = ()) -> dict:
    """A real route must supply acquired ranks and separate acquisition events.

    This function deliberately NEVER concludes world acquisition from an index
    hint or a Taught-by page. Even a proven trainer method requires a separate
    validated route event; no such event verifier is implemented yet.
    """
    actions = {a.id: a for a in ir.actions}
    acquired = set(int(x) for x in acquired_spell_ids)
    verified_trace = None
    if world_anchor_id is not None:
        from .source_world_acquisition import verify_acquisition_trace
        verified_trace = verify_acquisition_trace(
            class_key=ir.actor.metadata['class_key'], level=level,
            anchor_id=world_anchor_id, events=world_events, db_path=db_path)
        # Claims do not grant spells; the verified trace is the only authority.
        acquired = set(verified_trace['verified_learned_spell_ids'])
    selected = tuple(action_ids)
    all_ids = {sid for aid in selected if aid in actions
               for sid in _source_spell_ids(actions[aid])}
    evidence = read_acquisition_evidence(class_key=ir.actor.metadata['class_key'],
                                         spell_ids=all_ids, db_path=db_path)
    records = []
    for aid in selected:
        action = actions.get(aid)
        if action is None:
            records.append({'action_id': aid, 'status': 'BLOCKED_NOT_IN_EXECUTABLE_IR'})
            continue
        ids = sorted(_source_spell_ids(action))
        if not ids:
            records.append({'action_id': aid, 'status': 'BLOCKED_MISSING_SOURCE_SPELL_ID'})
            continue
        matching = [sid for sid in ids if sid in acquired]
        if not matching:
            records.append({'action_id': aid, 'source_spell_ids': ids,
                            'status': 'BLOCKED_NOT_LEARNED_IN_CHARACTER_STATE'})
            continue
        if len(matching) != 1 or len(ids) != 1:
            records.append({'action_id': aid, 'source_spell_ids': ids,
                            'status': 'BLOCKED_AMBIGUOUS_SOURCE_RANK'})
            continue
        sid = matching[0]
        row = evidence.get(sid)
        if not row or row['status'] != 'CURRENT_SOURCE_EVIDENCE':
            records.append({'action_id': aid, 'source_spell_ids': ids,
                            'status': 'BLOCKED_MISSING_OR_STALE_SOURCE_ACQUISITION'})
            continue
        if row['required_level_hint'] is None or int(row['required_level_hint']) > level:
            records.append({'action_id': aid, 'source_spell_ids': ids,
                            'status': 'BLOCKED_SOURCE_LEVEL_UNKNOWN_OR_TOO_HIGH'})
            continue
        # A claimed learned ID is not evidence, only an independently replayed
        # trainer/world transaction allows action acquisition to pass.
        if verified_trace is not None:
            records.append({'action_id':aid,'source_spell_ids':ids,
                            'status':'VERIFIED_WORLD_ACQUISITION'})
        else:
            records.append({'action_id': aid, 'source_spell_ids': ids,
                            'status': 'BLOCKED_ACQUISITION_EVENT_NOT_VERIFIED',
                            'methods_observed': row['methods_observed'],
                            'evidence_status': row['evidence_status']})
    blockers = [r for r in records if r['status'] != 'VERIFIED_WORLD_ACQUISITION']
    completed = bool(records) and not blockers
    return {'status': ('WORLD_ACQUISITION_VERIFIED' if completed else
                       'ACQUISITION_UNVERIFIED' if records else 'NO_ACTIONS'),
            'level': int(level), 'source_action_count':len(records),
            'verified_world_acquisition_count':len(records)-len(blockers),
            'blockers':blockers,'records':records,'complete':completed,
            'world_trace':verified_trace}
