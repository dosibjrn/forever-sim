from pathlib import Path

from src.rulesets.forever.classes.hunter.mechanics import _gear_from_catalogue


def test_hunter_canonical_gear_has_ranged_slot_and_live_weapon_stats():
    gear = _gear_from_catalogue(20, {})
    ranged = gear["slots"].get("ranged")
    assert ranged, "Hunter publication must carry the ranged weapon item used by the scorer"
    assert int(ranged.get("item_id") or 0) > 0
    assert float(ranged.get("weapon_dps") or 0.0) > 0.0
    assert abs(float(gear["weapon_dps"]) - float(ranged["weapon_dps"])) < 1e-12


def test_listener_renders_ranged_slot_and_does_not_flag_wand_for_ranged_loadout():
    js = Path("src/listener.py").read_text(encoding="utf-8")
    assert "'ranged','weapon','offhand','wand'" in js
    assert "if(slots.ranged)blocked.add('wand')" in js
    assert "if(slots.wand)blocked.add('ranged')" in js
