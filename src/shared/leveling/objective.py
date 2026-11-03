from __future__ import annotations

"""Transitional leveling objective helpers.

The canonical Classic-proxy target HP curve is scenario-owned in
src.scenarios.leveling_targets. Its historical names remain re-exported
here for compatibility. Hit-chance and expected-result helpers remain legacy
class-backend dependencies, not a second game-data source.
"""

from src.scenarios.leveling_targets import MOB_BASE_HP, mob_hp, representative_hp


def physical_hit_chance(level: int, mob_level: int, bonus_pct: float = 0.0) -> float:
    diff = max(0, int(mob_level) - int(level))
    miss = 5.0 + max(0, diff - 1) * 1.0
    return max(0.70, min(0.99, 1.0 - (miss - float(bonus_pct)) / 100.0))


def spell_hit_chance(level: int, mob_level: int, bonus_pct: float = 0.0) -> float:
    """Classic/Forever spell-hit baseline shared by class expected scorers.

    Same-level spells have 4% base miss.  The +3 level jump follows the classic
    discontinuity already used by the Mage engine. ``bonus_pct`` is percentage
    points of spell hit from talents/gear.
    """
    diff = int(mob_level) - int(level)
    miss = 4.0 + (diff if diff <= 2 else 2.0 + 11.0 * (diff - 2))
    miss = max(1.0, min(100.0, miss - float(bonus_pct)))
    return max(0.0, min(0.99, 1.0 - miss / 100.0))


def combat_result(*, level: int, dps: float, mana_spent: float, mana_pool: float,
                  regen_per_s: float, travel_s: float, rotation: str, profile: str,
                  flags: list[str], details: dict | None = None,
                  recovery_s_override: float | None = None) -> dict:
    """Compact expected-value scorer used by experimental class backends."""
    hp = representative_hp(level)
    kill_s = hp / max(0.1, float(dps))
    sustainable = max(0.0, 0.18 * mana_pool)
    recovery_s = (max(0.0, float(mana_spent) - sustainable) / max(0.1, float(regen_per_s))
                  if recovery_s_override is None else max(0.0, float(recovery_s_override)))
    total = max(0.25, kill_s + recovery_s + max(0.0, float(travel_s)))
    out = {
        "total_s": 100.0 * total,
        "kill_s": 100.0 * kill_s,
        "recovery_s": 100.0 * recovery_s,
        "travel_s": 100.0 * max(0.0, float(travel_s)),
        "dps": float(dps),
        "mana_spent_per_mob": float(mana_spent),
        "profile": profile,
        "rotation": rotation,
        "approximation_flags": list(flags),
    }
    if details:
        out.update(details)
    return out
