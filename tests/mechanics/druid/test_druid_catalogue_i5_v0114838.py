from __future__ import annotations

from src.rulesets.forever.classes.druid.mechanics import _balance_gear, _bear_gear, _feral_gear

SLOT_ORDER = (
    "head", "neck", "shoulder", "back", "chest", "wrist", "hands", "waist", "legs", "feet",
    "ring1", "ring2", "trinket1", "trinket2", "weapon", "offhand", "wand",
)


def _assert_coverage(gear: dict):
    counts = gear["catalogue_candidate_counts"]
    blocked = set(gear.get("blocked_slots") or ())
    missing = [slot for slot in SLOT_ORDER if slot not in gear["slots"] and slot not in blocked and counts.get(slot, 0) <= 0]
    assert missing == []
    assert gear["catalogue_mode"] == "sqlite_runtime_authority"
    for slot, row in gear["slots"].items():
        assert row["item_id"] > 0
        assert row["identity_origin"] == "wowhead_listview"
        assert row["model_kind"] == "canonical_sqlite_item"
        assert row["modeled"] is False


def test_l20_druid_selected_gear_is_sql_backed_and_catalogue_has_full_supported_slot_coverage():
    for gear in (_feral_gear(20), _balance_gear(20), _bear_gear(20)):
        assert gear["provenance"] == "sqlite_catalogue"
        _assert_coverage(gear)
        assert gear["catalogue_candidate_counts"]["neck"] > 0
        assert gear["catalogue_candidate_counts"]["shoulder"] > 0
        assert gear["catalogue_candidate_counts"]["ring1"] > 0
        assert gear["catalogue_candidate_counts"]["trinket1"] > 0


def test_l20_catalogue_role_selection_preserves_role_semantics():
    feral = _feral_gear(20)
    balance = _balance_gear(20)
    bear = _bear_gear(20)
    assert feral["agility"] > 0 and feral["spell_power"] == 0
    assert balance["spell_power"] > 0
    assert bear["stamina"] >= feral["stamina"]
