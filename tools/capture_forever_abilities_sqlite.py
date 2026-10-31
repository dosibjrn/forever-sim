#!/usr/bin/env python3
"""Capture WoW Forever class ability/talent *source records* into a separate SQLite.

Source: https://www.wowhead.com/forever/spells/{abilities|talents}/{class}

This is an auditable, deliberate, headed-browser BUILD-TIME snapshot, not a
runtime dependency and NOT an updater for the canonical item SQLite.

A complete class list is a prerequisite for its index to be marked complete.
A talent list is NOT a full talent tree: grid placement, prerequisites and
rank-level semantics require independent client/trait evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import sqlite3
import sys
import time
import zlib
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

# Direct script invocation sets sys.path[0] to tools/, not the project root.
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.v2.source_sqlite_detail_snapshots import (
    verified_spell_page, MAX_HTML_BYTES, MissingVerifiedSpellDetail,
    read_verified_spell_detail_snapshot,
)

CLASSES = ("warrior", "paladin", "hunter", "rogue", "priest", "shaman", "mage", "warlock", "druid")
KINDS = ("abilities", "talents")
SCHEMA_VERSION = 1
BLOCK_MARKERS = ("access denied", "error 403", "forbidden", "just a moment", "checking your browser", "verify you are human", "captcha")
BASE_URL = "https://www.wowhead.com/forever"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def clean_text(value: Any) -> str:
    value = re.sub(r"<[^>]*>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def spell_id_from_url(url: str) -> int | None:
    match = re.search(r"(?:^|[/])(?:forever/)?spell(?:=|/|%3[dD])(\d+)(?:[/#?]|$)", str(url))
    if not match:
        match = re.search(r"spell(?:=|%3[dD])(\d+)", str(url))
    return int(match.group(1)) if match else None


def normalize_list_row(row: dict[str, Any], class_key: str, kind: str) -> dict[str, Any]:
    raw_id = row.get("id", row.get("spell_id"))
    if raw_id is None:
        raw_id = spell_id_from_url(str(row.get("href", "")))
    try:
        spell_id = int(raw_id)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"missing spell id for {class_key}/{kind}: {row!r}") from exc
    if spell_id <= 0:
        raise ValueError(f"invalid spell id {spell_id}")
    name = clean_text(row.get("name") or row.get("label") or row.get("text"))
    if not name:
        raise ValueError(f"missing name for spell {spell_id}")
    level_raw = row.get("level")
    try:
        level = int(level_raw) if level_raw not in (None, "", "-") else None
    except (TypeError, ValueError):
        level = None
    rank_raw = row.get("rank")
    match = re.search(r"\bRank\s+(\d+)\b", str(rank_raw or name), re.I)
    rank = int(match.group(1)) if match else None
    url = f"{BASE_URL}/spell={spell_id}"
    return {
        "class_key": class_key, "kind": kind, "spell_id": spell_id,
        "name": name, "rank_hint": rank, "level_hint": level,
        "source_url": url, "list_row": row,
    }


def reported_count(text: str) -> int | None:
    # Wowhead lists can say '175 spells found' or '1 - 100 of 175'.
    for pattern in (r"([\d,]+)\s+spells?\s+found", r"(?:\d+)\s*[-–]\s*(?:\d+)\s+of\s+([\d,]+)"):
        m = re.search(pattern, text, re.I)
        if m:
            return int(m.group(1).replace(",", ""))
    return None


def complete_index(expected: int | None, collected: int, blocked: bool) -> bool:
    # Fail closed if the page omits the count. Wowhead commonly caps global lists at 1000.
    return not blocked and expected is not None and collected >= expected > 0


def initialize_db(db: sqlite3.Connection) -> None:
    db.executescript("""
    PRAGMA foreign_keys=ON;
    CREATE TABLE IF NOT EXISTS capture_batches (
      batch_id TEXT PRIMARY KEY, captured_at TEXT NOT NULL, source TEXT NOT NULL,
      client_build TEXT, status TEXT NOT NULL, notes TEXT
    );
    CREATE TABLE IF NOT EXISTS capture_lists (
      batch_id TEXT NOT NULL, class_key TEXT NOT NULL, kind TEXT NOT NULL,
      source_url TEXT NOT NULL, expected_count INTEGER,
      captured_count INTEGER NOT NULL, complete INTEGER NOT NULL,
      blocked_reason TEXT, content_sha256 TEXT,
      PRIMARY KEY(batch_id, class_key, kind),
      FOREIGN KEY(batch_id) REFERENCES capture_batches(batch_id)
    );
    CREATE TABLE IF NOT EXISTS spell_index (
      batch_id TEXT NOT NULL, class_key TEXT NOT NULL, kind TEXT NOT NULL,
      spell_id INTEGER NOT NULL, name TEXT NOT NULL,
      rank_hint INTEGER, level_hint INTEGER, source_url TEXT NOT NULL,
      raw_listview_json TEXT NOT NULL,
      PRIMARY KEY(batch_id, class_key, kind, spell_id),
      FOREIGN KEY(batch_id, class_key, kind)
        REFERENCES capture_lists(batch_id, class_key, kind)
    );
    CREATE TABLE IF NOT EXISTS spell_details (
      batch_id TEXT NOT NULL, spell_id INTEGER NOT NULL,
      source_url TEXT NOT NULL, page_title TEXT,
      raw_page_text TEXT NOT NULL, html_sha256 TEXT,
      captured_at TEXT NOT NULL, details_verified INTEGER NOT NULL,
      PRIMARY KEY(batch_id, spell_id),
      FOREIGN KEY(batch_id) REFERENCES capture_batches(batch_id)
    );
    CREATE TABLE IF NOT EXISTS spell_detail_snapshots (
      batch_id TEXT NOT NULL, spell_id INTEGER NOT NULL,
      final_url TEXT NOT NULL, http_status INTEGER NOT NULL,
      html_sha256 TEXT NOT NULL, html_bytes INTEGER NOT NULL,
      html_zlib BLOB NOT NULL,
      PRIMARY KEY(batch_id, spell_id),
      FOREIGN KEY(batch_id, spell_id) REFERENCES spell_details(batch_id, spell_id)
    );
    CREATE INDEX IF NOT EXISTS idx_spell_by_id ON spell_index(spell_id);
    CREATE INDEX IF NOT EXISTS idx_spell_class_kind ON spell_index(class_key,kind);
    """)
    db.commit()


def save_index(db: sqlite3.Connection, *, batch_id: str, class_key: str, kind: str,
               source_url: str, expected: int | None, rows: list[dict[str, Any]],
               blocked_reason: str | None, content_hash: str) -> dict[str, Any]:
    normalized: dict[int, dict[str, Any]] = {}
    errors: list[str] = []
    for row in rows:
        try:
            n = normalize_list_row(row, class_key, kind)
            normalized[n["spell_id"]] = n
        except ValueError as exc:
            errors.append(str(exc))
    ok = complete_index(expected, len(normalized), bool(blocked_reason) or bool(errors))
    db.execute("INSERT OR REPLACE INTO capture_lists VALUES (?,?,?,?,?,?,?,?,?)",
               (batch_id, class_key, kind, source_url, expected, len(normalized),
                int(ok), blocked_reason or (errors[0] if errors else None), content_hash))
    for n in normalized.values():
        db.execute("INSERT OR REPLACE INTO spell_index VALUES (?,?,?,?,?,?,?,?,?)",
                   (batch_id, class_key, kind, n["spell_id"], n["name"],
                    n["rank_hint"], n["level_hint"], n["source_url"],
                    json.dumps(n["list_row"], ensure_ascii=False, sort_keys=True)))
    db.commit()
    return {"class": class_key, "kind": kind, "expected": expected,
            "captured": len(normalized), "complete": ok,
            "errors": errors[:3], "blocked": blocked_reason}


def page_rows(page) -> tuple[list[dict[str, Any]], str]:
    """Prefer the full Wowhead listview backing array; DOM is a fallback only."""
    data = page.evaluate("""() => {
      for (const k of ['listviewspells', 'listviewspell', 'listviewabilities', 'listviewtalents']) {
        if (Array.isArray(window[k])) return { rows: window[k], source: k };
      }
      return {rows: [], source: 'dom'};
    }""")
    if isinstance(data, dict) and isinstance(data.get("rows"), list) and data["rows"]:
        return data["rows"], data.get("source", "listview")
    # Rendered, paginated list rows. Do not silently label one page as complete.
    data = page.evaluate("""() => {
      const out = [];
      for (const tr of document.querySelectorAll('.listview-row')) {
        const a = Array.from(tr.querySelectorAll('a[href]')).find(x => /spell(?:=|%3[dD])\\d+/.test(x.getAttribute('href') || ''));
        if (!a) continue;
        const u = a.getAttribute('href') || '';
        const m = u.match(/spell(?:=|%3[dD])(\\d+)/);
        if (!m) continue;
        out.push({id: Number(m[1]), name: a.textContent || '',
                  href: u, rendered_text: tr.innerText || ''});
      }
      return out;
    }""")
    return data if isinstance(data, list) else [], "dom"


def next_page(page) -> bool:
    """Conservative best-effort Wowhead pagination: never declare complete on failure."""
    for selector in (".listview-nav a:has-text('Next')", ".listview-nav-next",
                     "a:has-text('Next ›')"):
        locator = page.locator(selector)
        if locator.count():
            node = locator.first
            cls = (node.get_attribute("class") or "").lower()
            if "disabled" in cls:
                return False
            try:
                node.click(timeout=5000)
                page.wait_for_timeout(500)
                return True
            except Exception:
                continue
    return False


def capture_listing(page, *, class_key: str, kind: str,
                    timeout_ms: int, settle_ms: int, max_pages: int) -> dict[str, Any]:
    url = f"{BASE_URL}/spells/{kind}/{class_key}"
    response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    status = response.status if response else None
    page.wait_for_timeout(settle_ms)
    title = page.title()
    body = page.locator("body").inner_text(timeout=10000)
    blocked_reason = next((m for m in BLOCK_MARKERS if m in (title + "\n" + body[:15000]).lower()), None)
    if status and status >= 400:
        blocked_reason = blocked_reason or f"HTTP {status}"
    expected = reported_count(body)
    rows, source = page_rows(page)
    ids = {r.get("id") for r in rows if isinstance(r, dict) and r.get("id") is not None}
    page_count = 1
    # If page_rows used the rendered DOM, walk the listview pages and accumulate.
    if source == "dom" and not blocked_reason:
        while (expected is None or len(ids) < expected) and page_count < max_pages:
            before = (len(ids), page.locator(".listview-row").count())
            if not next_page(page):
                break
            more, _ = page_rows(page)
            new = 0
            for r in more:
                if isinstance(r, dict) and r.get("id") not in ids:
                    ids.add(r.get("id")); rows.append(r); new += 1
            page_count += 1
            if not new and before[0] == len(ids):
                break
    return {"url": url, "expected": expected, "rows": rows,
            "blocked_reason": blocked_reason, "page_title": title,
            "capture_backend": source, "page_count": page_count,
            "http_status": status, "html_sha256": hashlib.sha256(page.content().encode()).hexdigest()}


def capture_details(page, *, batch_id: str, db: sqlite3.Connection,
                    timeout_ms: int, settle_ms: int, max_details: int | None,
                    spell_ids: list[int] | None = None) -> dict[str, int]:
    """Capture durable HTML evidence, verifying identity before marking complete.

    The snapshot is *not* verified executable spell data. An old text-only
    detail row must be recaptured, even when its legacy verified flag is 1.
    """
    # Do not equate the presence of a row with a verified snapshot: an earlier
    # successful capture may have been corrupted, altered, or lost its index
    # authority. Resume must re-capture those rows, not silently skip them.
    sql = "SELECT DISTINCT spell_id FROM spell_index WHERE batch_id=?"
    params: tuple = (batch_id,)
    if spell_ids is not None:
        if not spell_ids or any(x <= 0 for x in spell_ids):
            raise ValueError('spell IDs must be positive and nonempty')
        indexed = {int(r[0]) for r in db.execute(
            'SELECT DISTINCT spell_id FROM spell_index WHERE batch_id=?', (batch_id,))}
        missing = sorted(set(spell_ids) - indexed)
        if missing:
            raise ValueError(f'spell IDs not indexed in batch {batch_id}: {missing}')
        sql += ' AND spell_id IN (' + ','.join('?' for _ in spell_ids) + ')'
        params += tuple(spell_ids)
    sql += " ORDER BY spell_id"
    ids = []
    skipped = 0
    for (spell_id,) in db.execute(sql, params).fetchall():
        try:
            read_verified_spell_detail_snapshot(
                db, batch_id=batch_id, spell_id=int(spell_id))
        except MissingVerifiedSpellDetail:
            ids.append(int(spell_id))
            if max_details is not None and len(ids) >= max_details:
                break
        else:
            skipped += 1
    stats = {"found": len(ids), "captured": 0, "skipped": skipped, "failed": 0}
    for i, spell_id in enumerate(ids, start=1):
        url = f"{BASE_URL}/spell={spell_id}"
        names = [r[0] for r in db.execute(
            'SELECT DISTINCT name FROM spell_index WHERE batch_id=? AND spell_id=?',
            (batch_id, spell_id))]
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(settle_ms)
            title = page.title()
            body = page.locator("body").inner_text(timeout=10000)[:60000]
            markup = page.content()
            encoded = markup.encode('utf-8')
            status = response.status if response else None
            final_url = page.url
            valid = len(encoded) <= MAX_HTML_BYTES and verified_spell_page(
                spell_id=spell_id, names=names, final_url=final_url,
                title=title, body=body, status=status, html_length=len(encoded))
            captured_at = now_iso()
            html_hash = hashlib.sha256(encoded).hexdigest()
            # Never replace accepted source evidence with a blocked, wrong-ID,
            # partial or corrupted fetch.  Failed attempts are reflected in the
            # returned manifest and may be retried; the database remains intact.
            if valid:
                with db:
                    db.execute('DELETE FROM spell_detail_snapshots WHERE batch_id=? AND spell_id=?',
                               (batch_id, spell_id))
                    db.execute("INSERT OR REPLACE INTO spell_details VALUES (?,?,?,?,?,?,?,?)",
                               (batch_id, spell_id, url, title, body[:60000], html_hash,
                                captured_at, 1))
                    db.execute("""INSERT INTO spell_detail_snapshots
                        (batch_id,spell_id,final_url,http_status,html_sha256,html_bytes,html_zlib)
                        VALUES (?,?,?,?,?,?,?)""",
                        (batch_id, spell_id, final_url, status, html_hash,
                         len(encoded), zlib.compress(encoded, level=6)))
            stats["captured" if valid else "failed"] += 1
            print(f"  detail {i}/{len(ids)} {spell_id}: {'OK' if valid else 'INVALID'}", flush=True)
        except Exception as exc:
            stats["failed"] += 1
            print(f"  detail {i}/{len(ids)} {spell_id}: {type(exc).__name__}: {exc}", flush=True)
    return stats


def load_detail_plan(path: Path, db: sqlite3.Connection) -> list[dict]:
    """Validate a multi-batch browser session against complete source indexes.

    This never grants acquisition or executable mechanics. It only chooses
    already indexed spell IDs for independent HTML capture.
    """
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict) or obj.get("schema") != "forever_detail_session_v1":
        raise ValueError("INVALID_DETAIL_SESSION_SCHEMA")
    chunks = obj.get("chunks")
    if not isinstance(chunks, list) or not chunks or len(chunks)>12:
        raise ValueError("EMPTY_DETAIL_SESSION")
    seen = set()
    out = []
    for chunk in chunks:
        if not isinstance(chunk, dict) or set(chunk) != {"batch_id", "spell_ids"}:
            raise ValueError("INVALID_DETAIL_SESSION_CHUNK")
        bid, ids = chunk["batch_id"], chunk["spell_ids"]
        if not isinstance(bid, str) or not bid or not isinstance(ids, list) or not ids or len(ids)>250:
            raise ValueError("INVALID_DETAIL_SESSION_IDS")
        if any(type(sid) is not int or sid <= 0 for sid in ids):
            raise ValueError("INVALID_DETAIL_SESSION_IDS")
        if len(ids) != len(set(ids)) or any((bid, sid) in seen for sid in ids):
            raise ValueError("DUPLICATE_DETAIL_SESSION_IDS")
        valid = {int(r[0]) for r in db.execute('''SELECT i.spell_id FROM spell_index i
            JOIN capture_lists l ON l.batch_id=i.batch_id AND l.class_key=i.class_key
            AND l.kind=i.kind JOIN capture_batches b ON b.batch_id=i.batch_id
            WHERE i.batch_id=? AND i.kind='abilities' AND l.complete=1
            AND b.status='complete' ''', (bid,))}
        if not valid or set(ids) - valid:
            raise ValueError("DETAIL_SESSION_IDS_NOT_COMPLETE_INDEX")
        seen.update((bid, sid) for sid in ids)
        out.append({"batch_id": bid, "spell_ids": ids})
    return out


def capture_main(args: argparse.Namespace) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("pip install playwright", file=sys.stderr)
        return 2
    db_path = args.db.expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(db_path)
    initialize_db(db)
    batch_id = args.batch_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    record = db.execute("SELECT batch_id FROM capture_batches WHERE batch_id=?", (batch_id,)).fetchone()
    detail_plan = load_detail_plan(args.detail_plan, db) if args.detail_plan else None
    if detail_plan is not None and getattr(args, 'detail_workers', 1) > 1:
        # Same source verifier and canonical SQLite schema, but concurrent
        # independent pages under ONE browser profile and ONE SQLite writer.
        import asyncio
        from tools.wf313_parallel_verified_capture import capture_browser_plan
        db.close()
        result = asyncio.run(capture_browser_plan(
            db_path=db_path, plan_path=args.detail_plan,
            user_data_dir=args.user_data_dir, channel=args.channel,
            headless=args.headless, timeout_ms=args.timeout_ms,
            settle_ms=args.settle_ms, workers=args.detail_workers))
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0 if result['failed_unverified'] == 0 else 1
    if args.details_only and detail_plan is None and record is None:
        db.close()
        raise ValueError(f'--details-only requires existing --batch-id, missing: {batch_id}')
    if args.details_only and detail_plan is None and not db.execute(
        'SELECT 1 FROM spell_index WHERE batch_id=? LIMIT 1', (batch_id,)).fetchone():
        db.close()
        raise ValueError('--details-only requires indexed spell rows in selected batch')
    if record is None and detail_plan is None:
        db.execute("INSERT INTO capture_batches VALUES (?,?,?,?,?,?)",
                   (batch_id, now_iso(), BASE_URL, None, "in_progress", "Class abilities/talents only. Tree grid and prereqs NOT asserted."))
        db.commit()
    output = db_path.parent / (f"wowhead_abilities_manifest_multi_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json"
                               if detail_plan else f"wowhead_abilities_manifest_{batch_id}.json")
    results: list[dict[str, Any]] = []
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(args.user_data_dir.expanduser().resolve()),
            channel=args.channel, headless=args.headless, locale="en-US")
        page = context.pages[0] if context.pages else context.new_page()
        try:
            for class_key in ([] if args.details_only else args.classes):
                for kind in args.kinds:
                    if args.resume and db.execute(
                        "SELECT complete FROM capture_lists WHERE batch_id=? AND class_key=? AND kind=?",
                        (batch_id, class_key, kind)).fetchone() == (1,):
                        print(f"SKIP {class_key}/{kind} (complete)", flush=True)
                        continue
                    print(f"FETCH {class_key}/{kind}", flush=True)
                    try:
                        capture = capture_listing(page, class_key=class_key, kind=kind,
                             timeout_ms=args.timeout_ms, settle_ms=args.settle_ms,
                             max_pages=args.max_pages)
                        result = save_index(db, batch_id=batch_id, class_key=class_key, kind=kind,
                              source_url=capture["url"], expected=capture["expected"],
                              rows=capture["rows"], blocked_reason=capture["blocked_reason"],
                              content_hash=capture["html_sha256"])
                        result.update({k:capture[k] for k in ("http_status", "capture_backend", "page_count")})
                    except Exception as exc:
                        result = {"class": class_key, "kind": kind, "complete": False,
                                  "error": f"{type(exc).__name__}: {exc}"}
                    results.append(result)
                    print("  " + json.dumps(result, ensure_ascii=False), flush=True)
            detail_stats = None
            if args.details:
                if detail_plan is None:
                    detail_stats = capture_details(page, batch_id=batch_id, db=db,
                         timeout_ms=args.timeout_ms, settle_ms=args.settle_ms,
                         max_details=args.max_details, spell_ids=args.spell_ids)
                else:
                    detail_stats = {"found": 0, "captured": 0, "skipped": 0,
                                    "failed": 0, "chunks": []}
                    for chunk in detail_plan:
                        try:
                            stats = capture_details(page, batch_id=chunk["batch_id"], db=db,
                                timeout_ms=args.timeout_ms, settle_ms=args.settle_ms,
                                max_details=None, spell_ids=chunk["spell_ids"])
                        except Exception as exc:
                            stats = {"found": len(chunk["spell_ids"]), "captured": 0,
                                     "skipped": 0, "failed": len(chunk["spell_ids"]),
                                     "error": f"{type(exc).__name__}: {exc}"}
                        for key in ("found", "captured", "skipped", "failed"):
                            detail_stats[key] += stats[key]
                        detail_stats["chunks"].append({"batch_id": chunk["batch_id"],
                            "requested": len(chunk["spell_ids"]), **stats})
                        print("CHUNK " + json.dumps(detail_stats["chunks"][-1]), flush=True)
        finally:
            context.close()
    checked = list(db.execute("SELECT class_key,kind,complete FROM capture_lists WHERE batch_id=?", (batch_id,)))
    all_ok = (True if detail_plan is not None else
              (all(bool(x[2]) for x in checked) and len(checked) > 0
               if args.details_only else
               len(checked) == len(args.classes) * len(args.kinds) and all(x[2] for x in checked)))
    if not args.details_only and detail_plan is None:
        db.execute("UPDATE capture_batches SET status=? WHERE batch_id=?", ("complete" if all_ok else "incomplete", batch_id))
    db.commit()
    manifest = {"schema":"forever_abilities_capture_v1", "batch_id":batch_id if detail_plan is None else None,
                "captured_at":now_iso(), "sqlite":str(db_path), "classes":args.classes,
                "kinds":args.kinds, "lists":results, "index_complete":bool(all_ok),
                "detail_stats":detail_stats, "warning":"Spell listings are not talent-tree geometry; source-backed raw data only."}
    output.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"\nSQLite: {db_path}\nManifest: {output}\nINDEX COMPLETE: {all_ok}", flush=True)
    if args.details and detail_stats and detail_stats["failed"]:
        print("WARNING: some detail pages failed; rerun with --resume --batch-id", batch_id)
    db.close()
    return 0 if all_ok and (not detail_stats or not detail_stats["failed"]) else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--classes", nargs="+", default=list(CLASSES), choices=CLASSES)
    ap.add_argument("--kinds", nargs="+", default=list(KINDS), choices=KINDS)
    ap.add_argument("--db", type=Path, default=Path("data/forever/catalogue/forever_abilities.sqlite"))
    ap.add_argument("--channel", default="chrome")
    ap.add_argument("--user-data-dir", type=Path, default=Path(".wowhead-chrome-profile"))
    ap.add_argument("--headless", action="store_true", help="Only use when authenticated headless browsing works")
    ap.add_argument("--timeout-ms", type=int, default=60000)
    ap.add_argument("--settle-ms", type=int, default=1200)
    ap.add_argument("--max-pages", type=int, default=20)
    ap.add_argument("--details", action="store_true", help="Visit every captured spell/talent page; potentially thousands of requests")
    ap.add_argument("--details-only", action="store_true", help="Reuse existing batch index; no list fetching or batch-status edits")
    ap.add_argument("--spell-ids", type=int, nargs="+", help="Only capture these existing indexed spell IDs (with --details-only)")
    ap.add_argument("--detail-plan", type=Path, help="Multi-batch verified detail session; one persistent browser context")
    ap.add_argument("--detail-workers", type=int, default=4,
                    help="Independent pages per persistent source browser (1=legacy serial)")
    ap.add_argument("--max-details", type=int, default=None, help="Development throttle for --details")
    ap.add_argument("--batch-id", default=None, help="Reuse one capture batch for interrupted runs")
    ap.add_argument("--resume", action="store_true", help="Skip complete class lists and verified detail pages")
    args = ap.parse_args(argv)
    if not 1 <= args.detail_workers <= 8:
        ap.error('--detail-workers must be between 1 and 8')
    if args.details_only:
        args.details = True
        if not args.batch_id and not args.detail_plan:
            ap.error('--details-only requires --batch-id or --detail-plan')
    if args.detail_plan and (not args.details_only or args.batch_id or args.spell_ids):
        ap.error('--detail-plan requires --details-only and excludes --batch-id/--spell-ids')
    if args.spell_ids is not None and not args.details_only:
        ap.error('--spell-ids requires --details-only')
    if args.details and args.max_details is not None and args.max_details < 1:
        ap.error("--max-details must be positive")
    return capture_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
