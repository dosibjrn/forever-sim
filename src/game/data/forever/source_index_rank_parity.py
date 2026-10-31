"""Fail-closed current-index numeric facts for existing ranked source actions.

These are *indexed* source facts, not independently verified spell-detail pages.
The adapter does not authorize L2 checkpoint completeness. It fixes a distinct
correctness issue: L2 must not silently score stale baked-in tooltip numbers
when the canonical index contains different observed values.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from datetime import date

from src.forever_build import current as current_forever_build

from .sqlite_talents import DEFAULT_DB
from .source_db_scope import active_ability_db

_N = r'(\d+(?:\.\d+)?)'
_PATTERNS = {
    'direct_damage': re.compile(rf'^(?:Causes?|Deals?) {_N} to {_N} (Arcane|Fire|Frost|Nature|Shadow|Holy) damage to the target\.$', re.I),
    'direct_periodic_damage': re.compile(rf'^Burns the enemy for {_N} to {_N} (Arcane|Fire|Frost|Nature|Shadow|Holy) damage and then an additional {_N} \3 damage over {_N} sec\.$', re.I),
    'direct_heal': re.compile(rf'^Heals a friendly target for {_N} to {_N}\.$', re.I),
    'periodic_heal': re.compile(rf'^Heals the target for {_N} over {_N} sec\.$', re.I),
}
_COST = re.compile(rf'^{_N} Mana$', re.I)
_CAST = re.compile(rf'^{_N} sec cast$', re.I)


class IndexedRankParityError(ValueError):
    pass


def parse_index_after(after: dict, effect_kind: str) -> dict:
    """Shared strict full-tooltip parser for index and external source snapshots."""
    if effect_kind not in _PATTERNS:
        raise IndexedRankParityError('UNSUPPORTED_INDEX_EFFECT_KIND')
    cost=_COST.fullmatch(str(after.get('cost') or '').strip())
    cast_text=str(after.get('cast') or '').strip()
    cast=_CAST.fullmatch(cast_text)
    if not cost or (cast_text.lower()!='instant' and not cast):
        raise IndexedRankParityError('INDEX_COST_OR_CAST_UNVERIFIED')
    text=' '.join(str(after.get('text') or '').replace('\xa0',' ').split())
    m=_PATTERNS[effect_kind].fullmatch(text)
    if not m:
        raise IndexedRankParityError('INDEX_EFFECT_DESCRIPTION_UNSUPPORTED:'+effect_kind)
    groups=m.groups(); parsed={'kind':effect_kind,'mana':float(cost.group(1)),
            'cast_s':0.0 if cast_text.lower()=='instant' else float(cast.group(1))}
    if effect_kind=='direct_damage':
        parsed.update(low=float(groups[0]),high=float(groups[1]),school=groups[2].lower())
    elif effect_kind=='direct_periodic_damage':
        parsed.update(low=float(groups[0]),high=float(groups[1]),school=groups[2].lower(),
                      periodic_total=float(groups[3]),duration_s=float(groups[4]))
    elif effect_kind=='direct_heal':
        parsed.update(low=float(groups[0]),high=float(groups[1]))
    else:
        parsed.update(total=float(groups[0]),duration_s=float(groups[1]))
    if 'low' in parsed and (parsed['low']<0 or parsed['low']>parsed['high']):
        raise IndexedRankParityError('INVALID_INDEX_RANGE')
    if parsed.get('duration_s',1)<=0 or parsed['mana']<0:
        raise IndexedRankParityError('INVALID_INDEX_EFFECT_VALUES')
    return parsed


def indexed_rank_fact(*, class_key: str, name: str, required_level: int, effect_kind: str,
                      db_path: Path | str | None = None) -> dict | None:
    """Get an exact full-tooltip indexed fact or explicit lack of `after` text.

    Missing row/unchanged (no after) returns None so callers can retain old
    values only with an *explicit* unresolved-provenance warning. Every present
    after-tooltip must match entirely or fail closed. No class/spell ID logic.
    """
    if effect_kind not in _PATTERNS:
        raise IndexedRankParityError('UNSUPPORTED_INDEX_EFFECT_KIND')
    p=Path(db_path or active_ability_db(DEFAULT_DB)).resolve()
    with sqlite3.connect(f'file:{p}?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        rows=db.execute('''SELECT i.*,b.captured_at,b.status AS batch_status
                 FROM spell_index i JOIN capture_batches b ON i.batch_id=b.batch_id
                 JOIN capture_lists l ON l.batch_id=i.batch_id AND l.class_key=i.class_key AND l.kind=i.kind
                 WHERE i.class_key=? AND i.kind='abilities' AND i.name=? AND i.level_hint=?
                 AND l.complete=1''',(str(class_key).lower(),name,int(required_level))).fetchall()
    if len(rows)>1:
        raise IndexedRankParityError('AMBIGUOUS_INDEX_RANK')
    if not rows:
        return None
    row=rows[0]
    # A newer snapshot must never rewrite a historical beta replay.
    if date.fromisoformat(str(row['captured_at'])[:10]) > current_forever_build().as_of:
        return None
    if row['batch_status']!='complete':
        raise IndexedRankParityError('INCOMPLETE_INDEX_CAPTURE_BATCH')
    raw=json.loads(row['raw_listview_json'])
    if raw.get('id') != row['spell_id'] or raw.get('name') != name or raw.get('level') != int(required_level):
        raise IndexedRankParityError('INDEX_RANK_IDENTITY_DRIFT')
    change=raw.get('envChange') or {}
    if change.get('status')=='removed':
        raise IndexedRankParityError('SOURCE_RANK_REMOVED')
    after=change.get('after') or {}
    if not after:
        return None
    if after.get('name')!=name:
        raise IndexedRankParityError('INDEX_TOOLTIP_NAME_DRIFT')
    parsed=parse_index_after(after,effect_kind)
    # Staged beta-client web-text observations may supersede stale index
    # values without ever changing canonical source-index bytes or hashes.
    from .source_observed_rank_parity import external_rank_fact
    with sqlite3.connect(f'file:{p}?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        external=external_rank_fact(db,row,effect_kind=effect_kind,as_of=current_forever_build().as_of)
    if external is not None:
        parsed=external
    return {**parsed,'spell_id':int(row['spell_id']),'name':name,
       'required_level':int(required_level),'source_url':row['source_url'],
       'captured_at':row['captured_at'],'index_batch_id':row['batch_id'],
       'raw_index_sha256':hashlib.sha256(row['raw_listview_json'].encode()).hexdigest(),
       'source_authority':parsed.get('source_authority','canonical_forever_source_index_after_tooltip'),
       'detail_html_independently_verified':False,
       'checkpoint_eligibility':parsed.get('checkpoint_eligibility','BLOCKED_INDEX_NOT_FULL_DETAIL_AUTHORITY')}


def indexed_rank_identity(*, class_key: str, name: str, required_level: int,
                          db_path: Path | str | None = None) -> dict | None:
    """Exact rank identity, independent of whether its numeric tooltip was captured.

    A missing `after` tooltip is NOT a reason to lose a known spell ID.  This
    accessor conveys no damage/heal values and cannot certify acquisition.
    """
    p = Path(db_path or active_ability_db(DEFAULT_DB)).resolve()
    with sqlite3.connect(f'file:{p}?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute('''SELECT i.spell_id,i.name,i.level_hint,i.rank_hint,
            i.source_url,i.batch_id,i.raw_listview_json,b.captured_at,b.status
            FROM spell_index i JOIN capture_batches b ON b.batch_id=i.batch_id
            JOIN capture_lists l ON l.batch_id=i.batch_id AND l.class_key=i.class_key
                AND l.kind=i.kind AND l.complete=1
            WHERE i.class_key=? AND i.kind='abilities' AND i.name=?
                AND i.level_hint=?''',
            (class_key.lower(), name, int(required_level))).fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise IndexedRankParityError('AMBIGUOUS_INDEX_RANK_IDENTITY')
    r = rows[0]
    if date.fromisoformat(str(r['captured_at'])[:10]) > current_forever_build().as_of:
        return None  # Do not leak a newer identity into historical replay.
    if r['status'] != 'complete':
        raise IndexedRankParityError('INDEX_RANK_IDENTITY_INCOMPLETE_BATCH')
    raw = json.loads(r['raw_listview_json'])
    if (raw.get('id') != r['spell_id'] or raw.get('name') != name
            or raw.get('level') != int(required_level)
            or f'/spell={int(r["spell_id"])}' not in str(r['source_url'])
            or (raw.get('envChange') or {}).get('status') == 'removed'):
        raise IndexedRankParityError('INDEX_RANK_IDENTITY_DRIFT')
    return {'source_spell_id': int(r['spell_id']), 'source_url': r['source_url'],
            'source_row_sha256': hashlib.sha256(r['raw_listview_json'].encode()).hexdigest(),
            'source_batch_id': r['batch_id'], 'rank_hint': r['rank_hint'],
            'identity_authority': 'canonical_source_index_identity_only',
            'numeric_and_acquisition_verified': False}
