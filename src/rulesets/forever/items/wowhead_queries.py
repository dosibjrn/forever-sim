from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

WOWHEAD_FOREVER_BASE = "https://www.wowhead.com/forever/items"
DEFAULT_FILTER = "161:195;1:1;0:0"
DEFAULT_SIDE = 2
WOWHEAD_QUALITY_VALUES = tuple(range(8))  # The full Classic quality filter domain.


@dataclass(frozen=True)
class WowheadClassQuery:
    class_key: str
    class_id: int
    side: int = DEFAULT_SIDE
    filter_expr: str = DEFAULT_FILTER


@dataclass(frozen=True)
class WowheadItemBand:
    class_key: str
    class_id: int
    min_item_level: int
    max_item_level: int
    side: int
    filter_expr: str
    url: str
    quality: int | None = None

    @property
    def band_key(self) -> str:
        return f"{self.class_key}:ilvl:{self.min_item_level}-{self.max_item_level}:quality:{self.quality}"


# Reviewed from the user-provided Wowhead Forever searches.  Keep this explicit:
# these are ingestion definitions, not inferred runtime rules.
CANONICAL_CLASS_QUERIES: dict[str, WowheadClassQuery] = {
    "mage": WowheadClassQuery("mage", 8),
    "hunter": WowheadClassQuery("hunter", 3),
    "rogue": WowheadClassQuery("rogue", 4),
    "priest": WowheadClassQuery("priest", 5),
    "shaman": WowheadClassQuery("shaman", 7),
    "warlock": WowheadClassQuery("warlock", 9),
    "druid": WowheadClassQuery("druid", 11),
    "paladin": WowheadClassQuery("paladin", 2),
    "warrior": WowheadClassQuery("warrior", 1),
}

# Item-level bands, not required-level bands.  Required-level eligibility is
# resolved later from item detail / the canonical ilvl->req-level model.
CANONICAL_ILVL_BANDS: tuple[tuple[int, int], ...] = (
    (10, 29),
    (30, 49),
    (50, 65),
)

# Warrior L30 cannot claim a complete legal item denominator from the legacy
# 10-65 source window alone. Include low-ilvl starter gear and all remaining
# possible WoW item levels in its own capture; this does not change other classes.
WARRIOR_SOURCE_ILVL_BANDS: tuple[tuple[int, int], ...] = (
    (1, 9), (10, 29), (30, 49), (50, 65), (66, 99), (100, 149), (150, 255),
)


def bands_for_class(class_key: str) -> tuple[tuple[int, int], ...]:
    """Complete item-level capture envelope for every class.

    The older 10–65 source windows are useful *provisional* candidate pools,
    but cannot prove all equippable items at a character level: a low-level
    item can have ilvl < 10 or > 65. Never certify such partial windows.
    """
    key = class_key.lower()
    if key not in CANONICAL_CLASS_QUERIES:
        raise ValueError('UNKNOWN_SOURCE_CLASS_QUERY')
    return WARRIOR_SOURCE_ILVL_BANDS


def build_search_url(query: WowheadClassQuery, min_item_level: int, max_item_level: int, *, quality: int | None = None) -> str:
    if min_item_level > max_item_level:
        raise ValueError("min item level must be <= max item level")
    if quality is not None and (not isinstance(quality, int) or quality not in WOWHEAD_QUALITY_VALUES):
        raise ValueError("unsupported Wowhead quality filter")
    quality_segment = "" if quality is None else f"/quality:{quality}"
    return (
        f"{WOWHEAD_FOREVER_BASE}/min-level:{int(min_item_level)}/max-level:{int(max_item_level)}"
        f"{quality_segment}/side:{int(query.side)}/class:{int(query.class_id)}?filter={query.filter_expr}"
    )



def child_capture_coordinates(lo: int, hi: int, quality: int | None = None) -> tuple[tuple[int, int, int | None], ...]:
    """Canonical deterministic partition, shared by fetch, resume and attestation.

    Quality children are *not* independently certified as exhaustive: their
    combined unique IDs must equal the source parent's found_count.
    """
    if lo < hi and quality is None:
        mid = (lo + hi) // 2
        return ((lo, mid, None), (mid + 1, hi, None))
    if lo == hi and quality is None:
        return tuple((lo, hi, q) for q in WOWHEAD_QUALITY_VALUES)
    raise ValueError('CAPTURE_UNSPLITTABLE_QUALITY_NEEDS_THIRD_PARTITION')


def canonical_bands(class_key: str) -> tuple[WowheadItemBand, ...]:
    query = CANONICAL_CLASS_QUERIES[class_key.lower()]
    return tuple(
        WowheadItemBand(
            class_key=query.class_key,
            class_id=query.class_id,
            min_item_level=lo,
            max_item_level=hi,
            side=query.side,
            filter_expr=query.filter_expr,
            url=build_search_url(query, lo, hi),
        )
        for lo, hi in bands_for_class(class_key)
    )


def all_canonical_bands() -> tuple[WowheadItemBand, ...]:
    return tuple(band for key in CANONICAL_CLASS_QUERIES for band in canonical_bands(key))


def strip_fragment(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
