from __future__ import annotations

"""Verified Forever crafted-item anchors used by the leveling models.

The purpose of this module is calibration, not BIS simulation. Rows are added
only when current Forever profession/client sources expose required level and
relevant stats. Profession families are useful designed baselines because they
expose role variants at comparable levels/slots.

Checked through 2026-09-24 against current Wowhead Forever item/profession
data, the beta client item datamine, and Mobalytics Forever profession tables.
Paladin rerolls additionally consume audited dungeon/quest/world/PvP items.
"""

from dataclasses import asdict, dataclass
from typing import Iterable


@dataclass(frozen=True)
class CraftedItem:
    profession: str
    family: str
    name: str
    slot: str
    item_level: int
    required_level: int
    armor: float = 0.0
    strength: float = 0.0
    agility: float = 0.0
    stamina: float = 0.0
    intellect: float = 0.0
    spirit: float = 0.0
    spell_damage: float = 0.0
    healing: float = 0.0
    spell_power: float = 0.0
    defense: float = 0.0
    bonus_armor: float = 0.0
    attack_power: float = 0.0
    mp5: float = 0.0
    source_url: str = ""

    @property
    def damage_power(self) -> float:
        # Wowhead uses either generic "Spell Power" or the old split
        # "Damage Done / Healing Done" wording depending on the item.
        return max(float(self.spell_power), float(self.spell_damage))

    def as_dict(self) -> dict:
        row = asdict(self)
        row["damage_power"] = self.damage_power
        return row


CRAFTED_ITEMS: tuple[CraftedItem, ...] = (
    # Tailoring -- caster/stat calibration.
    CraftedItem("tailoring", "novice_arcanist", "Novice Arcanist's Sash", "waist", 15, 10,
                armor=17, stamina=3, intellect=3, spell_power=4,
                source_url="https://www.wowhead.com/forever/item=253885/novice-arcanists-sash"),
    CraftedItem("tailoring", "pristine", "Pristine Gloves", "hands", 20, 15,
                armor=23, stamina=4, intellect=3, spell_damage=4, healing=11,
                source_url="https://www.wowhead.com/forever/spell=1257382/pristine-gloves"),
    CraftedItem("tailoring", "pristine", "Pristine Sash", "waist", 22, 17,
                armor=22, stamina=5, intellect=4, spell_damage=4, healing=11,
                source_url="https://www.wowhead.com/forever/item=253925/pristine-sash"),
    CraftedItem("tailoring", "filigreed_shadow", "Filigreed Shadow Gown", "chest", 20, 15,
                armor=37, stamina=4, intellect=5, spirit=3,
                source_url="https://www.wowhead.com/forever/spell=1257379/filigreed-shadow-gown"),
    CraftedItem("tailoring", "filigreed_pristine", "Filigreed Pristine Leggings", "legs", 25, 20,
                armor=37, stamina=5, intellect=6, spirit=4, spell_damage=6, healing=18,
                source_url="https://www.wowhead.com/forever/item=253937/filigreed-pristine-leggings"),
    CraftedItem("tailoring", "pristine", "Pristine Circlet", "head", 25, 20,
                armor=35, stamina=10, spell_damage=6, healing=18,
                source_url="https://www.wowhead.com/forever/item=253949/pristine-circlet"),
    CraftedItem("tailoring", "filigreed_pristine", "Filigreed Pristine Circlet", "head", 30, 25,
                armor=38, stamina=12, spell_damage=8, healing=22,
                source_url="https://www.wowhead.com/forever/item=253975/filigreed-pristine-circlet"),

    # Leatherworking -- Druid leveling calibration.  Brawler is the physical
    # Str/Agi family; Totemic is the hybrid Str/Int/SP family.  Rows are kept
    # only where the current Wowhead Forever craft tooltip exposes full stats.
    CraftedItem("leatherworking", "brawler", "Brawler's Leather Belt", "waist", 17, 12,
                armor=45, strength=4, agility=4, stamina=3,
                source_url="https://www.wowhead.com/forever/item=252428/brawlers-leather-belt"),
    CraftedItem("leatherworking", "brawler", "Brawler's Leather Gloves", "hands", 20, 15,
                armor=53, strength=4, agility=4, stamina=3,
                source_url="https://www.wowhead.com/forever/spell=1255130/brawlers-leather-gloves"),
    CraftedItem("leatherworking", "brawler", "Brawler's Leather Armor", "chest", 20, 15,
                armor=85, strength=5, agility=7, stamina=3, spirit=3,
                source_url="https://www.wowhead.com/forever/spell=1255136/brawlers-leather-armor"),
    CraftedItem("leatherworking", "brawler", "Brawler's Leather Boots", "feet", 22, 17,
                armor=61, strength=5, agility=5, stamina=4,
                source_url="https://www.wowhead.com/forever/item=252439/brawlers-leather-boots"),
    CraftedItem("leatherworking", "brawler", "Brawler's Leather Hood", "head", 25, 20,
                armor=76, agility=8, stamina=10,
                source_url="https://www.wowhead.com/forever/item=252504/brawlers-leather-hood"),
    CraftedItem("leatherworking", "brawler", "Brawler's Leather Pants", "legs", 25, 20,
                armor=82, strength=6, agility=9, stamina=4, spirit=4,
                source_url="https://www.wowhead.com/forever/spell=1255115/brawlers-leather-pants"),
    CraftedItem("leatherworking", "brawler", "Brawler's Leather Tunic", "chest", 27, 22,
                armor=98, strength=6, agility=8, stamina=6, spirit=5,
                source_url="https://www.wowhead.com/forever/spell=1255102/brawlers-leather-tunic"),
    CraftedItem("leatherworking", "brawler", "Brawler's Leather Helm", "head", 30, 25,
                armor=84, agility=10, stamina=13,
                source_url="https://www.wowhead.com/forever/spell=1255093/brawlers-leather-helm"),
    CraftedItem("leatherworking", "brawler", "Brawler's Leather Legguards", "legs", 30, 25,
                armor=90, strength=7, agility=9, stamina=7, spirit=6,
                source_url="https://www.wowhead.com/forever/item=252516/brawlers-leather-legguards"),

    CraftedItem("leatherworking", "totemic", "Totemic Leather Belt", "waist", 17, 12,
                armor=45, strength=4, stamina=3, spell_power=4,
                source_url="https://www.wowhead.com/forever/spell=1255139/totemic-leather-belt"),
    CraftedItem("leatherworking", "totemic", "Totemic Leather Gloves", "hands", 20, 15,
                armor=53, strength=4, stamina=3, spell_power=5,
                source_url="https://www.wowhead.com/forever/spell=1255127/totemic-leather-gloves"),
    CraftedItem("leatherworking", "totemic", "Totemic Leather Armor", "chest", 20, 15,
                armor=85, strength=7, stamina=3, intellect=3, spell_power=6,
                source_url="https://www.wowhead.com/forever/spell=1255133/totemic-leather-armor"),
    CraftedItem("leatherworking", "totemic", "Totemic Leather Boots", "feet", 22, 17,
                armor=61, strength=5, stamina=4, spell_power=6,
                source_url="https://www.wowhead.com/forever/spell=1255118/totemic-leather-boots"),
    CraftedItem("leatherworking", "totemic", "Totemic Leather Hood", "head", 25, 20,
                armor=76, stamina=10, spell_power=9,
                source_url="https://www.wowhead.com/forever/item=252448/totemic-leather-hood"),
    CraftedItem("leatherworking", "totemic", "Totemic Leather Pants", "legs", 25, 20,
                armor=82, strength=9, stamina=4, intellect=4, spell_power=7,
                source_url="https://www.wowhead.com/forever/spell=1255112/totemic-leather-pants"),
    CraftedItem("leatherworking", "totemic", "Totemic Leather Tunic", "chest", 27, 22,
                armor=98, strength=8, stamina=6, intellect=5, spell_power=7,
                source_url="https://www.wowhead.com/forever/spell=1255099/totemic-leather-tunic"),
    CraftedItem("leatherworking", "totemic", "Totemic Leather Helm", "head", 30, 25,
                armor=84, stamina=13, spell_power=12,
                source_url="https://www.wowhead.com/forever/spell=1255090/totemic-leather-helm"),
    CraftedItem("leatherworking", "totemic", "Totemic Leather Leggings", "legs", 30, 25,
                armor=90, strength=9, stamina=7, intellect=6, spell_power=8,
                source_url="https://www.wowhead.com/forever/spell=1255084/totemic-leather-leggings"),


    # Tailoring -- post-25 designed caster ladder.  High-level stat rows come
    # from the current Forever beta-client item datamine; profession-family
    # availability is cross-checked against the ACA profession recipe tables.
    CraftedItem("tailoring", "gilded", "Gilded Slippers", "feet", 35, 30,
                armor=35, stamina=6, intellect=7, spirit=4, spell_damage=7, healing=20,
                source_url="https://wowforeverbuilds.com/gear/feet"),
    CraftedItem("tailoring", "gilded", "Gilded Handwraps", "hands", 40, 35,
                armor=36, stamina=9, intellect=7, spell_damage=8, healing=22,
                source_url="https://wowforeverbuilds.com/gear/hands"),
    CraftedItem("tailoring", "gilded", "Gilded Cord", "waist", 45, 40,
                armor=37, stamina=8, intellect=8, spirit=6, spell_damage=8, healing=22,
                source_url="https://wowforeverbuilds.com/gear/waist"),
    CraftedItem("tailoring", "nethergeld", "Nethergeld Shoulders", "shoulder", 47, 42,
                armor=51, stamina=8, intellect=8, spirit=6, spell_damage=9, healing=26,
                source_url="https://wowforeverbuilds.com/gear/shoulder"),
    CraftedItem("tailoring", "nethergeld", "Nethergeld Cuffs", "wrist", 50, 45,
                armor=31, stamina=7, intellect=7, spirit=5, spell_damage=7, healing=20,
                source_url="https://wowforeverbuilds.com/gear/wrist"),
    CraftedItem("tailoring", "ghostweave", "Ghostweave Cord", "waist", 52, 47,
                armor=38, spirit=11, spell_power=14,
                source_url="https://wowforeverbuilds.com/gear/waist"),
    CraftedItem("tailoring", "gilded", "Gilded Waistcord", "waist", 52, 47,
                armor=42, stamina=12, intellect=9, spell_damage=10, healing=29,
                source_url="https://wowforeverbuilds.com/gear/waist"),
    CraftedItem("tailoring", "gilded", "Gilded Gloves", "hands", 55, 50,
                armor=49, stamina=9, intellect=10, spirit=8, spell_damage=10, healing=29,
                source_url="https://wowforeverbuilds.com/gear/hands"),
    CraftedItem("tailoring", "gilded", "Gilded Sandals", "feet", 55, 50,
                armor=54, stamina=13, intellect=9, spell_damage=11, healing=31,
                source_url="https://wowforeverbuilds.com/gear/feet"),
    CraftedItem("tailoring", "ghostweave", "Ghostweave Mantle", "shoulder", 59, 54,
                armor=57, spirit=12, spell_power=15,
                source_url="https://wowforeverbuilds.com/gear/shoulder"),
    CraftedItem("tailoring", "ghostweave", "Ghostweave Boots", "feet", 60, 55,
                armor=53, spirit=13, spell_power=16,
                source_url="https://wowforeverbuilds.com/gear/feet"),
    CraftedItem("tailoring", "ghostweave", "Ghostweave Hood", "head", 61, 56,
                armor=64, spirit=18, spell_power=21,
                source_url="https://wowforeverbuilds.com/gear/head"),

    # Leatherworking -- expert/post-25 Druid role ladders.
    # Prowler = Cat/physical, Skycaller = Balance/caster, Warden = Bear/tank.
    CraftedItem("leatherworking", "prowler", "Prowler's Leather Belt", "waist", 35, 30,
                armor=63, strength=9, agility=6, stamina=6, intellect=4,
                source_url="https://wowforeverbuilds.com/gear/waist"),
    CraftedItem("leatherworking", "skycaller", "Skycaller's Leather Belt", "waist", 35, 30,
                armor=63, stamina=6, intellect=6, spirit=4, spell_power=10,
                source_url="https://wowforeverbuilds.com/gear/waist"),
    CraftedItem("leatherworking", "warden", "Warden's Leather Belt", "waist", 35, 30,
                armor=63, bonus_armor=38, strength=6, agility=6, stamina=9,
                source_url="https://wowforeverbuilds.com/gear/waist"),
    CraftedItem("leatherworking", "prowler", "Prowler's Leather Gloves", "hands", 40, 35,
                armor=76, strength=10, agility=9, stamina=7,
                source_url="https://wowforeverbuilds.com/gear/hands"),
    CraftedItem("leatherworking", "skycaller", "Skycaller's Leather Gloves", "hands", 40, 35,
                armor=76, stamina=7, intellect=9, spell_power=11,
                source_url="https://wowforeverbuilds.com/gear/hands"),
    CraftedItem("leatherworking", "warden", "Warden's Leather Gloves", "hands", 40, 35,
                armor=76, bonus_armor=72, strength=9, stamina=10,
                source_url="https://wowforeverbuilds.com/gear/hands"),
    CraftedItem("leatherworking", "prowler", "Prowler's Leather Shoulders", "shoulder", 47, 42,
                armor=104, strength=11, agility=9, stamina=7, intellect=6,
                source_url="https://wowforeverbuilds.com/gear/shoulder"),
    CraftedItem("leatherworking", "skycaller", "Skycaller's Leather Shoulders", "shoulder", 47, 42,
                armor=104, stamina=7, intellect=9, spirit=6, spell_power=13,
                source_url="https://wowforeverbuilds.com/gear/shoulder"),
    CraftedItem("leatherworking", "warden", "Warden's Leather Shoulders", "shoulder", 47, 42,
                armor=104, bonus_armor=65, strength=9, agility=7, stamina=11,
                source_url="https://wowforeverbuilds.com/gear/shoulder"),
    CraftedItem("leatherworking", "prowler", "Prowler's Leather Bracers", "wrist", 50, 45,
                armor=64, strength=9, agility=7, stamina=6, intellect=5,
                source_url="https://wowforeverbuilds.com/gear/wrist"),
    CraftedItem("leatherworking", "skycaller", "Skycaller's Leather Bracers", "wrist", 50, 45,
                armor=64, stamina=6, intellect=7, spirit=5, spell_power=10,
                source_url="https://wowforeverbuilds.com/gear/wrist"),
    CraftedItem("leatherworking", "warden", "Warden's Leather Bracers", "wrist", 50, 45,
                armor=64, bonus_armor=52, strength=7, agility=6, stamina=9,
                source_url="https://wowforeverbuilds.com/gear/wrist"),
    CraftedItem("leatherworking", "prowler", "Prowler's Leather Boots", "feet", 52, 47,
                armor=104, strength=13, agility=11, stamina=9,
                source_url="https://wowforeverbuilds.com/gear/feet"),
    CraftedItem("leatherworking", "skycaller", "Skycaller's Leather Boots", "feet", 52, 47,
                armor=104, stamina=9, intellect=11, spell_power=15,
                source_url="https://wowforeverbuilds.com/gear/feet"),
    CraftedItem("leatherworking", "warden", "Warden's Leather Boots", "feet", 52, 47,
                armor=104, bonus_armor=93, strength=11, stamina=13,
                source_url="https://wowforeverbuilds.com/gear/feet"),
    CraftedItem("leatherworking", "prowler", "Prowler's Leather Gauntlets", "hands", 55, 50,
                armor=99, strength=14, agility=9, stamina=9, intellect=6,
                source_url="https://wowforeverbuilds.com/gear/hands"),
    CraftedItem("leatherworking", "skycaller", "Skycaller's Leather Gauntlets", "hands", 55, 50,
                armor=99, stamina=9, intellect=9, spirit=6, spell_power=16,
                source_url="https://wowforeverbuilds.com/gear/hands"),
    CraftedItem("leatherworking", "warden", "Warden's Leather Gauntlets", "hands", 55, 50,
                armor=99, bonus_armor=62, strength=9, agility=9, stamina=14,
                source_url="https://wowforeverbuilds.com/gear/hands"),
    CraftedItem("leatherworking", "prowler", "Prowler's Leather Waistguard", "waist", 55, 50,
                armor=89, strength=14, agility=12, stamina=10,
                source_url="https://wowforeverbuilds.com/gear/waist"),
    CraftedItem("leatherworking", "skycaller", "Skycaller's Leather Waistguard", "waist", 55, 50,
                armor=89, stamina=10, intellect=12, spell_power=16,
                source_url="https://wowforeverbuilds.com/gear/waist"),
    CraftedItem("leatherworking", "warden", "Warden's Leather Waistguard", "waist", 55, 50,
                armor=89, bonus_armor=102, strength=12, stamina=14,
                source_url="https://wowforeverbuilds.com/gear/waist"),

    # Blacksmithing -- Paladin role families.  Crusader/Justicar are the
    # offensive Str/SP ladder; Protector/Warder the shield/tank ladder;
    # Acolyte/Prefect capture the Holy Int/healing budget for audit purposes.
    CraftedItem("blacksmithing", "crusader", "Crusader's Chain Belt", "waist", 17, 12,
                armor=98, strength=3, stamina=4, spell_power=5,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "crusader", "Crusader's Gloves", "hands", 20, 15,
                armor=115, strength=3, stamina=5, spell_power=5,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "crusader", "Crusader's Chain Shirt", "chest", 20, 15,
                armor=184, strength=4, stamina=5, spell_power=8,
                source_url="https://www.wowhead.com/forever/spell=1252241/crusaders-chain-shirt"),
    CraftedItem("blacksmithing", "crusader", "Crusader's Boots", "feet", 22, 17,
                armor=131, strength=4, stamina=5, spell_power=6,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "crusader", "Crusader's Chain Leggings", "legs", 25, 20,
                armor=176, strength=5, stamina=7, spell_power=11,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "crusader", "Crusader's Silvered Chain Helm", "head", 25, 20,
                armor=163, stamina=9, spell_power=11,
                source_url="https://www.wowhead.com/forever/spell=1252281/crusaders-silvered-chain-helm"),
    CraftedItem("blacksmithing", "classic_mail", "Rough Bronze Shoulders", "shoulder", 22, 17,
                armor=130, strength=3, stamina=4,
                source_url="https://www.wowhead.com/forever/spell=3328/rough-bronze-shoulders"),
    CraftedItem("blacksmithing", "classic_mail", "Silvered Bronze Shoulders", "shoulder", 25, 20,
                armor=137, strength=3, stamina=3, spirit=3,
                source_url="https://www.wowhead.com/forever/item=3481/silvered-bronze-shoulders"),
    CraftedItem("blacksmithing", "crusader", "Crusader's Silvered Shirt", "chest", 27, 22,
                armor=208, strength=6, stamina=7, spell_power=12,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "crusader", "Crusader's Chain Helm", "head", 30, 25,
                armor=177, strength=11, spell_power=14,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "crusader", "Crusader's Silvered Leggings", "legs", 30, 25,
                armor=191, strength=7, stamina=8, spell_power=13,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "justicar", "Justicar's Belt", "waist", 35, 30,
                armor=132, strength=6, stamina=7, spell_power=12,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "justicar", "Justicar's Gauntlet", "hands", 40, 35,
                armor=159, strength=7, stamina=9, spell_power=11,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "justicar", "Justicar's Boots", "feet", 45, 40,
                armor=330, strength=7, stamina=9, spell_power=15,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "justicar", "Justicar's Pauldrons", "shoulder", 47, 42,
                armor=375, strength=8, stamina=10, spell_power=16,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "justicar", "Justicar's Wrist", "wrist", 50, 45,
                armor=231, strength=6, stamina=8, spell_power=12,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "justicar", "Justicar's Sabatons", "feet", 52, 47,
                armor=376, strength=9, stamina=12, spell_power=15,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "justicar", "Justicar's Gloves", "hands", 55, 50,
                armor=361, strength=9, stamina=11, spell_power=19,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "justicar", "Justicar's Waistguard", "waist", 55, 50,
                armor=324, strength=10, stamina=13, spell_power=16,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),

    CraftedItem("blacksmithing", "protector", "Protector's Chain Belt", "waist", 17, 12,
                armor=98, stamina=4, spell_power=5, defense=3,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "protector", "Protector's Gloves", "hands", 20, 15,
                armor=115, stamina=5, spell_power=5, defense=3,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "protector", "Protector's Boots", "feet", 22, 17,
                armor=131, stamina=5, spell_power=6, defense=4,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "protector", "Protector's Chain Leggings", "legs", 25, 20,
                armor=176, stamina=9, spell_power=6, defense=7,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "protector", "Protector's Silvered Helm", "head", 25, 20,
                armor=163, stamina=9, defense=7,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "protector", "Protector's Silvered Shirt", "chest", 27, 22,
                armor=208, stamina=10, spell_power=7, defense=7,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "protector", "Protector's Chain Helm", "head", 30, 25,
                armor=177, stamina=11, defense=8,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "protector", "Protector's Silvered Leggings", "legs", 30, 25,
                armor=191, stamina=11, spell_power=8, defense=8,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "warder", "Warder's Belt", "waist", 35, 30,
                armor=132, stamina=10, spell_power=7, defense=7,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "warder", "Warder's Gauntlet", "hands", 40, 35,
                armor=159, stamina=10, spell_power=11, defense=7,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "warder", "Warder's Boots", "feet", 45, 40,
                armor=330, stamina=13, spell_power=9, defense=9,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "warder", "Warder's Pauldrons", "shoulder", 47, 42,
                armor=375, stamina=13, spell_power=9, defense=10,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "warder", "Warder's Wrist", "wrist", 50, 45,
                armor=231, stamina=11, spell_power=7, defense=8,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "warder", "Warder's Sabatons", "feet", 52, 47,
                armor=376, stamina=13, spell_power=14, defense=9,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "warder", "Warder's Gloves", "hands", 55, 50,
                armor=361, stamina=16, spell_power=11, defense=11,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "warder", "Warder's Waistguard", "waist", 55, 50,
                armor=324, stamina=14, spell_power=15, defense=10,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),

    CraftedItem("blacksmithing", "prefect", "Prefect's Belt", "waist", 35, 30,
                armor=132, stamina=6, intellect=7, spell_damage=7, healing=22,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "prefect", "Prefect's Gauntlet", "hands", 40, 35,
                armor=159, stamina=9, intellect=7, spell_damage=7, healing=21,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "prefect", "Prefect's Boots", "feet", 45, 40,
                armor=330, stamina=7, intellect=9, spell_damage=9, healing=28,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "prefect", "Prefect's Pauldrons", "shoulder", 47, 42,
                armor=375, stamina=8, intellect=10, spell_damage=10, healing=29,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "prefect", "Prefect's Wrist", "wrist", 50, 45,
                armor=231, stamina=6, intellect=8, spell_damage=8, healing=23,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "prefect", "Prefect's Sabatons", "feet", 52, 47,
                armor=376, stamina=12, intellect=9, spell_damage=9, healing=27,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "prefect", "Prefect's Gloves", "hands", 55, 50,
                armor=361, stamina=9, intellect=11, spell_damage=12, healing=35,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "prefect", "Prefect's Waistguard", "waist", 55, 50,
                armor=324, stamina=13, intellect=10, spell_damage=10, healing=30,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),

    # Late Blacksmithing samples.  These extend the observable body ladder past
    # the ACA role-family sets without pretending every tradeoff is an upgrade.
    CraftedItem("blacksmithing", "blessed_plate", "Blessed Plate Chest", "chest", 61, 56,
                armor=579, strength=20, stamina=8, spell_power=13,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "blessed_plate", "Blessed Plate Helm", "head", 60, 55,
                armor=463, strength=11, stamina=7, spell_power=23,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "blessed_plate", "Blessed Plate Leggings", "legs", 59, 54,
                armor=491, strength=7, stamina=20, spell_power=13,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "depleted_thorium", "Depleted Thorium Sabatons", "feet", 65, 60,
                armor=507, strength=14, stamina=21, spell_damage=21,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "enriched_thorium", "Enriched Thorium Breastplate", "chest", 62, 57,
                armor=647, stamina=25, spell_power=14, defense=9,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "enriched_thorium", "Enriched Thorium Helm", "head", 63, 58,
                armor=534, stamina=21, spell_power=23, defense=8,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),
    CraftedItem("blacksmithing", "enriched_thorium", "Enriched Thorium Leggings", "legs", 63, 58,
                armor=575, stamina=26, spell_power=14, defense=9,
                source_url="https://mobalytics.gg/wow-forever/guides/blacksmithing-profession-guide"),

)

# Audited open-world / dungeon / quest / PvP Paladin candidates.  The historical
# CraftedItem type is reused here as a generic immutable stat row; ``profession``
# carries the acquisition category for listener provenance.  Keeping these rows
# separate from CRAFTED_ITEMS avoids silently changing profession-only APIs while
# allowing the Paladin per-level gear optimizer to use real non-crafted gear.
PALADIN_AUDITED_ITEMS: tuple[CraftedItem, ...] = (
    CraftedItem("dungeon", "rfc", "Cavedweller Bracers", "wrist", 18, 13,
                armor=78, strength=2, stamina=3,
                source_url="https://www.wowhead.com/forever/item=14147/cavedweller-bracers"),
    CraftedItem("quest", "hall_of_thanes", "Cryptwalker Bracers", "wrist", 17, 10,
                armor=76, strength=4, stamina=3,
                source_url="https://www.wowhead.com/forever/item=280095/cryptwalker-bracers"),
    CraftedItem("dungeon", "shadowfang_keep", "Rift Bracers", "wrist", 25, 20,
                armor=80, stamina=4, spell_power=2,
                source_url="https://www.wowhead.com/forever/item=5943/rift-bracers"),
    CraftedItem("world_rare", "blessing_of_kalimdor", "Raptor Hide Cloak", "back", 21, 16,
                armor=19, stamina=4, spirit=3,
                source_url="https://www.wowhead.com/forever/item=285329/raptor-hide-cloak"),
    CraftedItem("pvp", "battle_healer", "Battle Healer's Cloak", "back", 23, 18,
                armor=20, stamina=4, spirit=2, spell_power=3, healing=9,
                source_url="https://www.wowhead.com/forever/item=20427/battle-healers-cloak"),
    CraftedItem("quest", "riverglades", "Tarnished Locket", "neck", 24, 15,
                stamina=5, spirit=4,
                source_url="https://www.wowhead.com/forever/item=279870/tarnished-locket"),
    CraftedItem("world_rare", "blessing_of_kalimdor", "Mark of the Pack Leader", "neck", 25, 20,
                strength=5, intellect=5,
                source_url="https://www.wowhead.com/forever/item=285331/mark-of-the-pack-leader"),
    CraftedItem("quest", "ruins_of_lordaeron", "Slain Baron's Signet", "ring2", 23, 16,
                stamina=5, defense=2,
                source_url="https://www.wowhead.com/forever/item=279867/slain-barons-signet"),
    CraftedItem("dungeon", "deadmines", "First Mate Band", "ring1", 22, 17,
                strength=6, stamina=2,
                source_url="https://www.wowhead.com/forever/item=284715/first-mate-band"),
    CraftedItem("world_rare", "blessing_of_kalimdor", "Signet of the Zhevra", "ring2", 23, 18,
                agility=6, spirit=2,
                source_url="https://www.wowhead.com/forever/item=285330/signet-of-the-zhevra"),
    CraftedItem("pvp", "warsong", "Advisor's Ring", "ring1", 23, 18,
                stamina=2, spell_power=5, healing=5, mp5=2,
                source_url="https://www.wowhead.com/forever/item=20426/advisors-ring"),
    CraftedItem("pvp", "warsong", "Lorekeeper's Ring", "ring2", 23, 18,
                stamina=2, spell_power=5, healing=5, mp5=2,
                source_url="https://www.wowhead.com/forever/item=20431/lorekeepers-ring"),
    CraftedItem("quest", "wailing_caverns", "Talbar Mantle", "shoulder", 26, 15,
                armor=33, stamina=3, intellect=6, mp5=2,
                source_url="https://www.wowhead.com/forever/item=10657/talbar-mantle"),
    CraftedItem("dungeon", "ruins_of_lordaeron", "Atrophic Girdle", "waist", 20, 15,
                armor=104, strength=5, stamina=5,
                source_url="https://www.wowhead.com/forever/item=271201/atrophic-girdle"),
    CraftedItem("dungeon", "ruins_of_lordaeron", "Abomination Bones", "chest", 20, 15,
                armor=184, strength=9, agility=4, stamina=2,
                source_url="https://www.wowhead.com/forever/item=271205/abomination-bones"),
    CraftedItem("dungeon", "ruins_of_lordaeron", "Grip of Fear", "hands", 22, 17,
                armor=119, strength=5, agility=4, stamina=5,
                source_url="https://www.wowhead.com/forever/item=271208/grip-of-fear"),
    CraftedItem("dungeon", "ruins_of_lordaeron", "Bonerust Leggings", "legs", 21, 16,
                armor=164, strength=7, agility=6, spirit=3,
                source_url="https://www.wowhead.com/forever/item=271209/bonerust-leggings"),
    CraftedItem("quest", "deadmines", "Chausses of Westfall", "legs", 24, 14,
                armor=173, strength=11, stamina=5,
                source_url="https://www.wowhead.com/forever/item=6087/chausses-of-westfall"),
    CraftedItem("quest", "hall_of_thanes", "Deepgrave Trousers", "legs", 17, 10,
                armor=70, strength=7, agility=3, spirit=3,
                source_url="https://www.wowhead.com/forever/item=279900/deepgrave-trousers"),
    CraftedItem("quest", "deadmines", "Lookie's Spyglass", "trinket1", 23, 18,
                spirit=1,
                source_url="https://www.wowhead.com/forever/item=273298/lookies-spyglass"),
    CraftedItem("pvp", "rune_of_battle", "Rune of Perfection", "trinket2", 25, 20,
                stamina=4,
                source_url="https://www.wowhead.com/forever/item=21566/rune-of-perfection"),

    # Mid/high-level deterministic Paladin candidates.  Random-enchant greens
    # are intentionally excluded: every row below has one stable current
    # Forever tooltip, so the optimizer never invents a favorable suffix.
    CraftedItem("blacksmithing", "classic_mail", "Golden Scale Shoulders", "shoulder", 35, 30,
                armor=160, strength=7, spirit=6,
                source_url="https://www.wowhead.com/forever/item=3841/golden-scale-shoulders"),
    CraftedItem("dungeon", "scarlet_monastery", "Herod's Shoulder", "shoulder", 42, 37,
                armor=196, strength=6, stamina=15,
                source_url="https://www.wowhead.com/forever/item=7718/herods-shoulder"),
    CraftedItem("world_drop", "classic_neck", "Kaleidoscope Chain", "neck", 35, 30,
                strength=4, agility=4, stamina=4, intellect=4, spirit=4,
                source_url="https://www.wowhead.com/forever/item=13084/kaleidoscope-chain"),
    CraftedItem("dungeon", "scarlet_monastery", "Scorn's Icy Choker", "neck", 35, 30,
                stamina=5, intellect=6, spell_power=7,
                source_url="https://www.wowhead.com/forever/item=23169/scorns-icy-choker"),
    CraftedItem("dungeon", "uldaman", "Skullplate Bracers", "wrist", 42, 40,
                armor=163, strength=5, stamina=9, spirit=5,
                source_url="https://www.wowhead.com/forever/item=9432/skullplate-bracers"),
    CraftedItem("dungeon", "blackrock_depths", "Spritecaster Cape", "back", 52, 47,
                armor=37, stamina=5, intellect=6, spirit=6, spell_power=14,
                source_url="https://www.wowhead.com/forever/item=11623/spritecaster-cape"),
    CraftedItem("dungeon", "blackrock_depths", "Blackveil Cape", "back", 53, 48,
                armor=38, strength=6, agility=14,
                source_url="https://www.wowhead.com/forever/item=11626/blackveil-cape"),
    CraftedItem("dungeon", "stratholme", "Stoneskin Gargoyle Cape", "back", 61, 56,
                armor=43, strength=7, agility=8, stamina=14,
                source_url="https://www.wowhead.com/forever/item=13397/stoneskin-gargoyle-cape"),
    CraftedItem("quest", "silithus", "Crystalline Threaded Cape", "back", 63, 58,
                armor=45, stamina=5, intellect=4, spell_power=20,
                source_url="https://www.wowhead.com/forever/item=20697/crystalline-threaded-cape"),
    CraftedItem("dungeon", "maraudon", "Blackstone Ring", "ring1", 54, 49,
                stamina=6, attack_power=20,
                source_url="https://www.wowhead.com/forever/item=17713/blackstone-ring"),
    CraftedItem("quest", "blackrock_depths", "Magni's Will", "ring2", 60, 54,
                strength=6, stamina=7,
                source_url="https://www.wowhead.com/forever/item=12548/magnis-will"),
    CraftedItem("dungeon", "stratholme", "Star of Mystaria", "neck", 63, 58,
                stamina=9, intellect=9, spirit=8,
                source_url="https://www.wowhead.com/forever/item=12103/star-of-mystaria"),
    CraftedItem("dungeon", "deadmines", "Band of the Better Half", "ring1", 70, 60,
                strength=18, stamina=10,
                source_url="https://www.wowhead.com/forever/item=284716/band-of-the-better-half"),
)

_ALL_ITEMS = CRAFTED_ITEMS + PALADIN_AUDITED_ITEMS
_BY_NAME = {item.name: item for item in _ALL_ITEMS}

# A conservative cloth caster progression.  Each slot uses only a tooltip row
# whose required level and stats have been verified.  This is a calibration
# overlay on the old smooth curve, not an assertion that every Mage owns it.
MAGE_CASTER_SLOT_PROGRESSION: dict[str, tuple[str, ...]] = {
    "waist": ("Novice Arcanist's Sash", "Pristine Sash", "Gilded Cord", "Gilded Waistcord", "Ghostweave Cord"),
    "hands": ("Pristine Gloves", "Gilded Handwraps", "Gilded Gloves"),
    "chest": ("Filigreed Shadow Gown",),
    "legs": ("Filigreed Pristine Leggings",),
    "head": ("Pristine Circlet", "Filigreed Pristine Circlet", "Ghostweave Hood"),
    "feet": ("Gilded Slippers", "Gilded Sandals", "Ghostweave Boots"),
    "shoulder": ("Nethergeld Shoulders", "Ghostweave Mantle"),
    "wrist": ("Nethergeld Cuffs",),
}


def item(name: str) -> CraftedItem:
    return _BY_NAME[name]


def available(*, level: int, profession: str | None = None, family: str | None = None) -> tuple[CraftedItem, ...]:
    rows: Iterable[CraftedItem] = CRAFTED_ITEMS
    if profession is not None:
        rows = (x for x in rows if x.profession == profession)
    if family is not None:
        rows = (x for x in rows if x.family == family)
    return tuple(x for x in rows if x.required_level <= int(level))


def _latest_from_progression(level: int, names: tuple[str, ...]) -> CraftedItem | None:
    rows = [item(name) for name in names if item(name).required_level <= int(level)]
    return max(rows, key=lambda x: (x.required_level, x.item_level)) if rows else None


def mage_caster_items(level: int) -> tuple[CraftedItem, ...]:
    return _progression_items(level, MAGE_CASTER_SLOT_PROGRESSION)


DRUID_FERAL_SLOT_PROGRESSION: dict[str, tuple[str, ...]] = {
    "waist": ("Brawler's Leather Belt", "Prowler's Leather Belt", "Prowler's Leather Waistguard"),
    "hands": ("Brawler's Leather Gloves", "Prowler's Leather Gloves", "Prowler's Leather Gauntlets"),
    "chest": ("Brawler's Leather Armor", "Brawler's Leather Tunic"),
    "feet": ("Brawler's Leather Boots", "Prowler's Leather Boots"),
    "head": ("Brawler's Leather Hood", "Brawler's Leather Helm"),
    "legs": ("Brawler's Leather Pants", "Brawler's Leather Legguards"),
    "shoulder": ("Prowler's Leather Shoulders",),
    "wrist": ("Prowler's Leather Bracers",),
}

DRUID_BALANCE_SLOT_PROGRESSION: dict[str, tuple[str, ...]] = {
    "waist": ("Totemic Leather Belt", "Skycaller's Leather Belt", "Skycaller's Leather Waistguard"),
    "hands": ("Totemic Leather Gloves", "Skycaller's Leather Gloves", "Skycaller's Leather Gauntlets"),
    "chest": ("Totemic Leather Armor", "Totemic Leather Tunic"),
    "feet": ("Totemic Leather Boots", "Skycaller's Leather Boots"),
    "head": ("Totemic Leather Hood", "Totemic Leather Helm"),
    "legs": ("Totemic Leather Pants", "Totemic Leather Leggings"),
    "shoulder": ("Skycaller's Leather Shoulders",),
    "wrist": ("Skycaller's Leather Bracers",),
}

DRUID_BEAR_SLOT_PROGRESSION: dict[str, tuple[str, ...]] = {
    # Low levels reuse the verified Brawler physical pieces until the Warden
    # family starts at 30.  High-level slots then switch independently.
    "waist": ("Brawler's Leather Belt", "Warden's Leather Belt", "Warden's Leather Waistguard"),
    "hands": ("Brawler's Leather Gloves", "Warden's Leather Gloves", "Warden's Leather Gauntlets"),
    "chest": ("Brawler's Leather Armor", "Brawler's Leather Tunic"),
    "feet": ("Brawler's Leather Boots", "Warden's Leather Boots"),
    "head": ("Brawler's Leather Hood", "Brawler's Leather Helm"),
    "legs": ("Brawler's Leather Pants", "Brawler's Leather Legguards"),
    "shoulder": ("Warden's Leather Shoulders",),
    "wrist": ("Warden's Leather Bracers",),
}

# Paladin body calibration families.  These are not assumed to be a full
# equipped BIS set; they are designed-profession slot floors used to calibrate
# the old smooth gear curve and to measure post-30 stat-budget slope.
PALADIN_RET_SLOT_PROGRESSION: dict[str, tuple[str, ...]] = {
    "waist": ("Crusader's Chain Belt", "Justicar's Belt", "Justicar's Waistguard"),
    "hands": ("Crusader's Gloves", "Justicar's Gauntlet", "Justicar's Gloves"),
    "chest": ("Crusader's Chain Shirt", "Crusader's Silvered Shirt", "Blessed Plate Chest"),
    "feet": ("Crusader's Boots", "Justicar's Boots", "Justicar's Sabatons", "Depleted Thorium Sabatons"),
    "legs": ("Crusader's Chain Leggings", "Crusader's Silvered Leggings", "Blessed Plate Leggings"),
    "head": ("Crusader's Silvered Chain Helm", "Crusader's Chain Helm", "Blessed Plate Helm"),
    "shoulder": ("Rough Bronze Shoulders", "Silvered Bronze Shoulders", "Justicar's Pauldrons"),
    "wrist": ("Justicar's Wrist",),
}

PALADIN_TANK_SLOT_PROGRESSION: dict[str, tuple[str, ...]] = {
    "waist": ("Protector's Chain Belt", "Warder's Belt", "Warder's Waistguard"),
    "hands": ("Protector's Gloves", "Warder's Gauntlet", "Warder's Gloves"),
    "chest": ("Protector's Silvered Shirt", "Enriched Thorium Breastplate"),
    "feet": ("Protector's Boots", "Warder's Boots", "Warder's Sabatons"),
    "legs": ("Protector's Chain Leggings", "Protector's Silvered Leggings", "Enriched Thorium Leggings"),
    "head": ("Protector's Silvered Helm", "Protector's Chain Helm", "Enriched Thorium Helm"),
    "shoulder": ("Rough Bronze Shoulders", "Silvered Bronze Shoulders", "Warder's Pauldrons"),
    "wrist": ("Warder's Wrist",),
}

PALADIN_HOLY_SLOT_PROGRESSION: dict[str, tuple[str, ...]] = {
    "waist": ("Prefect's Belt", "Prefect's Waistguard"),
    "hands": ("Prefect's Gauntlet", "Prefect's Gloves"),
    "feet": ("Prefect's Boots", "Prefect's Sabatons"),
    "shoulder": ("Rough Bronze Shoulders", "Silvered Bronze Shoulders", "Prefect's Pauldrons"),
    "wrist": ("Prefect's Wrist",),
}

def _progression_items(level: int, progression: dict[str, tuple[str, ...]]) -> tuple[CraftedItem, ...]:
    out = []
    for names in progression.values():
        row = _latest_from_progression(level, names)
        if row is not None:
            out.append(row)
    return tuple(out)


def druid_feral_items(level: int) -> tuple[CraftedItem, ...]:
    return _progression_items(level, DRUID_FERAL_SLOT_PROGRESSION)


def druid_balance_items(level: int) -> tuple[CraftedItem, ...]:
    return _progression_items(level, DRUID_BALANCE_SLOT_PROGRESSION)


def druid_bear_items(level: int) -> tuple[CraftedItem, ...]:
    return _progression_items(level, DRUID_BEAR_SLOT_PROGRESSION)


def paladin_ret_items(level: int) -> tuple[CraftedItem, ...]:
    return _progression_items(level, PALADIN_RET_SLOT_PROGRESSION)


def paladin_tank_items(level: int) -> tuple[CraftedItem, ...]:
    return _progression_items(level, PALADIN_TANK_SLOT_PROGRESSION)


def paladin_holy_items(level: int) -> tuple[CraftedItem, ...]:
    return _progression_items(level, PALADIN_HOLY_SLOT_PROGRESSION)


def paladin_role_slot_candidates(level: int) -> dict[str, tuple[CraftedItem, ...]]:
    """Real named Paladin candidates available at ``level``, grouped by slot.

    Designed profession families remain useful baseline anchors, but the actual
    per-level reroll also sees audited dungeon, quest, rare and PvP candidates.
    There is deliberately no inventory-continuity constraint: each level answers
    what a representative attainable set at *that level* looks like.
    """
    out: dict[str, list[CraftedItem]] = {}
    for rows in (paladin_ret_items(level), paladin_tank_items(level), paladin_holy_items(level)):
        for row in rows:
            xs = out.setdefault(row.slot, [])
            if all(x.name != row.name for x in xs):
                xs.append(row)
    for row in PALADIN_AUDITED_ITEMS:
        if row.required_level > int(level):
            continue
        xs = out.setdefault(row.slot, [])
        if all(x.name != row.name for x in xs):
            xs.append(row)
    return {slot: tuple(rows) for slot, rows in out.items()}


def aggregate_items(rows: Iterable[CraftedItem]) -> dict:
    rows = tuple(rows)
    return {
        "strength": sum(float(x.strength) for x in rows),
        "agility": sum(float(x.agility) for x in rows),
        "stamina": sum(float(x.stamina) for x in rows),
        "intellect": sum(float(x.intellect) for x in rows),
        "spirit": sum(float(x.spirit) for x in rows),
        "spell_power": sum(float(x.damage_power) for x in rows),
        "healing": sum(float(x.healing) for x in rows),
        "armor": sum(float(x.armor) for x in rows),
        "bonus_armor": sum(float(x.bonus_armor) for x in rows),
        "defense": sum(float(x.defense) for x in rows),
        "attack_power": sum(float(x.attack_power) for x in rows),
        "crafted_items": [x.name for x in rows],
    }

