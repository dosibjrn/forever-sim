from __future__ import annotations

"""Mage leveling-chain resource helpers.

This module models *between-pull* choices only.  Combat kernels still own spell
mana spending.  Values that Forever public data does not expose cleanly are
profile-scoped, never hidden constants.
"""

from dataclasses import dataclass
from src.rulesets.forever.shared.recovery import ConsumableTier, water_tier


@dataclass(frozen=True)
class ManaGemTier:
    required_level: int
    restore: float
    name: str


# Current Forever keeps the vanilla gem ladder.  Restore values are rank-midpoint
# values from the public item/spell rows; use cooldown is 120 s.
MANA_GEMS: tuple[ManaGemTier, ...] = (
    ManaGemTier(28, 400.0, "Mana Agate"),
    ManaGemTier(38, 600.0, "Mana Jade"),
    ManaGemTier(48, 850.0, "Mana Citrine"),
    ManaGemTier(58, 1100.0, "Mana Ruby"),
)

# Best water usable at the level for the Mage baseline.  This deliberately uses
# the best normally usable recovery item, not the lowest self-conjurable rank.
# The L55 entry is Crystal Water usable at 55 even though self-conjuring it is a
# L60 spell; the optimizer's default objective is recovery speed, not self-found.
MAGE_BEST_WATER: tuple[ConsumableTier, ...] = (
    ConsumableTier(1, 151.2, 18.0, "Refreshing Spring Water tier"),
    ConsumableTier(5, 436.8, 21.0, "Ice Cold Milk tier"),
    ConsumableTier(15, 835.2, 24.0, "Melon Juice tier"),
    ConsumableTier(25, 1344.6, 27.0, "Sweet Nectar tier"),
    ConsumableTier(35, 1992.0, 30.0, "Moonberry Juice tier"),
    ConsumableTier(45, 2934.0, 30.0, "Morning Glory Dew tier"),
    ConsumableTier(55, 4200.0, 30.0, "Crystal Water tier"),
)

MAGE_SELF_CONJURED_WATER: tuple[ConsumableTier, ...] = (
    ConsumableTier(10, 436.8, 21.0, "Conjured Fresh Water tier"),
    ConsumableTier(20, 835.2, 24.0, "Conjured Purified Water tier"),
    ConsumableTier(30, 1344.6, 27.0, "Conjured Spring Water tier"),
    ConsumableTier(40, 1992.0, 30.0, "Conjured Mineral Water tier"),
    ConsumableTier(50, 2934.0, 30.0, "Conjured Sparkling Water tier"),
    ConsumableTier(60, 4200.0, 30.0, "Conjured Crystal Water tier"),
)


def mana_gem_tier(level: int) -> ManaGemTier | None:
    rows = [x for x in MANA_GEMS if x.required_level <= int(level)]
    return rows[-1] if rows else None


def best_mage_water(level: int, *, best_available: bool = True) -> ConsumableTier:
    table=MAGE_BEST_WATER if best_available else MAGE_SELF_CONJURED_WATER
    rows=[x for x in table if x.required_level <= int(level)]
    return rows[-1] if rows else water_tier(level)


def ooc_mana_regen_per_s(stats) -> float:
    """Mage out-of-combat passive mana regeneration used by shared recovery.

    Recovery timing itself is class-agnostic; this helper owns only the Mage
    input to that shared solver so every Mage backend uses the same Spirit/mp5
    semantics.
    """
    return max(0.0, (12.5 + float(stats.spirit) / 4.0) / 2.0 + float(getattr(stats, "mp5", 0.0)) / 5.0)


def primary_mana_floor(level: int, policy, talents, stats, engine) -> float:
    """Minimum sensible mana reserve before starting another pull.

    This is intentionally not a full-fight prediction; the previous pull's
    actual spend is used by the chain driver for the stronger continuation gate.
    """
    if getattr(policy, "primary", "") == "arcane_missiles":
        r = engine.latest(engine.ARCANE_MISSILES, level)
        return float(r.mana if r else 0.0)
    table = engine.SPELLS.get(getattr(policy, "primary", ""), engine.FROSTBOLT)
    r = engine.latest(table, level) if table else None
    if r is None:
        return 0.0
    if r.spell == "arcane_blast":
        return float(stats.base_mana) * float(engine.wh.ARCANE_BLAST_BASE_MANA_PCT)
    return float(engine.mana_cost(r, talents, stats))
