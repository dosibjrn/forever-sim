from __future__ import annotations

from pathlib import Path

import pytest

from src.rulesets.forever.items.catalogue import ItemCatalogue
from src.rulesets.forever.items.wowhead_list import ingest_list_page, parse_wowhead_list_page
from src.rulesets.forever.items.wowhead_queries import (
    CANONICAL_CLASS_QUERIES,
    all_canonical_bands,
    canonical_bands,
)


def test_canonical_queries_are_exact_three_non_overlapping_ilvl_bands_per_reviewed_class():
    assert {k: v.class_id for k, v in CANONICAL_CLASS_QUERIES.items()} == {
        "mage": 8,
        "druid": 11,
        "paladin": 2,
    }
    all_bands = all_canonical_bands()
    assert len(all_bands) == 9
    for class_key in CANONICAL_CLASS_QUERIES:
        bands = canonical_bands(class_key)
        assert [(b.min_item_level, b.max_item_level) for b in bands] == [(10, 29), (30, 49), (50, 65)]
        assert all(f"/side:2/class:{CANONICAL_CLASS_QUERIES[class_key].class_id}" in b.url for b in bands)
        assert all("?filter=161:195;1:1;0:0" in b.url for b in bands)


def test_list_parser_deduplicates_item_ids_and_keeps_visible_counts():
    page = parse_wowhead_list_page(
        '''
        <div>3 items found (3 displayed)</div>
        <a href="/forever/item=252448/totemic-leather-hood">Totemic Leather Hood</a>
        <a href="https://www.wowhead.com/forever/item=10001/example">Example &amp; Item</a>
        <a href="/forever/item=252448/totemic-leather-hood"><span>Totemic Leather Hood</span></a>
        '''
    )
    assert page.found_count == 3
    assert page.displayed_count == 3
    assert not page.truncated
    assert [x.item_id for x in page.hits] == [10001, 252448]
    assert page.hits[0].name == "Example & Item"


def test_truncated_page_is_hard_rejected_before_partial_catalogue_ingestion(tmp_path: Path):
    band = canonical_bands("druid")[0]
    page = parse_wowhead_list_page(
        '''
        <div>11,812 items found (5,963 displayed)</div>
        <a href="/forever/item=252448/totemic-leather-hood">Totemic Leather Hood</a>
        '''
    )
    assert page.truncated
    with ItemCatalogue(tmp_path / "items.sqlite") as catalogue:
        with pytest.raises(ValueError, match="truncated"):
            ingest_list_page(catalogue, band=band, page=page)
        assert catalogue.list_items() == []


def test_list_ingestion_creates_only_incomplete_placeholders_and_class_eligibility(tmp_path: Path):
    band = canonical_bands("mage")[1]
    page = parse_wowhead_list_page(
        '''
        <div>2 items found (2 displayed)</div>
        <a href="/forever/item=12345/foo">Foo</a>
        <a href="/forever/item=12346/bar">Bar</a>
        '''
    )
    with ItemCatalogue(tmp_path / "items.sqlite") as catalogue:
        ids = ingest_list_page(catalogue, band=band, page=page)
        assert ids == (12345, 12346)
        foo = catalogue.get_item(12345)
        assert foo is not None
        assert foo.fetch_status == "list_only"
        assert foo.required_level is None
        assert foo.slot == ""
        assert catalogue.eligible_items(class_id=8, level=60) == []
        rows = catalogue._conn.execute(
            "SELECT item_id,class_id,provenance FROM item_class_eligibility ORDER BY item_id"
        ).fetchall()
        assert [(r["item_id"], r["class_id"]) for r in rows] == [(12345, 8), (12346, 8)]
        assert all("mage:ilvl:30-49" in r["provenance"] for r in rows)
