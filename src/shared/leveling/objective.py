from __future__ import annotations

"""Transitional leveling objective compatibility helpers.

The canonical Classic-proxy target HP curve is scenario-owned in
src.scenarios.leveling_targets. Historical names remain re-exported here for
compatibility. Expected-value scoring is implemented in src.optimization;
hit-chance helpers remain legacy class-backend dependencies, not a second
game-data source.
"""

from src.scenarios.leveling_targets import MOB_BASE_HP, mob_hp, representative_hp


def physical_hit_chance(level: int, mob_level: int, bonus_pct: float = 0.0) -> float:
    diff = max(0, int(mob_level) - int(level))
    miss = 5.0 + max(0, diff - 1) * 1.0
    return max(0.70, min(0.99, 1.0 - (miss - float(bonus_pct)) / 100.0))


def spell_hit_chance(level: int, mob_level: int, bonus_pct: float = 0.0) -> float:
    """Classic/Forever spell-hit baseline shared by class expected scorers.

    Same-level spells have 4% base miss. The +3 level jump follows the classic
    discontinuity already used by the Mage engine. bonus_pct is percentage
    points of spell hit from talents/gear.
    """
    diff = int(mob_level) - int(level)
    miss = 4.0 + (diff if diff <= 2 else 2.0 + 11.0 * (diff - 2))
    miss = max(1.0, min(100.0, miss - float(bonus_pct)))
    return max(0.0, min(0.99, 1.0 - miss / 100.0))
