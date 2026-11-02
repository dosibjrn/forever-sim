"""P3 source-item score cache must follow the active catalogue revision.

Use real ItemRecord and real item_score: no simulated scorer or synthetic
positive stat weights. Two source snapshots may reuse one canonical item ID.
"""
from dataclasses import replace

from src.rulesets.forever.items import runtime_selection as items
from src.rulesets.forever.items.catalogue import ItemRecord


def _source_item() -> ItemRecord:
    return ItemRecord(
        item_id=7348, name="Source item", slot="hands",
        item_level=45, required_level=40, agility=3.0,
    )


def test_explicit_catalogue_refresh_invalidates_scoring_vector():
    before = _source_item()
    after = replace(before, agility=29.0)
    try:
        items.clear_runtime_item_cache()
        assert items.item_score(before, {"agility": 1.0}) == 3.0
        # A canonical catalogue refresh at the same file path explicitly
        # invalidates all source-derived vectors, including scored vectors.
        items.clear_runtime_item_cache()
        assert items.item_score(after, {"agility": 1.0}) == 29.0
    finally:
        items.clear_runtime_item_cache()


def test_source_catalogue_path_switch_invalidates_scoring_vector(tmp_path):
    before = _source_item()
    after = replace(before, agility=29.0)
    try:
        items.clear_runtime_item_cache()
        items._sync_catalogue_path(tmp_path / "pinned_before.sqlite")
        assert items.item_score(before, {"agility": 1.0}) == 3.0
        # Different pinned snapshot, same legitimate item ID. Scoring must
        # never silently reuse the first snapshot's stat vector.
        items._sync_catalogue_path(tmp_path / "pinned_after.sqlite")
        assert items.item_score(after, {"agility": 1.0}) == 29.0
    finally:
        items.clear_runtime_item_cache()
