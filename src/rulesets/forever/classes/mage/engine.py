#!/usr/bin/env python3
"""
WoW Forever Mage experimental solo-leveling simulator / optimizer.

Goal
----
Minimize wall-clock time for a sequence of ordinary melee mobs, including
combat time and mana recovery, while cooldowns persist between pulls.

The code is deliberately split into four layers:
1) data: spell ranks, player base stats, water, gear profile
2) combat kernel: movement, roots/slows, melee pushback, DoTs/channels, 5SR
3) policies: human-readable decision rules using the available actions
4) optimizers: policy parameter search and talent-path beam search

Current implemented actions
---------------------------
- Frostbolt (highest known rank, plus optional Rank 1 utility/downrank; projectile travel)
- Fireball (highest known rank; projectile travel)
- Pyroblast (highest known rank; optional pull opener when talented)
- Scorch (highest known rank)
- Arcane Missiles (highest known rank)
- Fire Blast (highest known rank)
- Frost Nova (optimizer considers Rank 1 or highest learned rank)
- Blink
- Move away for a chosen short distance

Current implemented talent effects
----------------------------------
Frost: Improved Frostbolt, Elemental Precision, Ice Shards, Frostbite,
       Improved Frost Nova, Permafrost, Piercing Ice, Arctic Reach,
       Frost Channeling, Shatter, Winter's Chill
Arcane: Arcane Focus, Improved Arcane Missiles, Arcane Concentration,
        Arcane Subtlety, Arcane Meditation, Arcane Mind, Arcane Instability
Fire: Improved Fireball, Improved Fire Blast, Ignite, Flame Throwing,
      Burning Soul, Incinerate, Improved Scorch, Master of Elements,
      Critical Mass, Fire Power, Pyroblast, Combustion

Important: this is a leveling model, not a server emulator. Several mechanics
are configurable approximations (notably melee leeway, Frostbite/root break,
named Forever gear plus explicit missing-slot calibration).
The program prints assumptions so results remain auditable.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Callable, Dict, Iterable, List, Optional, Tuple
import argparse
import math
import os
import random
import statistics

from src.rulesets.forever.shared import DataProvenance, VERIFIED_LEVEL_CAP
from src.rulesets.forever.data.rules import default_rules
from src.rulesets.forever.shared.crafted_itemization import mage_caster_items, CRAFTED_ITEMS
from src.rulesets.forever.shared.item_budget import peer_exchange_budget_units
from src.rulesets.forever.shared.mobs import normal_world_raw_dps
from src.rulesets.forever.shared.recovery import solve_recovery, RECOVERY_SOLVER_ID
from src.rulesets.forever.shared.defense import armor_reduction, representative_player_hp
from src.shared.leveling.objective import physical_hit_chance
from . import wowhead_facts as wh
from .server_profile import MageServerProfile, CURRENT_TARGET_SERVER_PROFILE
from .real_gear import snapshot as real_gear_snapshot

EPS = 1e-9
TIME_EPS = 1e-7
HP_EPS = 1e-8  # combat damage arithmetic below this is treated as zero HP
GCD = 1.5
PUSHBACK_SEQ = (1.0, 0.8, 0.6, 0.4, 0.2)

# Game-engine metadata consumed by the registry / CLI.  Forever is beta data:
# values verified through the current level-30 beta are preferred; unchanged or
# not-yet-public post-cap ranks intentionally fall back to Classic data.
RULESET = "forever"
CLASS_NAME = "mage"
ENGINE_KIND = "mage"
FAST_SUPPORTED = True
MC_SUPPORTED = True
DATA_BUILD = "Forever beta client 1.60.1.69893 + current Wowhead Forever audit (2026-09-22)"
DATA_ATTRIBUTION = "Talent data from beta snapshot; public spell facts cross-checked against Wowhead Forever"
DATA_QUALITY = {
    'talents': 'beta-client verified through original cap',
    'modeled_spell_ranks': 'client fixture with current Wowhead Forever corrections for audited new abilities',
    'forever_actives': 'public facts verified; several new active/proc rotations still unmodeled',
    'unmodeled_or_base_data': 'explicit Classic fallback/approximation where Forever data is not represented',
}
DATA_PROVENANCE = DataProvenance(
    build=DATA_BUILD,
    attribution=DATA_ATTRIBUTION,
    quality=DATA_QUALITY,
    mixed_build=False,
)
EXPERIMENTAL = True

PLANNING_LEVEL_CAP = 40

MAGE_CAPABILITY_MATRIX = {
    "frost": {
        "talent_legality_l10_l40": "source_backed",
        "single_target_rotation": "event_plus_expected_state",
        "frostbolt_control": "stateful",
        "fingers_of_frost_ice_lance": "event_validated_bounded",
        "blizzard_aoe_leveling": "opt_in_fail_closed",
    },
    "arcane": {
        "talent_legality_l10_l40": "source_backed",
        "single_target_rotation": "event_plus_expected_state",
        "arcane_blast_stacks": "stateful",
        "missile_barrage": "expected_state_plus_event_timing",
        "presence_of_mind_arcane_power": "unpriced_fail_closed",
    },
    "fire": {
        "talent_legality_l10_l40": "source_backed",
        "single_target_rotation": "event_plus_expected_state",
        "hot_streak": "expected_state_plus_event_timing",
        "reactive_pyro_fire_blast": "stateful_bounded",
        "aoe_leveling": "unmodeled_fail_closed",
    },
    "shared": {
        "gear": "canonical_sqlite_runtime_selection",
        "stat_weights": "canonical_scorer_sensitivity",
        "candidate_interface": "shared_school_filtered_search",
        "verified_level_cap": "L30",
        "planning_level_cap": "L40",
    },
}
MODEL_FIDELITY = {
    "backend": "shared_expected_state_plus_discrete_event_chain",
    "verified_level_cap": VERIFIED_LEVEL_CAP,
    "planning_level_cap": PLANNING_LEVEL_CAP,
    "capability_matrix": MAGE_CAPABILITY_MATRIX,
    "pull_model": "single_target_chain",
    "resource_continuity": "mana_cooldown_chain",
    "survival": "mature_melee_contact_control_model",
    "gear": "canonical_sqlite_runtime_selection",
    "mc_validated": True,
    "rating": "verified_l10_l30_medium_planning_l31_l40_bounded",
    "target_server_profile": CURRENT_TARGET_SERVER_PROFILE.key,
    "strategy_capabilities": CURRENT_TARGET_SERVER_PROFILE.capabilities(),
    "forever_missing_mechanics": (
        "presence_of_mind_normalized_effect_authority",
        "arcane_power_normalized_effect_authority",
        "blizzard_aoe_geometry_and_channel_policy",
        "fire_aoe_leveling_policy",
        "l41_l60_full_fidelity_audit",
    ),
}

PRIMARY_SCHOOL_ENV = "MAGE_PRIMARY_SCHOOL"
PRIMARY_SCHOOLS = ("all", "frost", "fire", "arcane")

def normalize_primary_school(value) -> str:
    """Normalize the primary rotation-school filter used by Fast and MC search.

    The filter constrains the *primary leveling rotation*, not talent-tree spend.
    Cross-tree support talents therefore remain legal (for example Arcane
    Subtlety on a Frost path).
    """
    v = str(value or "all").strip().lower()
    if v in ("any", "both", "none", "*"):
        v = "all"
    if v not in PRIMARY_SCHOOLS:
        raise ValueError(f"unknown primary school {value!r}; expected one of {PRIMARY_SCHOOLS}")
    return v

def configured_primary_school() -> str:
    return normalize_primary_school(os.environ.get(PRIMARY_SCHOOL_ENV, "all"))

def policy_primary_school(policy) -> str:
    """Mechanical primary-school identity for a leveling policy.

    Utility casts (Fire Blast, Frost Nova, etc.) do not change the identity.
    Fireball/Scorch cadence policies are Fire; Frostbolt is Frost; Arcane
    Missiles is Arcane.
    """
    primary = str(getattr(policy, "primary", "") or "").lower()
    if primary == "frostbolt":
        return "frost"
    if primary in ("fireball", "scorch") or (getattr(policy, "fireball_block", 0) and getattr(policy, "scorch_block", 0)):
        return "fire"
    if primary in ("arcane_missiles", "arcane_blast"):
        return "arcane"
    return "other"

def policy_allowed_by_primary_school(policy, school=None) -> bool:
    wanted = configured_primary_school() if school is None else normalize_primary_school(school)
    return wanted == "all" or policy_primary_school(policy) == wanted

def filter_policies_by_primary_school(policies, school=None):
    wanted = configured_primary_school() if school is None else normalize_primary_school(school)
    vals = list(policies)
    if wanted == "all":
        return vals
    return [p for p in vals if policy_primary_school(p) == wanted]

# ----------------------------- data ---------------------------------------

@dataclass(frozen=True)
class Rank:
    spell: str
    rank: int
    learn: int
    school: str
    mana: float
    cast: float = 0.0
    range: float = 0.0
    dmin: float = 0.0
    dmax: float = 0.0
    dot_total: float = 0.0
    dot_duration: float = 0.0
    dot_interval: float = 2.0
    channel_ticks: int = 0
    channel_tick_damage: float = 0.0
    slow: float = 0.0
    slow_duration: float = 0.0
    root_duration: float = 0.0
    radius: float = 0.0
    cooldown: float = 0.0
    missile_speed: float = 0.0


@dataclass(frozen=True)
class Wand:
    name: str
    req_level: int
    school: str
    dmin: float
    dmax: float
    speed: float
    item_id: int | None = None
    source_url: str = ""
    school_origin: str = "legacy_audit_fixture"

    @property
    def dps(self) -> float:
        return ((self.dmin + self.dmax) * 0.5) / max(self.speed, EPS)


# Forever wand progression.  Low-level entries are aligned to the same current
# named-item pool shown by the listener.  Quest rewards use the effective-level
# availability policy from real_gear.py rather than pretending they are granted
# at quest minimum level.  Damage ranges include any elemental line on the item
# so ``dps`` matches the audited tooltip total.
WANDS = [
    Wand('Lesser Magic Wand', 5, 'arcane', 8, 15, 1.50),
    Wand('Greater Magic Wand', 13, 'arcane', 14, 27, 1.80),
    Wand("Cookie's Stirring Rod", 17, 'arcane', 13, 25, 1.30),
    Wand('Thunderwood', 22, 'nature', 40, 80, 1.90),
    Wand('Gravestone Scepter', 25, 'shadow', 19, 36, 1.50),
    Wand('Starfaller', 29, 'arcane', 36, 73, 1.40),
    # Later bridge entries remain explicit audited/legacy rows until the full
    # L30-60 item sweep replaces them with the same rich provenance as L10-25.
    Wand('Noxious Shooter', 46, 'nature', 63, 126, 1.60),
    Wand('Mana Channeling Wand', 56, 'frost', 77, 154, 1.60),
    Wand('Thoughtblighter', 60, 'shadow', 100, 200, 1.80),
]

def best_wand(level:int) -> Wand:
    """Return the same SQL-backed wand selected for the published gear snapshot.

    The historical WANDS table remains as documentation/test fixture only; the
    runtime authority is the canonical item catalogue used by real_gear_snapshot.
    """
    snap = real_gear_snapshot(int(level))
    row = (snap.get("slots") or {}).get("wand")
    if row:
        speed = float(row.get("weapon_speed") or 0.0)
        dmin = float(row.get("weapon_min_damage") or 0.0)
        dmax = float(row.get("weapon_max_damage") or 0.0)
        dps = float(row.get("wand_dps") or 0.0)
        if speed <= EPS:
            speed = 1.5
        if dmin <= 0.0 and dmax <= 0.0 and dps > 0.0:
            dmin = dmax = dps * speed
        item_id = int(row.get("item_id")) if row.get("item_id") is not None else None
        school = wh.WAND_SCHOOL_BY_ITEM_ID.get(item_id) if item_id is not None else None
        school_origin = "wowhead_current_item_fact" if school else ""
        if not school:
            legacy = next((w for w in WANDS if w.name == str(row.get("name") or "")), None)
            if legacy is not None:
                school = legacy.school
                school_origin = "legacy_audit_fixture_by_name"
        if not school:
            school = "unknown"
            school_origin = "unknown_not_in_catalogue_schema"
        return Wand(str(row.get("name") or "Catalogue wand"), int(row.get("effective_level") or 1),
                    str(school), dmin, dmax, speed, item_id=item_id,
                    source_url=str(row.get("source_url") or ""), school_origin=school_origin)
    # A missing wand is legal below catalogue coverage; keep a zero-DPS sentinel
    # rather than silently reintroducing a curated combat item.
    return Wand('No wand equipped', 1, 'unknown', 0.0, 0.0, 1.5, school_origin='no_wand')


FROSTBOLT = [
    Rank('frostbolt',1,4,'frost',25,1.5,30,20,22,slow=.40,slow_duration=5,missile_speed=28),
    Rank('frostbolt',2,8,'frost',35,1.8,30,34,38,slow=.40,slow_duration=6,missile_speed=28),
    Rank('frostbolt',3,14,'frost',50,2.2,30,47,52,slow=.40,slow_duration=6,missile_speed=28),
    Rank('frostbolt',4,20,'frost',65,2.6,30,61,68,slow=.40,slow_duration=7,missile_speed=28),
    Rank('frostbolt',5,26,'frost',100,3.0,30,96,106,slow=.40,slow_duration=7,missile_speed=28),
    Rank('frostbolt',6,32,'frost',130,3.0,30,135,147,slow=.40,slow_duration=8,missile_speed=28),
    Rank('frostbolt',7,38,'frost',160,3.0,30,181,197,slow=.40,slow_duration=8,missile_speed=28),
    Rank('frostbolt',8,44,'frost',195,3.0,30,243,263,slow=.40,slow_duration=9,missile_speed=28),
    Rank('frostbolt',9,50,'frost',225,3.0,30,305,331,slow=.40,slow_duration=9,missile_speed=28),
    Rank('frostbolt',10,56,'frost',260,3.0,30,382,413,slow=.40,slow_duration=9,missile_speed=28),
    Rank('frostbolt',11,60,'frost',290,3.0,30,457,493,slow=.40,slow_duration=9,missile_speed=28),
]
FIREBALL = [
    Rank('fireball',1,1,'fire',30,1.5,35,16,25,dot_total=2,dot_duration=4,missile_speed=24),
    Rank('fireball',2,6,'fire',45,2.0,35,32,47,dot_total=3,dot_duration=6,missile_speed=24),
    Rank('fireball',3,12,'fire',65,2.5,35,48,66,dot_total=6,dot_duration=6,missile_speed=24),
    Rank('fireball',4,18,'fire',95,3.0,35,66,91,dot_total=12,dot_duration=8,missile_speed=24),
    Rank('fireball',5,24,'fire',140,3.5,35,97,131,dot_total=16,dot_duration=8,missile_speed=24),
    Rank('fireball',6,30,'fire',185,3.5,35,137,183,dot_total=24,dot_duration=8,missile_speed=24),
    Rank('fireball',7,36,'fire',220,3.5,35,170,223,dot_total=24,dot_duration=8,missile_speed=24),
    Rank('fireball',8,42,'fire',260,3.5,35,212,276,dot_total=32,dot_duration=8,missile_speed=24),
    Rank('fireball',9,48,'fire',305,3.5,35,270,349,dot_total=40,dot_duration=8,missile_speed=24),
    Rank('fireball',10,54,'fire',350,3.5,35,337,432,dot_total=48,dot_duration=8,missile_speed=24),
    Rank('fireball',11,60,'fire',395,3.5,35,397,505,dot_total=56,dot_duration=8,missile_speed=24),
    Rank('fireball',12,60,'fire',410,3.5,35,425,541,dot_total=60,dot_duration=8,missile_speed=24),
]
# Talent-gated Pyroblast ranks. Rank 1 is learned by taking the talent; later
# ranks are trained at the listed levels. The simulator uses it primarily as a
# pull opener, where its long 6 s cast is actually practical while soloing.
PYROBLAST = [
    Rank('pyroblast',1,20,'fire',125,6.0,35,100,132,dot_total=44,dot_duration=12,dot_interval=3,missile_speed=24),
    Rank('pyroblast',2,24,'fire',150,6.0,35,125,164,dot_total=56,dot_duration=12,dot_interval=3,missile_speed=24),
    Rank('pyroblast',3,30,'fire',195,6.0,35,178,229,dot_total=76,dot_duration=12,dot_interval=3,missile_speed=24),
    Rank('pyroblast',4,36,'fire',240,6.0,35,228,291,dot_total=100,dot_duration=12,dot_interval=3,missile_speed=24),
    Rank('pyroblast',5,42,'fire',285,6.0,35,289,366,dot_total=124,dot_duration=12,dot_interval=3,missile_speed=24),
    Rank('pyroblast',6,48,'fire',335,6.0,35,365,459,dot_total=152,dot_duration=12,dot_interval=3,missile_speed=24),
    Rank('pyroblast',7,54,'fire',385,6.0,35,446,557,dot_total=184,dot_duration=12,dot_interval=3,missile_speed=24),
    Rank('pyroblast',8,60,'fire',440,6.0,35,520,646,dot_total=212,dot_duration=12,dot_interval=3,missile_speed=24),
]
SCORCH = [
    Rank('scorch',1,22,'fire',50,1.5,30,38,46),
    Rank('scorch',2,28,'fire',65,1.5,30,53,65),
    Rank('scorch',3,34,'fire',80,1.5,30,66,80),
    Rank('scorch',4,40,'fire',100,1.5,30,89,107),
    Rank('scorch',5,46,'fire',115,1.5,30,111,132),
    Rank('scorch',6,52,'fire',135,1.5,30,142,170),
    Rank('scorch',7,58,'fire',150,1.5,30,166,196),
]
ARCANE_MISSILES = [
    Rank('arcane_missiles',1,8,'arcane',85,range=30,channel_ticks=3,channel_tick_damage=25),
    Rank('arcane_missiles',2,16,'arcane',140,range=30,channel_ticks=4,channel_tick_damage=33),
    Rank('arcane_missiles',3,24,'arcane',235,range=30,channel_ticks=5,channel_tick_damage=46),
    Rank('arcane_missiles',4,32,'arcane',320,range=30,channel_ticks=5,channel_tick_damage=68),
    Rank('arcane_missiles',5,40,'arcane',410,range=30,channel_ticks=5,channel_tick_damage=98),
    Rank('arcane_missiles',6,48,'arcane',500,range=30,channel_ticks=5,channel_tick_damage=133),
    Rank('arcane_missiles',7,56,'arcane',595,range=30,channel_ticks=5,channel_tick_damage=175),
    Rank('arcane_missiles',8,56,'arcane',655,range=30,channel_ticks=5,channel_tick_damage=209),
]
# Forever talent-granted spells audited against current Wowhead Forever pages.
# Arcane Blast uses a percentage base-mana cost and stack state that the current
# single-target policy kernel does not yet execute.  Keep Rank.mana=0 here and
# expose the real cost/stack constants via wowhead_facts until that state machine
# is implemented; this prevents a fake fixed-mana value from becoming authority.
ARCANE_BLAST = [
    Rank('arcane_blast',i+1,learn,'arcane',0,wh.ARCANE_BLAST_CAST_S,wh.ARCANE_BLAST_RANGE_YD,damage,damage)
    for i,(learn,damage) in enumerate(wh.ARCANE_BLAST_RANKS)
]
ICE_LANCE = [
    Rank('ice_lance',i+1,learn,'frost',mana,0.0,wh.ICE_LANCE_RANGE_YD,damage,damage)
    for i,(learn,mana,damage) in enumerate(wh.ICE_LANCE_RANKS)
]
FIRE_BLAST = [
    Rank('fire_blast',1,6,'fire',40,range=20,dmin=27,dmax=35,cooldown=8),
    Rank('fire_blast',2,14,'fire',75,range=20,dmin=56,dmax=70,cooldown=8),
    Rank('fire_blast',3,22,'fire',115,range=20,dmin=96,dmax=118,cooldown=8),
    Rank('fire_blast',4,30,'fire',165,range=20,dmin=156,dmax=188,cooldown=8),
    Rank('fire_blast',5,38,'fire',220,range=20,dmin=225,dmax=269,cooldown=8),
    Rank('fire_blast',6,46,'fire',280,range=20,dmin=315,dmax=373,cooldown=8),
    Rank('fire_blast',7,54,'fire',340,range=20,dmin=415,dmax=491,cooldown=8),
]
FROST_NOVA = [
    Rank('frost_nova',1,10,'frost',55,dmin=21,dmax=24,root_duration=8,radius=10,cooldown=25),
    Rank('frost_nova',2,26,'frost',85,dmin=34,dmax=39,root_duration=8,radius=10,cooldown=25),
    Rank('frost_nova',3,40,'frost',115,dmin=52,dmax=59,root_duration=8,radius=10,cooldown=25),
    Rank('frost_nova',4,54,'frost',145,dmin=71,dmax=80,root_duration=8,radius=10,cooldown=25),
]
SPELLS = {
    'frostbolt': FROSTBOLT,
    'fireball': FIREBALL,
    'pyroblast': PYROBLAST,
    'scorch': SCORCH,
    'arcane_missiles': ARCANE_MISSILES,
    'arcane_blast': ARCANE_BLAST,
    'ice_lance': ICE_LANCE,
    'fire_blast': FIRE_BLAST,
    'frost_nova': FROST_NOVA,
}

# Mage base mana, CMaNGOS/MaNGOS-zero class 8. Levels 11..60.
BASE_MANA = {
11:275,12:280,13:301,14:323,15:331,16:355,17:365,18:391,19:403,20:431,
21:445,22:475,23:491,24:523,25:541,26:575,27:595,28:616,29:652,30:673,
31:694,32:730,33:751,34:772,35:793,36:814,37:850,38:871,39:892,40:913,
41:934,42:955,43:976,44:997,45:1018,46:1039,47:1060,48:1081,49:1102,50:1108,
51:1129,52:1150,53:1171,54:1177,55:1198,56:1219,57:1225,58:1246,59:1252,60:1273,
}

# CMaNGOS warrior-class BaseHealthExp0.  Used as the canonical ordinary melee
# target curve; callers can apply hp_mult for tougher/softer mob families.
MOB_BASE_HP = {
11:222,12:247,13:273,14:300,15:328,16:356,17:386,18:417,19:449,20:484,
21:521,22:562,23:605,24:651,25:699,26:750,27:800,28:853,29:905,30:955,
31:1006,32:1057,33:1110,34:1163,35:1220,36:1277,37:1336,38:1395,39:1459,40:1524,
41:1585,42:1651,43:1716,44:1782,45:1848,46:1919,47:1990,48:2062,49:2138,50:2215,
51:2292,52:2371,53:2453,54:2533,55:2614,56:2699,57:2784,58:2871,59:2961,60:3052,
61:3144,62:3237,
}

# Troll mage base Int/Spirit from MaNGOS-zero player_levelstats.
TROLL_INT_SPI = {
11:(31,35),12:(33,36),13:(34,37),14:(35,39),15:(37,40),16:(38,41),17:(39,43),18:(41,44),19:(42,45),20:(44,47),
21:(45,48),22:(47,50),23:(48,51),24:(50,53),25:(51,54),26:(53,56),27:(55,57),28:(56,59),29:(58,60),30:(60,62),
31:(61,64),32:(63,65),33:(65,67),34:(66,69),35:(68,70),36:(70,72),37:(72,74),38:(74,76),39:(76,77),40:(77,79),
41:(79,81),42:(81,83),43:(83,85),44:(85,87),45:(87,89),46:(89,91),47:(91,93),48:(94,95),49:(96,97),50:(98,99),
51:(100,101),52:(102,103),53:(104,105),54:(107,107),55:(109,110),56:(111,112),57:(114,114),58:(116,116),59:(119,119),60:(121,121),
}

# Best drink usable at level: amount over duration. 55 tier intentionally usable before
# a mage can self-conjure it; separate self-conjured mode below.
WATER_USABLE = [(5,436,21),(15,835,24),(25,1344,27),(35,1992,30),(45,2934,30),(55,4200,30)]
WATER_SELF = [(10,436,21),(20,835,24),(30,1344,27),(40,1992,30),(50,2934,30),(60,4200,30)]
ARCANE_INTELLECT = [(1,2),(14,7),(28,15),(42,22),(56,31)]


def latest(table: List[Rank], level: int) -> Optional[Rank]:
    xs=[x for x in table if x.learn<=level]
    return xs[-1] if xs else None

def latest_pair(table, level):
    xs=[x for x in table if x[0]<=level]
    return xs[-1] if xs else None

# ----------------------------- talents ------------------------------------

@dataclass(frozen=True)
class Talents:
    # Frost — Forever beta tree (19 talents)
    frost_warding:int=0; imp_frostbolt:int=0; elemental_precision:int=0
    ice_shards:int=0; permafrost:int=0; imp_frost_nova:int=0; frostbite:int=0
    piercing_ice:int=0; frost_channeling:int=0; ice_lance:int=0; improved_blizzard:int=0
    arctic_reach:int=0; ice_block:int=0; shatter:int=0
    improved_cone_of_cold:int=0; cold_snap:int=0; fingers_of_frost:int=0
    winters_chill:int=0; ice_barrier:int=0
    # Arcane — Forever beta tree (18 talents)
    wand_specialization:int=0; arcane_focus:int=0; improved_channeling:int=0
    arcane_subtlety:int=0; magic_absorption:int=0; arcane_concentration:int=0; arcane_resilience:int=0
    arcane_geometry:int=0; arcane_impact:int=0; arcane_blast:int=0
    arcane_shielding:int=0; improved_counterspell:int=0; arcane_meditation:int=0; missile_barrage:int=0
    presence_of_mind:int=0; arcane_mind:int=0; arcane_instability:int=0; arcane_power:int=0
    # Fire — Forever beta tree (17 talents)
    wake_of_fire:int=0; incineration:int=0; imp_fireball:int=0
    ignite:int=0; flame_throwing:int=0; impact:int=0
    burning_soul:int=0; improved_flamestrike:int=0; pyroblast:int=0
    imp_scorch:int=0; improved_fire_ward:int=0; hot_streak:int=0; master_elements:int=0
    critical_mass:int=0; blast_wave:int=0; fire_power:int=0; combustion:int=0

    def points(self)->int:
        return sum(getattr(self,f) for f in self.__dataclass_fields__)

    # Compatibility names consumed by the mature Mage Fast/MC pipeline. They
    # are views, not dataclass fields, so they never create fake talent points.
    @property
    def imp_arcane_missiles(self)->int:
        return self.improved_channeling

    @property
    def incinerate(self)->int:
        return self.incineration

    @property
    def imp_fire_blast(self)->int:
        # Existing Classic code subtracts 0.5 s per "rank". Forever Wake of
        # Fire is -1.0 s/rank, so expose twice the logical rank to old callers.
        return 2*self.wake_of_fire

    @property
    def fire_warding(self)->int:
        return self.improved_fire_ward

    @property
    def arcane_filler(self)->int:
        return 0


# name: (tree, max_rank, points_required_in_tree, optional prerequisite)
# Forever keeps the familiar 5-points-per-row gate. Only prerequisites that are
# present in the beta data / unambiguous spell chain are encoded; row gating is
# authoritative for every talent.
TALENT_RULES = {
    # Frost
    'frost_warding':('frost',2,0,None),
    'imp_frostbolt':('frost',5,0,None),
    'elemental_precision':('frost',5,0,None),
    'ice_shards':('frost',5,5,None),
    'permafrost':('frost',3,5,None),
    'imp_frost_nova':('frost',2,5,None),
    'frostbite':('frost',3,5,None),
    'piercing_ice':('frost',3,10,None),
    'frost_channeling':('frost',3,10,None),
    'ice_lance':('frost',1,10,None),
    'improved_blizzard':('frost',3,10,None),
    'arctic_reach':('frost',2,15,None),
    'ice_block':('frost',1,15,None),
    'shatter':('frost',3,15,None),
    'improved_cone_of_cold':('frost',3,20,None),
    'cold_snap':('frost',1,20,None),
    'fingers_of_frost':('frost',2,20,('ice_lance',1)),
    'winters_chill':('frost',5,25,None),
    'ice_barrier':('frost',1,30,('cold_snap',1)),
    # Arcane
    'wand_specialization':('arcane',2,0,None),
    'arcane_focus':('arcane',5,0,None),
    'improved_channeling':('arcane',5,0,None),
    'arcane_subtlety':('arcane',2,5,None),
    'magic_absorption':('arcane',2,5,None),
    'arcane_concentration':('arcane',5,5,None),
    'arcane_resilience':('arcane',2,5,None),
    'arcane_geometry':('arcane',2,10,None),
    'arcane_impact':('arcane',3,10,None),
    'arcane_blast':('arcane',1,10,None),
    'arcane_shielding':('arcane',2,15,None),
    'improved_counterspell':('arcane',2,15,None),
    'arcane_meditation':('arcane',3,15,None),
    'missile_barrage':('arcane',1,15,None),
    'presence_of_mind':('arcane',1,20,None),
    'arcane_mind':('arcane',5,20,None),
    'arcane_instability':('arcane',3,25,None),
    'arcane_power':('arcane',1,30,('presence_of_mind',1)),
    # Fire
    'wake_of_fire':('fire',2,0,None),
    'incineration':('fire',3,0,None),
    'imp_fireball':('fire',5,0,None),
    'ignite':('fire',5,5,None),
    'flame_throwing':('fire',2,5,None),
    'impact':('fire',3,5,None),
    'burning_soul':('fire',3,10,None),
    'improved_flamestrike':('fire',3,10,None),
    'pyroblast':('fire',1,10,None),
    'imp_scorch':('fire',3,15,None),
    'improved_fire_ward':('fire',2,15,None),
    'hot_streak':('fire',1,15,('pyroblast',1)),
    'master_elements':('fire',3,15,None),
    'critical_mass':('fire',3,20,None),
    'blast_wave':('fire',1,20,('pyroblast',1)),
    'fire_power':('fire',5,25,None),
    'combustion':('fire',1,30,('critical_mass',3)),
}

_TREE_TALENT_FIELDS = {
    tree: tuple(name for name, (tr, _mx, _need, _pre) in TALENT_RULES.items() if tr == tree)
    for tree in ('frost', 'arcane', 'fire')
}

TREE_NAMES = ('frost','arcane','fire')

def tree_points(t:Talents, tree:str)->int:
    return sum(getattr(t,n) for n in _TREE_TALENT_FIELDS.get(tree, ()))

def legal_add(t:Talents, name:str)->bool:
    tree,mx,need,pre=TALENT_RULES[name]
    if getattr(t,name)>=mx: return False
    if tree_points(t,tree)<need: return False
    if pre and getattr(t,pre[0])<pre[1]: return False
    return True

def add_point(t:Talents,name:str)->Talents:
    if not legal_add(t,name): raise ValueError(f'illegal talent point: {name}')
    return replace(t, **{name:getattr(t,name)+1})

# -------------------------- stats / gear ----------------------------------

@dataclass(frozen=True)
class Stats:
    intellect:float
    spirit:float
    base_mana:float
    max_mana:float
    spell_crit:float
    spell_power:float=0.0
    mp5:float=0.0
    spell_hit_bonus:float=0.0   # fraction, e.g. 0.01 == +1% spell hit


@dataclass(frozen=True)
class IceBarrierRank:
    learn:int
    mana:float
    absorb:float


# Classic 1.12 base values.  v0.11.8 adds a conservative crafted-item spell-
# power floor, so Ice Barrier can now also use its historical +10% Frost-SP
# coefficient instead of silently discarding known gear contribution.
ICE_BARRIER = (
    IceBarrierRank(40,305.0,438.0),
    IceBarrierRank(46,360.0,549.0),
    IceBarrierRank(52,420.0,678.0),
    IceBarrierRank(58,480.0,818.0),
)


def ice_barrier_rank(level:int)->Optional[IceBarrierRank]:
    xs=[x for x in ICE_BARRIER if x.learn<=int(level)]
    return xs[-1] if xs else None


def ice_barrier_mana_cost(level:int,t:Talents)->float:
    r=ice_barrier_rank(level)
    if r is None:
        return math.inf
    # Frost Channeling reduces the mana cost of Frost spells by 5% per rank.
    return max(0.0,r.mana*(1.0-.05*max(0,min(3,int(t.frost_channeling)))))


def generic_melee_hit_damage(mob:'Mob',cfg:'SimConfig')->float:
    """Explicit generic-mob hit proxy used only for absorb depletion.

    The leveling-speed objective deliberately has no player-health/death model,
    so the simulator historically did not need incoming melee damage at all.
    Ice Barrier needs *some* damage scale to decide how long pushback immunity
    survives.  Keep that new approximation isolated/configurable instead of
    pretending it is an exact creature-template damage oracle.
    """
    return max(1.0,float(mob.hp)*max(1e-6,float(cfg.generic_melee_hit_hp_frac)))


# Legacy smooth random-suffix curve.  Keep it as the broad all-slot progression
# backbone because the current public Forever database still does not expose a
# complete attainable set at every level.  v0.11.8 *calibrates* verified crafted
# slots against this curve rather than treating the old Owl proxy as truth.
OWL_SLOTS = (
    ('chest',10,1.00), ('legs',10,1.00), ('feet',10,.75), ('hands',10,.75),
    ('waist',10,.60), ('wrist',10,.50), ('back',10,.50), ('weapon',10,1.30),
    ('shoulder',15,.75), ('head',20,1.00), ('neck',20,.50),
    ('ring1',20,.50), ('ring2',25,.50),
)
OWL_C = 0.05548  # legacy full-set normalization; no longer presented as verified Forever gear.
_OWL_SLOT_WEIGHT = {name: w for name, _unlock, w in OWL_SLOTS}

def _legacy_owl_slot_bonus(slot:str, level:int)->float:
    w=_OWL_SLOT_WEIGHT.get(str(slot),0.0)
    ilvl=min(65.0,float(level)+5.0)
    return OWL_C*(ilvl**1.35)*w

def owl_bonus(level:int, intensity:float=1.0)->Tuple[float,float]:
    """Compatibility API for the legacy smooth all-slot Int/Spi backbone."""
    ilvl=min(65.0, level+5.0)
    total=0.0
    for _,unlock,w in OWL_SLOTS:
        if level>=unlock:
            total += OWL_C * (ilvl**1.35) * w
    total *= intensity
    return total,total

def forever_crafted_gear(level:int, intensity:float=1.0)->dict:
    """Discrete audited named gear; no synthetic missing-slot stat proxy.

    The selected item list is now authoritative.  If the current catalogue has
    no real item for a legal slot, that slot contributes no gear stats and is
    reported in ``missing_slots`` instead of receiving an Owl/pseudo-item
    replacement.
    """
    snap=real_gear_snapshot(level)
    slots=set(snap.get('slots',{}))
    totals=snap.get('totals',{})
    scale=float(intensity)
    craft_rows=mage_caster_items(level)
    missing=list(snap.get('missing_slots',[]))
    return {
        'bonus_intellect':max(0.0,float(totals.get('intellect',0.0))*scale),
        'bonus_spirit':max(0.0,float(totals.get('spirit',0.0))*scale),
        'spell_power_floor':max(0.0,float(totals.get('spell_power',0.0))*scale),
        'stamina_floor':max(0.0,float(totals.get('stamina',0.0))*scale),
        'armor_floor':max(0.0,float(totals.get('armor',0.0))*scale),
        'mp5':max(0.0,float(totals.get('mp5',0.0))*scale),
        'spell_hit':max(0.0,float(totals.get('spell_hit',0.0))*scale),
        'spell_crit':max(0.0,float(totals.get('spell_crit',0.0))*scale),
        'selected_items':[x.get('name') for x in snap.get('items',[])],
        'selected_slots':sorted(slots),
        # Compatibility field retained for downstream callers; v0.11.29 never
        # fills it because there is no synthetic fallback anymore.
        'fallback_slots':[],
        'missing_slots':missing,
        'hand_setup':snap.get('hand_setup','none'),
        'crafted_items':[row.name for row in craft_rows],
        'provenance':'discrete_named_forever_items',
        'coverage':f"{len(slots)} real named slots; missing: {', '.join(missing) if missing else 'none'}",
    }


def mana_bonus_from_intellect(intellect:float)->float:
    base=min(20.0,intellect)
    return base + max(0.0,intellect-20.0)*15.0


def mage_spell_crit(level:int,intellect:float)->float:
    # CMaNGOS Classic: percentage = 3.70 + INT/(14.77 + 0.65*level)
    return (3.70 + intellect/(14.77 + .65*level))/100.0


def player_stats(level:int,t:Talents,owl_intensity:float=1.0,*,
                 bonus_intellect:float=0.0,bonus_spirit:float=0.0,spell_power:float=0.0)->Stats:
    bi,bs=TROLL_INT_SPI[level]
    gear=forever_crafted_gear(level,owl_intensity)
    gi=float(gear['bonus_intellect']); gs=float(gear['bonus_spirit'])
    ai=latest_pair(ARCANE_INTELLECT,level)[1]
    # Forever Arcane Mind is a rank-scaled maximum-mana aura: +2% max mana
    # per rank.  It must not inflate Intellect itself (or Int-derived crit).
    intellect=bi+gi+ai+float(bonus_intellect)
    spirit=bs+gs+float(bonus_spirit)
    base=BASE_MANA[level]
    pre_arcane_mind_mana=base+mana_bonus_from_intellect(intellect)
    maxmana=pre_arcane_mind_mana*(1+.02*t.arcane_mind)
    crit=mage_spell_crit(level,intellect) + .01*t.arcane_instability + .01*float(gear.get('spell_crit',0.0))
    return Stats(
        intellect, spirit, base, maxmana, crit,
        float(gear['spell_power_floor'])+float(spell_power),
        float(gear.get('mp5',0.0)),
        .01*float(gear.get('spell_hit',0.0)),
    )


def _rank_coeff(table, rank:Rank)->float:
    idx=int(rank.rank)-1
    if idx < 0 or idx >= len(table):
        raise ValueError(f"missing Forever spell-power modifier for {rank.spell} rank {rank.rank}")
    return float(table[idx])


def spell_power_direct_coeff(rank:Rank, profile:MageServerProfile|None=None)->float:
    """Audited Forever spell-power modifier for the modeled Mage spell rank.

    Unlike Classic, Forever publishes rank-specific SP modifiers directly and
    does not apply the old pre-20 learned-level penalty to the audited spells.
    Arcane Missiles returns the *whole-channel* modifier here so deterministic
    engines can divide it across missiles; the stochastic channel applies the
    same audited 28.6% modifier to each missile directly.
    """
    if rank.spell=='frostbolt':
        return _rank_coeff(wh.FROSTBOLT_SP_COEFF_BY_RANK,rank)
    if rank.spell=='fireball':
        return _rank_coeff(wh.FIREBALL_SP_COEFF_BY_RANK,rank)
    if rank.spell=='scorch':
        return _rank_coeff(wh.SCORCH_SP_COEFF_BY_RANK,rank)
    if rank.spell=='fire_blast':
        return _rank_coeff(wh.FIRE_BLAST_SP_COEFF_BY_RANK,rank)
    if rank.spell=='frost_nova':
        return _rank_coeff(wh.FROST_NOVA_SP_COEFF_BY_RANK,rank)
    if rank.spell=='pyroblast':
        return _rank_coeff(wh.PYROBLAST_DIRECT_SP_COEFF_BY_RANK,rank)
    if rank.spell=='arcane_missiles':
        return wh.ARCANE_MISSILES_SP_COEFF_PER_TICK * max(1,int(rank.channel_ticks))
    if rank.spell=='arcane_blast':
        return default_rules().spell_value('mage','arcane_blast',rank.learn,'spell_power_coefficient',target='arcane_blast')
    if rank.spell=='ice_lance':
        return float((profile or CURRENT_TARGET_SERVER_PROFILE).ice_lance_sp_coefficient)
    raise ValueError(f"no Forever spell-power modifier audit for {rank.spell} rank {rank.rank}")


def ice_lance_frozen_multiplier(profile:MageServerProfile|None=None)->float:
    return float((profile or CURRENT_TARGET_SERVER_PROFILE).ice_lance_frozen_damage_multiplier)


def spell_power_effective_coeff(rank:Rank, profile:MageServerProfile|None=None, *, frozen:bool=False)->float:
    coeff = spell_power_direct_coeff(rank, profile)
    if rank.spell == 'ice_lance' and frozen:
        coeff *= ice_lance_frozen_multiplier(profile)
    return coeff


def spell_power_dot_coeff(rank:Rank)->float:
    """Audited total SP modifier for attached periodic damage.

    Forever Pyroblast is 60% total over 12 s (15% per 3 s tick). Fireball's
    attached DoT currently exposes no SP modifier and remains zero here.
    """
    if rank.spell=='pyroblast':
        return _rank_coeff(wh.PYROBLAST_DOT_SP_COEFF_TOTAL_BY_RANK,rank)
    if rank.spell=='fireball':
        return 0.0
    return 0.0

# ----------------------------- combat -------------------------------------

@dataclass
class Mob:
    level:int
    hp:float
    run_speed:float=7.0
    swing:float=2.0
    melee_reach:float=5.0

@dataclass
class Dot:
    remaining_ticks:int
    next_tick:float
    interval:float
    damage:float
    school:str
    kind:str='generic'
    stacks:int=1
    crit_chance:float=0.0
    crit_multiplier:float=1.5

@dataclass
class Projectile:
    impact:float
    rank:Rank
    landed:bool
    crit:bool
    damage:float
    was_rooted_snapshot:bool

@dataclass
class State:
    t:float
    hp:float
    mana:float
    max_mana:float
    distance:float
    engaged:bool=False
    slow_until:float=-1e9
    slow_frac:float=0.0
    root_until:float=-1e9
    stun_until:float=-1e9
    next_swing:float=math.inf
    in_melee:bool=False
    last_mana_spend:float=-1e9
    clearcasting:bool=False
    fireblast_ready:float=0.0
    nova_ready:float=0.0
    blink_ready:float=0.0
    combustion_ready:float=0.0
    combustion_active:bool=False
    combustion_crits:int=0
    combustion_bonus:int=0
    ice_barrier_ready:float=0.0
    ice_barrier_absorb:float=0.0
    ice_barrier_until:float=-1e9
    pyro_opener_used:bool=False
    fire_cycle_pos:int=0
    wc_stacks:int=0
    wc_until:float=-1e9
    scorch_stacks:int=0
    scorch_until:float=-1e9
    dots:List[Dot]=field(default_factory=list)
    projectiles:List[Projectile]=field(default_factory=list)
    total_pushback:float=0.0
    damage_taken_swings:int=0
    # Forever Mage proc/stack state.
    arcane_blast_stacks:int=0
    arcane_blast_until:float=-1e9
    missile_barrage_until:float=-1e9
    fingers_of_frost_charges:int=0
    fingers_of_frost_until:float=-1e9
    hot_streak_stacks:int=0
    hot_streak_until:float=-1e9
    total_melee_contact:float=0.0
    min_distance:float=math.inf
    # HP-aware wand-finisher state: once a bounded finisher window is attempted
    # for this mob, fall back to the normal spell policy if it does not kill.
    wand_finisher_committed:bool=False

@dataclass(frozen=True)
class SimConfig:
    # Default leveling comparison target.  Zero means same-level mobs;
    # sensitivity runs may opt into harder/easier offsets explicitly.
    target_level_offset:int=0
    mob_speed:float=7.0
    mob_swing:float=2.0
    # Final search uses a small representative melee-speed mixture instead of
    # overfitting talents/policies to one 2.0 s dummy.  Same-level mobs cycle through this swing-speed tuple so target level and
    # attack-frequency sensitivity remain separate knobs.
    mob_swing_mix:Tuple[float,...]=(1.5,2.0,2.5)
    melee_reach:float=5.0
    # Target-server-dependent Frost control/contact semantics are profile-owned.
    # Per-run overrides remain available for sensitivity tests; None means use
    # the explicit server profile rather than a hidden engine default.
    moving_leeway:float|None=None
    root_break_mode:str|None=None # scaled | first | never
    root_break_base:float|None=None
    root_break_damage_scale:float|None=None
    root_break_fire_bonus:float|None=None
    # Generic ordinary mobs default to no inherent school resistance.  This is
    # configurable so Arcane Subtlety has its real spell-penetration value when
    # profiling resistant mob families, without inventing fake resistance for
    # the baseline leveling target.
    # Inherent school resistance. `mob_magic_resistance` remains a legacy
    # fallback; school-specific values override it when non-zero.
    mob_magic_resistance:float=0.0
    mob_fire_resistance:float=0.0
    mob_frost_resistance:float=0.0
    mob_arcane_resistance:float=0.0
    # Generic ordinary-mob melee-hit proxy used only to deplete Ice Barrier.
    # 1/18 of same-target HP gives roughly five absorbed normal swings across
    # ranks 1..4, and intentionally ignores player armor (conservative shield
    # lifetime).  Creature-specific damage is outside this leveling objective.
    generic_melee_hit_hp_frac:float=1.0/18.0
    use_best_water:bool=True
    owl_intensity:float=1.0
    # Analytic gear perturbation hooks.  Baseline simulations leave these zero.
    gear_bonus_intellect:float=0.0
    gear_bonus_spirit:float=0.0
    gear_bonus_spell_power:float=0.0
    gear_bonus_stamina:float=0.0
    gear_bonus_armor:float=0.0
    mage_armor:bool=True
    server_profile:MageServerProfile=CURRENT_TARGET_SERVER_PROFILE
    seed:int=1

    def __post_init__(self):
        p=self.server_profile
        if self.moving_leeway is None:
            object.__setattr__(self, "moving_leeway", float(p.moving_melee_leeway))
        if self.root_break_mode is None:
            object.__setattr__(self, "root_break_mode", str(p.root_break_mode))
        if self.root_break_base is None:
            object.__setattr__(self, "root_break_base", float(p.root_break_base))
        if self.root_break_damage_scale is None:
            object.__setattr__(self, "root_break_damage_scale", float(p.root_break_damage_scale))
        if self.root_break_fire_bonus is None:
            object.__setattr__(self, "root_break_fire_bonus", float(p.root_break_fire_bonus))


def player_stats_for_config(level:int,t:Talents,cfg:SimConfig)->Stats:
    return player_stats(
        level,t,cfg.owl_intensity,
        bonus_intellect=cfg.gear_bonus_intellect,
        bonus_spirit=cfg.gear_bonus_spirit,
        spell_power=cfg.gear_bonus_spell_power,
    )

@dataclass
class FightMetrics:
    kill_time:float=0.0
    mana_spent:float=0.0
    pushback:float=0.0
    swings:int=0
    unabsorbed_swings:int=0
    melee_contact:float=0.0
    min_range:float=math.inf
    wand_time:float=0.0
    wand_shots:int=0
    wand_damage:float=0.0
    casts:Dict[str,int]=field(default_factory=dict)


# Player HP / incoming melee damage are intentionally outside the leveling-speed objective.
# Melee contact is retained only for cast pushback/channel interruption and movement/control.

def effective_range(rank:Rank,t:Talents)->float:
    r=rank.range
    if rank.school=='fire' and rank.spell in ('fireball','pyroblast','scorch','fire_blast'):
        r += 3.0*t.flame_throwing
    if rank.spell=='frostbolt':
        r *= 1.0 + .10*t.arctic_reach
    return r


# CMaNGOS Classic pre-3.0 partial-resist distribution, indexed by whole
# percentage points of effective mitigation. Columns are 0/25/50/75/100%.
# Unit.cpp linearly interpolates between these rows to two decimal places.
_CMANGOS_PARTIAL_RESIST_BASE = (
(10000,0,0,0,0),(9700,200,100,0,0),(9400,400,200,0,0),(9000,800,200,0,0),
(8700,1000,300,0,0),(8400,1200,400,0,0),(8200,1300,400,100,0),(7900,1500,500,100,0),
(7600,1700,600,100,0),(7300,1900,700,100,0),(6900,2300,700,100,0),(6600,2500,800,100,0),
(6300,2700,900,100,0),(6000,2900,1000,100,0),(5800,3000,1000,200,0),(5400,3300,1100,200,0),
(5100,3600,1100,200,0),(4800,3800,1200,200,0),(4400,4200,1200,200,0),(4100,4400,1300,200,0),
(3700,4800,1300,200,0),(3400,5000,1400,200,0),(3100,5200,1500,200,0),(3000,5200,1500,200,100),
(2800,5300,1500,300,100),(2500,5500,1600,300,100),(2400,5400,1700,400,100),(2300,5300,1800,500,100),
(2200,5100,2100,500,100),(2100,5000,2200,600,100),(2000,4900,2400,600,100),(1900,4700,2600,700,100),
(1800,4600,2700,800,100),(1700,4400,3000,800,100),(1600,4300,3100,900,100),(1500,4200,3200,1000,100),
(1400,4100,3300,1100,100),(1300,3900,3600,1100,100),(1300,3600,3800,1200,100),(1200,3500,3900,1300,100),
(1100,3400,4000,1400,100),(1000,3300,4100,1500,100),(900,3100,4400,1500,100),(800,3000,4500,1600,100),
(800,2700,4700,1700,100),(700,2600,4800,1800,100),(600,2500,4900,1900,100),(600,2300,5000,1900,200),
(500,2200,5100,2000,200),(300,2200,5300,2000,200),(200,2100,5400,2100,200),(200,2000,5300,2200,300),
(200,2000,5100,2200,500),(200,1900,5000,2300,600),(100,1900,4900,2500,600),(100,1800,4800,2600,700),
(100,1700,4700,2700,800),(100,1600,4500,3000,800),(100,1500,4400,3100,900),(100,1500,4100,3300,1000),
(100,1400,4000,3400,1100),(100,1300,3900,3500,1200),(100,1200,3800,3600,1300),(100,1100,3600,3900,1300),
(100,1100,3300,4100,1400),(100,1000,3200,4200,1500),(100,900,3100,4300,1600),(100,800,3000,4400,1700),
(100,800,2700,4600,1800),(100,700,2600,4700,1900),(100,600,2400,4900,2000),(100,600,2200,5000,2100),
(100,500,2100,5100,2200),(100,500,1800,5300,2300),(100,400,1700,5400,2400),(100,300,1600,5500,2500),
(100,300,1500,5300,2800),(100,200,1500,5200,3000),(0,200,1500,5200,3100),(0,200,1400,5000,3400),
(0,200,1300,4800,3700),(0,200,1300,4400,4100),(0,200,1200,4200,4400),(0,200,1200,3800,4800),
(0,200,1100,3600,5100),(0,200,1100,3300,5400),(0,200,1000,3000,5800),(0,100,1000,2900,6000),
(0,100,900,2700,6300),(0,100,800,2500,6600),(0,100,700,2300,6900),(0,100,700,1900,7300),
(0,100,600,1700,7600),(0,100,500,1500,7900),(0,100,400,1300,8200),(0,0,400,1200,8400),
(0,0,300,1000,8700),(0,0,200,800,9000),(0,0,200,400,9400),(0,0,100,200,9700),(0,0,0,0,10000),
)

_BINARY_DAMAGE_SPELLS = frozenset(('frostbolt','frost_nova'))


def _school_resistance(cfg:SimConfig, school:str)->float:
    school=str(school or '').lower()
    specific={
        'fire':float(getattr(cfg,'mob_fire_resistance',0.0) or 0.0),
        'frost':float(getattr(cfg,'mob_frost_resistance',0.0) or 0.0),
        'arcane':float(getattr(cfg,'mob_arcane_resistance',0.0) or 0.0),
    }.get(school,0.0)
    return specific if specific else float(getattr(cfg,'mob_magic_resistance',0.0) or 0.0)


def spell_miss_chance(level:int,mob_level:int,school:str,t:Talents)->float:
    """CMaNGOS Classic pre-WotLK PvE spell miss table before resistance.

    Base is 4% versus equal-level NPCs, +1 percentage point per level through +2,
    then +11 points for every NPC level beyond +2. Spell hit talents subtract
    from this result; unavoidable miss is capped at a minimum 1%.
    """
    diff=int(mob_level)-int(level)
    miss=4.0 + (diff if diff<=2 else 2 + 11*(diff-2))
    if school in ('frost','fire'): miss -= 1.0*t.elemental_precision
    if school=='arcane': miss -= 1.0*t.arcane_focus
    # Real-item hit is stored as percentage points in the gear catalogue.
    miss -= float(real_gear_snapshot(level).get('totals',{}).get('spell_hit',0.0))
    return max(.01,min(1.0,miss/100.0))


def spell_hit(level:int,mob_level:int,school:str,t:Talents)->float:
    return 1.0-spell_miss_chance(level,mob_level,school,t)


def wand_hit_chance(level:int,mob_level:int)->float:
    """Ranged-weapon hit chance for wand Shoot, assuming capped wand skill.

    Wands use the physical/ranged attack table rather than spell hit.  Mage
    spell-hit talents therefore do not modify this value.
    """
    return physical_hit_chance(int(level), int(mob_level), bonus_pct=0.0)


def effective_magic_resistance_percent(level:int,mob_level:int,school:str,t:Talents,cfg:SimConfig,
                                       *,binary:bool=False)->float:
    """CMaNGOS Classic Unit::CalculateEffectiveMagicResistancePercent as 0..0.75.

    Spell penetration first reduces inherent resistance (never below zero). Pre-3.0
    converts resistance to mitigation as 0.75 * R / skill, where skill=max(5L,100).
    Non-binary damage against a higher-level uncontrolled NPC adds 0.4% per point
    of skill difference = 2 percentage points per NPC level. Final cap is 75%.
    """
    pen=(0.0,8.0,15.0)[max(0,min(2,int(t.arcane_subtlety)))]
    resist=max(0.0,_school_resistance(cfg,school)-pen)
    skill=max(float(level)*5.0,100.0)
    pct=.75*(resist/skill)
    if not binary:
        victim_skill=float(mob_level)*5.0
        pct += .004*max(victim_skill-skill,0.0)
    return max(0.0,min(.75,pct))


def _partial_resist_chances(percent:float)->Tuple[int,int,int,int,int]:
    """CMaNGOS Unit.cpp two-decimal linear interpolation; integer chances sum 10000."""
    pct=max(0.0,min(1.0,float(percent)))*100.0
    idx=max(0,min(10000,int(round(pct*100.0))))
    row=min(100,idx//100); frac=idx-row*100
    a=_CMANGOS_PARTIAL_RESIST_BASE[row]
    if row>=100 or frac<=0:
        return a
    b=_CMANGOS_PARTIAL_RESIST_BASE[row+1]
    vals=tuple(max(0,int(round(a[i]+(b[i]-a[i])*(frac/100.0)))) for i in range(5))
    # Preserve a 10000-sided die despite independent integer rounding.
    delta=10000-sum(vals)
    if delta:
        vals=list(vals); vals[0]=max(0,vals[0]+delta); vals=tuple(vals)
    return vals


def roll_magic_resistance_multiplier(level:int,mob_level:int,school:str,spell:str,t:Talents,
                                     cfg:SimConfig,rng:random.Random)->float:
    """Return post-resistance damage multiplier using Classic binary/partial behavior."""
    binary=str(spell or '') in _BINARY_DAMAGE_SPELLS
    pct=effective_magic_resistance_percent(level,mob_level,school,t,cfg,binary=binary)
    if pct<=0:
        return 1.0
    if binary:
        return 0.0 if rng.random()<pct else 1.0
    chances=_partial_resist_chances(pct)
    roll=rng.randint(1,10000); acc=0
    for portion,chance in enumerate(chances):
        acc+=chance
        if roll<=acc:
            return 1.0-.25*portion
    return 1.0


def resistance_damage_multiplier(level:int,t:Talents,cfg:SimConfig,school:str='arcane',mob_level:Optional[int]=None)->float:
    """Expected multiplier helper for diagnostics/tests; combat uses bucket rolls above."""
    ml=int(level if mob_level is None else mob_level)
    pct=effective_magic_resistance_percent(level,ml,school,t,cfg,binary=False)
    chances=_partial_resist_chances(pct)
    expected_resist=sum((.25*i)*(c/10000.0) for i,c in enumerate(chances))
    return 1.0-expected_resist

def shatter_crit_bonus(t:Talents)->float:
    return (0.0,.17,.33,.50)[max(0,min(3,int(t.shatter)))]

def impact_proc_chance(t:Talents)->float:
    return (0.0,.03,.07,.10)[max(0,min(3,int(t.impact)))]

def burning_soul_protection(t:Talents)->float:
    return (0.0,.23,.47,.70)[max(0,min(3,int(t.burning_soul)))]

def fire_blast_cooldown(rank:Rank,t:Talents)->float:
    # Compatibility-safe across generic test/plugin talent objects: current
    # Forever uses Wake of Fire (2 legacy Improved Fire Blast ranks per point).
    wake = getattr(t, 'wake_of_fire', None)
    if wake is None:
        wake = max(0, int(getattr(t, 'imp_fire_blast', 0) or 0) // 2)
    return max(1.0,float(rank.cooldown)-1.0*int(wake))

def am_pushback_protection(t:Talents)->float:
    channel = getattr(t, 'improved_channeling', None)
    if channel is None:
        channel = getattr(t, 'imp_arcane_missiles', 0)
    return min(1.0,.20*int(channel or 0))

def maybe_activate_combustion(s:State,t:Talents,rank:Rank)->None:
    if not t.combustion or rank.school!='fire' or s.combustion_active:
        return
    if s.t + TIME_EPS < s.combustion_ready:
        return
    s.combustion_active=True
    s.combustion_crits=0
    s.combustion_bonus=1
    s.combustion_ready=s.t+180.0


def combustion_after_hit(s:State,rank:Rank,landed:bool,crit:bool)->None:
    if not s.combustion_active or rank.school!='fire' or not landed:
        return
    if crit:
        s.combustion_crits+=1
        if s.combustion_crits>=4:
            s.combustion_active=False
            s.combustion_bonus=0
            return
    # Each landed Fire damage spell makes the next Fire spell 10% more likely
    # to crit while Combustion remains active.
    s.combustion_bonus+=1


def regen_fraction_in_5sr(level:int,t:Talents,cfg:SimConfig)->float:
    frac=.05*t.arcane_meditation
    if cfg.mage_armor and level>=34: frac+=.30
    return min(1.0,frac)


def advance_passive(s:State,dt:float,level:int,t:Talents,stats:Stats,cfg:SimConfig,mob:Mob,
                    moving:bool=False, player_speed_away:float=0.0, rng:random.Random|None=None):
    """Advance time with explicit player movement along the target axis.

    ``player_speed_away`` is positive while kiting away and negative while
    moving toward the target.  This keeps the MC/event kernel authoritative for
    the key Ice Lance property: its GCD can be spent moving while hard casts
    root the player in place.
    """
    if dt<=0:return
    start=s.t; end=s.t+dt
    if s.in_melee:
        s.total_melee_contact += dt
    s.min_distance=min(s.min_distance,s.distance)
    # Spirit regen integrated with exact 5SR boundary.
    mps=(12.5+stats.spirit/4)/2 + stats.mp5/5.0
    f=regen_fraction_in_5sr(level,t,cfg)
    if start < s.last_mana_spend+5 < end:
        a=s.last_mana_spend+5-start
        s.mana=min(s.max_mana,s.mana + mps*(a*f + (dt-a)))
    else:
        inside=end <= s.last_mana_spend+5
        s.mana=min(s.max_mana,s.mana + mps*dt*(f if inside else 1.0))

    effective_reach=mob.melee_reach+(cfg.moving_leeway if moving else 0)
    # Before aggro, only the player moves. This matters for Fire cadence where a
    # projectile may be in flight while the mage steps into Scorch range.
    if not s.engaged:
        s.distance=max(0.0,s.distance + float(player_speed_away)*dt)
        s.min_distance=min(s.min_distance,s.distance)
        s.t=end
    elif not s.in_melee and s.hp>0:
        # Split at root/slow/stun expirations so relative-speed movement is
        # piecewise exact for the state changes that matter to contact.
        rem=dt
        while rem>EPS and not s.in_melee:
            frozen=s.t + TIME_EPS < s.root_until
            stunned=s.t + TIME_EPS < s.stun_until
            slowed=s.t + TIME_EPS < s.slow_until
            nxt=min(rem,
                    max(0,s.root_until-s.t) if frozen else math.inf,
                    max(0,s.stun_until-s.t) if stunned else math.inf,
                    max(0,s.slow_until-s.t) if slowed else math.inf)
            if math.isinf(nxt): nxt=rem
            mob_speed=0.0 if (frozen or stunned) else mob.run_speed*((1-s.slow_frac) if slowed else 1.0)
            relative=float(player_speed_away)-mob_speed
            s.distance=max(effective_reach if relative<0 else 0.0, s.distance + relative*nxt)
            s.min_distance=min(s.min_distance,s.distance)
            if relative<0 and s.distance<=effective_reach+EPS:
                s.distance=effective_reach
                s.in_melee=True; s.next_swing=s.t+nxt
            s.t+=nxt; rem-=nxt
        if s.t<end-EPS: s.t=end
    else:
        # If already in melee, moving away can only escape if the player is
        # faster than the target (e.g. target rooted/slowed). Equal run speed
        # preserves contact, exactly the distinction the Ice Lance model needs.
        frozen=s.t + TIME_EPS < s.root_until
        stunned=s.t + TIME_EPS < s.stun_until
        slowed=s.t + TIME_EPS < s.slow_until
        mob_speed=0.0 if (frozen or stunned) else mob.run_speed*((1-s.slow_frac) if slowed else 1.0)
        relative=float(player_speed_away)-mob_speed
        if relative>EPS:
            s.distance += relative*dt
            if s.distance>effective_reach+EPS:
                s.in_melee=False; s.next_swing=math.inf
        s.min_distance=min(s.min_distance,s.distance)
        s.t=end

    # DoT ticks: apply all due ticks up to end (simple queue).
    for d in list(s.dots):
        while d.remaining_ticks>0 and d.next_tick<=end+EPS and s.hp>0:
            tick_damage=d.damage
            if d.crit_chance>0.0 and rng is not None and rng.random()<d.crit_chance:
                tick_damage*=d.crit_multiplier
            s.hp-=tick_damage; d.remaining_ticks-=1; d.next_tick+=d.interval
        if d.remaining_ticks<=0: s.dots.remove(d)
    if s.scorch_until<=end: s.scorch_stacks=0
    if s.wc_until<=end: s.wc_stacks=0
    if s.hot_streak_until<=end: s.hot_streak_stacks=0


def mana_cost(rank:Rank,t:Talents,stats:Stats)->float:
    c=rank.mana
    if rank.school=='frost': c*=1-.05*t.frost_channeling
    # Classic Era Elemental Precision used here as resist/hit only (no mana effect).
    return max(0,c)


def direct_mod(rank:Rank,t:Talents,s:State)->float:
    m=1.0
    if rank.spell!='arcane_blast' and s.arcane_blast_stacks and s.t + TIME_EPS < s.arcane_blast_until:
        m*=1.0 + wh.ARCANE_BLAST_OTHER_SPELL_DAMAGE_BONUS_PER_STACK*s.arcane_blast_stacks
    if rank.school=='frost' and t.piercing_ice:
        m*=1.0 + default_rules().talent_value('mage','piercing_ice',t.piercing_ice,'school_damage_pct',target='frost_spells',school='frost')
    if rank.school=='fire':
        m*=1+.02*t.fire_power
        if s.scorch_stacks and s.t + TIME_EPS < s.scorch_until: m*=1+.03*s.scorch_stacks
    m*=1+.01*t.arcane_instability
    return m


def crit_chance(rank:Rank,t:Talents,s:State,stats:Stats)->float:
    c=stats.spell_crit
    if rank.school=='frost':
        if s.t + TIME_EPS < s.wc_until:
            c+=.02*s.wc_stacks
        if s.t + TIME_EPS < s.root_until: c+=(0.0,.17,.33,.50)[max(0,min(3,int(t.shatter)))]
    if rank.spell in ('scorch','fire_blast','ice_lance','arcane_blast'): c+=.02*t.incineration
    if rank.school=='arcane': c+=.02*t.arcane_impact
    if rank.school=='fire': c+=.02*t.critical_mass
    if rank.school=='fire' and s.combustion_active:
        c+=.10*s.combustion_bonus
    return min(.99,c)


def crit_mult(rank:Rank,t:Talents)->float:
    if rank.school=='frost': return 1.5+.1*t.ice_shards
    if rank.school=='arcane': return 1.5+.1*t.arcane_mind
    return 1.5


def _hot_streak_effect(t:Talents):
    if not getattr(t, 'hot_streak', 0):
        return None
    for effect in default_rules().talent_effects('mage','hot_streak',1):
        if effect.normalization_status == 'supported' and effect.normalized_kind == 'cast_time_reduction_per_stack':
            return effect
    return None


def _hot_streak_active_stacks(s:State) -> int:
    if s.t + TIME_EPS >= s.hot_streak_until:
        s.hot_streak_stacks=0
        return 0
    return max(0,int(s.hot_streak_stacks))


def _maybe_grant_hot_streak(s:State,t:Talents,spell:str,crit:bool) -> None:
    effect=_hot_streak_effect(t)
    if effect is None or not crit:
        return
    triggers=set(effect.metadata.get('trigger_spells') or ())
    if str(spell) not in triggers:
        return
    max_stacks=int(effect.metadata.get('max_stacks',3))
    duration=float(effect.metadata.get('duration_s',15.0))
    s.hot_streak_stacks=min(max_stacks,_hot_streak_active_stacks(s)+1)
    s.hot_streak_until=s.t+duration


def _clear_arcane_blast_stacks(s:State) -> None:
    s.arcane_blast_stacks=0
    s.arcane_blast_until=-1e9


def maybe_clearcast(s:State,t:Talents,rng:random.Random,landed:bool):
    if landed and t.arcane_concentration and rng.random()<.02*t.arcane_concentration:
        s.clearcasting=True


def spend(s:State,cost:float):
    if cost>0:
        s.mana-=cost; s.last_mana_spend=s.t


def _ice_barrier_absorbs_swing(s:State,mob:Mob,cfg:SimConfig)->bool:
    """Consume one generic melee hit from Ice Barrier.

    Return True only when the hit is fully absorbed.  A hit that breaks the
    remaining shield with overflow is conservatively allowed to cause cast
    pushback/channel disruption.
    """
    if s.ice_barrier_absorb<=EPS or s.t+TIME_EPS>=s.ice_barrier_until:
        s.ice_barrier_absorb=0.0
        return False
    dmg=generic_melee_hit_damage(mob,cfg)
    if s.ice_barrier_absorb+EPS>=dmg:
        s.ice_barrier_absorb=max(0.0,s.ice_barrier_absorb-dmg)
        return True
    s.ice_barrier_absorb=0.0
    return False


def _maybe_cast_ice_barrier_pre_pull(s:State,level:int,t:Talents,stats:Stats,cfg:SimConfig,
                                     mob:Mob,rng:random.Random,metrics:FightMetrics)->bool:
    """Execute the policy-selected pre-pull Ice Barrier action.

    Policy search explicitly compares Barrier OFF vs ON for otherwise-identical
    rotations, because saved pushback can be worth less than the spell's real
    mana/GCD cost.  When selected we charge that mana, 1.5 s GCD, 30 s cooldown
    and shield depletion.  Leftover absorb and the 60 s aura duration persist
    across pulls; recovery/drink time ticks the duration before the next mob.
    """
    if not t.ice_barrier:
        return False
    rank=ice_barrier_rank(level)
    if rank is None or s.t+EPS<s.ice_barrier_ready:
        return False
    cost=ice_barrier_mana_cost(level,t)
    if s.mana+EPS<cost:
        return False
    spend(s,cost); metrics.mana_spent+=cost
    s.ice_barrier_absorb=float(rank.absorb)+.10*float(stats.spell_power)
    s.ice_barrier_until=s.t+60.0
    s.ice_barrier_ready=s.t+30.0
    metrics.casts['ice_barrier']=metrics.casts.get('ice_barrier',0)+1
    advance_events(s,GCD,level,t,stats,cfg,mob,rng,metrics)
    return True


def maybe_break_root(s:State, damage:float, mob:Mob, school:str, cfg:SimConfig, rng:random.Random):
    """Apply a configurable approximation to damage breaking Nova/Frostbite.

    Vanilla/Classic root breaking is intentionally random rather than a fixed
    damage threshold.  The exact server formula is not treated as known here,
    so the optimizer is validated against conservative/optimistic modes too.
    """
    if s.t >= s.root_until or damage <= 0:
        return
    if cfg.root_break_mode == 'never':
        return
    if cfg.root_break_mode == 'first':
        s.root_until=-1e9
        return
    frac=damage/max(1.0,mob.hp)
    p=cfg.root_break_base + cfg.root_break_damage_scale*frac
    if school=='fire': p+=cfg.root_break_fire_bonus
    p=min(.98,max(.05,p))
    if rng.random()<p:
        s.root_until=-1e9


def apply_ignite(s:State,total_damage:float):
    """Classic single-mage Ignite: refresh 4 s, add a stack up to 5.

    Each new crit contributes 40% of its damage at 5/5, split over two 2 s
    ticks.  This mirrors the Classic sim's ApplyOrRefresh + MaxStacks=5 shape
    without trying to emulate multi-mage ignite ownership.
    """
    if total_damage<=0:
        return
    existing=next((d for d in s.dots if d.kind=='ignite'),None)
    add_per_tick=total_damage/2.0
    if existing is None:
        s.dots.append(Dot(2,s.t+2,2,add_per_tick,'fire','ignite',1))
    else:
        # Refresh to two future ticks. Preserve/add snapshot damage until five stacks.
        if existing.stacks < 5:
            existing.damage += add_per_tick
            existing.stacks += 1
        existing.remaining_ticks=2
        existing.next_tick=s.t+2


def resolve_direct_impact(s:State,rank:Rank,landed:bool,crit:bool,dmg:float,
                          level:int,t:Talents,stats:Stats,cfg:SimConfig,mob:Mob,
                          rng:random.Random):
    # A hostile missile aggroes when it reaches the target even if it misses/resists.
    s.engaged=True
    if s.hp<=0 or not landed:
        combustion_after_hit(s,rank,landed,crit)
        return
    was_rooted=s.t + TIME_EPS < s.root_until
    s.hp-=dmg
    if crit and rank.school=='fire' and t.ignite:
        apply_ignite(s,.08*t.ignite*dmg)
    if was_rooted:
        maybe_break_root(s,dmg,mob,rank.school,cfg,rng)
    if rank.school=='fire' and t.impact and rng.random()<(0.0,.03,.07,.10)[max(0,min(3,int(t.impact)))]:
        s.stun_until=max(s.stun_until,s.t+2.0)
    if rank.spell=='scorch' and t.imp_scorch:
        proc=(1/3,2/3,1.0)[t.imp_scorch-1]
        if rng.random()<proc:
            s.scorch_stacks=min(5,s.scorch_stacks+1)
            s.scorch_until=s.t+30.0
    if rank.spell=='frostbolt':
        s.slow_frac=.40+[0,.04,.07,.10][t.permafrost]
        s.slow_until=s.t+rank.slow_duration+t.permafrost
        if getattr(t,'fingers_of_frost',0) and rng.random()<wh.FINGERS_OF_FROST_CHILL_PROC_CHANCE:
            s.fingers_of_frost_charges=max(1,int(cfg.server_profile.fingers_of_frost_charges))
            s.fingers_of_frost_until=s.t+wh.FINGERS_OF_FROST_DURATION_S
        if getattr(t,'missile_barrage',0) and rng.random()<wh.MISSILE_BARRAGE_OTHER_TRIGGER_PROC_CHANCE:
            s.missile_barrage_until=s.t+wh.MISSILE_BARRAGE_DURATION_S
        if t.winters_chill and rng.random()<.20*t.winters_chill:
            s.wc_stacks=min(5,s.wc_stacks+1)
            s.wc_until=s.t+15.0
        if t.frostbite and rng.random()<wh.FROSTBITE_PROC_CHANCE_PER_RANK*t.frostbite:
            s.root_until=max(s.root_until,s.t+wh.FROSTBITE_ROOT_DURATION_S)
    if rank.spell in ('fireball','pyroblast') and rank.dot_total>0:
        # Attached spell DoTs are one debuff per caster/spell: a new hit
        # refreshes/replaces the same spell's DoT rather than stacking copies.
        s.dots[:] = [d for d in s.dots if d.kind!=rank.spell]
        interval=max(EPS,rank.dot_interval)
        ticks=max(1,int(round(rank.dot_duration/interval)))
        dot_total=((rank.dot_total + stats.spell_power*spell_power_dot_coeff(rank))
                   *direct_mod(rank,t,s)
                   *resistance_damage_multiplier(level,t,cfg,'fire',mob.level))
        periodic_crit=(crit_chance(rank,t,s,stats) if rank.spell in wh.PERIODIC_CAN_CRIT_SPELLS else 0.0)
        s.dots.append(Dot(ticks,s.t+interval,interval,dot_total/ticks,'fire',rank.spell,1,periodic_crit,crit_mult(rank,t)))
    if rank.spell=='arcane_blast' and landed and getattr(t,'missile_barrage',0) and rng.random()<wh.MISSILE_BARRAGE_ARCANE_BLAST_PROC_CHANCE:
        s.missile_barrage_until=s.t+wh.MISSILE_BARRAGE_DURATION_S
    _maybe_grant_hot_streak(s,t,rank.spell,bool(landed and crit))
    combustion_after_hit(s,rank,landed,crit)


def advance_events(s:State,dt:float,level:int,t:Talents,stats:Stats,cfg:SimConfig,
                   mob:Mob,rng:random.Random,metrics:FightMetrics,moving:bool=False,
                   player_speed_away:float=0.0):
    """Advance non-casting time with exact projectile/contact/swing boundaries."""
    rem=dt
    guard=0
    while rem>EPS and s.hp>0 and guard<1000:
        guard+=1
        frozen=s.t + TIME_EPS < s.root_until; stunned=s.t + TIME_EPS < s.stun_until; slowed=s.t + TIME_EPS < s.slow_until
        reach=mob.melee_reach+(cfg.moving_leeway if moving else 0)
        mob_speed=0.0 if (frozen or stunned) else mob.run_speed*((1-s.slow_frac) if slowed else 1.0)
        # A moving player can immediately leave melee only when faster than the
        # target; otherwise contact is preserved.
        if s.in_melee and float(player_speed_away)>mob_speed+EPS:
            s.in_melee=False; s.next_swing=math.inf
        if s.engaged and not s.in_melee:
            closing=mob_speed-float(player_speed_away)
            contact=max(0,s.distance-reach)/closing if closing>EPS else math.inf
        else:
            contact=math.inf
        swing=max(0,s.next_swing-s.t) if s.in_melee and not stunned else math.inf
        proj=min((max(0,p.impact-s.t) for p in s.projectiles),default=math.inf)
        dot=min((max(0,d.next_tick-s.t) for d in s.dots),default=math.inf)
        rootexp=max(0,s.root_until-s.t) if frozen else math.inf
        stunexp=max(0,s.stun_until-s.t) if stunned else math.inf
        slowexp=max(0,s.slow_until-s.t) if slowed else math.inf
        step=min(rem,contact,swing,proj,dot,rootexp,stunexp,slowexp)
        if step<1e-8 and min(contact,swing,proj,dot,rootexp,stunexp,slowexp)==math.inf:
            step=rem
        advance_passive(s,step,level,t,stats,cfg,mob,moving=moving,player_speed_away=player_speed_away,rng=rng)
        rem-=step

        # Projectile impacts scheduled for this exact instant.
        due=[p for p in s.projectiles if p.impact<=s.t+EPS]
        for p in due:
            s.projectiles.remove(p)
            resolve_direct_impact(s,p.rank,p.landed,p.crit,p.damage,level,t,stats,cfg,mob,rng)
            if p.landed:
                maybe_clearcast(s,t,rng,True)
        if s.hp<=0: break

        # Contact creates next_swing==now in advance_passive.
        if s.in_melee and s.next_swing<=s.t+EPS and not (s.t + TIME_EPS < s.stun_until):
            metrics.swings+=1; s.damage_taken_swings+=1
            if not _ice_barrier_absorbs_swing(s,mob,cfg):
                metrics.unabsorbed_swings+=1
            s.next_swing=s.t+mob.swing

        # Avoid zero-time loops on expiry boundaries.
        if step<=EPS and not due and not (s.in_melee and s.next_swing<=s.t+EPS):
            tiny=min(rem,1e-4)
            if tiny>0:
                advance_passive(s,tiny,level,t,stats,cfg,mob,moving=moving,player_speed_away=player_speed_away,rng=rng)
                rem-=tiny

def perform_direct(s:State,rank:Rank,level:int,t:Talents,stats:Stats,cfg:SimConfig,mob:Mob,rng:random.Random,metrics:FightMetrics):
    if s.distance > effective_range(rank,t) + EPS:
        return False
    if rank.spell=='arcane_blast':
        stacks=s.arcane_blast_stacks if s.t + TIME_EPS < s.arcane_blast_until else 0
        c=stats.base_mana*wh.ARCANE_BLAST_BASE_MANA_PCT*(1.0+wh.ARCANE_BLAST_MANA_COST_INCREASE_PER_STACK*stacks)
    else:
        c=mana_cost(rank,t,stats)
    free=s.clearcasting
    if free: s.clearcasting=False; c=0
    if s.mana+EPS<c: return False
    maybe_activate_combustion(s,t,rank)
    cast=rank.cast
    if rank.spell=='frostbolt': cast=max(0.5,cast-.1*t.imp_frostbolt)
    if rank.spell=='fireball': cast=max(0.5,cast-.1*t.imp_fireball)
    if rank.spell=='pyroblast' and t.hot_streak:
        hs=_hot_streak_effect(t)
        stacks=_hot_streak_active_stacks(s)
        if hs is not None and stacks>0:
            cast=max(GCD,cast*(1.0-float(hs.base_value or 0.0)*stacks))

    pb_hits=0; rem=cast
    while rem>EPS and s.hp>0:
        frozen=s.t + TIME_EPS < s.root_until; stunned=s.t + TIME_EPS < s.stun_until; slowed=s.t + TIME_EPS < s.slow_until
        if s.engaged and not s.in_melee and not frozen and not stunned:
            speed=mob.run_speed*((1-s.slow_frac) if slowed else 1)
            contact=max(0,s.distance-mob.melee_reach)/speed if speed>0 else math.inf
        else: contact=math.inf
        swing=max(0,s.next_swing-s.t) if s.in_melee and not stunned else math.inf
        proj=min((max(0,p.impact-s.t) for p in s.projectiles),default=math.inf)
        dot=min((max(0,d.next_tick-s.t) for d in s.dots),default=math.inf)
        rootexp=max(0,s.root_until-s.t) if frozen else math.inf
        stunexp=max(0,s.stun_until-s.t) if stunned else math.inf
        slowexp=max(0,s.slow_until-s.t) if slowed else math.inf
        dt=min(rem,contact,swing,proj,dot,rootexp,stunexp,slowexp)
        advance_passive(s,dt,level,t,stats,cfg,mob,rng=rng); rem-=dt

        # resolve any missiles that land while we're casting
        due=[p for p in s.projectiles if p.impact<=s.t+EPS]
        for p in due:
            s.projectiles.remove(p)
            resolve_direct_impact(s,p.rank,p.landed,p.crit,p.damage,level,t,stats,cfg,mob,rng)
            if p.landed: maybe_clearcast(s,t,rng,True)
        if s.hp<=0: break
        if rem<=EPS: break

        if s.in_melee and s.next_swing<=s.t+EPS and not stunned:
            metrics.swings+=1; s.damage_taken_swings+=1
            barrier_protected=_ice_barrier_absorbs_swing(s,mob,cfg)
            if not barrier_protected:
                metrics.unabsorbed_swings+=1
            resist_pb = barrier_protected or (rank.school=='fire' and rng.random()<(0.0,.23,.47,.70)[max(0,min(3,int(t.burning_soul)))])
            if not resist_pb:
                pb=PUSHBACK_SEQ[pb_hits] if pb_hits<len(PUSHBACK_SEQ) else .2
                pb_hits+=1; rem+=pb; metrics.pushback+=pb; s.total_pushback+=pb
            s.next_swing=s.t+mob.swing
            continue
        # otherwise an expiry/contact/projectile event; continue
    if s.hp<=0:
        return True

    spend(s,c); metrics.mana_spent+=c

    # Roll hit/crit at cast completion (matching wowsims snapshot), but apply
    # damage/control at projectile impact for FBo/FBa.
    landed=rng.random()<spell_hit(level,mob.level,rank.school,t)
    resist_mult=roll_magic_resistance_multiplier(level,mob.level,rank.school,rank.spell,t,cfg,rng) if landed else 0.0
    if landed and resist_mult<=0.0: landed=False
    crit=False; dmg=0.0
    if landed:
        base=rng.uniform(rank.dmin,rank.dmax) + stats.spell_power*spell_power_direct_coeff(rank,cfg.server_profile)
        dmg=(base*direct_mod(rank,t,s)*resist_mult)
        crit=rng.random()<crit_chance(rank,t,s,stats)
        if crit:
            dmg*=crit_mult(rank,t)
            if rank.school=='fire' and t.ignite:
                total=.08*t.ignite*dmg
                # Ignite begins on impact for missiles; attach below for missile
                # via a tiny synthetic dot at impact in resolve path not yet ideal.
            if rank.school in ('fire','frost') and t.master_elements:
                s.mana=min(s.max_mana,s.mana+rank.mana*.10*t.master_elements)

    # Forever Arcane Blast stacks buff the next non-AB spell and that spell
    # clears the stack state. Damage above snapshots the bonus first.
    if rank.spell!='arcane_blast' and s.arcane_blast_stacks and s.t + TIME_EPS < s.arcane_blast_until:
        _clear_arcane_blast_stacks(s)
    # Hot Streak's buff consumption is server-scripted on Wowhead; current
    # Forever guide behavior uses Pyroblast as the stack spender. Keep this as
    # an explicit simulator override rather than generic source truth.
    if rank.spell=='pyroblast' and t.hot_streak and _hot_streak_active_stacks(s):
        s.hot_streak_stacks=0; s.hot_streak_until=-1e9

    s.engaged = s.engaged or (rank.missile_speed<=0)
    if rank.missile_speed>0:
        travel=max(5.0,s.distance)/rank.missile_speed
        s.projectiles.append(Projectile(s.t+travel,rank,landed,crit,dmg,s.t + TIME_EPS < s.root_until))
        # Hostile projectile does not make the mob move until impact in this model.
    else:
        resolve_direct_impact(s,rank,landed,crit,dmg,level,t,stats,cfg,mob,rng)
        s.engaged=True
        maybe_clearcast(s,t,rng,landed)

    # Fire Ignite from projectile crit needs to start at impact. Store it as a
    # zero-delay side effect by encoding into damage resolution below is omitted
    # for now; direct non-projectile Fire crits still handled elsewhere.
    if rank.spell=='arcane_blast':
        old_stacks=s.arcane_blast_stacks if s.t + TIME_EPS < s.arcane_blast_until else 0
        s.arcane_blast_stacks=min(wh.ARCANE_BLAST_MAX_STACKS,old_stacks+1)
        s.arcane_blast_until=s.t+wh.ARCANE_BLAST_STACK_DURATION_S
    metrics.casts[rank.spell]=metrics.casts.get(rank.spell,0)+1
    return True

def perform_instant_damage(s:State,rank:Rank,level:int,t:Talents,stats:Stats,cfg:SimConfig,mob:Mob,rng:random.Random,metrics:FightMetrics, *, moving_away:bool=False):
    c=mana_cost(rank,t,stats); free=s.clearcasting
    if free:s.clearcasting=False;c=0
    if s.mana+EPS<c:return False
    maybe_activate_combustion(s,t,rank)
    spend(s,c);metrics.mana_spent+=c
    was_rooted=s.t + TIME_EPS < s.root_until
    landed=rng.random()<spell_hit(level,mob.level,rank.school,t)
    resist_mult=roll_magic_resistance_multiplier(level,mob.level,rank.school,rank.spell,t,cfg,rng) if landed else 0.0
    if landed and resist_mult<=0.0: landed=False
    if landed:
        base=rng.uniform(rank.dmin,rank.dmax) + stats.spell_power*spell_power_direct_coeff(rank,cfg.server_profile)
        frozen=(s.t + TIME_EPS < s.root_until) or (rank.spell=='ice_lance' and s.fingers_of_frost_charges>0 and s.t + TIME_EPS < s.fingers_of_frost_until)
        dmg=(base*direct_mod(rank,t,s)*resist_mult)
        if rank.spell=='ice_lance' and frozen:
            dmg*=ice_lance_frozen_multiplier(cfg.server_profile)
        crit=rng.random()<crit_chance(rank,t,s,stats)
        if crit:
            dmg*=crit_mult(rank,t)
            if rank.school=='fire' and t.ignite:
                apply_ignite(s,.08*t.ignite*dmg)
            if rank.school in ('fire','frost') and t.master_elements:
                s.mana=min(s.max_mana,s.mana+rank.mana*.10*t.master_elements)
        s.hp-=dmg
        if was_rooted:
            maybe_break_root(s,dmg,mob,rank.school,cfg,rng)
        if rank.school=='fire' and t.impact and rng.random()<(0.0,.03,.07,.10)[max(0,min(3,int(t.impact)))]:
            s.stun_until=max(s.stun_until,s.t+2.0)
    if rank.spell=='ice_lance' and s.fingers_of_frost_charges>0 and s.t + TIME_EPS < s.fingers_of_frost_until:
        s.fingers_of_frost_charges=max(0,s.fingers_of_frost_charges-1)
        if not s.fingers_of_frost_charges:
            s.fingers_of_frost_until=-1e9
    _maybe_grant_hot_streak(s,t,rank.spell,bool(landed and crit))
    combustion_after_hit(s,rank,landed,crit if landed else False)
    if rank.spell!='arcane_blast' and s.arcane_blast_stacks and s.t + TIME_EPS < s.arcane_blast_until:
        _clear_arcane_blast_stacks(s)
    s.engaged=True
    maybe_clearcast(s,t,rng,landed)
    cd=rank.cooldown
    if rank.spell=='fire_blast':
        cd=max(1,cd-1.0*t.wake_of_fire);s.fireblast_ready=s.t+cd
    metrics.casts[rank.spell]=metrics.casts.get(rank.spell,0)+1
    advance_events(s,GCD,level,t,stats,cfg,mob,rng,metrics,moving=moving_away,player_speed_away=(7.0 if moving_away else 0.0))
    return True


def perform_nova(s:State,rank:Rank,level:int,t:Talents,stats:Stats,cfg:SimConfig,mob:Mob,rng:random.Random,metrics:FightMetrics):
    c=mana_cost(rank,t,stats);free=s.clearcasting
    if free:s.clearcasting=False;c=0
    if s.mana+EPS<c or s.t+EPS<s.nova_ready or s.distance>rank.radius*(1+.1*t.arctic_reach):return False
    spend(s,c);metrics.mana_spent+=c
    landed=rng.random()<spell_hit(level,mob.level,'frost',t)
    resist_mult=roll_magic_resistance_multiplier(level,mob.level,'frost','frost_nova',t,cfg,rng) if landed else 0.0
    if landed and resist_mult<=0.0: landed=False
    if landed:
        base=rng.uniform(rank.dmin,rank.dmax) + stats.spell_power*spell_power_direct_coeff(rank,cfg.server_profile)
        frozen=(s.t + TIME_EPS < s.root_until) or (rank.spell=='ice_lance' and s.fingers_of_frost_charges>0 and s.t + TIME_EPS < s.fingers_of_frost_until)
        dmg=(base*direct_mod(rank,t,s)*resist_mult)
        if rank.spell=='ice_lance' and frozen:
            dmg*=ice_lance_frozen_multiplier(cfg.server_profile)
        crit=rng.random()<crit_chance(rank,t,s,stats)
        if crit:
            dmg*=crit_mult(rank,t)
        s.hp-=dmg
        s.root_until=s.t+rank.root_duration
    s.engaged=True
    maybe_clearcast(s,t,rng,landed)
    s.nova_ready=s.t+max(0,rank.cooldown-2*t.imp_frost_nova)
    metrics.casts['frost_nova']=metrics.casts.get('frost_nova',0)+1
    advance_events(s,GCD,level,t,stats,cfg,mob,rng,metrics)
    return True


def perform_blink(s:State,level:int,t:Talents,stats:Stats,cfg:SimConfig,mob:Mob,rng:random.Random,metrics:FightMetrics):
    cost=.35*stats.base_mana
    if s.mana+EPS<cost or level<20 or s.t+EPS<s.blink_ready:return False
    spend(s,cost);metrics.mana_spent+=cost
    s.distance+=20;s.in_melee=False;s.next_swing=math.inf;s.blink_ready=s.t+15
    metrics.casts['blink']=metrics.casts.get('blink',0)+1
    advance_events(s,GCD,level,t,stats,cfg,mob,rng,metrics)
    return True


def perform_move(s:State,yards:float,level:int,t:Talents,stats:Stats,cfg:SimConfig,mob:Mob,rng:random.Random,metrics:FightMetrics):
    # Explicit away movement at normal player run speed. The event kernel owns
    # relative target movement; do not pre-adjust distance and then move the mob
    # again (the old implementation effectively double-counted closing).
    if yards<=0:return True
    dur=yards/7.0
    metrics.casts['move']=metrics.casts.get('move',0)+1
    advance_events(s,dur,level,t,stats,cfg,mob,rng,metrics,moving=True,player_speed_away=7.0)
    return True


def perform_am(s:State,rank:Rank,level:int,t:Talents,stats:Stats,cfg:SimConfig,mob:Mob,rng:random.Random,metrics:FightMetrics):
    barrage=bool(getattr(t,'missile_barrage',0) and s.t + TIME_EPS < s.missile_barrage_until)
    ab_stacks=s.arcane_blast_stacks if s.t + TIME_EPS < s.arcane_blast_until else 0
    ab_mult=1.0 + wh.ARCANE_BLAST_OTHER_SPELL_DAMAGE_BONUS_PER_STACK*ab_stacks
    if ab_stacks:
        _clear_arcane_blast_stacks(s)
    c=0.0 if barrage else rank.mana;free=s.clearcasting
    if free:s.clearcasting=False;c=0
    tick_duration=wh.MISSILE_BARRAGE_MISSILE_INTERVAL_S if barrage else 1.0
    if s.mana+EPS<c:return False
    spend(s,c);metrics.mana_spent+=c
    landed_once=False
    s.engaged=True  # channel begins doing hostile work immediately in this approximation

    for _ in range(rank.channel_ticks):
        if s.hp<=0:break
        rem=tick_duration; disrupted=False
        while rem>EPS and s.hp>0:
            frozen=s.t + TIME_EPS < s.root_until; stunned=s.t + TIME_EPS < s.stun_until; slowed=s.t + TIME_EPS < s.slow_until
            if s.engaged and not s.in_melee and not frozen and not stunned:
                speed=mob.run_speed*((1-s.slow_frac) if slowed else 1)
                contact=max(0,s.distance-mob.melee_reach)/speed if speed else math.inf
            else:contact=math.inf
            swing=max(0,s.next_swing-s.t) if s.in_melee and not stunned else math.inf
            proj=min((max(0,p.impact-s.t) for p in s.projectiles),default=math.inf)
            dot=min((max(0,d.next_tick-s.t) for d in s.dots),default=math.inf)
            rootexp=max(0,s.root_until-s.t) if frozen else math.inf
            stunexp=max(0,s.stun_until-s.t) if stunned else math.inf
            slowexp=max(0,s.slow_until-s.t) if slowed else math.inf
            dt=min(rem,contact,swing,proj,dot,rootexp,stunexp,slowexp)
            advance_passive(s,dt,level,t,stats,cfg,mob,rng=rng);rem-=dt

            due=[p for p in s.projectiles if p.impact<=s.t+EPS]
            for p in due:
                s.projectiles.remove(p)
                resolve_direct_impact(s,p.rank,p.landed,p.crit,p.damage,level,t,stats,cfg,mob,rng)
                if p.landed:maybe_clearcast(s,t,rng,True)
            if s.hp<=0: break
            if rem<=EPS:break

            if s.in_melee and s.next_swing<=s.t+EPS and not stunned:
                metrics.swings+=1;s.damage_taken_swings+=1
                protected=_ice_barrier_absorbs_swing(s,mob,cfg)
                if not protected:
                    metrics.unabsorbed_swings+=1
                if not protected:
                    protected=rng.random()<.20*t.imp_arcane_missiles
                s.next_swing=s.t+mob.swing
                if not protected:disrupted=True
                continue

        if s.hp<=0:break
        if not disrupted and rng.random()<spell_hit(level,mob.level,'arcane',t):
            landed_once=True
            resist_mult=roll_magic_resistance_multiplier(level,mob.level,'arcane','arcane_missiles',t,cfg,rng)
            if resist_mult<=0.0:
                continue
            dmg=((rank.channel_tick_damage + stats.spell_power*wh.ARCANE_MISSILES_SP_COEFF_PER_TICK)
                 *(1+.01*t.arcane_instability)*ab_mult*resist_mult)
            if rng.random()<stats.spell_crit: dmg*=1.5
            was_rooted=s.t + TIME_EPS < s.root_until
            s.hp-=dmg
            if was_rooted:maybe_break_root(s,dmg,mob,'arcane',cfg,rng)

    if barrage:
        s.missile_barrage_until=-1e9
    maybe_clearcast(s,t,rng,landed_once)
    metrics.casts['arcane_missiles']=metrics.casts.get('arcane_missiles',0)+1
    return True

# -------------------------- policy/search layer ----------------------------
# Kept as a compatibility facade: external callers historically import these
# names from ``mage.engine``.  The implementation now lives in ``mage.policy``
# so the combat kernel remains reviewable instead of growing as one 3k-line file.
from .policy import (
    Policy,
    policy_spell_usage,
    talent_directly_affects_policy,
    choose_action,
    _wand_resistance_multiplier,
    _mana_wait_seconds,
    _required_mana,
    perform_wand_fallback,
    perform_wand_finisher,
    simulate_fight,
    _mage_player_hp_and_armor,
    recovery_time,
    simulate_chain_incremental,
    simulate_chain,
    with_ice_barrier_policy_variants,
    candidate_policies,
    candidate_fire_cadence_policies,
    candidate_policies_coarse,
    policy_legal_for_talents,
    guide_meta_policy,
    _focused_policy_family,
    candidate_policies_for_build,
    _policy_result_summary,
    policy_ab,
    policy_search,
    talent_value,
    optimize_policy,
    PathState,
    talent_key,
    talent_preference_key,
    _structural_progress_key,
    _retain_structural_frontiers,
    talent_candidates,
    optimize_talent_path,
    optimize_talent_paths,
    final_allocation,
    policy_desc,
)

def write_coarse_reports(paths:List[PathState],prefix:str='/mnt/data/mage_11_60'):
    import csv
    from pathlib import Path
    top_path=Path(prefix+'_top_builds.csv')
    rot_path=Path(prefix+'_winner_rotations.csv')
    with top_path.open('w',newline='') as f:
        w=csv.writer(f)
        w.writerow(['rank','normalized_hours_100_mobs_per_level','final_allocation'])
        for i,p in enumerate(paths,1):
            w.writerow([i,p.cumulative_s/3600,final_allocation(p.talents)])
    winner=paths[0]
    with rot_path.open('w',newline='') as f:
        w=csv.writer(f)
        w.writerow(['level','talent_point','policy','rotation','normalized_min_per_100'])
        for lvl,name,pol,score in winner.path:
            if lvl>=11:
                w.writerow([lvl,name,pol.name,policy_desc(pol,lvl),score/60])
    return str(top_path),str(rot_path)

def validate_path(path:PathState,cfg:SimConfig,mobs_per_level:int=100,seed:int=123)->List[Tuple[int,str,Policy,Dict[str,float]]]:
    """Re-optimize policy and rescore every level along one fixed talent path."""
    out=[];t=Talents()
    for lvl,name,_,_ in path.path:
        t=add_point(t,name)
        if lvl<11: continue
        pol,res=optimize_policy(lvl,t,cfg,n=mobs_per_level,seed=seed+lvl*104729)
        out.append((lvl,name,pol,res))
    return out


def school_isolation_selftest():
    """Deterministic checks that school-specific talents cannot leak across schools."""
    st=Stats(100,100,1000,2000,.10)
    fba=latest(FIREBALL,30)
    fbo=latest(FROSTBOLT,30)
    base=Talents()
    assert abs(mana_cost(fba,replace(base,frost_channeling=3),st)-mana_cost(fba,base,st)) < 1e-12
    assert abs(crit_mult(fba,replace(base,ice_shards=5))-1.5) < 1e-12
    assert abs(crit_mult(fbo,replace(base,ice_shards=5))-2.0) < 1e-12
    # Cast-time reducers are spell-name scoped in perform_direct; verify source-level helpers by formula.
    assert abs(max(.5,fba.cast-.1*5) - (fba.cast-.5)) < 1e-12
    assert abs(max(.5,fbo.cast-.1*5) - (fbo.cast-.5)) < 1e-12
    assert abs(effective_range(fba,replace(base,flame_throwing=2))-(fba.range+6.0)) < 1e-12
    assert abs(effective_range(fbo,replace(base,arctic_reach=2))-(fbo.range*1.20)) < 1e-12
    assert len(candidate_policies(60))==len({tuple(getattr(p,f) for f in p.__dataclass_fields__ if f!='name') for p in candidate_policies(60)})
    return True

# ----------------------------- smoke CLI ----------------------------------

def screenshot_build()->Talents:
    return Talents(imp_frostbolt=5,elemental_precision=2,frostbite=2,permafrost=3,piercing_ice=3,arctic_reach=2)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--level',type=int,default=26)
    ap.add_argument('--mobs',type=int,default=40)
    ap.add_argument('--self-water',action='store_true')
    ap.add_argument('--owl',type=float,default=1.0)
    ap.add_argument('--seed',type=int,default=7)
    ap.add_argument('--root-break',choices=['scaled','first','never'],default='scaled')
    ap.add_argument('--optimize-11-60',action='store_true')
    ap.add_argument('--beam',type=int,default=8)
    ap.add_argument('--top',type=int,default=5)
    ap.add_argument('--report-prefix',type=str,default='/mnt/data/mage_11_60')
    a=ap.parse_args()
    cfg=SimConfig(use_best_water=not a.self_water,owl_intensity=a.owl,seed=a.seed,root_break_mode=a.root_break)
    if a.optimize_11_60:
        school_isolation_selftest()
        mplevel=max(4,min(12,a.mobs))
        paths=optimize_talent_paths(11,60,cfg,beam_width=a.beam,mobs_per_level=mplevel,seed=a.seed,top_k=a.top)
        print(f'Coarse optimized 11-60 paths, beam={a.beam}, mobs/level={mplevel}, root={a.root_break}')
        print('TOP BUILDS (coarse beam ranking):')
        for i,pth in enumerate(paths,1):
            print(f'#{i}: {pth.cumulative_s/3600:.2f} h normalized | {final_allocation(pth.talents)}')
        winner=paths[0]
        print('\nWINNER TALENT PATH + USED POLICY:')
        lastrot=None
        for lvl,name,pol,score in winner.path:
            if lvl>=11:
                rot=policy_desc(pol,lvl)
                changed=' *ROT*' if rot!=lastrot else ''
                print(f'{lvl:2d}: {name:22s} | {rot:55s} | {score/60:7.2f} min/100{changed}')
                lastrot=rot
        topcsv,rotcsv=write_coarse_reports(paths,a.report_prefix)
        print(f'\nReports: {topcsv} ; {rotcsv}')
        return
    tal=screenshot_build() if a.level==26 else Talents(imp_frostbolt=5,elemental_precision=3)
    p,r=optimize_policy(a.level,tal,cfg,n=a.mobs,seed=a.seed)
    st=player_stats(a.level,tal,cfg.owl_intensity)
    print(f'Level {a.level}, points={tal.points()}, Owl={a.owl:.2f}, water={"best usable" if cfg.use_best_water else "self conjured"}')
    print(f'Int={st.intellect:.1f} Spirit={st.spirit:.1f} Mana={st.max_mana:.0f} Crit={100*st.spell_crit:.2f}%')
    print('Best policy:',p)
    print(f'{a.mobs} mobs: total={r["total_s"]/60:.2f} min; combat={r["kill_s"]/60:.2f}; recovery={r["recovery_s"]/60:.2f}; pushback={r["pushback_s"]:.1f}s; swings={r["swings"]:.0f}')
    print('casts:',{k[6:]:v for k,v in r.items() if k.startswith('casts_')})

if __name__=='__main__':main()



# ---------------------- smooth gearing gradient ---------------------------


# -------------------------- analytic stat helpers --------------------------
from .analytic import (
    _analytic_gradient_rank,
    _analytic_gradient_static_crit,
    _analytic_gradient_spell_terms,
    item_budget_units,
    analytic_stat_gradient,
)
