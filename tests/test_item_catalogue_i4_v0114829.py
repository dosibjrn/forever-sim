from __future__ import annotations

from pathlib import Path

from src.rulesets.forever.items.catalogue import ItemCatalogue, ItemRecord, RequiredLevelOrigin
from src.rulesets.forever.items.required_level_model import (
    apply_inferred_required_levels,
    build_required_level_model,
)


def _item(item_id: int, ilvl: int, req: int | None, *, origin: str = RequiredLevelOrigin.OBSERVED.value) -> ItemRecord:
    return ItemRecord(
        item_id=item_id,
        name=f"item-{item_id}",
        slot="head",
        item_level=ilvl,
        required_level=req,
        required_level_origin=origin if req is not None else RequiredLevelOrigin.MISSING.value,
        fetch_status="verified",
        last_verified_at="2026-09-29T00:00:00Z",
    )


def test_model_uses_observed_median_and_records_distribution(tmp_path: Path):
    with ItemCatalogue(tmp_path / "items.sqlite") as cat:
        cat.upsert_items([
            _item(1, 20, 15), _item(2, 20, 17), _item(3, 20, 16),
            _item(4, 22, 18),
        ])
        rows = build_required_level_model(cat, computed_at="2026-09-29T10:00:00Z")
        row20 = next(r for r in rows if r.item_level == 20)
        assert row20.observed_sample_count == 3
        assert row20.median_required_level == 16.0
        assert row20.p25_required_level == 15.5
        assert row20.p75_required_level == 16.5
        assert row20.model_status == "observed_median"
        assert len(row20.source_catalogue_hash) == 64


def test_empty_ilvl_bucket_is_linearly_interpolated(tmp_path: Path):
    with ItemCatalogue(tmp_path / "items.sqlite") as cat:
        cat.upsert_items([_item(1, 20, 15), _item(2, 22, 19)])
        rows = build_required_level_model(cat, computed_at="2026-09-29T10:00:00Z")
        row21 = next(r for r in rows if r.item_level == 21)
        assert row21.observed_sample_count == 0
        assert row21.median_required_level == 17.0
        assert row21.model_status == "interpolated"
        assert row21.p25_required_level is None
        assert row21.p75_required_level is None


def test_apply_fills_missing_only_and_marks_provenance(tmp_path: Path):
    with ItemCatalogue(tmp_path / "items.sqlite") as cat:
        cat.upsert_items([
            _item(1, 20, 15), _item(2, 20, 17),
            _item(3, 22, 19),
            _item(10, 20, None),
            _item(11, 21, None),
            _item(12, 20, 14),
        ])
        build_required_level_model(cat, computed_at="2026-09-29T10:00:00Z")
        assert apply_inferred_required_levels(cat) == 2
        median_item = cat.get_item(10)
        interp_item = cat.get_item(11)
        observed_item = cat.get_item(12)
        assert (median_item.required_level, median_item.required_level_origin) == (15, "inferred_median")
        assert (interp_item.required_level, interp_item.required_level_origin) == (17, "inferred_interpolated")
        assert (observed_item.required_level, observed_item.required_level_origin) == (14, "observed")


def test_inferred_values_never_train_the_next_model(tmp_path: Path):
    with ItemCatalogue(tmp_path / "items.sqlite") as cat:
        cat.upsert_items([
            _item(1, 20, 10),
            _item(2, 20, 60, origin=RequiredLevelOrigin.INFERRED_MEDIAN.value),
            _item(3, 22, 14),
        ])
        first = build_required_level_model(cat, computed_at="2026-09-29T10:00:00Z")
        second = build_required_level_model(cat, computed_at="2026-09-29T10:01:00Z")
        a = next(r for r in first if r.item_level == 20)
        b = next(r for r in second if r.item_level == 20)
        assert a.observed_sample_count == b.observed_sample_count == 1
        assert a.median_required_level == b.median_required_level == 10.0
        assert a.source_catalogue_hash == b.source_catalogue_hash
