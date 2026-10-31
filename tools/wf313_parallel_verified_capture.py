"""Concurrent, resume-safe capture of independently verified Wowhead HTML.

One persistent browser context, bounded independent pages, and ONE SQLite writer.
This is a transport for the existing canonical capture/verification pipeline,
not an alternate spell database or an executable-fact ingester. The async
transport is injectable so its legality and persistence can be tested offline.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from hashlib import sha256
from pathlib import Path
import sqlite3
import zlib

from tools.capture_forever_abilities_sqlite import (
    BASE_URL, MAX_HTML_BYTES, load_detail_plan, now_iso, verified_spell_page,
)
from src.v2.source_sqlite_detail_snapshots import (
    MissingVerifiedSpellDetail, read_verified_spell_detail_snapshot,
)


class InvalidCapture(ValueError):
    pass


def pending_plan(db: sqlite3.Connection, plan: list[dict]) -> tuple[list[tuple[str, int]], int]:
    """Revalidate planned IDs and every already captured snapshot before skipping.

    Plan authorization is performed by the existing load_detail_plan validator;
    callers cannot use this method to introduce new source IDs.
    """
    todo = []
    skipped = 0
    for chunk in plan:
        for sid in chunk['spell_ids']:
            try:
                read_verified_spell_detail_snapshot(db, batch_id=chunk['batch_id'], spell_id=sid)
            except MissingVerifiedSpellDetail:
                todo.append((chunk['batch_id'], sid))
            else:
                skipped += 1
    return todo, skipped


def persist_verified_capture(db: sqlite3.Connection, *, batch_id: str,
                             spell_id: int, response: dict) -> str:
    """Single SQLite transaction, fail closed; no write on invalid or wrong-ID HTML."""
    names = [r[0] for r in db.execute(
        'SELECT DISTINCT name FROM spell_index WHERE batch_id=? AND spell_id=?',
        (batch_id, spell_id))]
    html = response['html']
    if not isinstance(html, str):
        raise InvalidCapture('NON_TEXT_HTML')
    raw = html.encode('utf-8')
    if len(raw) > MAX_HTML_BYTES:
        raise InvalidCapture('HTML_TOO_LARGE')
    title = str(response['title'])
    body = str(response['body'])[:60000]
    final_url = str(response['final_url'])
    status = response['status']
    if not verified_spell_page(spell_id=spell_id, names=names, final_url=final_url,
                               title=title, body=body, status=status, html_length=len(raw)):
        raise InvalidCapture('UNVERIFIED_SOURCE_IDENTITY_OR_BLOCK_PAGE')
    url = f'{BASE_URL}/spell={spell_id}'
    html_hash = sha256(raw).hexdigest()
    with db:
        # A valid replacement is atomic. A failed verification rolls it back.
        db.execute('DELETE FROM spell_detail_snapshots WHERE batch_id=? AND spell_id=?',
                   (batch_id, spell_id))
        db.execute('INSERT OR REPLACE INTO spell_details VALUES (?,?,?,?,?,?,?,?)',
                   (batch_id, spell_id, url, title, body, html_hash, now_iso(), 1))
        db.execute('''INSERT INTO spell_detail_snapshots
            (batch_id,spell_id,final_url,http_status,html_sha256,html_bytes,html_zlib)
            VALUES (?,?,?,?,?,?,?)''',
            (batch_id, spell_id, final_url, status, html_hash,
             len(raw), zlib.compress(raw, level=6)))
        evidence = read_verified_spell_detail_snapshot(db, batch_id=batch_id, spell_id=spell_id)
        if evidence['html_sha256'] != html_hash:
            raise InvalidCapture('POST_WRITE_SOURCE_HASH_MISMATCH')
    return html_hash


async def capture_parallel(db: sqlite3.Connection, *, plan: list[dict], fetch,
                           workers: int = 4, retries: int = 1) -> dict:
    """Process planned pages with isolated fetch workers and serialized DB commits.

    `fetch(worker_index, spell_id, url)` is async and returns title, body, html,
    final_url, status. Failures are paid attempts and remain pending for resume.
    Browser-side errors are NOT interpreted as source evidence.
    """
    if not 1 <= workers <= 8 or not 0 <= retries <= 2:
        raise ValueError('INVALID_SOURCE_CAPTURE_BUDGET')
    todo, skipped = pending_plan(db, plan)
    queue = asyncio.Queue()
    for item in todo:
        queue.put_nowait(item)
    outcomes = []
    # Eight consecutive identity/block failures indicate a broken source
    # session (wrong route, expired login, anti-bot). Do not burn 2,000 pages.
    stop = asyncio.Event()
    consecutive_invalid = 0
    async def worker(index: int):
        nonlocal consecutive_invalid
        while not stop.is_set():
            try:
                batch_id, sid = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            attempts = 0
            try:
                for attempt in range(retries + 1):
                    attempts += 1
                    try:
                        result = await fetch(index, sid, f'{BASE_URL}/spell={sid}')
                        digest = persist_verified_capture(db, batch_id=batch_id,
                                                          spell_id=sid, response=result)
                        outcomes.append({'batch_id':batch_id,'spell_id':sid,
                                         'status':'VERIFIED_HTML','sha256':digest,
                                         'attempts':attempts})
                        consecutive_invalid = 0
                        break
                    except sqlite3.Error:
                        stop.set()
                        raise  # disk/schema failure is global, never a per-spell blocker
                    except Exception as exc:
                        # Invalid identity is not a transient network failure.
                        if isinstance(exc, InvalidCapture) or attempt >= retries:
                            outcomes.append({'batch_id':batch_id,'spell_id':sid,
                                             'status':'FAILED_NOT_VERIFIED',
                                             'reason':f'{type(exc).__name__}:{exc}'[:200],
                                             'attempts':attempts})
                            if isinstance(exc, InvalidCapture):
                                consecutive_invalid += 1
                                if consecutive_invalid >= 8:
                                    stop.set()
                            else:
                                consecutive_invalid = 0
                            break
                        await asyncio.sleep(0.05 * (attempt + 1))
            finally:
                queue.task_done()
    await asyncio.gather(*(worker(i) for i in range(min(workers, max(1,len(todo))))))
    outcomes.sort(key=lambda x:(x['batch_id'],x['spell_id']))
    counts = Counter(x['status'] for x in outcomes)
    return {'planned':len(todo)+skipped,'previously_verified':skipped,
            'attempted_unique':len(todo),'newly_verified':counts['VERIFIED_HTML'],
            'failed_unverified':counts['FAILED_NOT_VERIFIED'],
            'fetch_attempts_including_failures':sum(x['attempts'] for x in outcomes),
            'worker_count':workers,'results':outcomes,
            'stopped_on_repeated_invalid_source':stop.is_set(),
            'unattempted_pending':len(todo)-len(outcomes),
            'source_evidence_only':True,'executable_promotions':0,'accepted_checkpoints':0}


async def capture_browser_plan(*, db_path: Path, plan_path: Path,
                               user_data_dir: Path, channel: str,
                               headless: bool, timeout_ms: int,
                               settle_ms: int, workers: int) -> dict:
    """Bounded Playwright worker pages share one authenticated browser profile."""
    from playwright.async_api import async_playwright
    with sqlite3.connect(db_path) as db:
        plan = load_detail_plan(plan_path, db)
        async with async_playwright() as playwright:
            context = await playwright.chromium.launch_persistent_context(
                str(user_data_dir.expanduser().resolve()), channel=channel,
                headless=headless, locale='en-US')
            pages = []
            try:
                # Create all worker pages before launching tasks. One page per
                # worker prevents concurrent navigation of the same page.
                pages = [await context.new_page() for _ in range(workers)]
                async def fetch(index, sid, url):
                    page = pages[index]
                    response = await page.goto(url, wait_until='domcontentloaded',
                                               timeout=timeout_ms)
                    if settle_ms:
                        await page.wait_for_timeout(settle_ms)
                    return {'status':response.status if response else None,
                            'final_url':page.url,'title':await page.title(),
                            'body':(await page.locator('body').inner_text(timeout=10000))[:60000],
                            'html':await page.content()}
                result = await capture_parallel(db, plan=plan, fetch=fetch, workers=workers)
            finally:
                await context.close()
    return result
