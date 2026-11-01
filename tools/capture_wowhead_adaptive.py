from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.rulesets.forever.items.wowhead_queries import (
    CANONICAL_CLASS_QUERIES,
    bands_for_class,
    WowheadItemBand,
    build_search_url, child_capture_coordinates,
)

BLOCK_MARKERS = (
    "access denied", "error 403", "forbidden", "just a moment",
    "checking your browser", "verify you are human", "captcha",
)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def detect_blocked(html: str, title: str) -> str | None:
    haystack = f"{title}\n{html[:20000]}".lower()
    return next((m for m in BLOCK_MARKERS if m in haystack), None)


def make_band(class_key: str, lo: int, hi: int, quality: int | None = None) -> WowheadItemBand:
    q = CANONICAL_CLASS_QUERIES[class_key]
    return WowheadItemBand(
        class_key=q.class_key, class_id=q.class_id,
        min_item_level=lo, max_item_level=hi,
        side=q.side, filter_expr=q.filter_expr,
        url=build_search_url(q, lo, hi, quality=quality), quality=quality,
    )


def capture_one(page, band: WowheadItemBand, out_dir: Path, timeout_ms: int, settle_ms: int) -> dict:
    response = page.goto(band.url, wait_until="domcontentloaded", timeout=timeout_ms)
    status = response.status if response is not None else None
    try:
        page.wait_for_function(
            """() => Array.isArray(window.listviewitems) ||
                     /items? found/i.test(document.body ? document.body.innerText : '')""",
            timeout=min(timeout_ms, 30000),
        )
    except Exception:
        pass
    if settle_ms:
        page.wait_for_timeout(settle_ms)

    html = page.content()
    title = page.title()
    body = page.locator("body").inner_text(timeout=5000) if page.locator("body").count() else ""
    blocked = detect_blocked(html, title)

    match = re.search(r"([\d,]+)\s+items?\s+found(?:\s*\(([\d,]+)\s+displayed\))?", body, re.I)
    found = int(match.group(1).replace(",", "")) if match else None
    displayed = int(match.group(2).replace(",", "")) if match and match.group(2) else None

    try:
        rows = page.evaluate("() => Array.isArray(window.listviewitems) ? window.listviewitems : null")
    except Exception:
        rows = None
    rows = rows if isinstance(rows, list) else []
    ids = [r.get("id") for r in rows if isinstance(r, dict) and r.get("id") is not None]
    unique_ids = len(set(ids))

    suffix = "" if band.quality is None else f"_quality_{band.quality}"
    stem = f"{band.class_key}_ilvl_{band.min_item_level}_{band.max_item_level}{suffix}"
    html_bytes = html.encode("utf-8")
    _atomic_bytes(out_dir / f"{stem}.html", html_bytes)
    rows_bytes = (json.dumps(rows, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    _atomic_bytes(out_dir / f"{stem}.listview.json", rows_bytes)

    accepted = (blocked is None and (bool(rows) or found == 0)
                and not (found is not None and found > 0 and not rows))
    truncated = (
        unique_ids >= 1000 or
        (found is not None and displayed is not None and found > displayed) or
        (found is not None and found > len(rows) and displayed is None)
    )

    return {
        **({"quality": band.quality} if band.quality is not None else {}),
        "class_key": band.class_key,
        "class_id": band.class_id,
        "min_item_level": band.min_item_level,
        "max_item_level": band.max_item_level,
        "url": band.url,
        "http_status": status,
        "title": title,
        "found_count": found,
        "displayed_count": displayed,
        "listview_rows": len(rows),
        "listview_unique_ids": unique_ids,
        "blocked_marker": blocked,
        "accepted": accepted,
        "needs_split": bool(accepted and truncated),
        "html_file": f"{stem}.html",
        "listview_file": f"{stem}.listview.json",
        "html_sha256": sha256(html_bytes),
        "listview_sha256": sha256(rows_bytes),
    }


def _atomic_bytes(path: Path, value: bytes) -> None:
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('wb') as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _atomic_json(path: Path, value: dict | list) -> None:
    """Commit the journal only after all referenced source files are durable."""
    encoded = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    _atomic_bytes(path, encoded)


def _verified_attempt(record: dict, band: WowheadItemBand, folder: Path) -> None:
    """Replay the captured source evidence, never merely trust a journal flag."""
    if (record.get('class_key') != band.class_key
            or record.get('class_id') != band.class_id
            or record.get('min_item_level') != band.min_item_level
            or record.get('max_item_level') != band.max_item_level
            or record.get('url') != band.url
            or record.get('quality') != band.quality):
        raise ValueError('CAPTURE_RESUME_CLASS_OR_QUERY_MISMATCH')
    if record.get('accepted') is not True or record.get('http_status') != 200 or record.get('blocked_marker'):
        raise ValueError('CAPTURE_RESUME_UNVERIFIED_RESPONSE')
    for key, digest in (('html_file', 'html_sha256'), ('listview_file', 'listview_sha256')):
        filename = record.get(key)
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise ValueError('CAPTURE_RESUME_UNSAFE_SOURCE_PATH')
        try:
            source_bytes = (folder / filename).read_bytes()
        except OSError as exc:
            raise ValueError('CAPTURE_RESUME_SOURCE_FILE_MISSING') from exc
        if sha256(source_bytes) != record.get(digest):
            raise ValueError('CAPTURE_RESUME_SOURCE_HASH_MISMATCH')
    from src.rulesets.forever.items.source_capture_integrity import verify_html_found_count
    verify_html_found_count((folder / record['html_file']).read_bytes(),
                            record.get('found_count'),
                            required=(band.min_item_level == band.max_item_level
                                      and band.quality is None and bool(record.get('needs_split'))),
                            prefix='CAPTURE_RESUME_')
    try:
        rows = json.loads((folder / record['listview_file']).read_bytes())
        ids = {int(row['id']) for row in rows}
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError('CAPTURE_RESUME_INVALID_SOURCE_ROWS') from exc
    if (not isinstance(rows, list) or len(rows) != record.get('listview_rows')
            or len(ids) != record.get('listview_unique_ids')):
        raise ValueError('CAPTURE_RESUME_SOURCE_ROW_COUNT_MISMATCH')
    if (not record.get('needs_split') and (
            len(ids) >= 1000 or (record.get('found_count') is not None
            and record.get('found_count') > len(rows)))):
        raise ValueError('CAPTURE_RESUME_TRUNCATED_TERMINAL')


def run_adaptive_capture(class_key: str, folder: Path, capture_fn, *,
                         resume: bool = False, captured_at: str | None = None) -> dict:
    """Capture all 1–255 class listviews with durable, source-bound resume.

    ``capture_fn(band, folder)`` is the actual Playwright fetcher in production;
    injection permits deterministic crash/replay tests without fabricating P3.
    One class per manifest matches the existing verified-capture admission gate.
    """
    from src.rulesets.forever.items.source_capture_integrity import verify_class_capture

    if class_key not in CANONICAL_CLASS_QUERIES:
        raise ValueError('CAPTURE_UNKNOWN_CLASS')
    folder = Path(folder)
    path = folder / 'manifest.json'
    seeds = [list(pair) for pair in bands_for_class(class_key)]
    if resume:
        if not path.is_file():
            raise FileNotFoundError('CAPTURE_RESUME_MANIFEST_MISSING')
        manifest = json.loads(path.read_text(encoding='utf-8'))
        if (manifest.get('classes') != [class_key]
                or manifest.get('seed_bands') != seeds
                or manifest.get('capture_backend') != 'playwright_persistent_chrome_adaptive'):
            raise ValueError('CAPTURE_RESUME_CLASS_OR_QUERY_MISMATCH')
    else:
        if path.exists():
            raise FileExistsError('CAPTURE_EXISTS_USE_RESUME')
        folder.mkdir(parents=True, exist_ok=True)
        manifest = dict(schema_version=1,
            capture_backend='playwright_persistent_chrome_adaptive',
            captured_at=captured_at or datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            classes=[class_key], seed_bands=seeds, attempts=[], leaves=[], complete=False)
        _atomic_json(path, manifest)

    queue = [make_band(class_key, lo, hi) for lo, hi in seeds]
    leaves = []

    def split_children(band: WowheadItemBand) -> list[WowheadItemBand]:
        return [make_band(class_key, lo, hi, quality)
                for lo, hi, quality in child_capture_coordinates(
                    band.min_item_level, band.max_item_level, band.quality)]

    def check_quality_parent(record: dict, band: WowheadItemBand) -> None:
        if record.get('needs_split') and band.min_item_level == band.max_item_level and band.quality is None:
            if record.get('found_count') is None:
                raise ValueError('CAPTURE_QUALITY_PARENT_COUNT_REQUIRED')
            if int(record['found_count']) < int(record['listview_unique_ids']):
                raise ValueError('CAPTURE_QUALITY_PARENT_COUNT_INCONSISTENT')
    for record in manifest['attempts']:
        if not queue:
            raise ValueError('CAPTURE_RESUME_EXTRA_ATTEMPT')
        band = queue.pop(0)
        _verified_attempt(record, band, folder)
        check_quality_parent(record, band)
        if record['needs_split']:
            queue[0:0] = split_children(band)
        else:
            leaves.append(record)
    if manifest.get('leaves') != leaves:
        raise ValueError('CAPTURE_RESUME_LEAF_JOURNAL_MISMATCH')

    while queue:
        band = queue[0]
        result = capture_fn(band, folder)
        _verified_attempt(result, band, folder)
        check_quality_parent(result, band)
        queue.pop(0)
        if result.get('needs_split'):
            queue[0:0] = split_children(band)
        else:
            leaves.append(result)
        manifest['attempts'].append(result)
        manifest['leaves'] = list(leaves)
        _atomic_json(path, manifest)

    merged = []
    for leaf in leaves:
        merged.extend(json.loads((folder / leaf['listview_file']).read_text(encoding='utf-8')))
    ids = sorted({int(row['id']) for row in merged})
    _atomic_json(folder / f'{class_key}_merged.listview.json', merged)
    _atomic_json(folder / f'{class_key}_unique_item_ids.json', ids)
    verify_class_capture(folder, class_key)
    manifest['complete'] = True
    _atomic_json(path, manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='Resumable verified Wowhead Forever class capture using persistent Chrome.')
    ap.add_argument('classes', nargs='*', default=sorted(CANONICAL_CLASS_QUERIES))
    ap.add_argument('--channel', default='chrome')
    ap.add_argument('--headless', action='store_true')
    ap.add_argument('--executable-path', default=None)
    ap.add_argument('--user-data-dir', default='.wowhead-chrome-profile')
    ap.add_argument('--output', default=None)
    ap.add_argument('--timeout-ms', type=int, default=60000)
    ap.add_argument('--settle-ms', type=int, default=1500)
    ap.add_argument('--resume', action='store_true', help='Verify existing source bytes and continue unfinished bands')
    args = ap.parse_args(argv)
    unknown = sorted(set(args.classes) - set(CANONICAL_CLASS_QUERIES))
    if unknown:
        ap.error(f'unknown classes: {", ".join(unknown)}')
    if len(set(args.classes)) != len(args.classes):
        ap.error('duplicate class')
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('ERROR: install Playwright: pip install playwright', file=sys.stderr)
        return 2
    out_dir = Path(args.output or f'wowhead_adaptive_capture_{utc_stamp()}').resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(Path(args.user_data_dir).expanduser().resolve()),
            **({'executable_path': args.executable_path} if args.executable_path else {'channel': args.channel}),
            headless=args.headless, locale='en-US')
        page = context.pages[0] if context.pages else context.new_page()
        try:
            for class_key in args.classes:
                # The existing verifier expects one class per manifest. A
                # multi-class run stores independent, resumable class folders.
                folder = out_dir if len(args.classes) == 1 else out_dir / class_key
                continue_existing = args.resume and (folder / 'manifest.json').is_file()
                result = run_adaptive_capture(class_key, folder,
                    lambda band, target: capture_one(page, band, target, args.timeout_ms, args.settle_ms),
                    resume=continue_existing)
                print(f'[{class_key}] verified {len(result["leaves"])} leaves; '
                      f'captured {len(result["attempts"])} source pages', flush=True)
        finally:
            context.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
