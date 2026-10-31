from __future__ import annotations

import os
import re
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from src.rulesets.forever.items.catalogue import ItemCatalogue, extract_wowhead_item_id
from src.rulesets.forever.items.wowhead_detail import refresh_item_detail

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOGUE = ROOT / "data" / "forever" / "catalogue" / "items_2026-09-29.sqlite"
DEFAULT_PROFILE = ROOT / ".wowhead-chrome-profile"
CLASS_IDS = {"paladin": 2, "mage": 8, "druid": 11}
_ID_RE = re.compile(r"^\s*(\d+)\s*$")
_FETCH_LOCK = threading.Lock()


@dataclass(frozen=True)
class AddItemResult:
    item_id: int
    status: str
    name: str
    slot: str
    item_level: int | None
    required_level: int | None
    effective_required_level: int | None
    class_name: str | None
    class_id: int | None
    eligibility_added: bool
    eligible_classes: tuple[str, ...]
    affected_ranges: dict[str, tuple[int, int]]
    affected_from_level: int | None
    affected_to_level: int | None
    source_url: str
    catalogue_hash: str
    message: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def parse_item_input(value: object) -> tuple[int, str]:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("item is required (Wowhead Forever URL or numeric item ID)")
    match = _ID_RE.match(raw)
    if match:
        item_id = int(match.group(1))
        return item_id, f"https://www.wowhead.com/forever/item={item_id}"
    item_id = extract_wowhead_item_id(raw)
    if item_id is None:
        raise ValueError("item must be a numeric ID or a Wowhead Forever item URL")
    if "wowhead.com/forever/item=" not in raw.lower():
        raise ValueError("URL must point to a Wowhead Forever item")
    return item_id, raw


def catalogue_path() -> Path:
    return Path(os.environ.get("FOREVER_ITEM_CATALOGUE", DEFAULT_CATALOGUE))


def fetch_wowhead_item_html(item_id: int, source_url: str, *, timeout_ms: int = 60000, settle_ms: int = 1800) -> str:
    """Fetch one exact Wowhead Forever item with the same headed persistent Chrome path that passes WAF.

    Headless Chrome is deliberately not used: the validated Wowhead flow returns 403 headless.
    The lock prevents two service requests from sharing the persistent profile concurrently.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is required for Add item") from exc

    profile = Path(os.environ.get("WOWHEAD_CHROME_PROFILE", DEFAULT_PROFILE))
    channel = os.environ.get("WOWHEAD_BROWSER_CHANNEL", "chrome") or None
    profile.mkdir(parents=True, exist_ok=True)
    with _FETCH_LOCK:
        with sync_playwright() as p:
            kwargs = {
                "user_data_dir": str(profile),
                "headless": False,
                "locale": "en-US",
            }
            if channel:
                kwargs["channel"] = channel
            context = p.chromium.launch_persistent_context(**kwargs)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                response = page.goto(source_url, wait_until="domcontentloaded", timeout=int(timeout_ms))
                page.wait_for_timeout(int(settle_ms))
                status = response.status if response is not None else None
                html = page.content()
                title = page.title()
                if status is not None and status >= 400:
                    raise RuntimeError(f"Wowhead returned HTTP {status} ({title or 'no title'})")
                if "Forever" not in title and f"item={int(item_id)}" not in page.url:
                    raise RuntimeError(f"unexpected Wowhead page: {title or page.url}")
                return html
            finally:
                context.close()


def add_item(
    value: object,
    *,
    class_name: str | None = None,
    html_fetcher: Callable[[int, str], str] | None = None,
    catalogue_file: str | Path | None = None,
) -> AddItemResult:
    item_id, source_url = parse_item_input(value)
    cls = str(class_name or "").strip().lower() or None
    if cls is not None and cls not in CLASS_IDS:
        raise ValueError(f"unsupported class_name: {cls}")
    class_id = CLASS_IDS.get(cls) if cls else None

    fetcher = html_fetcher or fetch_wowhead_item_html
    raw_html = fetcher(item_id, source_url)
    path = Path(catalogue_file) if catalogue_file is not None else catalogue_path()
    if not path.exists():
        raise FileNotFoundError(f"Forever item catalogue not found: {path}")

    with ItemCatalogue(path) as catalogue:
        prior_eligibility = {
            int(row[0]) for row in catalogue._conn.execute(
                "SELECT class_id FROM item_class_eligibility WHERE item_id=?", (item_id,)
            )
        }
        # Point-add is one catalogue mutation: item facts and any explicitly selected
        # class eligibility either both commit or both roll back.  This matters for
        # the long-running service, where /decisions may query the catalogue as soon
        # as this request returns.
        try:
            catalogue._conn.execute("BEGIN")
            refresh = refresh_item_detail(
                catalogue,
                item_id=item_id,
                raw_html=raw_html,
                source_url=source_url,
                commit=False,
            )
            if refresh.status != "verified":
                raise RuntimeError(refresh.message or f"item {item_id} detail refresh failed")
            if class_id is not None:
                catalogue.add_class_eligibility(
                    item_id, class_id, f"point_add:{source_url}", commit=False
                )
            item = catalogue.get_item(item_id)
            if item is None:
                raise RuntimeError(f"item {item_id} missing after verified upsert")
            effective = catalogue.effective_required_level(item)
            current_eligibility = {
                int(row[0]) for row in catalogue._conn.execute(
                    "SELECT class_id FROM item_class_eligibility WHERE item_id=?", (item_id,)
                )
            }
            catalogue._conn.commit()
        except Exception:
            catalogue._conn.rollback()
            raise
        eligibility_added = class_id is not None and class_id not in prior_eligibility and class_id in current_eligibility
        cat_hash = catalogue.catalogue_hash()

    # The optimizer deliberately keeps canonical catalogue rows in process
    # memory.  Point mutations must invalidate that tiny cache before the next
    # recompute can observe the updated item set.
    from src.rulesets.forever.items.runtime_selection import clear_runtime_item_cache
    clear_runtime_item_cache()

    class_names_by_id = {value: key for key, value in CLASS_IDS.items()}
    eligible_classes = tuple(sorted(class_names_by_id[cid] for cid in current_eligibility if cid in class_names_by_id))
    if effective is not None and int(effective) <= 60:
        affected_ranges = {name: (int(effective), 60) for name in eligible_classes}
    else:
        affected_ranges = {}
    selected_range = affected_ranges.get(cls) if cls else None
    affected_from = selected_range[0] if selected_range else None
    affected_to = selected_range[1] if selected_range else None
    message = ""
    if class_id is None and not current_eligibility:
        message = "Item catalogued, but class eligibility is unresolved; add it from a class Decisions view or run a bulk refresh."
    elif eligibility_added:
        message = f"Item verified and enabled for {cls}."
    else:
        message = "Item verified; existing class eligibility preserved."

    return AddItemResult(
        item_id=item.item_id,
        status=refresh.status,
        name=item.name,
        slot=item.slot,
        item_level=item.item_level,
        required_level=item.required_level,
        effective_required_level=effective,
        class_name=cls,
        class_id=class_id,
        eligibility_added=eligibility_added,
        eligible_classes=eligible_classes,
        affected_ranges=affected_ranges,
        affected_from_level=affected_from,
        affected_to_level=affected_to,
        source_url=item.source_url or source_url,
        catalogue_hash=cat_hash,
        message=message,
    )
