from __future__ import annotations

from pathlib import Path

from src.rulesets.forever.items.catalogue import ItemCatalogue, ItemRecord, RequiredLevelOrigin
from src.rulesets.forever.items.wowhead_detail import refresh_item_detail


def _fixture(*, req: str = '"required_level":20,', item_id: int = 252448) -> str:
    return f'''
    <html><head><title>Totemic Leather Hood - Wowhead</title></head><body>
    <script id="wowhead-item-data" type="application/json">
    {{
      "item_id": {item_id},
      "name": "Totemic Leather Hood",
      "slot": "Head",
      "item_level": 25,
      {req}
      "quality": 3,
      "armor_type": "Leather",
      "armor": 76,
      "stats": {{"stamina": 10, "spell_power": 9}}
    }}
    </script>
    </body></html>
    '''


def test_verified_detail_replaces_placeholder_with_typed_facts(tmp_path: Path):
    with ItemCatalogue(tmp_path / "items.sqlite") as catalogue:
        catalogue.upsert_item(ItemRecord(
            item_id=252448,
            name="Totemic Leather Hood",
            slot="",
            required_level=None,
            required_level_origin=RequiredLevelOrigin.MISSING.value,
            source_url="https://www.wowhead.com/forever/item=252448/totemic-leather-hood",
            identity_origin="wowhead_list",
            fetch_status="list_only",
        ))
        result = refresh_item_detail(
            catalogue,
            item_id=252448,
            raw_html=_fixture(),
            fetched_at="2026-09-29T08:00:00Z",
        )
        assert result.status == "verified"
        assert not result.used_cached_values
        item = catalogue.get_item(252448)
        assert item is not None
        assert item.fetch_status == "verified"
        assert item.identity_origin == "wowhead_item"
        assert item.slot == "head"
        assert item.item_level == 25
        assert item.required_level == 20
        assert item.required_level_origin == RequiredLevelOrigin.OBSERVED.value
        assert item.armor_type == "leather"
        assert item.armor == 76
        assert item.stamina == 10
        assert item.spell_power == 9
        assert item.last_verified_at == "2026-09-29T08:00:00Z"
        assert item.last_fetch_error == ""
        assert len(item.upstream_fingerprint) == 64


def test_fetch_or_parse_failure_preserves_last_verified_values_and_marks_cached_fallback(tmp_path: Path):
    with ItemCatalogue(tmp_path / "items.sqlite") as catalogue:
        refresh_item_detail(
            catalogue,
            item_id=252448,
            raw_html=_fixture(),
            fetched_at="2026-09-29T08:00:00Z",
        )
        before = catalogue.get_item(252448)
        assert before is not None
        result = refresh_item_detail(
            catalogue,
            item_id=252448,
            fetch_error="HTTP 503",
            fetched_at="2026-09-29T09:00:00Z",
        )
        assert result.status == "cached_fallback"
        assert result.used_cached_values
        assert "using locally cached values" in result.message
        assert "2026-09-29T08:00:00Z" in result.message
        after = catalogue.get_item(252448)
        assert after is not None
        assert after.fetch_status == "cached_fallback"
        assert after.required_level == before.required_level
        assert after.item_level == before.item_level
        assert after.stamina == before.stamina
        assert after.spell_power == before.spell_power
        assert after.upstream_fingerprint == before.upstream_fingerprint
        assert after.last_verified_at == before.last_verified_at
        assert after.last_fetch_error == "HTTP 503"


def test_placeholder_failure_is_not_misrepresented_as_cached_values(tmp_path: Path):
    with ItemCatalogue(tmp_path / "items.sqlite") as catalogue:
        catalogue.upsert_item(ItemRecord(
            item_id=12345,
            name="Unverified item",
            slot="",
            required_level=None,
            required_level_origin=RequiredLevelOrigin.MISSING.value,
            fetch_status="list_only",
            identity_origin="wowhead_list",
        ))
        result = refresh_item_detail(catalogue, item_id=12345, fetch_error="timeout")
        assert result.status == "fetch_failed"
        assert not result.used_cached_values
        assert "no verified local cache" in result.message
        item = catalogue.get_item(12345)
        assert item is not None
        assert item.fetch_status == "fetch_failed"
        assert item.last_verified_at is None
        assert catalogue.eligible_items(class_id=11, level=60) == []


def test_missing_required_level_stays_missing_for_i4_inference(tmp_path: Path):
    html = _fixture(req="")
    with ItemCatalogue(tmp_path / "items.sqlite") as catalogue:
        result = refresh_item_detail(
            catalogue,
            item_id=252448,
            raw_html=html,
            fetched_at="2026-09-29T08:00:00Z",
        )
        assert result.status == "verified"
        item = catalogue.get_item(252448)
        assert item is not None
        assert item.item_level == 25
        assert item.required_level is None
        assert item.required_level_origin == RequiredLevelOrigin.MISSING.value
