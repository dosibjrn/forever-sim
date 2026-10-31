from __future__ import annotations

"""Capture -> raw snapshot -> normalize -> canonical TalentsForever references.

This intentionally mirrors the Wowhead capture model.  Runtime code never
fetches TalentsForever.  A failed/invalid capture leaves the canonical last-known-
good JSON byte-for-byte untouched.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_URLS = {
    "druid": "https://talentsforever.com/druid/60/5032220115501351--505203-6",
}
DEFAULT_CANONICAL_DIR = ROOT / "data" / "forever" / "reference_builds" / "talentsforever"

_SPLIT_RE = re.compile(r"(?<!\d)(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})(?!\d)")
_BUILD_RE = re.compile(r"\b(?:build|version)\s*[:#]?\s*(\d+(?:\.\d+){1,3})\b", re.I)
_COUNT_PATTERNS = {
    "shared": re.compile(r"(?:shared|shares?)\s*[:·-]?\s*([\d,]+)", re.I),
    "saved": re.compile(r"(?:saved|saves?)\s*[:·-]?\s*([\d,]+)", re.I),
    "opened": re.compile(r"(?:opened|opens?|views?)\s*[:·-]?\s*([\d,]+)", re.I),
    "close_builds": re.compile(r"(?:close\s+builds?|similar\s+builds?)\s*[:·-]?\s*([\d,]+)", re.I),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    data = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n").encode("utf-8")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _count(text: str, key: str) -> int | None:
    m = _COUNT_PATTERNS[key].search(text or "")
    return int(m.group(1).replace(",", "")) if m else None


def _family_for_split(split: tuple[int, int, int]) -> str:
    names = ("balance", "feral", "restoration")
    mx = max(split)
    return names[next(i for i, v in enumerate(split) if v == mx)]


def _extract_rows(raw: dict, class_name: str) -> list[dict]:
    candidates = list(raw.get("candidates") or [])
    # Fixture/converter-friendly explicit rows are accepted in raw snapshots too.
    candidates += list(raw.get("reference_rows") or [])
    seen: set[tuple[int, int, int]] = set()
    rows = []
    for candidate in candidates:
        text = str(candidate.get("text") or candidate.get("label") or "")
        split_v = candidate.get("split")
        if isinstance(split_v, list) and len(split_v) == 3:
            split = tuple(int(x) for x in split_v)
        else:
            m = _SPLIT_RE.search(text)
            if not m:
                continue
            split = tuple(int(x) for x in m.groups())
        if sum(split) <= 0 or split in seen:
            continue
        seen.add(split)
        href = str(candidate.get("href") or candidate.get("source_url") or raw.get("url") or "")
        if href and href.startswith("/"):
            href = urljoin("https://talentsforever.com/", href)
        pop = {k: _count(text, k) for k in _COUNT_PATTERNS}
        for k in pop:
            if candidate.get(k) is not None:
                pop[k] = int(candidate[k])
        rank = candidate.get("overall_rank")
        rows.append({
            "class": class_name,
            "build_type": str(candidate.get("build_type") or _family_for_split(split)),
            "overall_rank": int(rank) if rank is not None else None,
            "split": list(split),
            "tree_points": dict(zip(("balance", "feral", "restoration"), split)) if class_name == "druid" else {},
            "source_url": href or raw.get("url"),
            "popularity": pop,
            "talent_ranks": dict(candidate.get("talent_ranks") or {}),
            "leveling_order": [str(x) for x in (candidate.get("leveling_order") or ())],
            "allocation_detail_status": "exact" if candidate.get("talent_ranks") else "family_split_only",
        })
    # Prefer source rank, then stable split/family ordering.
    rows.sort(key=lambda r: (r["overall_rank"] is None, r["overall_rank"] or 10**9, r["build_type"], r["split"]))
    # When source provides no ranks, visible order is the only honest rank.
    for i, row in enumerate(rows, 1):
        if row["overall_rank"] is None:
            row["overall_rank"] = i
    return rows


def normalize_capture(raw: dict, *, requested_per_build_type: int = 3) -> dict:
    class_name = str(raw.get("class") or "").lower()
    if class_name != "druid":
        raise ValueError(f"unsupported reference class: {class_name!r}")
    if not raw.get("accepted", True):
        raise ValueError("capture was not accepted")
    rows = _extract_rows(raw, class_name)
    if not rows:
        raise ValueError("capture contains no source-visible reference families")
    source_build = raw.get("source_build")
    if not source_build:
        m = _BUILD_RE.search(str(raw.get("body_text") or ""))
        source_build = m.group(1) if m else None
    captured_at = raw.get("captured_at") or _now()
    builds = []
    for row in rows:
        split = row["split"]
        rid = f"tf-{class_name}-{row['build_type']}-{'-'.join(map(str, split))}"
        builds.append({
            "id": rid,
            "class": class_name,
            "build_type": row["build_type"],
            "label": f"#{row['overall_rank']} overall · {'/'.join(map(str, split))}",
            "overall_rank": row["overall_rank"],
            "level": 60,
            "tree_points": row["tree_points"],
            "split": split,
            "popularity": row["popularity"],
            "source_url": row["source_url"],
            "allocation_detail_status": row["allocation_detail_status"],
            "talent_ranks": row["talent_ranks"],
            "leveling_order": row.get("leveling_order") or [],
            "progression_status": "exact_source_visible" if row.get("leveling_order") else "final_allocation_only",
            "score_status": "not_scored_reference_only",
            "source_build": source_build,
            "captured_at": captured_at,
        })
    # Exact source allocations are accepted into the canonical snapshot only if
    # they are valid in the runtime's current Druid schema. Split-only popular
    # families stay source-honest and are not guessed.
    if class_name == "druid":
        from src.rulesets.forever.classes.druid.reference_builds import validate_exact_reference_build
        for build in builds:
            if build.get("allocation_detail_status") != "exact":
                continue
            validation = validate_exact_reference_build(build)
            if not validation.get("ok"):
                raise ValueError(f"stale/invalid exact Druid reference build: {validation.get('errors')}")
            build["runtime_schema_validation"] = validation

    groups = {}
    for typ, label in (("balance", "Balance"), ("feral", "Feral Combat"), ("restoration", "Restoration")):
        subset = [dict(x) for x in builds if x["build_type"] == typ][:requested_per_build_type]
        groups[typ] = {"label": label, "requested": requested_per_build_type, "available": len(subset),
                       "coverage_complete": len(subset) >= requested_per_build_type, "builds": subset}
    payload = {
        "schema_version": 2,
        "class": class_name,
        "source": {
            "provider": "Talents Forever",
            "provider_url": raw.get("url"),
            "attribution_url": "https://talentsforever.com/",
            "source_build": source_build,
            "license": "CC BY 4.0",
            "ranking_semantics": "source-visible popular-build order/activity only; missing families are never synthesized",
        },
        "capture": {
            "provider": "Talents Forever",
            "capture_backend": raw.get("capture_backend", "playwright"),
            "captured_at": captured_at,
            "generated_at": captured_at,
            "provenance_url": raw.get("url"),
            "raw_sha256": raw.get("raw_sha256"),
        },
        "requested_per_build_type": requested_per_build_type,
        "groups": groups,
        "builds": builds,
        "comparison_semantics": {
            "search_authority": False, "route_authority": False,
            "tree_split_comparison": True, "exact_talent_diff_when_available": True,
            "throughput_comparison": False,
            "throughput_note": "Reference throughput is absent until an exact allocation is scored in the same class/build context.",
        },
    }
    stable = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    payload["content_sha256"] = _sha(stable)
    return payload



def publish_capture(raw: dict, canonical_path: Path) -> dict:
    """Validate/normalize first, then atomically replace the canonical LKG."""
    normalized = normalize_capture(raw)
    _atomic_json(canonical_path, normalized)
    return normalized

def capture_page(page, class_name: str, url: str, timeout_ms: int, settle_ms: int) -> dict:
    started = _now()
    response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    try:
        page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 15000))
    except Exception:
        pass
    if settle_ms:
        page.wait_for_timeout(settle_ms)
    body = page.locator("body").inner_text(timeout=5000)
    html = page.content()
    # Capture generous DOM context around candidate build links. The normalizer
    # remains independent from live DOM and can be fixture-tested deterministically.
    candidates = page.evaluate(r"""() => Array.from(document.querySelectorAll('a[href]')).map(a => {
      let n=a; for(let i=0;i<4 && n.parentElement;i++) n=n.parentElement;
      return {href:a.href, text:(n.innerText||a.innerText||'').slice(0,3000)};
    }).filter(x => /talentsforever\\.com\\/(?:druid|mage|paladin|hunter)\\/60\//i.test(x.href) || /\\d+\\s*\\/\\s*\\d+\\s*\\/\\s*\\d+/.test(x.text))""")
    status = response.status if response else None
    accepted = (status is None or 200 <= status < 400) and bool(_SPLIT_RE.search(body) or candidates)
    raw = {"schema_version": 1, "class": class_name, "url": url, "http_status": status,
           "capture_backend": "playwright", "captured_at": started, "finished_at": _now(),
           "accepted": accepted, "title": page.title(), "body_text": body, "html": html, "candidates": candidates}
    raw["raw_sha256"] = _sha(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return raw


def refresh(class_name: str, *, output_dir: Path, canonical_dir: Path, headed: bool = False,
            channel: str | None = None, timeout_ms: int = 60000, settle_ms: int = 2000) -> tuple[Path, Path]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is required: pip install playwright && python -m playwright install chromium") from exc
    url = DEFAULT_URLS[class_name]
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / f"{class_name}.raw.json"
    canonical_path = canonical_dir / f"{class_name}.json"
    with sync_playwright() as p:
        kw = {"headless": not headed}
        if channel:
            kw["channel"] = channel
        browser = p.chromium.launch(**kw)
        try:
            raw = capture_page(browser.new_page(), class_name, url, timeout_ms, settle_ms)
        finally:
            browser.close()
    _atomic_json(raw_path, raw)
    # Publish only after successful validation/normalization: LKG is preserved.
    publish_capture(raw, canonical_path)
    return raw_path, canonical_path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Capture and normalize TalentsForever popular reference builds.")
    p.add_argument("classes", nargs="*", default=["druid"], choices=sorted(DEFAULT_URLS))
    p.add_argument("--headed", action="store_true")
    p.add_argument("--channel", default=None)
    p.add_argument("--timeout-ms", type=int, default=60000)
    p.add_argument("--settle-ms", type=int, default=2000)
    p.add_argument("--output", default=None)
    p.add_argument("--canonical-dir", default=str(DEFAULT_CANONICAL_DIR))
    args = p.parse_args(argv)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = Path(args.output or f"talentsforever_capture_{stamp}").resolve()
    for cls in args.classes:
        raw, canonical = refresh(cls, output_dir=out, canonical_dir=Path(args.canonical_dir), headed=args.headed,
                                 channel=args.channel, timeout_ms=args.timeout_ms, settle_ms=args.settle_ms)
        print(f"{cls}: raw={raw} canonical={canonical}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
