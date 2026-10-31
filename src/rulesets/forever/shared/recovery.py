from __future__ import annotations

"""Shared out-of-combat recovery contract for Forever leveling models.

The cross-class contract is intentionally simple:
* when a caller chooses a full sit recovery, this module returns the time to 100% HP/mana; callers may carry resources across pulls;
* use ordinary level-appropriate vendor food + water concurrently;
* a healer may cast a direct heal before sitting only when that lowers total
  time-to-full; whole casts are evaluated, not fractional healing;
* class-specific transitions (for example Druid re-shifting) are charged by the
  caller rather than hidden inside the generic food/water model.

Consumable rows are the ordinary Vanilla/Forever vendor tiers.  At 45+ the
normal vendor ceiling remains Roasted Quail / Morning Glory Dew; special event,
quest and class-conjured consumables are intentionally outside this shared
baseline.
"""

from dataclasses import dataclass
import math
from typing import Iterable


@dataclass(frozen=True)
class ConsumableTier:
    required_level: int
    amount: float
    duration_s: float
    name: str

    @property
    def rate_per_s(self) -> float:
        return float(self.amount) / max(1e-9, float(self.duration_s))


# Current Wowhead Forever ordinary vendor-food ladder.
FOOD_TIERS: tuple[ConsumableTier, ...] = (
    ConsumableTier(1, 61.2, 18.0, "starter food"),
    ConsumableTier(5, 243.6, 21.0, "Haunch of Meat tier"),
    ConsumableTier(15, 552.0, 24.0, "Mutton Chop tier"),
    ConsumableTier(25, 874.8, 27.0, "Hot Wolf Ribs tier"),
    ConsumableTier(35, 1392.0, 30.0, "Filet of Redgill tier"),
    ConsumableTier(45, 2148.0, 30.0, "Roasted Quail tier"),
    ConsumableTier(55, 2452.0, 30.0, "Filet o' Flank tier"),
)

# Current ordinary vendor-water ladder.  Level 45 Morning Glory Dew remains the
# regular-vendor ceiling through 60; Mage-conjured water is a class-specific
# option and must not silently improve the shared comparison baseline.
WATER_TIERS: tuple[ConsumableTier, ...] = (
    ConsumableTier(1, 151.2, 18.0, "Refreshing Spring Water tier"),
    ConsumableTier(5, 436.8, 21.0, "Ice Cold Milk tier"),
    ConsumableTier(15, 835.2, 24.0, "Melon Juice tier"),
    ConsumableTier(25, 1344.6, 27.0, "Sweet Nectar tier"),
    ConsumableTier(35, 1992.0, 30.0, "Moonberry Juice tier"),
    ConsumableTier(45, 2934.0, 30.0, "Morning Glory Dew tier"),
)


@dataclass(frozen=True)
class HealOption:
    name: str
    heal: float
    mana: float
    cast_s: float


@dataclass(frozen=True)
class RecoveryResult:
    total_s: float
    food_s: float
    water_s: float
    heal_cast_s: float
    heal_casts: int
    heal_name: str | None
    hp_missing_after_heals: float
    mana_missing_after_heals: float
    method: str
    food_tier: str
    water_tier: str


def _tier(rows: Iterable[ConsumableTier], level: int) -> ConsumableTier:
    eligible = [r for r in rows if int(r.required_level) <= int(level)]
    if not eligible:
        raise ValueError(f"no consumable tier available at level {level}")
    return eligible[-1]


def food_tier(level: int) -> ConsumableTier:
    return _tier(FOOD_TIERS, level)


def water_tier(level: int) -> ConsumableTier:
    return _tier(WATER_TIERS, level)


def _eat_drink_times(level: int, hp_missing: float, mana_missing: float) -> tuple[float, float]:
    food = food_tier(level)
    water = water_tier(level)
    food_s = max(0.0, float(hp_missing)) / food.rate_per_s
    water_s = max(0.0, float(mana_missing)) / water.rate_per_s
    return food_s, water_s


RECOVERY_SOLVER_ID = "forever_shared_recovery_v2"


def solve_recovery(level: int, hp_missing: float, mana_missing: float,
                    heal_options: Iterable[HealOption] = (), *,
                    passive_mana_regen_per_s: float = 0.0,
                    food_override: ConsumableTier | None = None,
                    water_override: ConsumableTier | None = None) -> RecoveryResult:
    """Minimum deterministic time to return both resources to 100%.

    Food and water run concurrently.  Direct heals are whole casts made before
    sitting.  We enumerate a small number of casts for every supplied heal rank
    and choose the candidate minimizing

        cast_time + max(food_time, water_time).

    This naturally implements the desired "heal until HP and mana recovery take
    about the same time" behavior without a separate threshold policy.
    """
    hp0 = max(0.0, float(hp_missing))
    mana0 = max(0.0, float(mana_missing))
    food = food_override or food_tier(level)
    water = water_override or water_tier(level)
    passive_mana_regen_per_s=max(0.0,float(passive_mana_regen_per_s))

    best = None
    options = [None] + [h for h in heal_options if h.heal > 0 and h.mana >= 0 and h.cast_s >= 0]
    for heal in options:
        max_casts = 0 if heal is None else int(math.ceil(hp0 / max(1e-9, heal.heal)))
        # One extra over-heal cast can never improve HP but can only add mana/time,
        # so 0..ceil(deficit/heal) is a complete search.
        for casts in range(max_casts + 1):
            heal_amount = 0.0 if heal is None else casts * float(heal.heal)
            heal_mana = 0.0 if heal is None else casts * float(heal.mana)
            cast_s = 0.0 if heal is None else casts * float(heal.cast_s)
            hp_after = max(0.0, hp0 - heal_amount)
            # Flat mp5-style regeneration continues during combat downtime and
            # while drinking.  During pre-drink heal casts it also ticks, so the
            # remaining deficit is reduced by cast_time * passive regen.
            mana_after = max(0.0, mana0 + heal_mana - cast_s*passive_mana_regen_per_s)
            food_s = hp_after / food.rate_per_s
            water_s = mana_after / (water.rate_per_s + passive_mana_regen_per_s)
            total = cast_s + max(food_s, water_s)
            key = (total, casts, mana_after)
            if best is None or key < best[0]:
                best = (key, heal, casts, hp_after, mana_after, food_s, water_s, cast_s)

    assert best is not None
    _, heal, casts, hp_after, mana_after, food_s, water_s, cast_s = best
    if casts > 0:
        method = "heal+food+water"
        heal_name = heal.name if heal else None
    else:
        method = "food+water" if (hp0 > 0 and mana0 > 0) else ("food" if hp0 > 0 else ("water" if mana0 > 0 else "none"))
        heal_name = None
    return RecoveryResult(
        total_s=float(cast_s + max(food_s, water_s)),
        food_s=float(food_s), water_s=float(water_s), heal_cast_s=float(cast_s),
        heal_casts=int(casts), heal_name=heal_name,
        hp_missing_after_heals=float(hp_after), mana_missing_after_heals=float(mana_after),
        method=method, food_tier=food.name, water_tier=water.name,
    )


def recover_to_full(level: int, hp_missing: float, mana_missing: float,
                    heal_options: Iterable[HealOption] = (), *,
                    passive_mana_regen_per_s: float = 0.0,
                    food_override: ConsumableTier | None = None,
                    water_override: ConsumableTier | None = None) -> RecoveryResult:
    """Compatibility alias for pre-v0.11.48.71 callers.

    New Forever class models must call :func:`solve_recovery` directly so the
    cross-class recovery authority is explicit and machine-auditable.
    """
    return solve_recovery(
        level, hp_missing, mana_missing, heal_options,
        passive_mana_regen_per_s=passive_mana_regen_per_s,
        food_override=food_override, water_override=water_override,
    )
