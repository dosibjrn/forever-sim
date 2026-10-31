"""Fail-closed retrieval of independently checkable Wowhead detail-page evidence.

A captured HTML page is *source evidence*, never an executable combat fact.
Parsing damage, costs, ranks and effects requires a separate validated extractor.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import zlib
from pathlib import Path
from urllib.parse import urlparse

MAX_HTML_BYTES = 4 * 1024 * 1024
BLOCK_MARKERS = (
    'access denied', 'error 403', 'forbidden', 'just a moment',
    'checking your browser', 'verify you are human', 'captcha',
    'page not found', '404 not found',
)


class MissingVerifiedSpellDetail(ValueError):
    """The snapshot is absent, corrupt, mismatched or not source-verified."""


def verified_spell_page(*, spell_id: int, names: list[str], final_url: str,
                        title: str, body: str, status: int | None,
                        html_length: int) -> bool:
    """Conservatively check page identity; does NOT verify combat semantics."""
    parsed = urlparse(final_url)
    match = re.fullmatch(r'/forever/spell=(\d+)(?:/[a-z0-9][a-z0-9-]*)?/?', parsed.path)
    if (parsed.scheme != 'https' or parsed.hostname not in ('www.wowhead.com', 'wowhead.com')
            or match is None or int(match.group(1)) != spell_id or status != 200
            or html_length < 32 or not names):
        return False
    visible = re.sub(r'\s+', ' ', title + '\n' + body).casefold()
    if any(marker in visible[:15000] for marker in BLOCK_MARKERS):
        return False
    def comparable_name(name: str) -> str:
        # Listview sometimes adds a rank suffix omitted from the page title.
        return re.sub(r'\s*\(?Rank\s+\d+\)?$', '', re.sub(r'\s+', ' ', name), flags=re.I).casefold().strip()
    return any(comparable_name(name) in visible for name in names if comparable_name(name))


def read_verified_spell_detail_snapshot(db: sqlite3.Connection, *, batch_id: str,
                                        spell_id: int) -> dict:
    """Verify a snapshot in an existing connection (including in-memory tests).

    Reuse exactly the same authority/integrity gate for resume and consumers.
    Never interpret a valid HTML snapshot as validated combat semantics.
    """
    previous_factory = db.row_factory
    try:
        db.row_factory = sqlite3.Row
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'spell_detail_snapshots' not in tables:
            raise MissingVerifiedSpellDetail('no HTML snapshot table: re-capture details with updated tooling')
        row = db.execute("""SELECT d.*, s.html_zlib, s.html_bytes, s.html_sha256 AS snapshot_sha,
                                  s.final_url, s.http_status, b.status AS batch_status
                FROM spell_details d
                JOIN spell_detail_snapshots s ON s.batch_id=d.batch_id AND s.spell_id=d.spell_id
                JOIN capture_batches b ON b.batch_id=d.batch_id
                WHERE d.batch_id=? AND d.spell_id=?""", (batch_id, spell_id)).fetchone()
        if row is None or row['details_verified'] != 1 or row['batch_status'] != 'complete':
            raise MissingVerifiedSpellDetail('missing verified detail/snapshot or incomplete batch')
        index = db.execute("""SELECT i.name, i.source_url FROM spell_index i
                JOIN capture_lists l ON l.batch_id=i.batch_id AND l.class_key=i.class_key
                                    AND l.kind=i.kind
                WHERE i.batch_id=? AND i.spell_id=? AND l.complete=1""",
                (batch_id, spell_id)).fetchall()
        if not index:
            raise MissingVerifiedSpellDetail('no complete indexed source list for spell')
        if any(x['source_url'] != row['source_url'] for x in index):
            raise MissingVerifiedSpellDetail('detail source URL does not match indexed URL')
        decoder = zlib.decompressobj()
        try:
            raw = decoder.decompress(row['html_zlib'], MAX_HTML_BYTES + 1)
            if (len(raw) > MAX_HTML_BYTES or not decoder.eof or decoder.unused_data
                    or decoder.unconsumed_tail):
                raise MissingVerifiedSpellDetail('snapshot exceeds limit or has invalid compressed stream')
            raw += decoder.flush()
            if len(raw) > MAX_HTML_BYTES:
                raise MissingVerifiedSpellDetail('snapshot exceeds decompressed size limit')
        except (zlib.error, ValueError, TypeError) as exc:
            raise MissingVerifiedSpellDetail('invalid compressed HTML snapshot') from exc
        sha = hashlib.sha256(raw).hexdigest()
        if (len(raw) != row['html_bytes'] or sha != row['snapshot_sha']
                or sha != row['html_sha256']):
            raise MissingVerifiedSpellDetail('HTML integrity/hash mismatch')
        if not verified_spell_page(spell_id=spell_id, names=[x['name'] for x in index],
                                  final_url=row['final_url'], title=row['page_title'] or '',
                                  body=row['raw_page_text'], status=row['http_status'],
                                  html_length=len(raw)):
            raise MissingVerifiedSpellDetail('page identity or content not independently verifiable')
        return {'html': raw.decode('utf-8', errors='replace'),
                'source_url': row['source_url'], 'final_url': row['final_url'],
                'html_sha256': sha}
    except sqlite3.Error as exc:
        raise MissingVerifiedSpellDetail(f'SQLite source unavailable or invalid: {exc}') from exc
    finally:
        db.row_factory = previous_factory


def materialize_spell_detail_snapshot(database: str | Path, *, batch_id: str,
                                      spell_id: int) -> dict:
    """Read and verify raw HTML and provenance; no combat facts are asserted."""
    db_path = Path(database).resolve()
    try:
        with sqlite3.connect(f'file:{db_path}?mode=ro', uri=True) as db:
            verified = read_verified_spell_detail_snapshot(
                db, batch_id=batch_id, spell_id=spell_id)
    except sqlite3.Error as exc:
        raise MissingVerifiedSpellDetail(f'SQLite source unavailable or invalid: {exc}') from exc
    return {
        'html': verified['html'],
        'lineage': {'authority': 'canonical_sqlite', 'database': str(db_path),
                    'table': 'spell_detail_snapshots',
                    'row_key': {'batch_id': batch_id, 'spell_id': spell_id},
                    'source_url': verified['source_url'],
                    'final_url': verified['final_url'],
                    'html_sha256': verified['html_sha256']},
        'scope': 'raw_html_source_evidence_only_not_verified_executable_combat_facts',
    }
