from __future__ import annotations

from src.rulesets.forever.items.catalogue import ItemCatalogue
from src.rulesets.forever.items.runtime_selection import catalogue_path
from src.rulesets.forever.classes.mage.real_gear import snapshot as mage_snapshot
from src.rulesets.forever.classes.paladin.gear import archetypes as paladin_archetypes, gear_snapshot as paladin_snapshot
from src.rulesets.forever.classes.druid import mechanics as druid
from src.v2.experimental_classes import _gear_label


def _assert_rows_are_canonical(level: int, rows: dict[str, dict]) -> None:
    assert rows, f"no selected rows at L{level}"
    with ItemCatalogue(catalogue_path()) as cat:
        for slot, row in rows.items():
            item_id = int(row.get("item_id") or 0)
            assert item_id > 0, (level, slot, row)
            assert row.get("model_kind") == "canonical_sqlite_item", (level, slot, row)
            assert int(row.get("effective_level") or 0) <= level, (level, slot, row)
            db = cat.get_item(item_id)
            assert db is not None, (level, slot, item_id)
            assert row.get("name") == db.name, (level, slot, row.get("name"), db.name)


def test_all_three_classes_publish_only_canonical_sql_gear_at_checkpoints():
    for level in (10, 20, 34, 40, 60):
        mage = mage_snapshot(level)
        assert mage["provenance"] == "canonical_sqlite_forever_catalogue"
        _assert_rows_are_canonical(level, mage["slots"])

        for gear in paladin_archetypes(level):
            snap = paladin_snapshot(gear)
            assert snap["catalogue_mode"] == "sqlite_runtime_authority"
            assert snap["reconciliation_ok"] is True
            _assert_rows_are_canonical(level, snap["slots"])

        for getter in (druid._feral_gear, druid._bear_gear, druid._balance_gear):
            snap = getter(level)
            assert snap["catalogue_mode"] == "sqlite_runtime_authority"
            assert snap["provenance"] == "sqlite_catalogue"
            _assert_rows_are_canonical(level, snap["slots"])


def test_experimental_listener_never_invents_placeholder_gear_label():
    assert _gear_label({}) is None
    assert _gear_label({"gear_stats": {}}) is None
    assert _gear_label({"gear_stats": {"name": "canonical_sqlite_druid_feral"}}) == "canonical_sqlite_druid_feral"
    assert _gear_label({"gear": "canonical_sqlite_druid_bear"}) == "canonical_sqlite_druid_bear"
