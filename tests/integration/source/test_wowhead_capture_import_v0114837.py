from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.rulesets.forever.items.catalogue import ItemCatalogue
from src.rulesets.forever.items.wowhead_capture_import import canonical_base_rows, import_adaptive_capture, item_record_from_listview


def test_variant_rows_collapse_to_one_canonical_base_row():
    rows = [
        {"id": 7, "name": "Base", "level": 20, "slot": 1},
        {"id": 7, "name": "Base", "level": 20, "slot": 1, "parentListviewRowItem": 7, "bonuses": [1]},
    ]
    assert canonical_base_rows(rows)[7]["name"] == "Base"
    with pytest.raises(ValueError):
        canonical_base_rows([rows[1]])


def test_listview_row_maps_core_item_facts_and_preserves_unknown_numeric_stats():
    rec = item_record_from_listview({
        "id": 123, "name": "Example", "level": 25, "reqlevel": 20, "slot": 17,
        "quality": 3, "classs": 2, "subclass": 10, "sta": 8, "int": 5,
        "splpwr": 12, "manargn": 3, "critstrkrtng": 4, "dmgmin1": 30,
        "dmgmax1": 50, "speed": 2.5, "dps": 16, "spldmg": 6,
    }, captured_at="2026-09-29T10:28:08Z")
    assert rec.slot == "two_hand"
    assert rec.weapon_type == "staff"
    assert rec.weapon_hands == 2
    assert rec.stamina == 8 and rec.intellect == 5
    assert rec.spell_power == 12 and rec.mp5 == 3 and rec.crit == 4
    assert rec.weapon_min_damage == 30 and rec.weapon_max_damage == 50 and rec.weapon_speed == 2.5
    assert rec.extra_stats["spldmg"] == 6
    assert rec.required_level_origin == "observed"
    assert rec.fetch_status == "verified_listview"


def _write_capture(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    attempts = []
    for cls, cid in (("mage", 8), ("druid", 11), ("paladin", 2)):
        rows = [
            {"id": 100, "name": "Shared", "level": 20, "reqlevel": 15, "slot": 1, "quality": 2, "classs": 4, "subclass": 1, "int": 3},
            {"id": 100, "name": "Shared", "level": 20, "reqlevel": 15, "slot": 1, "quality": 2, "classs": 4, "subclass": 1, "int": 3, "parentListviewRowItem": 100},
            {"id": 100 + cid, "name": cls, "level": 20, "slot": 5, "quality": 2, "classs": 4, "subclass": 1},
        ]
        (root / f"{cls}_merged.listview.json").write_text(json.dumps(rows), encoding="utf-8")
        attempts.append({
            "class_key": cls, "min_item_level": 10, "max_item_level": 29,
            "accepted": True, "needs_split": False, "listview_unique_ids": 2,
            "found_count": None, "displayed_count": None, "url": f"https://example/{cls}",
        })
    (root / "manifest.json").write_text(json.dumps({
        "captured_at": "2026-09-29T10:28:08Z", "classes": ["mage", "druid", "paladin"], "attempts": attempts,
    }), encoding="utf-8")
    return root


def test_capture_import_builds_global_deduplicated_catalogue_and_class_links(tmp_path: Path):
    capture = _write_capture(tmp_path / "capture")
    db = tmp_path / "items.sqlite"
    summary = import_adaptive_capture(capture, db)
    assert summary.canonical_items == 4
    assert summary.class_eligibility_rows == 6
    assert summary.unique_ids_by_class == {"mage": 2, "druid": 2, "paladin": 2}
    assert summary.union_unique_ids == 4
    assert summary.variant_rows_by_class == {"mage": 1, "druid": 1, "paladin": 1}
    assert summary.observed_required_level == 1
    assert summary.inferred_required_level == 3
    assert summary.unresolved_required_level == 0
    with ItemCatalogue(db) as cat:
        shared = cat.get_item(100)
        assert shared is not None and shared.intellect == 3
        assert len(cat.eligible_items(class_id=8, level=60)) == 2
        assert len(cat.eligible_items(class_id=11, level=60)) == 2
        assert len(cat.eligible_items(class_id=2, level=60)) == 2


def test_terminal_capped_leaf_is_rejected(tmp_path: Path):
    capture = _write_capture(tmp_path / "capture")
    manifest = json.loads((capture / "manifest.json").read_text())
    manifest["attempts"][0]["listview_unique_ids"] = 1000
    (capture / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="still capped"):
        import_adaptive_capture(capture, tmp_path / "items.sqlite")
