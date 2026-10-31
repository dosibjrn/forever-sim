#!/usr/bin/env python3
"""Fail-closed verified detail -> typed known grammar -> staged canonical SQLite.

This migrates *values*, not mechanics: only an existing, fully typed effect
whose grammar is already executed by the generic compiler may be refreshed.
A verified Wowhead page is indispensable, but alone cannot prove unknown
coefficients, target semantics, form legality or new effect types.

No production database is written by this module. Staging is an isolated clone.
"""
from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path
import re
import sqlite3

from src.game.data.forever.source_ability_semantics import _PERIODIC_COMBO
from src.game.data.forever.sqlite_talents import _slug
from src.game.multi_pull import evaluate_repeated_pulls
from src.v2.source_sqlite_detail_snapshots import read_verified_spell_detail_snapshot


class SourceRepairBlocked(ValueError):
    """Missing or inconsistent source evidence, or an unproven executable effect."""


def _clean(s: str) -> str:
    return re.sub(r'\s+', ' ', s.replace('\xa0',' ')).strip()


class _VisibleHTML(HTMLParser):
    """Conservative text of non-hidden DOM nodes, excluding inline hidden content.

    This is not a browser renderer; externally styled invisibility is not
    inferred. Known hidden/script nodes cannot supply an effect tooltip.
    """
    _VOID = frozenset(('area','base','br','col','embed','hr','img','input',
                       'link','meta','param','source','track','wbr'))
    _NON_TEXT = frozenset(('script','style','noscript','template','svg'))

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._hidden = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        name=tag.lower()
        if name in self._VOID:
            return
        options={k.lower(): (v or '') for k,v in attrs}
        style=re.sub(r'\s+', '', options.get('style','').lower())
        suppressed=(name in self._NON_TEXT or 'hidden' in options
                    or options.get('aria-hidden','').lower()=='true'
                    or 'display:none' in style or 'visibility:hidden' in style)
        self._hidden.append((name, suppressed or (self._hidden[-1][1] if self._hidden else False)))

    def handle_endtag(self, tag):
        name=tag.lower()
        if name in self._VOID:
            return
        for idx in range(len(self._hidden)-1,-1,-1):
            if self._hidden[idx][0]==name:
                del self._hidden[idx:]
                break

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data):
        if not self._hidden or not self._hidden[-1][1]:
            self.parts.append(data)


def _verified_visible_text(html: str) -> str:
    extractor=_VisibleHTML()
    extractor.feed(html)
    extractor.close()
    return _clean(' '.join(extractor.parts))


def _reconcile_one(db: sqlite3.Connection, spell_id: int) -> dict:
    db.row_factory = sqlite3.Row
    rows = db.execute('''SELECT i.*,s.semantic_type,s.required_mode_id,b.status AS batch_status,
        l.complete AS list_complete,d.raw_page_text
        FROM spell_index i JOIN capture_lists l ON i.batch_id=l.batch_id
          AND i.class_key=l.class_key AND i.kind=l.kind
        JOIN capture_batches b ON i.batch_id=b.batch_id
        LEFT JOIN ability_semantic_source_facts s ON s.class_key=i.class_key
          AND s.spell_id=i.spell_id
        LEFT JOIN spell_details d ON d.batch_id=i.batch_id AND d.spell_id=i.spell_id
        WHERE i.spell_id=? AND i.kind='abilities' ''',(spell_id,)).fetchall()
    if len(rows)!=1:
        raise SourceRepairBlocked(f'AMBIGUOUS_OR_MISSING_INDEX:{spell_id}')
    row=rows[0]
    if row['batch_status']!='complete' or row['list_complete']!=1 or not row['level_hint']:
        raise SourceRepairBlocked(f'INDEX_OR_LEVEL_NOT_VERIFIED:{spell_id}')
    if row['semantic_type']!='melee_direct_periodic_combo':
        raise SourceRepairBlocked(f'UNKNOWN_OR_UNSUPPORTED_TYPED_EFFECT:{spell_id}:{row["semantic_type"]}')
    # The exact existing snapshot authority/HTML hash + final URL is checked by
    # the shared capture gate. Never accept a text-only legacy details row.
    try:
        evidence=read_verified_spell_detail_snapshot(
            db,batch_id=row['batch_id'],spell_id=spell_id)
    except ValueError as exc:
        raise SourceRepairBlocked(f'DETAIL_NOT_VERIFIED:{spell_id}:{exc}') from exc
    raw=json.loads(row['raw_listview_json'])
    after=(raw.get('envChange') or {}).get('after') or {}
    before=_clean(str(after.get('text') or ''))
    if not _PERIODIC_COMBO.fullmatch(before):
        raise SourceRepairBlocked(f'EXISTING_GRAMMAR_NOT_PARSED:{spell_id}')
    # Restrict extraction to an entire known grammar, with the sourced name as
    # a literal boundary. Do not look for arbitrary integers in HTML/tooltips.
    name=_clean(row['name'])
    template=(re.escape(name)+r' the target for (\d+) damage and an additional '
              r'(\d+) damage over (\d+) sec\. Awards (\d+) combo point\.')
    page=_verified_visible_text(evidence['html'])
    found=list(re.finditer(r'(?<!\w)'+template+r'(?!\w)',page,flags=re.I))
    if len(found)!=1:
        raise SourceRepairBlocked(f'DETAIL_GRAMMAR_UNIQUE_MATCH_REQUIRED:{spell_id}:{len(found)}')
    parsed=found[0].group(0)
    if parsed.casefold() not in _clean(str(row['raw_page_text'] or '')).casefold():
        raise SourceRepairBlocked(f'HTML_AND_CAPTURED_BODY_DISAGREE:{spell_id}')
    if not _PERIODIC_COMBO.fullmatch(parsed):
        raise SourceRepairBlocked(f'DETAIL_GRAMMAR_REJECTED:{spell_id}')
    if not str(after.get('cost') or '').strip() or not str(after.get('cast') or '').strip():
        raise SourceRepairBlocked(f'INDEX_COST_CAST_MISSING:{spell_id}')
    if _clean(str(after['cost'])).casefold() not in page.casefold():
        raise SourceRepairBlocked(f'DETAIL_COST_DISAGREEMENT:{spell_id}')
    if not re.search(r'\bRequires level\s+'+str(int(row['level_hint']))+r'\b',page,re.I):
        raise SourceRepairBlocked(f'DETAIL_ACQUISITION_DISAGREEMENT:{spell_id}')
    if _clean(str(after['cast'])).casefold() not in page.casefold():
        raise SourceRepairBlocked(f'DETAIL_CAST_DISAGREEMENT:{spell_id}')
    if row['rank_hint'] is not None and not re.search(
        r'\bRank\s+'+str(int(row['rank_hint']))+r'\b',page,re.I):
        raise SourceRepairBlocked(f'DETAIL_RANK_DISAGREEMENT:{spell_id}')
    # Only known numeric values are repaired; no cost/rank/timing/mechanic
    # metadata is inferred. This preserves unknown AP or crit blockers.
    raw['envChange']['after']['text']=parsed
    db.execute('''UPDATE spell_index SET raw_listview_json=?
        WHERE batch_id=? AND class_key=? AND kind='abilities' AND spell_id=?''',
        (json.dumps(raw,sort_keys=True),row['batch_id'],row['class_key'],spell_id))
    return {'spell_id':spell_id,'class_key':row['class_key'],
            'level_hint':int(row['level_hint']),'family':_slug(name),
            'typed_semantics':row['semantic_type'],'before':before,'after':parsed,
            'changed':before!=parsed,'source_url':row['source_url'],
            'detail_html_sha256':evidence['html_sha256']}


def parse_into_staging(staging: Path, *, spell_ids: tuple[int,...]) -> list[dict]:
    if not spell_ids or any(int(i)<=0 for i in spell_ids) or len(set(spell_ids))!=len(spell_ids):
        raise SourceRepairBlocked('INVALID_EXACT_SPELL_IDS')
    with sqlite3.connect(staging) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise SourceRepairBlocked('STAGING_SQLITE_CORRUPT')
        db.execute('BEGIN IMMEDIATE')
        try:
            result=[_reconcile_one(db,int(sid)) for sid in spell_ids]
            db.commit()
            return result
        except Exception:
            db.rollback()
            raise


