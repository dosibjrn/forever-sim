from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from typing import Iterable

from .catalogue import ItemCatalogue, ItemRecord
from .wowhead_queries import WowheadItemBand

_ITEM_LINK_RE = re.compile(
    r'href=["\'](?P<url>(?:https?://www\.wowhead\.com)?/forever/item=(?P<id>\d+)(?:/[^"\']*)?)["\'][^>]*>(?P<body>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_COUNT_RE = re.compile(
    r"(?P<found>[\d,]+)\s+items?\s+found(?:\s*\((?P<displayed>[\d,]+)\s+displayed\))?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class WowheadListHit:
    item_id: int
    name: str
    url: str


@dataclass(frozen=True)
class WowheadListPage:
    hits: tuple[WowheadListHit, ...]
    found_count: int | None
    displayed_count: int | None

    @property
    def truncated(self) -> bool:
        return (
            self.found_count is not None
            and self.displayed_count is not None
            and self.displayed_count < self.found_count
        )


def _count(value: str | None) -> int | None:
    return int(value.replace(",", "")) if value else None


def parse_wowhead_list_page(raw_html: str) -> WowheadListPage:
    """Parse conservative list evidence from a captured Wowhead page.

    The parser intentionally consumes only explicit item anchors plus the visible
    found/displayed summary.  It does not depend on Wowhead's internal JS object
    layout, so captured HTML can be replayed deterministically in tests.
    """
    text = str(raw_html)
    count_match = _COUNT_RE.search(text)
    found = _count(count_match.group("found")) if count_match else None
    displayed = _count(count_match.group("displayed")) if count_match else None

    by_id: dict[int, WowheadListHit] = {}
    for match in _ITEM_LINK_RE.finditer(text):
        item_id = int(match.group("id"))
        body = html_lib.unescape(_TAG_RE.sub("", match.group("body"))).strip()
        url = match.group("url")
        if url.startswith("/"):
            url = f"https://www.wowhead.com{url}"
        candidate = WowheadListHit(item_id=item_id, name=body or f"Wowhead item {item_id}", url=url)
        prior = by_id.get(item_id)
        if prior is None or (prior.name.startswith("Wowhead item ") and not candidate.name.startswith("Wowhead item ")):
            by_id[item_id] = candidate
    return WowheadListPage(tuple(sorted(by_id.values(), key=lambda x: x.item_id)), found, displayed)


def ingest_list_page(
    catalogue: ItemCatalogue,
    *,
    band: WowheadItemBand,
    page: WowheadListPage,
) -> tuple[int, ...]:
    """Upsert list-only identities/eligibility without inventing item facts.

    A truncated page is rejected wholesale: accepting it would silently create
    an incomplete corpus.  Detail ingestion in I3 replaces these placeholders.
    """
    if page.truncated:
        raise ValueError(
            f"Wowhead band {band.band_key} truncated: found={page.found_count} displayed={page.displayed_count}"
        )

    ids: list[int] = []
    provenance = band.band_key + "|" + band.url
    for hit in page.hits:
        existing = catalogue.get_item(hit.item_id)
        if existing is None:
            catalogue.upsert_item(
                ItemRecord(
                    item_id=hit.item_id,
                    name=hit.name,
                    slot="",
                    required_level=None,
                    required_level_origin="observed",
                    source_url=hit.url,
                    identity_origin="wowhead_list",
                    fetch_status="list_only",
                )
            )
        catalogue.add_class_eligibility(hit.item_id, band.class_id, provenance)
        ids.append(hit.item_id)
    return tuple(sorted(set(ids)))
