from __future__ import annotations

"""Forever world-mob fixtures used by deterministic leveling proxies.

The 69893 client does not expose a trustworthy complete NPC stat database yet,
so this module deliberately does *not* invent Forever-specific mob buffs.  It
keeps the project's existing Classic-like normal world-mob raw-DPS curve and
splits ordinary melee targets into a small weighted family mix whose mean DPS
multiplier is exactly 1.0.  The family mix exists to model attack-frequency
sensitivity for block, thorns/Ret Aura, Redoubt, absorbs and healing pushback.

Target levels follow the solo-leveling objective: same-level ordinary mobs by
default.  Harder/easier target sensitivities are opt-in instead of silently
changing the baseline between classes.  These fixtures are ruleset-level.
"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class MobFamily:
    name: str
    weight: float
    swing_s: float
    dps_multiplier: float
    damage_sigma_fraction: float

    def as_dict(self) -> dict:
        return asdict(self)


# Weighted mean dps_multiplier = 1.0 and weighted mean swing_s = 2.0 sec.
# This preserves the old average-DPS assumption while exposing meaningful
# attack-frequency variation to shield/thorns mechanics.
WORLD_MELEE_FAMILIES: tuple[MobFamily, ...] = (
    MobFamily("fast_light", 0.25, 1.50, 0.92, 0.30),
    MobFamily("normal",     0.50, 2.00, 1.00, 0.35),
    MobFamily("slow_heavy",0.25, 2.50, 1.08, 0.40),
)

TARGET_LEVEL_OFFSETS: tuple[tuple[int, float], ...] = ((0, 1.0),)


def normal_world_raw_dps(mob_level: int) -> float:
    """Provisional Classic-like ordinary-world-mob raw physical DPS curve.

    This is intentionally the same linear curve previously embedded in the
    Paladin survival helper.  Target-level choice and attack-frequency families are modeled explicitly;
    the current default target offset is zero (same level).
    """
    return 4.0 + 0.38 * float(mob_level)


def weighted_family_dps_multiplier() -> float:
    return sum(f.weight * f.dps_multiplier for f in WORLD_MELEE_FAMILIES)


def weighted_family_swing_s() -> float:
    return sum(f.weight * f.swing_s for f in WORLD_MELEE_FAMILIES)


def fixture_snapshot(player_level: int) -> dict:
    rows=[]
    for offset, level_weight in TARGET_LEVEL_OFFSETS:
        mob_level=int(player_level)+int(offset)
        base=normal_world_raw_dps(mob_level)
        for family in WORLD_MELEE_FAMILIES:
            rows.append({
                "mob_level": mob_level,
                "level_weight": float(level_weight),
                "family": family.name,
                "family_weight": float(family.weight),
                "combined_weight": float(level_weight)*float(family.weight),
                "swing_s": float(family.swing_s),
                "raw_dps": base*float(family.dps_multiplier),
                "dps_multiplier": float(family.dps_multiplier),
                "damage_sigma_fraction": float(family.damage_sigma_fraction),
            })
    return {
        "kind": "ordinary_world_melee_mix",
        "player_level": int(player_level),
        "target_level_offsets": [list(x) for x in TARGET_LEVEL_OFFSETS],
        "weighted_family_dps_multiplier": weighted_family_dps_multiplier(),
        "weighted_family_swing_s": weighted_family_swing_s(),
        "rows": rows,
        "provenance": (
            "Forever 69893 NPC pages/stats unavailable; Classic-like normal-mob "
            "raw-DPS curve retained, with explicit swing-family mixture"
        ),
    }
