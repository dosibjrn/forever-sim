from __future__ import annotations

from pathlib import Path

from src.rulesets.forever.items.catalogue import ItemCatalogue, ItemRecord
from src.rulesets.forever.items.required_level_model import build_availability_floor_model


def _item(item_id: int, ilvl: int, req: int) -> ItemRecord:
    return ItemRecord(item_id=item_id, name=f"i{item_id}", slot="head", item_level=ilvl,
                      required_level=req, required_level_origin="observed")


def test_robust_quadratic_floor_rejects_only_implausibly_low_observations(tmp_path: Path):
    db = tmp_path / "items.sqlite"
    with ItemCatalogue(db) as cat:
        rows = []
        item_id = 1
        for ilvl in range(10, 61):
            for delta in (-1, 0, 1):
                rows.append(_item(item_id, ilvl, max(1, ilvl - 5 + delta)))
                item_id += 1
        rows.append(_item(item_id, 60, 1))
        cat.upsert_items(rows)
        model = build_availability_floor_model(cat, computed_at="2026-09-29T10:28:08Z")
        assert model.degree == 2
        assert model.excluded_low_outliers >= 1
        assert 51 <= model.floor_for_item_level(60) <= 55
        assert cat.availability_floor_model() == model


def test_eligible_items_must_satisfy_both_source_reqlevel_and_ilvl_floor(tmp_path: Path):
    db = tmp_path / "items.sqlite"
    with ItemCatalogue(db) as cat:
        rows = []
        item_id = 1
        for ilvl in range(10, 61):
            rows.append(_item(item_id, ilvl, max(1, ilvl - 5)))
            item_id += 1
        bad = _item(999, 60, 1)
        legit = _item(1000, 20, 15)
        cat.upsert_items(rows + [bad, legit])
        cat.add_class_eligibility(999, 11, "test")
        cat.add_class_eligibility(1000, 11, "test")
        build_availability_floor_model(cat, computed_at="2026-09-29T10:28:08Z")
        ids20 = {x.item_id for x in cat.eligible_items(class_id=11, level=20)}
        assert 1000 in ids20
        assert 999 not in ids20
        assert cat.effective_required_level(bad) > 20
