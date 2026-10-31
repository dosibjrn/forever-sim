from __future__ import annotations

from src.rulesets.forever.classes.mage.real_gear import snapshot


def _name(level: int, slot: str) -> str:
    return snapshot(level)["slots"][slot]["name"]


def test_midlevel_mage_progression_uses_real_named_forever_items():
    assert _name(30, "head") == "Embalmed Shroud"
    assert _name(34, "weapon") == "Illusionary Rod"
    assert _name(35, "weapon") == "Celestial Stave"
    assert _name(40, "chest") == "Dreamweave Vest"
    assert _name(40, "hands") == "Dreamweave Gloves"
    assert _name(45, "head") == "Dreamweave Circlet"
    assert _name(47, "back") == "Spritecaster Cape"
    assert _name(49, "ring1") == "Cyclopean Band"
    assert _name(50, "neck") == "Arcane Crystal Pendant"
    assert _name(55, "ring2") == "Maiden's Circle"
    assert _name(58, "weapon") == "Rod of the Ogre Magi"
    assert _name(58, "back") == "Crystalline Threaded Cape"


def test_new_real_items_keep_literal_item_levels_and_never_become_modeled_rows():
    for level in range(10, 61):
        s = snapshot(level)
        assert s["provenance"] == "discrete_named_forever_items"
        assert all(not row["name"].startswith("Modeled ") for row in s["slots"].values())

    s60 = snapshot(60)
    assert s60["slots"]["chest"]["name"] == "Dreamweave Vest"
    assert s60["slots"]["chest"]["effective_level"] == 40
    assert s60["slots"]["weapon"]["name"] == "Rod of the Ogre Magi"
    assert s60["slots"]["weapon"]["effective_level"] == 58
