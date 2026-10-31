from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tarfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

# Allow direct execution via `python tools/capture_wowhead.py` on Windows/Git Bash.
# Python otherwise puts only tools/ on sys.path, not the repository root.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.rulesets.forever.items.wowhead_queries import all_canonical_bands, canonical_bands


BLOCK_MARKERS = (
    "access denied",
    "error 403",
    "forbidden",
    "just a moment",
    "checking your browser",
    "verify you are human",
    "captcha",
)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value)


def _detect_blocked(html: str, title: str) -> str | None:
    haystack = f"{title}\n{html[:20000]}".lower()
    for marker in BLOCK_MARKERS:
        if marker in haystack:
            return marker
    return None


def _capture_one(page, band, out_dir: Path, timeout_ms: int, settle_ms: int) -> dict:
    started = datetime.now(timezone.utc)
    response = page.goto(band.url, wait_until="domcontentloaded", timeout=timeout_ms)
    status = response.status if response is not None else None

    # Wowhead hydrates list data client-side. networkidle is useful when it arrives,
    # but is not mandatory because ad/analytics requests can keep a page busy.
    try:
        page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 20000))
    except Exception:
        pass

    # Wait for either the visible result summary or at least one Forever item link.
    try:
        page.wait_for_function(
            """() => {
                const text = document.body ? document.body.innerText : '';
                return /items? found/i.test(text) ||
                       !!document.querySelector('a[href*="/forever/item="]');
            }""",
            timeout=min(timeout_ms, 30000),
        )
    except Exception:
        # Still save the page for diagnosis; validation below decides acceptance.
        pass

    if settle_ms:
        page.wait_for_timeout(settle_ms)

    html = page.content()
    title = page.title()
    body_text = page.locator("body").inner_text(timeout=5000) if page.locator("body").count() else ""
    blocked_marker = _detect_blocked(html, title)

    filename = _safe_name(f"{band.class_key}_ilvl_{band.min_item_level}_{band.max_item_level}.html")
    html_path = out_dir / filename
    html_bytes = html.encode("utf-8")
    html_path.write_bytes(html_bytes)

    # Small text dump makes failures easy to inspect without opening a browser.
    text_path = html_path.with_suffix(".txt")
    text_path.write_text(body_text[:200000], encoding="utf-8")

    found_match = re.search(r"([\d,]+)\s+items?\s+found(?:\s*\(([\d,]+)\s+displayed\))?", body_text, re.I)
    found_count = int(found_match.group(1).replace(",", "")) if found_match else None
    displayed_count = int(found_match.group(2).replace(",", "")) if found_match and found_match.group(2) else None
    item_link_count = page.locator('a[href*="/forever/item="]').count()

    accepted = (
        (status is None or 200 <= status < 400)
        and blocked_marker is None
        and (found_count is not None or item_link_count > 0)
    )

    return {
        "class_key": band.class_key,
        "class_id": band.class_id,
        "band_key": band.band_key,
        "min_item_level": band.min_item_level,
        "max_item_level": band.max_item_level,
        "url": band.url,
        "http_status": status,
        "title": title,
        "html_file": filename,
        "text_file": text_path.name,
        "html_bytes": len(html_bytes),
        "html_sha256": _sha256(html_bytes),
        "found_count": found_count,
        "displayed_count": displayed_count,
        "dom_item_link_count": item_link_count,
        "blocked_marker": blocked_marker,
        "accepted": accepted,
        "started_at": started.isoformat().replace("+00:00", "Z"),
        "finished_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture canonical Wowhead Forever item search pages with Playwright.")
    parser.add_argument("classes", nargs="*", default=["mage", "druid", "paladin", "hunter"], help="Canonical class keys")
    parser.add_argument("--headed", action="store_true", help="Show browser window (useful if Wowhead presents a challenge)")
    parser.add_argument("--channel", default=None, help="Playwright browser channel, e.g. chrome or msedge")
    parser.add_argument("--timeout-ms", type=int, default=60000)
    parser.add_argument("--settle-ms", type=int, default=2500)
    parser.add_argument("--output", default=None, help="Output directory; default wowhead_capture_<UTC stamp>")
    parser.add_argument("--no-archive", action="store_true", help="Do not create .tar.gz bundle")
    args = parser.parse_args(argv)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: Playwright is not installed. Run: pip install playwright && python -m playwright install chromium", file=sys.stderr)
        return 2

    known = {band.class_key for band in all_canonical_bands()}
    unknown = sorted(set(args.classes) - known)
    if unknown:
        parser.error(f"unknown class key(s): {', '.join(unknown)}; known: {', '.join(sorted(known))}")

    stamp = _utc_stamp()
    out_dir = Path(args.output or f"wowhead_capture_{stamp}").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    bands = [band for class_key in args.classes for band in canonical_bands(class_key)]
    manifest = {
        "schema_version": 1,
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "capture_backend": "playwright",
        "headed": bool(args.headed),
        "channel": args.channel,
        "bands": [],
    }

    with sync_playwright() as p:
        launch_kwargs = {"headless": not args.headed}
        if args.channel:
            launch_kwargs["channel"] = args.channel
        browser = p.chromium.launch(**launch_kwargs)
        context = browser.new_context(locale="en-US")
        page = context.new_page()
        try:
            for index, band in enumerate(bands, 1):
                print(f"[{index}/{len(bands)}] {band.band_key} -> {band.url}", flush=True)
                try:
                    result = _capture_one(page, band, out_dir, args.timeout_ms, args.settle_ms)
                except Exception as exc:
                    result = {
                        "class_key": band.class_key,
                        "class_id": band.class_id,
                        "band_key": band.band_key,
                        "min_item_level": band.min_item_level,
                        "max_item_level": band.max_item_level,
                        "url": band.url,
                        "accepted": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                manifest["bands"].append(result)
                state = "OK" if result.get("accepted") else "FAIL"
                print(
                    f"  {state} status={result.get('http_status')} found={result.get('found_count')} "
                    f"displayed={result.get('displayed_count')} links={result.get('dom_item_link_count')} "
                    f"blocked={result.get('blocked_marker')}",
                    flush=True,
                )
        finally:
            context.close()
            browser.close()

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    accepted = sum(1 for row in manifest["bands"] if row.get("accepted"))
    failed = len(manifest["bands"]) - accepted
    print(f"Captured: {accepted} accepted, {failed} failed -> {out_dir}")

    if not args.no_archive:
        archive = out_dir.with_suffix(".tar.gz")
        with tarfile.open(archive, "w:gz") as tf:
            tf.add(out_dir, arcname=out_dir.name)
        print(f"Archive: {archive}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
