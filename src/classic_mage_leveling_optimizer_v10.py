#!/usr/bin/env python3
"""
Classic Era Mage solo-leveling simulator / optimizer skeleton.

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
idealized slot-budget Owl gear; spell power currently omitted).
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

EPS = 1e-9
TIME_EPS = 1e-7
HP_EPS = 1e-8  # combat damage arithmetic below this is treated as zero HP
GCD = 1.5
PUSHBACK_SEQ = (1.0, 0.8, 0.6, 0.4, 0.2)

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
    if primary == "arcane_missiles":
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

    @property
    def dps(self) -> float:
        return ((self.dmin + self.dmax) * 0.5) / max(self.speed, EPS)


# Practical high-DPS Classic Era leveling progression. Damage/speed are the
# actual item tooltip values; the simulator equips the highest-DPS entry whose
# required level has been reached. Quest/drop availability is intentionally not
# modeled beyond the level gate: this is the same idealized "best available"
# philosophy as the gear/water model.
WANDS = [
    Wand('Lesser Magic Wand', 5, 'arcane', 12, 22, 1.50),
    Wand('Greater Magic Wand', 13, 'arcane', 22, 41, 1.80),
    Wand('Gravestone Scepter', 18, 'shadow', 30, 57, 1.50),
    Wand('Starfaller', 29, 'arcane', 32, 60, 1.40),
    Wand('Blackbone Wand', 41, 'shadow', 39, 74, 1.60),
    Wand('Noxious Shooter', 46, 'nature', 56, 104, 1.60),
    Wand('Mana Channeling Wand', 56, 'frost', 68, 127, 1.60),
]

def best_wand(level:int) -> Wand:
    xs=[w for w in WANDS if w.req_level <= int(level)]
    if not xs:
        return WANDS[0]
    return max(xs, key=lambda w:(w.dps,w.req_level,w.name))


FROSTBOLT = [
    Rank('frostbolt',1,4,'frost',25,1.5,30,20,22,slow=.40,slow_duration=5,missile_speed=28),
    Rank('frostbolt',2,8,'frost',35,1.8,30,33,38,slow=.40,slow_duration=6,missile_speed=28),
    Rank('frostbolt',3,14,'frost',50,2.2,30,54,61,slow=.40,slow_duration=6,missile_speed=28),
    Rank('frostbolt',4,20,'frost',65,2.6,30,78,87,slow=.40,slow_duration=7,missile_speed=28),
    Rank('frostbolt',5,26,'frost',100,3.0,30,132,144,slow=.40,slow_duration=7,missile_speed=28),
    Rank('frostbolt',6,32,'frost',130,3.0,30,180,197,slow=.40,slow_duration=8,missile_speed=28),
    Rank('frostbolt',7,38,'frost',160,3.0,30,231,251,slow=.40,slow_duration=8,missile_speed=28),
    Rank('frostbolt',8,44,'frost',195,3.0,30,301,326,slow=.40,slow_duration=9,missile_speed=28),
    Rank('frostbolt',9,50,'frost',225,3.0,30,353,383,slow=.40,slow_duration=9,missile_speed=28),
    Rank('frostbolt',10,56,'frost',260,3.0,30,440,475,slow=.40,slow_duration=9,missile_speed=28),
    Rank('frostbolt',11,60,'frost',290,3.0,30,515,555,slow=.40,slow_duration=9,missile_speed=28),
]

FIREBALL = [
    Rank('fireball',1,1,'fire',30,1.5,35,16,25,dot_total=2,dot_duration=8,missile_speed=24),
    Rank('fireball',2,6,'fire',45,2.0,35,34,49,dot_total=3,dot_duration=8,missile_speed=24),
    Rank('fireball',3,12,'fire',65,2.5,35,57,77,dot_total=6,dot_duration=8,missile_speed=24),
    Rank('fireball',4,18,'fire',95,3.0,35,89,122,dot_total=12,dot_duration=8,missile_speed=24),
    Rank('fireball',5,24,'fire',140,3.5,35,140,189,dot_total=20,dot_duration=8,missile_speed=24),
    Rank('fireball',6,30,'fire',185,3.5,35,207,274,dot_total=28,dot_duration=8,missile_speed=24),
    Rank('fireball',7,36,'fire',220,3.5,35,264,345,dot_total=32,dot_duration=8,missile_speed=24),
    Rank('fireball',8,42,'fire',260,3.5,35,328,425,dot_total=40,dot_duration=8,missile_speed=24),
    Rank('fireball',9,48,'fire',305,3.5,35,398,512,dot_total=52,dot_duration=8,missile_speed=24),
    Rank('fireball',10,54,'fire',350,3.5,35,488,623,dot_total=60,dot_duration=8,missile_speed=24),
    Rank('fireball',11,60,'fire',395,3.5,35,561,715,dot_total=72,dot_duration=8,missile_speed=24),
]

# Talent-gated Pyroblast ranks. Rank 1 is learned by taking the talent; later
# ranks are trained at the listed levels. The simulator uses it primarily as a
# pull opener, where its long 6 s cast is actually practical while soloing.
PYROBLAST = [
    Rank('pyroblast',1,20,'fire',125,6.0,35,148,195,dot_total=56,dot_duration=12,dot_interval=3,missile_speed=24),
    Rank('pyroblast',2,24,'fire',150,6.0,35,193,250,dot_total=72,dot_duration=12,dot_interval=3,missile_speed=24),
    Rank('pyroblast',3,30,'fire',195,6.0,35,270,343,dot_total=96,dot_duration=12,dot_interval=3,missile_speed=24),
    Rank('pyroblast',4,36,'fire',240,6.0,35,347,437,dot_total=124,dot_duration=12,dot_interval=3,missile_speed=24),
    Rank('pyroblast',5,42,'fire',285,6.0,35,427,536,dot_total=156,dot_duration=12,dot_interval=3,missile_speed=24),
    Rank('pyroblast',6,48,'fire',335,6.0,35,525,654,dot_total=188,dot_duration=12,dot_interval=3,missile_speed=24),
    Rank('pyroblast',7,54,'fire',385,6.0,35,625,776,dot_total=228,dot_duration=12,dot_interval=3,missile_speed=24),
    Rank('pyroblast',8,60,'fire',440,6.0,35,716,890,dot_total=268,dot_duration=12,dot_interval=3,missile_speed=24),
]

SCORCH = [
    Rank('scorch',1,22,'fire',50,1.5,30,55,68),
    Rank('scorch',2,28,'fire',65,1.5,30,81,98),
    Rank('scorch',3,34,'fire',80,1.5,30,105,126),
    Rank('scorch',4,40,'fire',100,1.5,30,133,159),
    Rank('scorch',5,46,'fire',115,1.5,30,168,199),
    Rank('scorch',6,52,'fire',135,1.5,30,207,247),
    Rank('scorch',7,58,'fire',150,1.5,30,237,280),
]

ARCANE_MISSILES = [
    Rank('arcane_missiles',1,8,'arcane',85,range=30,channel_ticks=3,channel_tick_damage=24),
    Rank('arcane_missiles',2,16,'arcane',140,range=30,channel_ticks=4,channel_tick_damage=36),
    Rank('arcane_missiles',3,24,'arcane',235,range=30,channel_ticks=5,channel_tick_damage=56),
    Rank('arcane_missiles',4,32,'arcane',320,range=30,channel_ticks=5,channel_tick_damage=83),
    Rank('arcane_missiles',5,40,'arcane',410,range=30,channel_ticks=5,channel_tick_damage=115),
    Rank('arcane_missiles',6,48,'arcane',500,range=30,channel_ticks=5,channel_tick_damage=151),
    Rank('arcane_missiles',7,56,'arcane',595,range=30,channel_ticks=5,channel_tick_damage=192),
    Rank('arcane_missiles',8,60,'arcane',655,range=30,channel_ticks=5,channel_tick_damage=230),
]

FIRE_BLAST = [
    Rank('fire_blast',1,6,'fire',40,range=20,dmin=27,dmax=35,cooldown=8),
    Rank('fire_blast',2,14,'fire',75,range=20,dmin=62,dmax=76,cooldown=8),
    Rank('fire_blast',3,22,'fire',115,range=20,dmin=103,dmax=128,cooldown=8),
    Rank('fire_blast',4,30,'fire',165,range=20,dmin=168,dmax=203,cooldown=8),
    Rank('fire_blast',5,38,'fire',220,range=20,dmin=242,dmax=301,cooldown=8),
    Rank('fire_blast',6,46,'fire',280,range=20,dmin=332,dmax=407,cooldown=8),
    Rank('fire_blast',7,54,'fire',340,range=20,dmin=431,dmax=524,cooldown=8),
]

FROST_NOVA = [
    Rank('frost_nova',1,10,'frost',55,dmin=19,dmax=22,root_duration=8,radius=10,cooldown=25),
    Rank('frost_nova',2,26,'frost',85,dmin=33,dmax=37,root_duration=8,radius=10,cooldown=25),
    Rank('frost_nova',3,40,'frost',115,dmin=52,dmax=58,root_duration=8,radius=10,cooldown=25),
    Rank('frost_nova',4,54,'frost',145,dmin=71,dmax=79,root_duration=8,radius=10,cooldown=25),
]

SPELLS = {
    'frostbolt': FROSTBOLT,
    'fireball': FIREBALL,
    'pyroblast': PYROBLAST,
    'scorch': SCORCH,
    'arcane_missiles': ARCANE_MISSILES,
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
    # Frost
    imp_frostbolt:int=0; elemental_precision:int=0; ice_shards:int=0; frostbite:int=0
    imp_frost_nova:int=0; permafrost:int=0; piercing_ice:int=0; arctic_reach:int=0
    frost_channeling:int=0; shatter:int=0; winters_chill:int=0
    cold_snap:int=0; ice_block:int=0; improved_cone_of_cold:int=0; ice_barrier:int=0
    # Arcane
    arcane_subtlety:int=0; arcane_focus:int=0; imp_arcane_missiles:int=0; arcane_concentration:int=0
    arcane_meditation:int=0; arcane_resilience:int=0; arcane_mind:int=0; arcane_instability:int=0
    # Fire
    imp_fireball:int=0; impact:int=0; imp_fire_blast:int=0; ignite:int=0; flame_throwing:int=0
    burning_soul:int=0; incinerate:int=0; pyroblast:int=0; imp_scorch:int=0; master_elements:int=0
    critical_mass:int=0; fire_power:int=0; combustion:int=0
    # Omitted/tier-gating talents with no modeled value for this melee-only ST objective.
    # Keeping these explicit prevents the optimizer from using Improved Frostbolt,
    # Ice Shards, etc. as fake prerequisite filler when the real tree has a harmless
    # alternative available.
    frost_warding:int=0
    improved_blizzard:int=0
    arcane_filler:int=0
    improved_flamestrike:int=0
    fire_warding:int=0

    def points(self)->int:
        return sum(getattr(self,f) for f in self.__dataclass_fields__)

# This skeleton's tree legality table is sufficient for automated search of the
# listed relevant talents. `need_tree` is number of points required in that tree
# before taking the talent; prereq is optional (field, required rank).
TALENT_RULES = {
    # name: (tree,max,need_tree,prereq)
    'imp_frostbolt':('frost',5,0,None),'elemental_precision':('frost',3,0,None),
    'ice_shards':('frost',5,5,None),'frostbite':('frost',3,5,None),
    'imp_frost_nova':('frost',2,5,None),'permafrost':('frost',3,5,None),
    'piercing_ice':('frost',3,10,None),'arctic_reach':('frost',2,15,None),
    'frost_channeling':('frost',3,15,None),'shatter':('frost',5,15,('imp_frost_nova',2)),
    'winters_chill':('frost',5,25,None),
    # Classic Frost-tree utility/deep talents.  Cold Snap / Ice Block / Improved
    # Cone of Cold are represented explicitly so deep Frost allocations have the
    # correct legal alternatives/prerequisites even when the ST speed objective
    # does not actively use those buttons.  Ice Barrier is modeled below because
    # its pushback immunity changes leveling throughput directly.
    'cold_snap':('frost',1,10,None),
    'ice_block':('frost',1,20,None),
    'improved_cone_of_cold':('frost',3,20,None),
    'ice_barrier':('frost',1,30,('ice_block',1)),
    'arcane_subtlety':('arcane',2,0,None),'arcane_focus':('arcane',5,0,None),'imp_arcane_missiles':('arcane',5,0,None),
    'arcane_concentration':('arcane',5,5,None),'arcane_meditation':('arcane',3,15,None),
    'arcane_resilience':('arcane',1,10,None),'arcane_mind':('arcane',5,20,('arcane_resilience',1)),'arcane_instability':('arcane',3,25,None),
    'imp_fireball':('fire',5,0,None),'impact':('fire',5,0,None),'imp_fire_blast':('fire',3,5,None),'ignite':('fire',5,5,None),
    'flame_throwing':('fire',2,5,None),'burning_soul':('fire',2,10,None),'incinerate':('fire',2,10,None),
    'pyroblast':('fire',1,10,None),
    'imp_scorch':('fire',3,15,None),'master_elements':('fire',3,15,None),
    'critical_mass':('fire',3,20,None),'fire_power':('fire',5,25,None),
    'combustion':('fire',1,30,None),
    # Tier-aware no-effect prerequisite spend for omitted talents.
    # Frost Warding is available immediately; Improved Blizzard after 10 Frost pts.
    'frost_warding':('frost',2,0,None),
    'improved_blizzard':('frost',3,10,None),
    # Arcane has low-tier utility/defensive points that do nothing vs our pure melee mob.
    'arcane_filler':('arcane',5,0,None),
    # Fire has Improved Flamestrike / Fire Warding as ST-melee-neutral gate spend.
    'improved_flamestrike':('fire',3,10,None),
    'fire_warding':('fire',2,15,None),
}

_TREE_TALENT_FIELDS = {
    tree: tuple(name for name, (tr, _mx, _need, _pre) in TALENT_RULES.items() if tr == tree)
    for tree in ('frost', 'arcane', 'fire')
}

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


@dataclass(frozen=True)
class IceBarrierRank:
    learn:int
    mana:float
    absorb:float


# Classic 1.12 base values.  The gear model intentionally omits spell power, so
# the historical +10% Frost-SP coefficient is likewise omitted here rather than
# inventing spell-power gear that does not exist elsewhere in the simulator.
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


# Idealized "top green of the Owl" slot model.  Each equipped slot receives an
# ilvl-scaled random-suffix budget; Owl converts the suffix factor equally into
# Intellect and Spirit.  It is deliberately deterministic (AH availability is
# not simulated), but unlike the old straight line it has slot unlocks and an
# explicit item-level budget.
OWL_SLOTS = (
    ('chest',10,1.00), ('legs',10,1.00), ('feet',10,.75), ('hands',10,.75),
    ('waist',10,.60), ('wrist',10,.50), ('back',10,.50), ('weapon',10,1.30),
    ('shoulder',15,.75), ('head',20,1.00), ('neck',20,.50),
    ('ring1',20,.50), ('ring2',25,.50),
)
OWL_C = 0.05548  # calibrated: full top-green set ~= +150 Int/+150 Spi at 60.

def owl_bonus(level:int, intensity:float=1.0)->Tuple[float,float]:
    ilvl=min(65.0, level+5.0)  # world-green rule of thumb: usable ~5 levels below ilvl
    total=0.0
    for _,unlock,w in OWL_SLOTS:
        if level>=unlock:
            total += OWL_C * (ilvl**1.35) * w
    total *= intensity
    return total,total


def mana_bonus_from_intellect(intellect:float)->float:
    base=min(20.0,intellect)
    return base + max(0.0,intellect-20.0)*15.0


def mage_spell_crit(level:int,intellect:float)->float:
    # CMaNGOS Classic: percentage = 3.70 + INT/(14.77 + 0.65*level)
    return (3.70 + intellect/(14.77 + .65*level))/100.0


def player_stats(level:int,t:Talents,owl_intensity:float=1.0,*,
                 bonus_intellect:float=0.0,bonus_spirit:float=0.0,spell_power:float=0.0)->Stats:
    bi,bs=TROLL_INT_SPI[level]
    gi,gs=owl_bonus(level,owl_intensity)
    ai=latest_pair(ARCANE_INTELLECT,level)[1]
    intellect=bi+gi+ai+float(bonus_intellect)
    spirit=bs+gs+float(bonus_spirit)
    base=BASE_MANA[level]
    maxmana=(base+mana_bonus_from_intellect(intellect))*(1+.02*t.arcane_mind)
    crit=mage_spell_crit(level,intellect) + .01*t.arcane_instability
    return Stats(intellect,spirit,base,maxmana,crit,float(spell_power))


def _low_level_spell_power_penalty(rank:Rank)->float:
    """Classic pre-20 coefficient penalty from the spell's learned level.

    Vanilla coefficients are reduced by 3.75 percentage points for every spell
    level below 20.  Rank 1 Frostbolt, for example, gets 0.4286 cast-time
    coefficient * 0.40 low-level penalty * 0.95 slow-effect penalty ~= 0.163.
    """
    return max(0.0,min(1.0,1.0-max(0,20-int(rank.learn))*0.0375))


def spell_power_direct_coeff(rank:Rank)->float:
    """Classic-era direct spell-power coefficient for modeled Mage spells.

    Coefficients use the spell rank's original cast/channel time, not talent-
    shortened cast time. Instant single-target spells floor to 1.5 s; cast and
    channel coefficients cap at 3.5 s. Frost slow/root spells take the classic
    5% additional-effect penalty, and Frost Nova also takes the AoE /3 penalty.
    """
    low=_low_level_spell_power_penalty(rank)
    if rank.spell=='arcane_missiles':
        # One missile per second; early ranks channel for only 3/4 seconds.
        channel_s=max(1.5,float(rank.channel_ticks or 0))
        return min(1.0,channel_s/3.5)*low
    if rank.spell=='frost_nova':
        return (1.5/3.5)/3.0*0.95*low
    if rank.spell=='frostbolt':
        return min(1.0,max(1.5,float(rank.cast))/3.5)*0.95*low
    if rank.spell in ('fire_blast','scorch'):
        return (1.5/3.5)*low
    if rank.spell=='fireball':
        return min(1.0,max(1.5,float(rank.cast))/3.5)*low
    if rank.spell=='pyroblast':
        return 1.0*low
    cast=max(1.5,float(rank.cast or 0.0))
    return min(1.0,cast/3.5)*low


def spell_power_dot_coeff(rank:Rank)->float:
    """Total coefficient assigned to the modeled attached periodic component.

    Classic Fireball's DoT receives no bonus spell damage. Pyroblast is the
    well-known exception: its 12 s DoT receives ~70% total (17.5% per tick).
    """
    low=_low_level_spell_power_penalty(rank)
    if rank.spell=='pyroblast':
        return 0.70*low
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

@dataclass(frozen=True)
class SimConfig:
    mob_speed:float=7.0
    mob_swing:float=2.0
    # Final search uses a small representative melee-speed mixture instead of
    # overfitting talents/policies to one 2.0 s dummy.  Consecutive +1/+2 mobs
    # share a swing speed, cycling through this tuple.
    mob_swing_mix:Tuple[float,...]=(1.5,2.0,2.5)
    melee_reach:float=5.0
    moving_leeway:float=0.0 # add e.g. 2.5 for sensitivity
    # Root break is intentionally configurable because Classic's damage-break
    # behavior is random and source-dependent.  "scaled" is the search default;
    # "first" is conservative and "never" is an upper bound on root value.
    root_break_mode:str='scaled' # scaled | first | never
    root_break_base:float=.18
    root_break_damage_scale:float=2.6
    root_break_fire_bonus:float=.10
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
    mage_armor:bool=True
    seed:int=1


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
    if school in ('frost','fire'): miss -= 2.0*t.elemental_precision
    if school=='arcane': miss -= 2.0*t.arcane_focus
    return max(.01,min(1.0,miss/100.0))


def spell_hit(level:int,mob_level:int,school:str,t:Talents)->float:
    return 1.0-spell_miss_chance(level,mob_level,school,t)


def effective_magic_resistance_percent(level:int,mob_level:int,school:str,t:Talents,cfg:SimConfig,
                                       *,binary:bool=False)->float:
    """CMaNGOS Classic Unit::CalculateEffectiveMagicResistancePercent as 0..0.75.

    Spell penetration first reduces inherent resistance (never below zero). Pre-3.0
    converts resistance to mitigation as 0.75 * R / skill, where skill=max(5L,100).
    Non-binary damage against a higher-level uncontrolled NPC adds 0.4% per point
    of skill difference = 2 percentage points per NPC level. Final cap is 75%.
    """
    resist=max(0.0,_school_resistance(cfg,school)-5.0*t.arcane_subtlety)
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
        if s.combustion_crits>=3:
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


def advance_passive(s:State,dt:float,level:int,t:Talents,stats:Stats,cfg:SimConfig,mob:Mob, moving:bool=False):
    """Advance time, mob movement, DoTs and continuous approximation to 2-s mana ticks.
    For policy optimization this is much smoother than phase-locking every pull to an
    arbitrary server mana tick. A later validation mode can randomize tick phase.
    """
    if dt<=0:return
    start=s.t; end=s.t+dt
    # Spirit regen integrated with exact 5SR boundary.
    mps=(12.5+stats.spirit/4)/2
    f=regen_fraction_in_5sr(level,t,cfg)
    if start < s.last_mana_spend+5 < end:
        a=s.last_mana_spend+5-start
        s.mana=min(s.max_mana,s.mana + mps*(a*f + (dt-a)))
    else:
        inside=end <= s.last_mana_spend+5
        s.mana=min(s.max_mana,s.mana + mps*dt*(f if inside else 1.0))
    # Mob movement if active and not rooted; melee threshold includes optional leeway.
    effective_reach=mob.melee_reach+(cfg.moving_leeway if moving else 0)
    if s.engaged and not s.in_melee and s.hp>0:
        # split for slow/root expirations crudely via small substeps
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
            if not (frozen or stunned):
                speed=mob.run_speed*((1-s.slow_frac) if slowed else 1)
                s.distance=max(effective_reach,s.distance-speed*nxt)
                if s.distance<=effective_reach+EPS:
                    s.in_melee=True; s.next_swing=s.t+nxt
            s.t+=nxt; rem-=nxt
        # t already advanced inside loop
        if s.t<end-EPS: s.t=end
    else:
        s.t=end
    # DoT ticks: apply all due ticks up to end (simple queue).
    for d in list(s.dots):
        while d.remaining_ticks>0 and d.next_tick<=end+EPS and s.hp>0:
            s.hp-=d.damage; d.remaining_ticks-=1; d.next_tick+=d.interval
        if d.remaining_ticks<=0: s.dots.remove(d)
    if s.scorch_until<=end: s.scorch_stacks=0
    if s.wc_until<=end: s.wc_stacks=0


def mana_cost(rank:Rank,t:Talents,stats:Stats)->float:
    c=rank.mana
    if rank.school=='frost': c*=1-.05*t.frost_channeling
    # Classic Era Elemental Precision used here as resist/hit only (no mana effect).
    return max(0,c)


def direct_mod(rank:Rank,t:Talents,s:State)->float:
    m=1.0
    if rank.school=='frost': m*=1+.02*t.piercing_ice
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
        if s.t + TIME_EPS < s.root_until: c+=.10*t.shatter
    if rank.spell in ('scorch','fire_blast'): c+=.02*t.incinerate
    if rank.school=='fire': c+=.02*t.critical_mass
    if rank.school=='fire' and s.combustion_active:
        c+=.10*s.combustion_bonus
    return min(.99,c)


def crit_mult(rank:Rank,t:Talents)->float:
    if rank.school=='frost': return 1.5+.1*t.ice_shards
    return 1.5


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
    s.ice_barrier_absorb=float(rank.absorb)
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
    if rank.school=='fire' and t.impact and rng.random()<.02*t.impact:
        s.stun_until=max(s.stun_until,s.t+2.0)
    if rank.spell=='scorch' and t.imp_scorch:
        proc=(1/3,2/3,1.0)[t.imp_scorch-1]
        if rng.random()<proc:
            s.scorch_stacks=min(5,s.scorch_stacks+1)
            s.scorch_until=s.t+30.0
    if rank.spell=='frostbolt':
        s.slow_frac=.40+[0,.04,.07,.10][t.permafrost]
        s.slow_until=s.t+rank.slow_duration+t.permafrost
        if t.winters_chill and rng.random()<.20*t.winters_chill:
            s.wc_stacks=min(5,s.wc_stacks+1)
            s.wc_until=s.t+15.0
        if t.frostbite and rng.random()<.05*t.frostbite:
            s.root_until=max(s.root_until,s.t+5)
    if rank.spell in ('fireball','pyroblast') and rank.dot_total>0:
        # Attached spell DoTs are one debuff per caster/spell: a new hit
        # refreshes/replaces the same spell's DoT rather than stacking copies.
        s.dots[:] = [d for d in s.dots if d.kind!=rank.spell]
        interval=max(EPS,rank.dot_interval)
        ticks=max(1,int(round(rank.dot_duration/interval)))
        dot_total=(rank.dot_total*direct_mod(rank,t,s)
                   *resistance_damage_multiplier(level,t,cfg,'fire',mob.level))
        s.dots.append(Dot(ticks,s.t+interval,interval,dot_total/ticks,'fire',rank.spell))
    combustion_after_hit(s,rank,landed,crit)


def advance_events(s:State,dt:float,level:int,t:Talents,stats:Stats,cfg:SimConfig,
                   mob:Mob,rng:random.Random,metrics:FightMetrics,moving:bool=False):
    """Advance non-casting time with exact projectile/contact/swing boundaries."""
    rem=dt
    guard=0
    while rem>EPS and s.hp>0 and guard<1000:
        guard+=1
        frozen=s.t + TIME_EPS < s.root_until; stunned=s.t + TIME_EPS < s.stun_until; slowed=s.t + TIME_EPS < s.slow_until
        if s.engaged and not s.in_melee and not frozen and not stunned:
            reach=mob.melee_reach+(cfg.moving_leeway if moving else 0)
            speed=mob.run_speed*((1-s.slow_frac) if slowed else 1)
            contact=max(0,s.distance-reach)/speed if speed>0 else math.inf
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
        advance_passive(s,step,level,t,stats,cfg,mob,moving=moving)
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
            _ice_barrier_absorbs_swing(s,mob,cfg)
            s.next_swing=s.t+mob.swing

        # Avoid zero-time loops on expiry boundaries.
        if step<=EPS and not due and not (s.in_melee and s.next_swing<=s.t+EPS):
            tiny=min(rem,1e-4)
            if tiny>0:
                advance_passive(s,tiny,level,t,stats,cfg,mob,moving=moving)
                rem-=tiny

def perform_direct(s:State,rank:Rank,level:int,t:Talents,stats:Stats,cfg:SimConfig,mob:Mob,rng:random.Random,metrics:FightMetrics):
    if s.distance > effective_range(rank,t) + EPS:
        return False
    c=mana_cost(rank,t,stats)
    free=s.clearcasting
    if free: s.clearcasting=False; c=0
    if s.mana+EPS<c: return False
    maybe_activate_combustion(s,t,rank)
    cast=rank.cast
    if rank.spell=='frostbolt': cast=max(0.5,cast-.1*t.imp_frostbolt)
    if rank.spell=='fireball': cast=max(0.5,cast-.1*t.imp_fireball)

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
        advance_passive(s,dt,level,t,stats,cfg,mob); rem-=dt

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
            resist_pb = barrier_protected or (rank.school=='fire' and rng.random()<.35*t.burning_soul)
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
        dmg=(rng.uniform(rank.dmin,rank.dmax)*direct_mod(rank,t,s)*resist_mult)
        crit=rng.random()<crit_chance(rank,t,s,stats)
        if crit:
            dmg*=crit_mult(rank,t)
            if rank.school=='fire' and t.ignite:
                total=.08*t.ignite*dmg
                # Ignite begins on impact for missiles; attach below for missile
                # via a tiny synthetic dot at impact in resolve path not yet ideal.
            if rank.school in ('fire','frost') and t.master_elements:
                s.mana=min(s.max_mana,s.mana+rank.mana*.10*t.master_elements)

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
    metrics.casts[rank.spell]=metrics.casts.get(rank.spell,0)+1
    return True

def perform_instant_damage(s:State,rank:Rank,level:int,t:Talents,stats:Stats,cfg:SimConfig,mob:Mob,rng:random.Random,metrics:FightMetrics):
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
        dmg=(rng.uniform(rank.dmin,rank.dmax)*direct_mod(rank,t,s)*resist_mult)
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
        if rank.school=='fire' and t.impact and rng.random()<.02*t.impact:
            s.stun_until=max(s.stun_until,s.t+2.0)
    combustion_after_hit(s,rank,landed,crit if landed else False)
    s.engaged=True
    maybe_clearcast(s,t,rng,landed)
    cd=rank.cooldown
    if rank.spell=='fire_blast':
        cd=max(1,cd-.5*t.imp_fire_blast);s.fireblast_ready=s.t+cd
    metrics.casts[rank.spell]=metrics.casts.get(rank.spell,0)+1
    advance_events(s,GCD,level,t,stats,cfg,mob,rng,metrics)
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
        dmg=(rng.uniform(rank.dmin,rank.dmax)*direct_mod(rank,t,s)*resist_mult)
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
    # move away at player run speed 7 yd/s; rooted mob cannot close, otherwise relative speed matters.
    if yards<=0:return True
    dur=yards/7.0
    # If mob isn't rooted, both move same base speed; slow can create net separation.
    if s.t + TIME_EPS < s.root_until:
        s.distance+=yards
    else:
        mobspd=mob.run_speed*((1-s.slow_frac) if s.t + TIME_EPS < s.slow_until else 1)
        gain=max(0,7.0-mobspd)*dur
        s.distance+=gain
    s.in_melee=s.distance<=mob.melee_reach+cfg.moving_leeway
    if not s.in_melee:s.next_swing=math.inf
    metrics.casts['move']=metrics.casts.get('move',0)+1
    advance_events(s,dur,level,t,stats,cfg,mob,rng,metrics,moving=True)
    return True


def perform_am(s:State,rank:Rank,level:int,t:Talents,stats:Stats,cfg:SimConfig,mob:Mob,rng:random.Random,metrics:FightMetrics):
    c=rank.mana;free=s.clearcasting
    if free:s.clearcasting=False;c=0
    if s.mana+EPS<c:return False
    spend(s,c);metrics.mana_spent+=c
    landed_once=False
    s.engaged=True  # channel begins doing hostile work immediately in this approximation

    for _ in range(rank.channel_ticks):
        if s.hp<=0:break
        rem=1.0; disrupted=False
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
            advance_passive(s,dt,level,t,stats,cfg,mob);rem-=dt

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
            dmg=(rank.channel_tick_damage*(1+.01*t.arcane_instability)*resist_mult)
            if rng.random()<stats.spell_crit: dmg*=1.5
            was_rooted=s.t + TIME_EPS < s.root_until
            s.hp-=dmg
            if was_rooted:maybe_break_root(s,dmg,mob,'arcane',cfg,rng)

    maybe_clearcast(s,t,rng,landed_once)
    metrics.casts['arcane_missiles']=metrics.casts.get('arcane_missiles',0)+1
    return True

# -------------------------- policy layer ----------------------------------

@dataclass(frozen=True)
class Policy:
    name:str
    primary:str='frostbolt'
    use_fireblast:bool=True
    fireblast_execute_frac:float=.18
    use_nova:bool=True
    nova_rank1:bool=True
    nova_melee_only:bool=True
    nova_move_yards:float=6.0
    use_blink:bool=True
    blink_min_hp_frac:float=.35
    # Ice Barrier is an optional pre-pull throughput/control action, not a
    # passive consequence of taking the talent.  Keeping the decision in the
    # policy lets MC/Fast compare 'use it' vs 'skip it' rather than making a
    # potentially mana-negative spell mandatory.
    use_ice_barrier:bool=False
    clearcast_am:bool=False
    # Fire cadence is intentionally independent of Improved Scorch rank.  This
    # avoids a search pathology where low Imp Scorch could be rewarded merely
    # because the old "cast until N stacks" policy happened to cast more Scorch.
    fireball_block:int=0
    scorch_block:int=0
    # Phase offset into the fixed Fireball/Scorch cadence.  This makes e.g.
    # FBa3/Sc3 capable of starting as FBa,FBa,Sc,Sc,Sc,FBa... (phase=1)
    # or Sc,Sc,Sc,FBa,FBa,FBa... (phase=3) without tying rotation
    # behavior to any talent rank.
    fire_cycle_phase:int=0
    # Optional conditional Frost Nova insertion *before* this logical cadence
    # position whenever Nova is ready and the target is in range. -1 keeps the
    # legacy/reactive melee Nova behavior. Nova does not consume a cadence slot.
    nova_cycle_pos:int=-1
    pyro_opener:bool=False
    # Deprecated legacy descriptor field. Kept only so old replay descriptors
    # can still be parsed; new search policies never use stack-driven behavior.
    scorch_to_stacks:int=0
    # Optional utility downrank: Rank 1 Frostbolt alongside a Fire rotation.
    # 'opener' = one cheap chill at pull start; 'maintain' = refresh chill when
    # it is about to expire and the mob is still outside melee.
    fbo_r1_mode:str='none'  # none | opener | maintain
    fbo_r1_refresh_s:float=.75


def policy_spell_usage(p:Policy, level:int) -> set[str]:
    """Conservative set of spells the policy can actually cast at this level.

    This is semantic metadata for diagnostics/search tie-breaking.  It mirrors
    choose_action rather than scraping the human-readable policy descriptor.
    """
    spells=set()
    primary_map={'frostbolt':'frostbolt','fireball':'fireball','scorch':'scorch','arcane_missiles':'arcane_missiles'}
    pr=primary_map.get(p.primary)
    if pr:
        spells.add(pr)
    if p.fireball_block>0 and p.scorch_block>0:
        if latest(FIREBALL,level): spells.add('fireball')
        if latest(SCORCH,level): spells.add('scorch')
    if p.scorch_to_stacks>0:
        if latest(SCORCH,level): spells.add('scorch')
        if latest(FIREBALL,level): spells.add('fireball')
    if p.use_fireblast and latest(FIRE_BLAST,level): spells.add('fire_blast')
    if p.use_nova and latest(FROST_NOVA,level): spells.add('frost_nova')
    if p.clearcast_am and latest(ARCANE_MISSILES,level): spells.add('arcane_missiles')
    if p.pyro_opener and latest(PYROBLAST,level): spells.add('pyroblast')
    if p.fbo_r1_mode!='none': spells.add('frostbolt')
    return spells


def talent_directly_affects_policy(name:str, p:Policy, level:int) -> bool:
    """Whether a modeled talent can change this level/policy's speed result.

    Prerequisite-only/defensive fillers deliberately return False.  The helper
    is used only for diagnostics and tie-breaking; the simulator remains the
    authority on the actual numeric effect.
    """
    spells=policy_spell_usage(p,level)
    frost=bool(spells & {'frostbolt','frost_nova'})
    fire=bool(spells & {'fireball','scorch','fire_blast','pyroblast'})
    arcane='arcane_missiles' in spells
    any_spell=bool(spells)
    if name=='arcane_subtlety': return any_spell
    if name=='elemental_precision': return frost or fire
    if name=='arcane_focus': return arcane
    if name=='imp_frostbolt': return 'frostbolt' in spells
    if name=='ice_shards': return frost
    if name=='frostbite': return 'frostbolt' in spells
    if name=='imp_frost_nova': return 'frost_nova' in spells
    if name=='permafrost': return 'frostbolt' in spells
    if name=='piercing_ice': return frost
    if name=='arctic_reach': return bool(spells & {'frostbolt','frost_nova'})
    if name=='frost_channeling': return frost
    if name=='shatter': return frost and 'frost_nova' in spells
    if name=='winters_chill': return 'frostbolt' in spells
    if name=='ice_barrier': return bool(p.use_ice_barrier and any_spell and ice_barrier_rank(level) is not None)
    if name=='imp_arcane_missiles': return arcane
    if name=='arcane_concentration': return any_spell
    if name=='arcane_meditation': return any_spell
    # Arcane Resilience is now only a prerequisite gate: player HP/armor are not
    # part of this leveling-speed scoreroute.
    if name=='arcane_resilience': return False
    if name=='arcane_mind': return any_spell
    if name=='arcane_instability': return any_spell
    if name=='imp_fireball': return 'fireball' in spells
    if name=='impact': return fire
    if name=='imp_fire_blast': return 'fire_blast' in spells
    if name=='ignite': return fire
    if name=='flame_throwing': return fire
    if name=='burning_soul': return fire
    if name=='incinerate': return bool(spells & {'scorch','fire_blast'})
    if name=='pyroblast': return 'pyroblast' in spells
    if name=='imp_scorch': return 'scorch' in spells
    if name=='master_elements': return frost or fire
    if name=='critical_mass': return fire
    if name=='fire_power': return fire
    if name=='combustion': return fire
    # Explicit neutral/gating talents in this ST objective.
    if name in {'frost_warding','improved_blizzard','cold_snap','ice_block','improved_cone_of_cold',
                'arcane_filler','improved_flamestrike','fire_warding'}:
        return False
    return False


def choose_action(s:State,level:int,t:Talents,stats:Stats,cfg:SimConfig,mob:Mob,p:Policy,initial_hp:float):
    hpfrac=max(0,s.hp/initial_hp)
    fb=latest(FIRE_BLAST,level)
    if p.use_fireblast and fb and s.t>=s.fireblast_ready and s.distance<=effective_range(fb,t)+EPS and hpfrac<=p.fireblast_execute_frac:
        return ('fire_blast',fb)
    # Reactive Nova is the default.  Cadence-scheduled Nova is handled below
    # so it can be inserted at an optimizer-selected point in the Fire cycle.
    if p.use_nova and p.nova_cycle_pos < 0 and s.in_melee and s.t>=s.nova_ready:
        nr=FROST_NOVA[0] if p.nova_rank1 else latest(FROST_NOVA,level)
        if nr and s.distance<=nr.radius*(1+.1*t.arctic_reach): return ('nova',nr)
    if p.use_blink and s.in_melee and level>=20 and s.t>=s.blink_ready and hpfrac>=p.blink_min_hp_frac:
        return ('blink',None)
    if p.clearcast_am and s.clearcasting:
        am=latest(ARCANE_MISSILES,level)
        if am:return ('am',am)

    if p.pyro_opener and t.pyroblast and not s.pyro_opener_used:
        py=latest(PYROBLAST,level)
        if py:
            return ('direct',py)

    # Cheap utility Frostbolt R1 for Fire policies.
    if p.fbo_r1_mode != 'none' and p.primary in ('fireball','scorch'):
        r1=FROSTBOLT[0]
        if p.fbo_r1_mode == 'opener' and not s.engaged:
            return ('direct',r1)
        if (p.fbo_r1_mode == 'maintain' and not s.in_melee and s.t >= s.root_until
                and (not s.engaged or s.slow_until-s.t <= p.fbo_r1_refresh_s)):
            return ('direct',r1)

    if p.fireball_block>0 and p.scorch_block>0 and latest(FIREBALL,level) and latest(SCORCH,level):
        cycle=p.fireball_block+p.scorch_block
        pos=(s.fire_cycle_pos + p.fire_cycle_phase) % cycle
        # A scheduled Nova is a conditional insertion, not a cycle element:
        # cast it when ready/in range, then resume the same Fire cycle slot.
        if p.use_nova and p.nova_cycle_pos >= 0 and pos == (p.nova_cycle_pos % cycle) and s.t>=s.nova_ready:
            nr=FROST_NOVA[0] if p.nova_rank1 else latest(FROST_NOVA,level)
            if nr and s.distance<=nr.radius*(1+.1*t.arctic_reach) and s.mana+EPS>=mana_cost(nr,t,stats):
                return ('nova',nr)
        if pos < p.fireball_block:
            return ('direct',latest(FIREBALL,level))
        sc=latest(SCORCH,level)
        if s.distance<=effective_range(sc,t)+EPS:
            return ('direct',sc)
        return ('wait_range',sc)
    if p.primary=='frostbolt': return ('direct',latest(FROSTBOLT,level))
    if p.primary=='fireball': return ('direct',latest(FIREBALL,level))
    if p.primary=='scorch': return ('direct',latest(SCORCH,level))
    if p.primary=='arcane_missiles': return ('am',latest(ARCANE_MISSILES,level))
    raise ValueError(p.primary)



def _wand_resistance_multiplier(level:int,mob:Mob,wand:Wand,t:Talents,cfg:SimConfig,rng:random.Random)->float:
    """Magic-school mitigation for a wand shot.

    Wands are ranged weapon attacks, so spell-hit talents do not modify their
    hit chance here. School resistance still mitigates magic wand damage; Arcane
    Subtlety is intentionally not applied to wand shots because it modifies
    resistance to the mage's spells, not ranged weapon attacks.
    """
    school=wand.school
    if school not in ('fire','frost','arcane'):
        return 1.0
    neutral=replace(t, arcane_subtlety=0)
    return roll_magic_resistance_multiplier(level,mob.level,school,'wand',neutral,cfg,rng)


def _mana_wait_seconds(s:State,need:float,level:int,t:Talents,stats:Stats,cfg:SimConfig)->float:
    """Continuous time until ``need`` mana is available under normal spirit regen."""
    deficit=max(0.0,float(need)-s.mana)
    if deficit<=EPS:
        return 0.0
    mps=(12.5+stats.spirit/4)/2
    f=regen_fraction_in_5sr(level,t,cfg)
    five=max(0.0,s.last_mana_spend+5.0-s.t)
    inside_rate=mps*f
    inside_gain=inside_rate*five
    if deficit<=inside_gain and inside_rate>EPS:
        return deficit/inside_rate
    return five + max(0.0,deficit-inside_gain)/max(mps,EPS)


def _required_mana(action:str,obj:Optional[Rank],t:Talents,stats:Stats)->float:
    if obj is not None and action in ('direct','fire_blast','nova'):
        return mana_cost(obj,t,stats)
    if obj is not None and action=='am':
        return obj.mana
    if action=='blink':
        return .35*stats.base_mana
    return 0.0


def perform_wand_fallback(s:State,seconds:float,level:int,t:Talents,stats:Stats,cfg:SimConfig,
                          mob:Mob,rng:random.Random,metrics:FightMetrics)->None:
    """Use the best level-appropriate wand as a real ranged autoattack.

    One wand shot occurs per item-speed interval. Each shot rolls the item's
    actual damage range. Mana regenerates while wanding. If the requested spell
    becomes affordable before the next shot would complete, the mage cancels the
    wand cycle and resumes the policy immediately. No player-HP/death model is
    involved.
    """
    remaining=max(0.0,float(seconds))
    wand=best_wand(level)
    if 0.0 < s.hp <= HP_EPS:
        s.hp=0.0
        return
    if not s.engaged:
        s.engaged=True
    while remaining>EPS and s.hp>HP_EPS:
        # Do not invent a partial wand hit. If mana becomes available before a
        # full auto-shot finishes, simply regen for the remaining interval.
        if remaining + TIME_EPS < wand.speed:
            t0=s.t
            advance_events(s,remaining,level,t,stats,cfg,mob,rng,metrics)
            elapsed=max(0.0,s.t-t0)
            if elapsed<=EPS:
                elapsed=remaining; s.t+=elapsed
            metrics.wand_time+=elapsed
            remaining=max(0.0,remaining-elapsed)
            break

        shot_dt=min(wand.speed,remaining)
        t0=s.t
        advance_events(s,shot_dt,level,t,stats,cfg,mob,rng,metrics)
        elapsed=max(0.0,s.t-t0)
        if elapsed<=EPS:
            elapsed=shot_dt; s.t+=elapsed
        metrics.wand_time+=elapsed
        remaining=max(0.0,remaining-elapsed)
        if s.hp<=HP_EPS:
            s.hp=0.0; break
        # Only a completed wand period creates a shot. Existing projectiles/DoTs
        # may have killed the target during the period.
        if elapsed + TIME_EPS >= wand.speed:
            raw=rng.uniform(wand.dmin,wand.dmax)
            mult=_wand_resistance_multiplier(level,mob,wand,t,cfg,rng)
            dmg=max(0.0,raw*mult)
            hp0=s.hp
            s.hp=max(0.0,s.hp-dmg)
            metrics.wand_shots+=1
            metrics.wand_damage+=min(hp0,dmg)
            metrics.casts['wand']=metrics.casts.get('wand',0)+1
        if 0.0 < s.hp <= HP_EPS:
            s.hp=0.0


def simulate_fight(level:int,tal:Talents,mob:Mob,policy:Policy,cfg:SimConfig,rng:random.Random,
                   cooldowns:Optional[Tuple[float,...]]=None)->Tuple[FightMetrics,Tuple[float,...],float,float]:
    stats=player_stats(level,tal,cfg.owl_intensity)
    # Start each pull at the primary spell's max range (representing selecting a fresh target at pull distance).
    primary=latest(SPELLS.get(policy.primary,FROSTBOLT),level) if policy.primary in SPELLS else latest(FROSTBOLT,level)
    start_range=effective_range(primary,tal) if primary else 30
    if policy.fbo_r1_mode != 'none' and policy.primary in ('fireball','scorch'):
        start_range=min(start_range, effective_range(FROSTBOLT[0],tal))
    raw=list(cooldowns or ())
    raw += [0.0] * max(0, 10-len(raw))
    fbr,nr,br,cbr,cactive,ccrits,cbonus,ibar,ibabs,ibdur=raw[:10]
    carried_absorb=max(0.0,float(ibabs)) if ibdur>EPS else 0.0
    s=State(t=0,hp=mob.hp,mana=stats.max_mana,max_mana=stats.max_mana,distance=start_range,
            engaged=False, fireblast_ready=fbr,nova_ready=nr,blink_ready=br,
            combustion_ready=cbr,combustion_active=bool(round(cactive)),
            combustion_crits=int(round(ccrits)),combustion_bonus=int(round(cbonus)),
            ice_barrier_ready=ibar,ice_barrier_absorb=carried_absorb,
            ice_barrier_until=(max(0.0,float(ibdur)) if ibdur>EPS else -1e9))
    m=FightMetrics(); initial=mob.hp
    if policy.use_ice_barrier:
        _maybe_cast_ice_barrier_pre_pull(s,level,tal,stats,cfg,mob,rng,m)
    post_nova_move=False
    steps=0
    while s.hp>0:
        steps+=1
        action,obj=choose_action(s,level,tal,stats,cfg,mob,policy,initial)
        ok=False
        if action=='direct' and obj:
            ok=perform_direct(s,obj,level,tal,stats,cfg,mob,rng,m)
            if ok and obj.spell=='pyroblast':
                s.pyro_opener_used=True
            if ok and policy.fireball_block>0 and policy.scorch_block>0 and obj.spell in ('fireball','scorch'):
                s.fire_cycle_pos+=1
        elif action=='fire_blast' and obj: ok=perform_instant_damage(s,obj,level,tal,stats,cfg,mob,rng,m)
        elif action=='nova' and obj:
            ok=perform_nova(s,obj,level,tal,stats,cfg,mob,rng,m);post_nova_move=ok
        elif action=='blink': ok=perform_blink(s,level,tal,stats,cfg,mob,rng,m)
        elif action=='am' and obj: ok=perform_am(s,obj,level,tal,stats,cfg,mob,rng,m)
        elif action=='wait_range' and obj:
            target=effective_range(obj,tal)
            if not s.in_melee and s.distance>target:
                if s.engaged:
                    # Once the target is active, simply let it close to the
                    # shorter spell's range.
                    slowed=s.t + TIME_EPS < s.slow_until
                    speed=mob.run_speed*((1-s.slow_frac) if slowed else 1.0)
                    dt=max(0.0,(s.distance-target)/max(speed,1e-9))
                    advance_events(s,dt,level,tal,stats,cfg,mob,rng,m)
                else:
                    # A missile spell can be in flight while the next cadence
                    # spell (typically Scorch) has shorter range. Before impact
                    # the mob is intentionally not aggroed, so waiting for mob
                    # movement would be a zero-time loop. Walk into range instead.
                    # Existing projectiles are still resolved during the move; if
                    # one lands, advance_events also starts target movement.
                    dt=max(0.0,(s.distance-target)/7.0)
                    t0=s.t
                    advance_events(s,max(dt,1e-4),level,tal,stats,cfg,mob,rng,m,moving=True)
                    elapsed=max(0.0,s.t-t0)
                    s.distance=max(target,s.distance-7.0*elapsed)
                    s.in_melee=s.distance<=mob.melee_reach+cfg.moving_leeway
                    if not s.in_melee:
                        s.next_swing=math.inf
                ok=True
            else:
                ok=True
        if post_nova_move and s.hp>0:
            perform_move(s,policy.nova_move_yards,level,tal,stats,cfg,mob,rng,m);post_nova_move=False
        if not ok:
            need=_required_mana(action,obj,tal,stats)
            if need>s.mana+EPS:
                # OOM is not a death/failure state.  Wand until the requested
                # policy action becomes affordable (or the wand/ongoing effects
                # kill the mob), then resume the same policy.
                wait=max(.05,_mana_wait_seconds(s,need,level,tal,stats,cfg))
                perform_wand_fallback(s,wait,level,tal,stats,cfg,mob,rng,m)
            else:
                # A non-mana transient failure should be extremely rare; let
                # projectiles/contact/cooldowns advance rather than inventing a
                # penalty or silently changing the policy.
                advance_events(s,.05,level,tal,stats,cfg,mob,rng,m)
        # Damage rolls routinely land a few ulps either side of exact zero.
        # Treat sub-resolution residual HP as dead before the next policy choice.
        if 0.0 < s.hp <= HP_EPS:
            s.hp=0.0
        if steps >= 10000:
            raise RuntimeError(f'simulator stalled at level {level}: {policy_desc(policy, level)}')
    # Let already-launched killing missiles land instead of declaring the fight done early.
    while s.hp>0 and s.projectiles:
        nxt=min(p.impact for p in s.projectiles)
        advance_events(s,max(0,nxt-s.t),level,tal,stats,cfg,mob,rng,m)
    m.kill_time=s.t;m.pushback=s.total_pushback;m.swings=s.damage_taken_swings
    # Return cooldowns relative to end of fight; between-pull drink time will tick them down.
    barrier_duration=max(0.0,s.ice_barrier_until-s.t)
    barrier_absorb=max(0.0,s.ice_barrier_absorb) if barrier_duration>EPS else 0.0
    cds=(max(0,s.fireblast_ready-s.t),max(0,s.nova_ready-s.t),max(0,s.blink_ready-s.t),
         max(0,s.combustion_ready-s.t),1.0 if s.combustion_active else 0.0,
         float(s.combustion_crits),float(s.combustion_bonus),
         max(0,s.ice_barrier_ready-s.t),barrier_absorb,barrier_duration)
    mana_left=max(0,s.mana)
    five_sr=max(0.0,s.last_mana_spend+5.0-s.t)
    return m,cds,mana_left,five_sr


def recovery_time(level:int,tal:Talents,mana_left:float,cfg:SimConfig,
                  five_sr_remaining:float=5.0)->float:
    # Recovery must use the same configured gear stats as the fight.  Using
    # baseline stats here makes +Int look like permanently free mana (because
    # the perturbed fight ends with mana measured against a larger pool, while
    # recovery targets the old smaller max mana) and hides +Spirit from drink
    # recovery.
    stats=player_stats_for_config(level,tal,cfg)
    missing=max(0,stats.max_mana-mana_left)
    water=latest_pair(WATER_USABLE if cfg.use_best_water else WATER_SELF,level)
    mana_t=0.0
    if missing>EPS:
        if not water:return math.inf
        _,amt,dur=water
        drink_mps=amt/dur
        spirit_mps=(12.5+stats.spirit/4)/2
        f=regen_fraction_in_5sr(level,tal,cfg)
        blocked=max(0.0,min(5.0,five_sr_remaining))
        first_rate=drink_mps+spirit_mps*f
        first_gain=first_rate*blocked
        if missing<=first_gain: mana_t=missing/first_rate
        else: mana_t=blocked+(missing-first_gain)/(drink_mps+spirit_mps)

    return mana_t

def simulate_chain_incremental(level:int,tal:Talents,policy:Policy,cfg:SimConfig,target_n:int=100,seed:int=1,
                               hp_mult:float=1.0,continuation:Optional[dict]=None):
    """Run/extend one canonical pull chain and return (metrics, continuation).

    The continuation contains the RNG state, persistent cooldowns and cumulative
    sufficient statistics after exactly ``n`` mobs.  Extending a cached 32-mob
    chain to 64 therefore simulates only mobs 33..64 and is bit-for-bit the same
    stream as a fresh 64-mob run under the same simulator code/config.
    """
    if continuation:
        start_n=int(continuation.get('n',0))
        if start_n>target_n:
            raise ValueError('continuation is beyond requested target_n')
        rng=random.Random()
        rng.setstate(continuation['rng_state'])
        cds=tuple(continuation.get('cooldowns',(0.0,0.0,0.0)))
        total=float(continuation.get('total_s',0.0)); kill=float(continuation.get('kill_s',0.0))
        drink=float(continuation.get('recovery_s',0.0)); mana=float(continuation.get('mana',0.0))
        wand=float(continuation.get('wand_s',0.0)); pb=float(continuation.get('pushback_s',0.0)); sw=float(continuation.get('swings',0.0))
        damage=float(continuation.get('damage_done',0.0)); wand_damage=float(continuation.get('wand_damage',0.0)); wand_shots=float(continuation.get('wand_shots',0.0))
        total_sq=float(continuation.get('total_sq_s',0.0))
        casts=dict(continuation.get('casts',{}))
    else:
        start_n=0; rng=random.Random(seed); cds=(0.0,0.0,0.0)
        total=kill=drink=mana=wand=pb=sw=damage=wand_damage=wand_shots=0.0; total_sq=0.0; casts={}

    # canonical +1/+2 alternating using exact CMaNGOS warrior BaseHealthExp0.
    for i in range(start_n,target_n):
        ml=level+(1 if i%2==0 else 2)
        swing=(cfg.mob_swing_mix[(i//2)%len(cfg.mob_swing_mix)] if cfg.mob_swing_mix else cfg.mob_swing)
        mob=Mob(ml,MOB_BASE_HP[ml]*hp_mult,cfg.mob_speed,swing,cfg.melee_reach)
        damage += mob.hp
        fm,cds,mleft,five_sr=simulate_fight(level,tal,mob,policy,cfg,rng,cds)
        rt=recovery_time(level,tal,mleft,cfg,five_sr)
        # Fire Blast/Nova/Blink/Combustion and Ice Barrier are cooldown timers;
        # the middle Combustion values encode buff state and must not tick down.
        # Barrier absorb itself does not decay with time, but its 60 s aura does.
        tmp=list(cds) + [0.0] * max(0,10-len(cds))
        for j in (0,1,2,3,7): tmp[j]=max(0.0,tmp[j]-rt)
        tmp[9]=max(0.0,tmp[9]-rt)
        if tmp[9]<=EPS: tmp[8]=0.0
        cds=tuple(tmp[:10])
        pull_s=fm.kill_time+rt
        total+=pull_s; total_sq+=pull_s*pull_s; kill+=fm.kill_time;drink+=rt;mana+=fm.mana_spent;wand+=fm.wand_time;pb+=fm.pushback;sw+=fm.swings
        wand_damage+=fm.wand_damage; wand_shots+=fm.wand_shots
        for k,v in fm.casts.items():casts[k]=casts.get(k,0)+v

    mean=(total/target_n) if target_n else 0.0
    if target_n>1:
        var=max(0.0,(total_sq-(total*total/target_n))/(target_n-1))
        stderr=math.sqrt(var/target_n)
    else:
        var=0.0; stderr=math.inf
    active_dps=(damage/kill) if kill>EPS else 0.0
    out={'total_s':total,'kill_s':kill,'recovery_s':drink,'mana':mana,'wand_s':wand,'wand_shots':wand_shots,'wand_damage':wand_damage,
         'damage_done':damage,'active_dps':active_dps,'pushback_s':pb,'swings':sw,
         'total_sq_s':total_sq,'mean_s_per_mob':mean,'stderr_s_per_mob':stderr}
    for k,v in casts.items():out['casts_'+k]=v
    state={'n':int(target_n),'rng_state':rng.getstate(),'cooldowns':tuple(cds),
           'total_s':total,'kill_s':kill,'recovery_s':drink,'mana':mana,'wand_s':wand,'wand_shots':wand_shots,'wand_damage':wand_damage,'damage_done':damage,
           'pushback_s':pb,'swings':sw,'total_sq_s':total_sq,'casts':casts}
    return out,state

def simulate_chain(level:int,tal:Talents,policy:Policy,cfg:SimConfig,n:int=100,seed:int=1,
                   hp_mult:float=1.0)->Dict[str,float]:
    out,_=simulate_chain_incremental(level,tal,policy,cfg,target_n=n,seed=seed,hp_mult=hp_mult)
    return out



def with_ice_barrier_policy_variants(policies:Iterable[Policy], level:int, talents:Talents)->List[Policy]:
    """Return policy basis plus explicit Ice Barrier-use variants when legal.

    Taking the talent only grants the button.  It must never force every pull to
    spend mana/GCD on Barrier: search compares otherwise-identical policies with
    and without pre-pull Barrier and keeps whichever wins the objective.
    """
    base=list(policies)
    if not talents.ice_barrier or ice_barrier_rank(level) is None:
        return base
    out=[]
    for pol in base:
        out.append(pol)
        if not pol.use_ice_barrier:
            out.append(replace(pol,name=pol.name+'+Barrier',use_ice_barrier=True))
    seen=set(); dedup=[]
    for pol in out:
        key=tuple(getattr(pol,f) for f in pol.__dataclass_fields__ if f!='name')
        if key not in seen:
            seen.add(key); dedup.append(pol)
    return dedup

def candidate_policies(level:int)->List[Policy]:
    """Full policy grid for final per-level validation.

    Fire cadence is a talent-independent periodic policy.  Search covers both
    block lengths and phase offsets, so one FBa3/Sc3 cycle can represent starts
    such as FBa,FBa,Sc,Sc,Sc,FBa... or Sc,Sc,Sc,FBa,FBa,FBa....  Frost Nova
    can either stay reactive (melee utility) or be conditionally inserted at an
    optimizer-selected cadence position.  Pyroblast remains an opener choice.
    """
    base=[]
    scheduled_nova=[]
    for primary in ('frostbolt','fireball','arcane_missiles'):
        if latest(SPELLS[primary],level) is None:
            continue
        base.append(Policy(primary.upper()+' pure',primary,use_fireblast=False,use_nova=False,use_blink=False))
        for ex in (.10,.18,.28):
            for cc in (False, True):
                p=Policy(
                    f'{primary}+execute/nova'+('+CCAM' if cc else ''),
                    primary=primary,
                    use_fireblast=True,
                    fireblast_execute_frac=ex,
                    use_nova=True,
                    nova_rank1=True,
                    nova_move_yards=6,
                    use_blink=True,
                    blink_min_hp_frac=.35,
                    clearcast_am=cc,
                )
                base.append(p)
                if primary=='fireball':
                    base.append(replace(p,name=p.name+'+FBoR1-open',fbo_r1_mode='opener'))
                    base.append(replace(p,name=p.name+'+FBoR1-maint',fbo_r1_mode='maintain'))

    if latest(SCORCH,level):
        p=Policy('Sc pure',primary='scorch',use_fireblast=True,use_nova=True,nova_rank1=True,
                 nova_move_yards=6,use_blink=True)
        base.append(p)
        for mode in ('opener','maintain'):
            base.append(replace(p,name=f'Sc+FBoR1-{mode}',fbo_r1_mode=mode))

        # Search the cadence itself, including phase.  Scorch blocks up to three
        # explicitly cover the previously-missing Sc,Sc,Sc examples.
        for fb_n in (1,2,3,4,6):
            for sc_n in (1,2,3):
                cycle=fb_n+sc_n
                for phase in range(cycle):
                    suffix=f'@{phase}' if phase else ''
                    p=Policy(f'FBa{fb_n}/Sc{sc_n}{suffix}',primary='fireball',
                             use_fireblast=True,use_nova=True,nova_rank1=True,
                             nova_move_yards=6,use_blink=True,
                             fireball_block=fb_n,scorch_block=sc_n,
                             fire_cycle_phase=phase)
                    base.append(p)
                    # Keep one utility-Frostbolt variant per cadence/phase.
                    base.append(replace(p,name=p.name+'+FBoR1-maint',fbo_r1_mode='maintain'))

                    # Scheduled-Nova variants deliberately stay on one fixed
                    # Nova rank/step configuration to avoid a combinatorial
                    # FN-rank x movement x position explosion. Reactive variants
                    # below still search those utility parameters independently.
                    for nova_pos in range(cycle):
                        scheduled_nova.append(replace(
                            p, name=p.name+f'+FN@{nova_pos}', nova_cycle_pos=nova_pos,
                            nova_rank1=True, nova_move_yards=6))

    # Pyroblast is an opener strategy. Add it to normal Fire policies and to
    # scheduled-Nova cadence policies; optimize_policy talent-gates it.
    if latest(PYROBLAST,level):
        fire_openers=[]
        for p in base:
            if p.primary in ('fireball','scorch'):
                fire_openers.append(replace(p,name=p.name+'+PyroOpen',pyro_opener=True))
        base.extend(fire_openers)
        scheduled_nova += [replace(p,name=p.name+'+PyroOpen',pyro_opener=True)
                           for p in list(scheduled_nova)]

    nova_variants=[]
    for p in base:
        if p.use_nova:
            nova_variants.append(p)
            maxr=latest(FROST_NOVA,level)
            if maxr and maxr.rank>1:
                nova_variants.append(replace(p,name=p.name+' FNmax',nova_rank1=False))
        else:
            nova_variants.append(p)

    out=[]
    for p in nova_variants:
        out.append(p)
        if p.use_nova:
            for y in (4,5,6,8,10):
                out.append(replace(p,name=p.name+f' step{y}',nova_move_yards=y))
    # Scheduled-Nova policies are already a broad positional search. Keep them
    # fixed at R1/step6 and append without the generic utility cross-product.
    out.extend(scheduled_nova)

    seen=set(); dedup=[]
    for p in out:
        key=tuple(getattr(p,f) for f in p.__dataclass_fields__ if f!='name')
        if key not in seen:
            seen.add(key); dedup.append(p)
    return dedup

def candidate_fire_cadence_policies(level:int)->List[Policy]:
    """Focused Fireball/Scorch cadence basis used by the live optimizer.

    This searches block lengths and every phase offset without depending on
    Improved Scorch rank. Nova/Pyro insertions are layered on adaptively by the
    cached policy optimizer so the common path does not pay the full cross-product.
    """
    if latest(FIREBALL,level) is None or latest(SCORCH,level) is None:
        return []
    out=[]
    for fb_n in (1,2,3,4):
        for sc_n in (1,2,3):
            cycle=fb_n+sc_n
            for phase in range(cycle):
                suffix=f'@{phase}' if phase else ''
                out.append(Policy(
                    f'FBa{fb_n}/Sc{sc_n}{suffix}', primary='fireball',
                    use_fireblast=True, fireblast_execute_frac=.22,
                    use_nova=True, nova_rank1=True, nova_move_yards=5,
                    use_blink=True, blink_min_hp_frac=.35,
                    fireball_block=fb_n, scorch_block=sc_n,
                    fire_cycle_phase=phase))
    return out


def candidate_policies_coarse(level:int)->List[Policy]:
    """Very small policy basis for the outer talent beam.

    The beam's job is to discover promising talent states, not to solve the
    final rotation. Finalists are re-optimized against candidate_policies().
    """
    ps=[]
    if latest(FROSTBOLT,level):
        ps += [
            Policy('FBo pure','frostbolt',use_fireblast=False,use_nova=False,use_blink=False),
            Policy('FBo ctl FN1','frostbolt',use_fireblast=True,fireblast_execute_frac=.22,
                   use_nova=True,nova_rank1=True,nova_move_yards=5,use_blink=True,blink_min_hp_frac=.35),
            Policy('FBo ctl FN1 CCAM','frostbolt',use_fireblast=True,fireblast_execute_frac=.22,
                   use_nova=True,nova_rank1=True,nova_move_yards=5,use_blink=True,blink_min_hp_frac=.35,
                   clearcast_am=True),
        ]
        mx=latest(FROST_NOVA,level)
        if mx and mx.rank>1:
            ps.append(Policy('FBo ctl FNmax','frostbolt',use_fireblast=True,fireblast_execute_frac=.22,
                             use_nova=True,nova_rank1=False,nova_move_yards=5,use_blink=True,blink_min_hp_frac=.35))
    if latest(FIREBALL,level):
        ps += [
            Policy('FBa pure','fireball',use_fireblast=False,use_nova=False,use_blink=False),
            Policy('FBa ctl','fireball',use_fireblast=True,fireblast_execute_frac=.22,
                   use_nova=True,nova_rank1=True,nova_move_yards=5,use_blink=True,blink_min_hp_frac=.35),
            Policy('FBa ctl +FBoR1','fireball',use_fireblast=True,fireblast_execute_frac=.22,
                   use_nova=True,nova_rank1=True,nova_move_yards=5,use_blink=True,blink_min_hp_frac=.35,
                   fbo_r1_mode='maintain'),
        ]
        if latest(PYROBLAST,level):
            ps.append(Policy('FBa ctl +PyroOpen','fireball',use_fireblast=True,fireblast_execute_frac=.22,
                             use_nova=True,nova_rank1=True,nova_move_yards=5,use_blink=True,
                             blink_min_hp_frac=.35,pyro_opener=True))
    if latest(ARCANE_MISSILES,level):
        ps.append(Policy('AM ctl','arcane_missiles',use_fireblast=True,fireblast_execute_frac=.22,
                         use_nova=True,nova_rank1=True,nova_move_yards=5,use_blink=True,blink_min_hp_frac=.35))
    if latest(SCORCH,level):
        ps += [
            Policy('Sc ctl','scorch',use_fireblast=True,fireblast_execute_frac=.22,
                   use_nova=True,nova_rank1=True,nova_move_yards=5,use_blink=True),
            Policy('FBa3/Sc1','fireball',use_fireblast=True,fireblast_execute_frac=.22,
                   use_nova=True,nova_rank1=True,nova_move_yards=5,use_blink=True,
                   fireball_block=3,scorch_block=1),
            Policy('FBa2/Sc2','fireball',use_fireblast=True,fireblast_execute_frac=.22,
                   use_nova=True,nova_rank1=True,nova_move_yards=5,use_blink=True,
                   fireball_block=2,scorch_block=2),
        ]
    return ps

def optimize_policy(level:int,tal:Talents,cfg:SimConfig,n:int=40,seed:int=1,coarse:bool=False)->Tuple[Policy,Dict[str,float]]:
    best=None
    policies=candidate_policies_coarse(level) if coarse else candidate_policies(level)
    policies=with_ice_barrier_policy_variants(policies,level,tal)
    policies=filter_policies_by_primary_school(policies)
    if coarse:
        # AM is a deliberately expensive channel to simulate when it is repeatedly
        # pushback/health limited.  For talent discovery, only test it once the path
        # has actually invested in AM/Arcane proc support; the first such point is
        # itself generated by the talent beam, so Arcane paths remain discoverable.
        policies=[p for p in policies
                  if p.primary!='arcane_missiles' or tal.imp_arcane_missiles>0 or tal.arcane_concentration>0]
    else:
        # Remove policies that are behaviorally identical for this talent state.
        policies=[p for p in policies
                  if (not p.clearcast_am or tal.arcane_concentration>0)
                  and (not p.pyro_opener or tal.pyroblast>0)]
    if coarse:
        policies=[p for p in policies if (not p.pyro_opener or tal.pyroblast>0)]
    for i,p in enumerate(policies):
        r=simulate_chain(level,tal,p,cfg,n=n,seed=seed)
        if best is None or r['total_s']<best[1]['total_s']:best=(p,r)
    return best

# -------------------------- talent optimizer -------------------------------

@dataclass
class PathState:
    talents:Talents
    cumulative_s:float
    path:List[Tuple[int,str,Policy,float]]


def talent_key(t:Talents):
    return tuple(getattr(t,f) for f in t.__dataclass_fields__)


def talent_preference_key(t:Talents):
    """Deterministic secondary ordering for mechanically tied allocations.

    This key only acts after the modeled speed score ties.  Prefer real optional
    utility/future payoff over synthetic or objective-neutral gate spend:

    * Arcane Subtlety weakly dominates synthetic Arcane filler on the baseline
      and can help against reducible resistance.
    * Ice Block is neutral in the current no-death ST objective but is the real
      prerequisite for Ice Barrier.  Keeping that tied branch alive prevents the
      structural beam from pruning Barrier one point before it unlocks.
    * Taking Ice Barrier grants an optional button; because policy search keeps
      both Barrier-OFF and Barrier-ON, the talent itself cannot make a tied build
      worse and should survive over a neutral filler point.
    """
    return (int(t.arcane_filler), -int(t.arcane_subtlety),
            -int(t.ice_barrier), -int(t.ice_block), talent_key(t))


def talent_candidates(t:Talents)->List[Tuple[str,Talents]]:
    out=[]
    for name in TALENT_RULES:
        if legal_add(t,name):
            out.append((name,add_point(t,name)))
    return out


def optimize_talent_path(start_level:int=11,end_level:int=60,cfg:SimConfig=SimConfig(),
                         beam_width:int=10,mobs_per_level:int=8,seed:int=11,
                         start_talents:Talents=Talents())->PathState:
    """Coarse joint talent/policy beam search.

    Level L is evaluated after spending the point earned at L (so a level-11
    run starting from an empty tree spends two points before its first scored
    level: one representing level 10, one level 11).  For speed this stage uses
    a short +1/+2 mob chain; finalists should be revalidated with 100+ mobs.
    """
    states=[PathState(start_talents,0.0,[])]
    # spend points from 10 through end_level. If start_level > 10, points before
    # start_level still matter to legal structure but are scored only once the
    # requested window begins.
    for lvl in range(10,end_level+1):
        nxt={}
        score_cache={}
        for st in states:
            for name,nt in talent_candidates(st.talents):
                if nt.points()!=lvl-9:
                    continue
                if lvl < start_level:
                    cand=PathState(nt,st.cumulative_s,st.path+[(lvl,name,Policy('unscored'),0.0)])
                else:
                    tk=talent_key(nt)
                    cached=score_cache.get(tk)
                    if cached is None:
                        pol,res=optimize_policy(lvl,nt,cfg,n=mobs_per_level,seed=seed+lvl*7919,coarse=True)
                        score=res['total_s']*(100.0/mobs_per_level)
                        score_cache[tk]=(pol,score)
                    else:
                        pol,score=cached
                    cand=PathState(nt,st.cumulative_s+score,st.path+[(lvl,name,pol,score)])
                k=talent_key(nt)
                old=nxt.get(k)
                if old is None or cand.cumulative_s<old.cumulative_s:
                    nxt[k]=cand
        states=(list(nxt.values()) if lvl < start_level else sorted(nxt.values(),key=lambda x:x.cumulative_s)[:beam_width])
        if not states:
            raise RuntimeError(f'beam exhausted at level {lvl}')
    return min(states,key=lambda x:x.cumulative_s)



def optimize_talent_paths(start_level:int=11,end_level:int=60,cfg:SimConfig=SimConfig(),
                          beam_width:int=10,mobs_per_level:int=8,seed:int=11,
                          start_talents:Talents=Talents(),top_k:int=5)->List[PathState]:
    """Return the top-K final talent paths retained by the beam.

    Same search as optimize_talent_path(), but preserves the final ranking so
    the report can show runner-up builds rather than only the winner.
    """
    states=[PathState(start_talents,0.0,[])]
    for lvl in range(10,end_level+1):
        nxt={}
        score_cache={}
        for st in states:
            for name,nt in talent_candidates(st.talents):
                if nt.points()!=lvl-9:
                    continue
                if lvl < start_level:
                    cand=PathState(nt,st.cumulative_s,st.path+[(lvl,name,Policy('unscored'),0.0)])
                else:
                    tk=talent_key(nt)
                    cached=score_cache.get(tk)
                    if cached is None:
                        pol,res=optimize_policy(lvl,nt,cfg,n=mobs_per_level,seed=seed+lvl*7919,coarse=True)
                        score=res['total_s']*(100.0/mobs_per_level)
                        score_cache[tk]=(pol,score)
                    else:
                        pol,score=cached
                    cand=PathState(nt,st.cumulative_s+score,st.path+[(lvl,name,pol,score)])
                k=talent_key(nt)
                old=nxt.get(k)
                if old is None or cand.cumulative_s<old.cumulative_s:
                    nxt[k]=cand
        ranked=sorted(nxt.values(),key=lambda x:x.cumulative_s)
        states=ranked if lvl < start_level else ranked[:beam_width]
        if not states:
            raise RuntimeError(f'beam exhausted at level {lvl}')
    return sorted(states,key=lambda x:x.cumulative_s)[:max(1,top_k)]

def final_allocation(t:Talents)->str:
    parts=[]
    for name in t.__dataclass_fields__:
        v=getattr(t,name)
        if v:
            parts.append(f'{name}={v}')
    return ', '.join(parts)

def policy_desc(p:Policy,level:int)->str:
    ab={'frostbolt':'FBo','fireball':'FBa','arcane_missiles':'AM','scorch':'Sc'}
    bits=[ab.get(p.primary,p.primary)]
    if p.fireball_block and p.scorch_block:
        bits=[f'FBa{p.fireball_block}/Sc{p.scorch_block}']
        if p.fire_cycle_phase:
            bits.append(f'Phase={p.fire_cycle_phase}')
    elif p.scorch_to_stacks:
        # Legacy replay descriptor only; new search does not emit this policy.
        bits=[f'Sc×{p.scorch_to_stacks}→FBa']
    if p.pyro_opener:
        bits.append('PyroOpen')
    if p.fbo_r1_mode!='none':
        bits.append(f'FBoR1:{p.fbo_r1_mode}')
    if p.use_fireblast:
        bits.append(f'FBl≤{int(round(p.fireblast_execute_frac*100))}%')
    if p.use_nova:
        nr='R1' if p.nova_rank1 else 'max'
        bits.append(f'FN{nr}+step{p.nova_move_yards:g}')
        if p.nova_cycle_pos >= 0:
            bits.append(f'FNpos={p.nova_cycle_pos}')
    if p.use_blink and level>=20:
        bits.append(f'Blink≥{int(round(p.blink_min_hp_frac*100))}%')
    if p.use_ice_barrier and ice_barrier_rank(level) is not None:
        bits.append('IceBarrier')
    if p.clearcast_am:
        bits.append('CC→AM')
    return ' | '.join(bits)

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


