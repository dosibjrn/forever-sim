from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import os

from src.rulesets.forever.items.catalogue import ItemCatalogue, ItemRecord, extract_wowhead_item_id
from src.rulesets.forever.items.gear_requirements import (
    candidate_counts_from_coverage, catalogue_coverage, requirements_for,
)

DRUID_CLASS_ID = 11
_REPO_ROOT = Path(__file__).resolve().parents[5]
_DEFAULT_DB = _REPO_ROOT / "data" / "forever" / "catalogue" / "items_2026-09-29.sqlite"

_ARMOR_SLOTS = {"head", "shoulder", "chest", "wrist", "hands", "waist", "legs", "feet"}
_ALLOWED_ARMOR = {"", "misc", "cloth", "leather"}


def catalogue_path() -> Path:
    return Path(os.environ.get("FOREVER_ITEM_CATALOGUE", _DEFAULT_DB))


def _druid_usable(item: ItemRecord) -> bool:
    if item.slot in _ARMOR_SLOTS and item.armor_type not in _ALLOWED_ARMOR:
        return False
    if item.armor_type == "shield":
        return False
    return True


def candidate_counts(level: int, *, role: str = "druid_balance", selected: dict | None = None) -> dict[str, int]:
    """Compatibility accessor backed by the shared production coverage authority."""
    cov = catalogue_coverage(
        requirements_for("druid", role, selected or {}),
        level=int(level), selected=selected or {},
    )
    return candidate_counts_from_coverage(cov)


def _lookup_anchor(anchor, rows: tuple[ItemRecord, ...]) -> ItemRecord | None:
    upstream_id = extract_wowhead_item_id(getattr(anchor, "source_url", "") or "")
    if upstream_id is not None:
        hit = next((x for x in rows if x.item_id == upstream_id), None)
        if hit is not None:
            return hit
    name = str(getattr(anchor, "name", ""))
    return next((x for x in rows if x.name == name), None)


def resolve_anchor_items(level: int, anchors) -> tuple[ItemRecord, ...]:
    rows = available_items(int(level))
    out: list[ItemRecord] = []
    for anchor in anchors:
        hit = _lookup_anchor(anchor, rows)
        if hit is not None:
            out.append(hit)
    return tuple(out)


@lru_cache(maxsize=1)
def _availability_model():
    path = catalogue_path()
    if not path.exists():
        return None
    with ItemCatalogue(path) as cat:
        return cat.availability_floor_model()


def item_effective_level(level: int, item: ItemRecord) -> int | None:
    req = item.required_level
    model = _availability_model()
    floor = model.floor_for_item_level(item.item_level) if model is not None and item.item_level is not None else None
    if req is None:
        return floor
    return int(req) if floor is None else max(int(req), int(floor))


def enrich_gear_metadata(gear: dict, level: int, *, role: str, selected: dict[str, ItemRecord]) -> dict:
    requirements = requirements_for("druid", role, selected)
    coverage = catalogue_coverage(requirements, level=int(level), selected=selected)
    gear["catalogue_coverage"] = coverage
    gear["catalogue_candidate_counts"] = candidate_counts_from_coverage(coverage)
    gear["blocked_slots"] = [
        slot for slot, meta in coverage.items()
        if meta.get("status") in {"setup_blocked", "proficiency_blocked"}
    ]
    gear["catalogue_path"] = str(catalogue_path())
    gear["catalogue_mode"] = "sqlite_runtime_authority"
    gear["catalogue_coverage_authority"] = "shared_gear_requirements_v1"
    return gear
