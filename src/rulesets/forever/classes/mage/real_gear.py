from __future__ import annotations

"""Forever Mage runtime gear backed by the canonical SQLite catalogue.

The active selector consumes legal canonical catalogue rows and never invents
an ``of the Owl`` set or materializes interpolated/extrapolated pseudo-items.
Historical curated rows below are retained only as audit fixtures; they are not
the runtime candidate authority.

Availability policy
-------------------
1. An explicit item required level wins.
2. Quest rewards without an item required level use the midpoint between the
   quest minimum level and its grey/trivial level when both are known.
3. If quest metadata is incomplete, quest minimum level is used.
4. Otherwise item level supplies the fallback ``ilvl - 5`` gate.

The low-level (10-25) pool mixes dungeon/quest rewards and crafted gear because
that is what a real leveling character can reasonably encounter. Profession
items do not require the Mage itself to own that profession; BoE/AH/trade access
is treated as normal availability.
"""

from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from contextlib import contextmanager
from contextvars import ContextVar
from math import ceil
from pathlib import Path
import os

from src.rulesets.forever.items.runtime_selection import available_items as runtime_available_items, effective_level as runtime_effective_level
from src.rulesets.forever.items.gear_requirements import enrich_catalogue_metadata

from src.rulesets.forever.shared.crafted_itemization import (
    CRAFTED_ITEMS,
    MAGE_CASTER_SLOT_PROGRESSION,
    mage_caster_items,
)


@dataclass(frozen=True)
class MageGearItem:
    name: str
    slot: str
    item_level: int
    required_level: int | None = None
    quest_min_level: int | None = None
    quest_gray_level: int | None = None
    source_type: str = "drop"       # quest | dungeon | world | crafted | vendor
    source: str = ""
    intellect: float = 0.0
    spirit: float = 0.0
    stamina: float = 0.0
    spell_power: float = 0.0
    mp5: float = 0.0
    spell_hit: float = 0.0          # percentage points
    spell_crit: float = 0.0         # percentage points
    armor: float = 0.0
    wand_dps: float = 0.0
    weapon_min_damage: float = 0.0
    weapon_max_damage: float = 0.0
    weapon_speed: float = 0.0
    weapon_hands: int = 0           # 0=n/a, 1=one-hand, 2=two-hand
    source_url: str = ""
    item_id: int | None = None
    identity_origin: str = "legacy_audit_fixture"
    required_level_origin: str = "observed"
    model_kind: str = "audit_fixture"

    @property
    def effective_level(self) -> int:
        if self.required_level is not None and self.required_level > 0:
            return int(self.required_level)
        if self.quest_min_level is not None and self.quest_gray_level is not None:
            return int(ceil((float(self.quest_min_level) + float(self.quest_gray_level)) / 2.0))
        if self.quest_min_level is not None:
            return int(self.quest_min_level)
        return max(1, int(self.item_level) - 5)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["effective_level"] = self.effective_level
        return d


# Current Wowhead Forever rows audited 2026-09-22.  These supplement the
# verified Tailoring ladder in shared/crafted_itemization.py.
CURATED_ITEMS: tuple[MageGearItem, ...] = (
    # Wands.  Greater Magic Wand / Cookie / Gravestone retain the currently
    # audited Forever tooltip variants used by the simulator; source URLs are
    # kept so changed beta tooltips can be re-audited without guesswork.
    MageGearItem("Lesser Magic Wand", "wand", 15, required_level=5,
                 source_type="crafted", source="Enchanting",
                 spell_power=1, wand_dps=7.67,
                 source_url="https://www.wowhead.com/forever/item=11287/lesser-magic-wand"),
    MageGearItem("Greater Magic Wand", "wand", 23, required_level=13,
                 source_type="crafted", source="Enchanting",
                 spell_power=2, wand_dps=11.39,
                 source_url="https://www.wowhead.com/forever/spell=14807/greater-magic-wand"),
    MageGearItem("Cookie's Stirring Rod", "wand", 22, required_level=17,
                 source_type="dungeon", source="Cookie / The Deadmines",
                 spell_power=3, wand_dps=14.62,
                 source_url="https://www.wowhead.com/forever/item=5198/cookies-stirring-rod"),
    MageGearItem("Thunderwood", "wand", 27, required_level=22,
                 source_type="world", source="world drop", wand_dps=31.58,
                 source_url="https://www.wowhead.com/forever/item=13062/thunderwood"),
    MageGearItem("Gravestone Scepter", "wand", 29,
                 quest_min_level=18, quest_gray_level=31,
                 source_type="quest", source="Blackfathom Villainy",
                 spirit=3, wand_dps=18.33,
                 source_url="https://www.wowhead.com/forever/item=7001/gravestone-scepter"),
    MageGearItem("Starfaller", "wand", 34, required_level=29,
                 source_type="world", source="world drop", wand_dps=38.93,
                 source_url="https://www.wowhead.com/forever/item=13063/starfaller"),
    MageGearItem("Noxious Shooter", "wand", 51, required_level=46,
                 source_type="dungeon", source="Noxxion / Maraudon",
                 stamina=7, wand_dps=59.06,
                 source_url="https://www.wowhead.com/forever/item=17745/noxious-shooter"),
    MageGearItem("Mana Channeling Wand", "wand", 61, required_level=56,
                 source_type="dungeon", source="Cho'Rush the Observer / Dire Maul",
                 mp5=4, wand_dps=72.19,
                 source_url="https://www.wowhead.com/forever/item=18483/mana-channeling-wand"),
    MageGearItem("Thoughtblighter", "wand", 68, required_level=60,
                 source_type="dungeon", source="Hazza'rah / Zul'Gurub",
                 mp5=5, wand_dps=83.33,
                 source_url="https://www.wowhead.com/forever/item=19967/thoughtblighter"),

    # Weapons / offhand.  Handedness is explicit so the optimizer can never
    # equip an offhand next to a 2H staff.
    MageGearItem("Dwarven Tome", "offhand", 17,
                 source_type="quest", source="quest reward",
                 spirit=2, spell_power=5,
                 source_url="https://www.wowhead.com/forever/item=279898/dwarven-tome"),
    MageGearItem("Searing Dagger", "weapon", 18, required_level=13,
                 source_type="dungeon", source="Bazzalan / Ragefire Chasm",
                 weapon_hands=1,
                 source_url="https://www.wowhead.com/forever/item=273003/searing-dagger"),
    MageGearItem("Staff of Orgrimmar", "weapon", 18,
                 quest_min_level=9, quest_gray_level=22,
                 source_type="quest", source="Hidden Enemies / Ragefire Chasm",
                 intellect=4, spirit=5, mp5=2, weapon_hands=2,
                 source_url="https://www.wowhead.com/forever/item=15444/staff-of-orgrimmar"),
    MageGearItem("Staff of Westfall", "weapon", 24,
                 source_type="quest", source="The Defias Brotherhood",
                 intellect=5, spirit=6, weapon_hands=2,
                 source_url="https://www.wowhead.com/forever/item=2042/staff-of-westfall"),
    MageGearItem("Glimmering Staff", "weapon", 30, required_level=25,
                 source_type="crafted", source="Enchanting",
                 stamina=11, intellect=11, weapon_hands=2,
                 source_url="https://www.wowhead.com/forever/spell=1248703/glimmering-staff"),
    MageGearItem("Wind Spirit Staff", "weapon", 32, required_level=27,
                 source_type="dungeon", source="Earthcaller Halmgar / Razorfen Kraul",
                 stamina=3, intellect=5, spirit=15, weapon_hands=2,
                 source_url="https://www.wowhead.com/forever/item=6689/wind-spirit-staff"),
    # Mid-level real-item bridge. These rows are literal current Forever
    # tooltips; unlike the removed continuous field they never scale with
    # character level after being equipped.
    MageGearItem("Celestial Stave", "weapon", 40, quest_min_level=35,
                 source_type="quest", source="Celestial Power / Tabetha mage quest",
                 intellect=8, spell_power=22, weapon_hands=2,
                 source_url="https://www.wowhead.com/forever/item=9517/celestial-stave"),
    MageGearItem("Illusionary Rod", "weapon", 39, required_level=34,
                 source_type="dungeon", source="Arcanist Doan / Scarlet Monastery",
                 stamina=7, intellect=15, spirit=10, weapon_hands=2,
                 source_url="https://www.wowhead.com/forever/item=7713/illusionary-rod"),
    MageGearItem("Rod of the Ogre Magi", "weapon", 63, required_level=58,
                 source_type="dungeon", source="Gordok Tribute / Dire Maul North",
                 stamina=11, intellect=14, spirit=7, spell_power=23,
                 spell_crit=1.0, weapon_hands=2,
                 source_url="https://www.wowhead.com/forever/item=18534/rod-of-the-ogre-magi"),

    # L10-25 neck/back/chest/wrist/hands/waist/legs/feet/shoulders.
    MageGearItem("Ephemeral Choker", "neck", 18, required_level=13,
                 source_type="dungeon", source="Hall of Thanes",
                 stamina=4, spirit=2,
                 source_url="https://www.wowhead.com/forever/item=270227/ephemeral-choker"),
    MageGearItem("Scholarly Pendant", "neck", 25,
                 source_type="quest", source="quest reward",
                 stamina=6, spirit=4,
                 source_url="https://www.wowhead.com/forever/item=277203/scholarly-pendant"),
    MageGearItem("Glowing Eye of Mordresh", "neck", 41, required_level=36,
                 source_type="dungeon", source="Mordresh Fire Eye / Razorfen Downs",
                 intellect=5, spirit=11,
                 source_url="https://www.wowhead.com/forever/item=10769/glowing-eye-of-mordresh"),
    MageGearItem("Triune Amulet", "neck", 44, required_level=39,
                 source_type="dungeon", source="High Inquisitor Whitemane / Scarlet Monastery",
                 stamina=7, intellect=7, spirit=7,
                 source_url="https://www.wowhead.com/forever/item=7722/triune-amulet"),
    MageGearItem("Gemshard Heart", "neck", 54, required_level=49,
                 source_type="dungeon", source="Princess Theradras / Maraudon",
                 stamina=10, intellect=10, spirit=6,
                 source_url="https://www.wowhead.com/forever/item=17707/gemshard-heart"),
    MageGearItem("Arcane Crystal Pendant", "neck", 52, quest_min_level=50,
                 source_type="quest", source="Destroy Morphaz / Mage class quest",
                 intellect=6, spell_power=16,
                 source_url="https://www.wowhead.com/forever/item=20037/arcane-crystal-pendant"),
    MageGearItem("Heavy Woolen Cloak", "back", 21, required_level=16,
                 source_type="crafted", source="Tailoring",
                 spirit=4, spell_power=4, armor=17,
                 source_url="https://www.wowhead.com/forever/item=4311/heavy-woolen-cloak"),
    MageGearItem("Spritecaster Cape", "back", 52, required_level=47,
                 source_type="dungeon", source="Houndmaster Grebmar / Blackrock Depths",
                 stamina=5, intellect=6, spirit=6, spell_power=14, armor=37,
                 source_url="https://www.wowhead.com/forever/item=11623/spritecaster-cape"),
    MageGearItem("Crystalline Threaded Cape", "back", 63, required_level=58,
                 source_type="quest", source="Sack of Spoils / Silithus",
                 stamina=5, intellect=4, spell_power=20, armor=45,
                 source_url="https://www.wowhead.com/forever/item=20697/crystalline-threaded-cape"),
    MageGearItem("Lookie's Spyglass", "trinket1", 23, required_level=18,
                 source_type="quest", source="quest reward", spirit=1,
                 source_url="https://www.wowhead.com/forever/item=273298/lookies-spyglass"),
    MageGearItem("Robes of the Disgraced Thane", "chest", 18, required_level=13,
                 source_type="dungeon", source="Hall of Thanes",
                 intellect=5, spirit=7, armor=35,
                 source_url="https://www.wowhead.com/forever/item=270261/robes-of-the-disgraced-thane"),
    MageGearItem("Robe of Evocation", "chest", 18, required_level=13,
                 source_type="dungeon", source="Jergosh / Ragefire Chasm",
                 stamina=4, intellect=4, spirit=5, armor=35,
                 source_url="https://www.wowhead.com/forever/item=14150/robe-of-evocation"),
    MageGearItem("Leftover Abomination Skin", "chest", 20, required_level=15,
                 source_type="dungeon", source="The Baron / Ruins of Lordaeron",
                 spirit=7, spell_power=8, armor=37,
                 source_url="https://www.wowhead.com/forever/item=271206/leftover-abomination-skin"),
    MageGearItem("Lesser Wizard's Robe", "chest", 27, required_level=22,
                 source_type="crafted", source="Tailoring",
                 intellect=8, spirit=5, armor=41,
                 source_url="https://www.wowhead.com/forever/spell=6690/lesser-wizards-robe"),
    MageGearItem("Aetherwisp Bracers", "wrist", 18, required_level=13,
                 source_type="dungeon", source="Hall of Thanes",
                 stamina=3, spell_power=3, armor=15,
                 source_url="https://www.wowhead.com/forever/item=271096/aetherwisp-bracers"),
    MageGearItem("Crystalline Cuffs", "wrist", 18, required_level=13,
                 source_type="dungeon", source="Taragaman / Ragefire Chasm",
                 intellect=2, spirit=3, armor=15,
                 source_url="https://www.wowhead.com/forever/item=14148/crystalline-cuffs"),
    MageGearItem("Mindthrust Bracers", "wrist", 22, required_level=17,
                 source_type="world", source="world drop",
                 stamina=1, intellect=5, mp5=3, armor=17,
                 source_url="https://www.wowhead.com/forever/item=1974/mindthrust-bracers"),
    MageGearItem("Heavy Woolen Gloves", "hands", 17, required_level=12,
                 source_type="crafted", source="Tailoring",
                 intellect=2, spirit=2, armor=19,
                 source_url="https://www.wowhead.com/forever/item=4310/heavy-woolen-gloves"),
    MageGearItem("Tuskwrap Belt", "waist", 21, required_level=16,
                 source_type="dungeon", source="Bjork / Ruins of Lordaeron",
                 stamina=5, intellect=5, armor=22,
                 source_url="https://www.wowhead.com/forever/item=271210/tuskwrap-belt"),
    MageGearItem("Double-Stitched Woolen Shoulders", "shoulder", 22, required_level=17,
                 source_type="crafted", source="Tailoring",
                 stamina=4, spell_power=4, armor=27,
                 source_url="https://www.wowhead.com/forever/item=4314/double-stitched-woolen-shoulders"),
    MageGearItem("Rotmender's Leggings", "legs", 22, required_level=17,
                 source_type="dungeon", source="The Abandoned / Ruins of Lordaeron",
                 stamina=5, intellect=8, spirit=5, armor=35,
                 source_url="https://www.wowhead.com/forever/item=271207/rotmenders-leggings"),
    MageGearItem("Rotmender's Treads", "feet", 24, required_level=19,
                 source_type="dungeon", source="Rath'mael / Ruins of Lordaeron",
                 stamina=7, intellect=4, spirit=4, armor=29,
                 source_url="https://www.wowhead.com/forever/item=271214/rotmenders-treads"),

    # Rings / later bridge items already audited in v0.11.21.
    MageGearItem("Lavishly Jeweled Ring", "ring1", 22, required_level=17,
                 source_type="dungeon", source="Gilnid / The Deadmines", intellect=6,
                 source_url="https://www.wowhead.com/forever/item=1156/lavishly-jeweled-ring"),
    MageGearItem("Deep Fathom Ring", "ring2", 24, required_level=19,
                 source_type="dungeon", source="Mutanus / Wailing Caverns", stamina=3, spirit=5,
                 source_url="https://www.wowhead.com/forever/item=6463/deep-fathom-ring"),
    MageGearItem("Cyclopean Band", "ring1", 54, required_level=49,
                 source_type="dungeon", source="Ok'thor the Breaker / Blackrock Depths",
                 stamina=8, intellect=7, spirit=4, spell_power=9,
                 source_url="https://www.wowhead.com/forever/item=11824/cyclopean-band"),
    MageGearItem("Maiden's Circle", "ring2", 61, required_level=55,
                 source_type="world", source="world drop",
                 intellect=7, spirit=6, spell_power=18,
                 source_url="https://www.wowhead.com/forever/item=13001/maidens-circle"),
    MageGearItem("Feline Mantle", "shoulder", 28, required_level=23,
                 source_type="dungeon", source="Wolf Master Nandos / Shadowfang Keep",
                 intellect=10, spirit=3, armor=34,
                 source_url="https://www.wowhead.com/forever/item=3748/feline-mantle"),
    MageGearItem("Belt of Arugal", "waist", 29, required_level=24,
                 source_type="dungeon", source="Archmage Arugal / Shadowfang Keep",
                 intellect=10, spirit=3, armor=26,
                 source_url="https://www.wowhead.com/forever/item=6392/belt-of-arugal"),
    MageGearItem("Robes of Arugal", "chest", 28, required_level=23,
                 source_type="dungeon", source="Archmage Arugal / Shadowfang Keep",
                 spirit=6, stamina=5, spell_power=6, armor=46,
                 source_url="https://www.wowhead.com/forever/item=6324/robes-of-arugal"),
    MageGearItem("Acidic Walkers", "feet", 32, required_level=27,
                 source_type="dungeon", source="Viscous Fallout / Gnomeregan",
                 intellect=8, spirit=4, spell_power=5, armor=34,
                 source_url="https://www.wowhead.com/forever/item=9454/acidic-walkers"),
    MageGearItem("Embalmed Shroud", "head", 35, required_level=30,
                 source_type="dungeon", source="Fallen Champion / Scarlet Monastery Graveyard",
                 stamina=7, intellect=11, spirit=12, armor=42,
                 source_url="https://www.wowhead.com/forever/item=7691/embalmed-shroud"),
    MageGearItem("Mantle of Doan", "shoulder", 38, required_level=33,
                 source_type="dungeon", source="Arcanist Doan / Scarlet Monastery",
                 intellect=8, spirit=7, armor=38,
                 source_url="https://www.wowhead.com/forever/item=7712/mantle-of-doan"),
    MageGearItem("Dreamweave Vest", "chest", 45, required_level=40,
                 source_type="crafted", source="Tailoring",
                 intellect=9, spirit=14, spell_power=18, armor=65,
                 source_url="https://www.wowhead.com/forever/item=10021/dreamweave-vest"),
    MageGearItem("Dreamweave Gloves", "hands", 45, required_level=40,
                 source_type="crafted", source="Tailoring",
                 intellect=4, spirit=7, spell_power=18, armor=41,
                 source_url="https://www.wowhead.com/forever/item=10019/dreamweave-gloves"),
    MageGearItem("Dreamweave Circlet", "head", 50, required_level=45,
                 source_type="crafted", source="Tailoring",
                 intellect=10, spirit=12, spell_power=21, armor=58,
                 source_url="https://www.wowhead.com/forever/item=10041/dreamweave-circlet"),
    MageGearItem("Star Belt", "waist", 40, required_level=35,
                 source_type="crafted", source="Tailoring", spirit=4, spell_power=13, armor=30,
                 source_url="https://www.wowhead.com/forever/item=4329/star-belt"),
    MageGearItem("Red Mageweave Pants", "legs", 43, required_level=38,
                 source_type="crafted", source="Tailoring", intellect=12, spell_power=14, armor=49,
                 source_url="https://www.wowhead.com/forever/item=10009/red-mageweave-pants"),
    MageGearItem("Black Mageweave Gloves", "hands", 43, required_level=38,
                 source_type="crafted", source="Tailoring", spell_power=15, armor=35,
                 source_url="https://www.wowhead.com/forever/item=10003/black-mageweave-gloves"),
)


def _crafted_rows(level: int) -> tuple[MageGearItem, ...]:
    rows=[]
    for x in mage_caster_items(int(level)):
        rows.append(MageGearItem(
            x.name, x.slot, x.item_level, required_level=x.required_level,
            source_type="crafted", source=f"{x.profession}: {x.family}",
            intellect=x.intellect, spirit=x.spirit, stamina=x.stamina,
            spell_power=x.damage_power, armor=x.armor, source_url=x.source_url,
        ))
    return tuple(rows)


MAGE_CLASS_ID = 8
_REPO_ROOT = Path(__file__).resolve().parents[5]
_DEFAULT_CATALOGUE = _REPO_ROOT / "data" / "forever" / "catalogue" / "items_2026-09-29.sqlite"
_ARMOR_SLOTS = {"head", "shoulder", "chest", "wrist", "hands", "waist", "legs", "feet"}


def _catalogue_path() -> Path:
    return Path(os.environ.get("FOREVER_ITEM_CATALOGUE", _DEFAULT_CATALOGUE))


def _mage_catalogue_item(row, effective_level: int) -> MageGearItem | None:
    # Class eligibility comes from the Wowhead class-filtered capture.  The
    # extra armor/weapon guards keep impossible equipment out even if upstream
    # metadata becomes noisy.
    if row.slot in _ARMOR_SLOTS and row.armor_type not in ("", "misc", "cloth"):
        return None
    if row.armor_type == "shield":
        return None

    slot = row.slot
    wand_dps = 0.0
    if slot == "ranged" and row.weapon_type == "wand":
        slot = "wand"
        wand_dps = float(row.weapon_dps)
    elif slot in ("one_hand", "main_hand", "two_hand"):
        slot = "weapon"
    elif slot == "off_hand":
        slot = "offhand"
    elif slot == "finger":
        slot = "ring"
    elif slot == "trinket":
        slot = "trinket"
    elif slot in ("relic", "shirt", "tabard", "ranged"):
        return None

    return MageGearItem(
        name=row.name, slot=slot, item_level=int(row.item_level or 0),
        required_level=int(effective_level), source_type=row.source_type or "wowhead",
        source=row.source_name or "Wowhead Forever catalogue",
        intellect=float(row.intellect), spirit=float(row.spirit), stamina=float(row.stamina),
        spell_power=float(row.spell_power), mp5=float(row.mp5),
        spell_hit=float(row.hit), spell_crit=float(row.crit), armor=float(row.armor + row.bonus_armor),
        wand_dps=wand_dps, weapon_min_damage=float(row.weapon_min_damage),
        weapon_max_damage=float(row.weapon_max_damage), weapon_speed=float(row.weapon_speed),
        weapon_hands=int(row.weapon_hands or (2 if row.slot == "two_hand" else 1 if row.slot in ("one_hand", "main_hand") else 0)),
        source_url=row.source_url or f"https://www.wowhead.com/forever/item={row.item_id}", item_id=int(row.item_id),
        identity_origin=str(row.identity_origin or "wowhead_listview"),
        required_level_origin=str(row.required_level_origin or "observed"),
        model_kind="canonical_sqlite_item",
    )


@lru_cache(maxsize=128)
def available_items(level: int) -> tuple[MageGearItem, ...]:
    """All legal Mage candidates from the shared runtime eligibility pool.

    I26 removes the second Mage-specific SQLite/proficiency authority: class/armor/
    weapon legality now comes from ``runtime_selection.available_items`` exactly
    like the other migrated classes. Mage still owns how legal rows are scored.
    """
    out=[]
    for row in runtime_available_items("mage", int(level)):
        effective = runtime_effective_level(row)
        if effective is None or effective > int(level):
            continue
        item = _mage_catalogue_item(row, effective)
        if item is not None:
            out.append(item)
    return tuple(out)


@lru_cache(maxsize=1)
def all_sample_items() -> tuple[MageGearItem, ...]:
    """All audited Mage-relevant samples through the modeled L60 horizon."""
    # mage_caster_items(level) intentionally returns only the latest row per
    # slot.  The continuous field needs *every* audited rung, so pull the named
    # Mage caster progression directly from the shared crafted catalogue.
    mage_names = {name for names in MAGE_CASTER_SLOT_PROGRESSION.values() for name in names}
    crafted = [x for x in CRAFTED_ITEMS if x.name in mage_names]
    rows = list(CURATED_ITEMS) + [MageGearItem(
        x.name, x.slot, x.item_level, required_level=x.required_level,
        source_type="crafted", source=f"{x.profession}: {x.family}",
        intellect=x.intellect, spirit=x.spirit, stamina=x.stamina,
        spell_power=x.damage_power, armor=x.armor, source_url=x.source_url,
    ) for x in crafted]
    # CURATED_ITEMS intentionally overlaps a few crafted audit rows.  Collapse
    # exact-name/slot duplicates so frontier fitting is deterministic.
    out: dict[tuple[str, str], MageGearItem] = {}
    for x in rows:
        out[(x.slot, x.name)] = x
    return tuple(out.values())


_GEAR_OVERRIDE: ContextVar[tuple[MageGearItem, ...] | None] = ContextVar("mage_gear_override", default=None)


def _normalized_selector_weights(weights: dict[str, float] | None) -> dict[str, float]:
    """Map measured Mage stat values onto the legacy selector's stable scale.

    Mage currently probes Intellect, Spirit, and Spell Power.  Preserve the
    existing relative values for unprobed utility stats, while replacing the
    three measured dimensions with build-specific ratios normalized to Int=1.
    """
    base={"intellect":1.00,"spell_power":1.18,"spirit":0.34,"mp5":0.55,
          "spell_hit":8.0,"spell_crit":6.0,"stamina":0.05}
    vals={str(k):max(0.0,float(v or 0.0)) for k,v in dict(weights or {}).items()}
    ref=vals.get("intellect",0.0)
    if ref <= 1e-12:
        ref=max(vals.get("spell_power",0.0), vals.get("spirit",0.0), 0.0)
    if ref > 1e-12:
        for k in ("intellect","spell_power","spirit"):
            if k in vals:
                base[k]=vals[k]/ref
    return base


def _score(x: MageGearItem, level: int, weights: dict[str, float] | None = None) -> float:
    """Practical leveling selector, optionally reranked by measured stat values."""
    l=max(1,int(level))
    wand_weight=max(0.12, 1.25-(l-10)*0.035)
    w=_normalized_selector_weights(weights)
    return (
        w["intellect"]*x.intellect + w["spell_power"]*x.spell_power + w["spirit"]*x.spirit
        + w["mp5"]*x.mp5 + w["spell_hit"]*x.spell_hit + w["spell_crit"]*x.spell_crit
        + wand_weight*x.wand_dps + w["stamina"]*x.stamina
    )


def _best(rows: list[MageGearItem], level: int, weights: dict[str, float] | None = None) -> MageGearItem | None:
    if not rows:
        return None
    return max(rows, key=lambda x: (_score(x,level,weights), x.effective_level, x.item_level, x.name))


def _legal_hands(rows: tuple[MageGearItem, ...], level: int, weights: dict[str, float] | None = None) -> tuple[MageGearItem, ...]:
    """Pick the better legal 2H or 1H+offhand package."""
    weapons=[x for x in rows if x.slot == "weapon"]
    offhands=[x for x in rows if x.slot == "offhand"]
    one=_best([x for x in weapons if x.weapon_hands != 2], level, weights)
    two=_best([x for x in weapons if x.weapon_hands == 2], level, weights)
    off=_best(offhands, level, weights)

    packages: list[tuple[float, tuple[MageGearItem, ...]]] = []
    if one is not None:
        p=(one,) + ((off,) if off is not None else ())
        packages.append((sum(_score(x,level,weights) for x in p), p))
    if two is not None:
        packages.append((_score(two,level,weights), (two,)))
    # Do not equip an offhand by itself; a legal main-hand is required.
    if not packages:
        return ()
    return max(packages, key=lambda p: (p[0], sum(x.item_level for x in p[1])))[1]


def equipped_items(level: int, weights: dict[str, float] | None = None) -> tuple[MageGearItem, ...]:
    """Return the best legal SQL-backed set for the current Mage model.

    The selector is unchanged in spirit from the previous named-item scorer,
    but its candidate universe and every consumed stat now come from SQLite.
    """
    rows=available_items(level)
    best: dict[str, MageGearItem] = {}
    multi: dict[str, list[MageGearItem]] = {"ring": [], "trinket": []}
    for x in rows:
        if x.slot in ("weapon", "offhand"):
            continue
        if x.slot in multi:
            multi[x.slot].append(x)
            continue
        old=best.get(x.slot)
        key=((x.wand_dps, _score(x,level), x.effective_level, x.item_level, x.name)
             if x.slot == "wand" else
             (_score(x,level,weights), x.effective_level, x.item_level, x.name))
        oldkey=((-1.0,) if old is None else
                ((old.wand_dps, _score(old,level), old.effective_level, old.item_level, old.name)
                 if old.slot == "wand" else
                 (_score(old,level,weights), old.effective_level, old.item_level, old.name)))
        if old is None or key > oldkey:
            best[x.slot]=x
    for base_slot in ("ring", "trinket"):
        ranked=sorted(multi[base_slot], key=lambda x: (_score(x,level,weights), x.effective_level, x.item_level, x.name), reverse=True)
        for idx,x in enumerate(ranked[:2], start=1):
            best[f"{base_slot}{idx}"]=replace(x, slot=f"{base_slot}{idx}")
    for x in _legal_hands(rows, level, weights):
        best[x.slot]=x
    order=("head","neck","shoulder","back","chest","wrist","hands","waist","legs","feet","ring1","ring2","trinket1","trinket2","weapon","offhand","wand")
    return tuple(best[s] for s in order if s in best)


def observed_snapshot(level: int, weights: dict[str, float] | None = None) -> dict:
    """Literal best set from the currently audited named item samples."""
    rows=equipped_items(level, weights)
    slots={x.slot:x.as_dict() for x in rows}
    all_slots=("head","neck","shoulder","back","chest","wrist","hands","waist","legs","feet","ring1","ring2","trinket1","trinket2","weapon","offhand","wand")
    weapon=slots.get("weapon")
    hand_setup=("2h" if weapon and int(weapon.get("weapon_hands",0))==2 else
                "1h_offhand" if weapon and "offhand" in slots else
                "1h" if weapon else "none")
    blocked_slots=("offhand",) if hand_setup == "2h" else ()
    out = {
        "level": int(level),
        "slots": slots,
        "items": [x.as_dict() for x in rows],
        "missing_slots": [s for s in all_slots if s not in slots and s not in blocked_slots],
        "blocked_slots": list(blocked_slots),
        "hand_setup": hand_setup,
        "totals": {
            "intellect": sum(x.intellect for x in rows),
            "spirit": sum(x.spirit for x in rows),
            "stamina": sum(x.stamina for x in rows),
            "spell_power": sum(x.spell_power for x in rows),
            "mp5": sum(x.mp5 for x in rows),
            "spell_hit": sum(x.spell_hit for x in rows),
            "spell_crit": sum(x.spell_crit for x in rows),
            "armor": sum(x.armor for x in rows),
        },
        "availability_rule": "shared runtime eligibility + canonical SQLite fixed-point selection",
        "provenance": "canonical_sqlite_forever_catalogue",
    }
    enrich_catalogue_metadata(out, class_key="mage", role="mage", level=int(level), selected={x.slot:x for x in rows})
    out["missing_slots"] = [s for s,m in out["catalogue_coverage"].items() if m.get("status") in {"catalogue_gap","query_gap"}]
    out["blocked_slots"] = [s for s,m in out["catalogue_coverage"].items() if m.get("status") in {"setup_blocked","proficiency_blocked"}]
    return out



@lru_cache(maxsize=None)
def _default_snapshot(level: int) -> dict:
    """Discrete named-item snapshot used by combat and listener.

    v0.11.29 deliberately stops materializing interpolated/extrapolated
    pseudo-items.  A slot contains an audited, named item or it is absent.
    Existing named gear is carried forward until a real sampled replacement
    wins the per-slot selector.
    """
    out = observed_snapshot(int(level))
    out = dict(out)
    out["availability_rule"] = (
        "canonical SQLite candidates only: best available item per legal slot under the current Mage gear scorer; "
        "no curated/synthetic runtime fallback"
    )
    out["provenance"] = "canonical_sqlite_forever_catalogue"
    out["sample_growth_exponent"] = None
    out["observed_snapshot"] = {
        "selected_items": [x.get("name") for x in out.get("items", [])],
        "hand_setup": out.get("hand_setup", "none"),
    }
    return out


def snapshot_for_weights(level: int, weights: dict[str, float] | None) -> dict:
    return observed_snapshot(int(level), dict(weights or {}))


def _selection_from_snapshot(snap: dict) -> tuple[MageGearItem, ...]:
    ids={int(row.get("item_id")) for row in (snap.get("slots") or {}).values()
         if isinstance(row,dict) and row.get("item_id") is not None}
    return tuple(x for x in available_items(int(snap.get("level",0))) if x.item_id in ids)


@contextmanager
def gear_override(items: tuple[MageGearItem, ...]):
    token=_GEAR_OVERRIDE.set(tuple(items))
    try:
        yield
    finally:
        _GEAR_OVERRIDE.reset(token)


def snapshot(level: int) -> dict:
    override=_GEAR_OVERRIDE.get()
    if override is None:
        return _default_snapshot(int(level))
    rows=tuple(override)
    slots={x.slot:x.as_dict() for x in rows}
    all_slots=("head","neck","shoulder","back","chest","wrist","hands","waist","legs","feet","ring1","ring2","trinket1","trinket2","weapon","offhand","wand")
    weapon=slots.get("weapon")
    hand_setup=("2h" if weapon and int(weapon.get("weapon_hands",0))==2 else
                "1h_offhand" if weapon and "offhand" in slots else "1h" if weapon else "none")
    blocked_slots=("offhand",) if hand_setup=="2h" else ()
    out={"level":int(level),"slots":slots,"items":[x.as_dict() for x in rows],
            "missing_slots":[x for x in all_slots if x not in slots and x not in blocked_slots],
            "blocked_slots":list(blocked_slots),"hand_setup":hand_setup,
            "totals":{"intellect":sum(x.intellect for x in rows),"spirit":sum(x.spirit for x in rows),
                      "stamina":sum(x.stamina for x in rows),"spell_power":sum(x.spell_power for x in rows),
                      "mp5":sum(x.mp5 for x in rows),"spell_hit":sum(x.spell_hit for x in rows),
                      "spell_crit":sum(x.spell_crit for x in rows),"armor":sum(x.armor for x in rows)},
            "availability_rule":"shared runtime eligibility + canonical SQLite fixed-point selection",
            "provenance":"canonical_sqlite_forever_catalogue","sample_growth_exponent":None,
            "observed_snapshot":{"selected_items":[x.name for x in rows],"hand_setup":hand_setup}}
    enrich_catalogue_metadata(out, class_key="mage", role="mage", level=int(level), selected={x.slot:x for x in rows})
    out["missing_slots"] = [s for s,m in out["catalogue_coverage"].items() if m.get("status") in {"catalogue_gap","query_gap"}]
    out["blocked_slots"] = [s for s,m in out["catalogue_coverage"].items() if m.get("status") in {"setup_blocked","proficiency_blocked"}]
    return out
