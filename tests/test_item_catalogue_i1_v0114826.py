from __future__ import annotations

from pathlib import Path

from src.rulesets.forever.classes.druid.weapon import FERAL_WEAPON_PROGRESSION
from src.rulesets.forever.classes.mage.real_gear import CURATED_ITEMS
from src.rulesets.forever.items.catalogue import ItemCatalogue, extract_wowhead_item_id, legacy_item_id
from src.rulesets.forever.items.migration import legacy_row_to_item, migrate_legacy_rows
from src.rulesets.forever.shared.crafted_itemization import CRAFTED_ITEMS


def test_identity_prefers_real_item_id_and_uses_stable_negative_legacy_id():
    assert extract_wowhead_item_id("https://www.wowhead.com/forever/item=252448/totemic-leather-hood") == 252448
    assert extract_wowhead_item_id("https://www.wowhead.com/forever/spell=1255112/totemic-leather-pants") is None
    a = legacy_item_id(name="Totemic Leather Pants", source_url="https://www.wowhead.com/forever/spell=1255112/totemic-leather-pants", namespace="crafted")
    b = legacy_item_id(name="Totemic Leather Pants", source_url="https://www.wowhead.com/forever/spell=1255112/totemic-leather-pants", namespace="crafted")
    assert a == b < 0


def test_current_crafted_and_mage_rows_round_trip(tmp_path: Path):
    crafted = migrate_legacy_rows(CRAFTED_ITEMS, namespace="crafted")
    mage = migrate_legacy_rows(CURATED_ITEMS, namespace="mage")
    records = crafted + mage
    db = tmp_path / "items.sqlite"
    with ItemCatalogue(db) as catalogue:
        catalogue.upsert_items(records)
        loaded = {row.item_id: row for row in catalogue.list_items()}
        assert len(loaded) == len({row.item_id for row in records})
        for original in records:
            assert loaded[original.item_id].canonical_dict() == original.canonical_dict()
        before = catalogue.catalogue_hash()
    with ItemCatalogue(db) as catalogue:
        assert catalogue.catalogue_hash() == before


def test_druid_weapon_fixture_is_catalogue_readable_and_class_filterable(tmp_path: Path):
    row = legacy_row_to_item(FERAL_WEAPON_PROGRESSION[0], namespace="druid_weapon", default_slot="weapon")
    assert row.item_id == 270018
    assert row.weapon_dps == 20.44
    assert row.weapon_speed == 3.40
    assert row.required_level == 10

    with ItemCatalogue(tmp_path / "items.sqlite") as catalogue:
        catalogue.upsert_item(row)
        catalogue.add_class_eligibility(row.item_id, 11, "legacy_druid_weapon")
        got = catalogue.eligible_items(class_id=11, level=20, slot="weapon")
        assert [x.item_id for x in got] == [270018]
        assert got[0].canonical_dict() == row.canonical_dict()
