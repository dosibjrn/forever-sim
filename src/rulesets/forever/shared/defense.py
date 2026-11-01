from __future__ import annotations

"""Shared physical-defense helpers for the Forever ruleset.

M44 centralizes the low-level defense contract so Mage/Paladin/Druid do not keep
shadow copies of armor/HP formulas.  The armor and +Defense skill relationships
are qualified Classic-era combat-table proxies until Forever publishes a more
specific server-side formula.  Wowhead Forever exposes the Defense skill entity
(204) and describes +Defense as +0.04% miss/dodge/parry/block per point. Armor
uses the qualified Classic-era attacker-level curve (1-59 versus 60+).

The helpers deliberately separate avoidance from block: block does not avoid an
attack, it reduces damage on a landed attack.  Crit/crushing suppression is not
currently part of the ordinary-leveling incoming-damage model and therefore is
not silently credited here.
"""

from dataclasses import dataclass

ARMOR_CAP = 0.75
DEFENSE_CHANCE_PER_SKILL = 0.0004
HP_PER_STAMINA = 10.0


@dataclass(frozen=True)
class DefensiveState:
    hp: float
    armor: float
    armor_reduction: float
    defense_skill_bonus: float = 0.0
    avoidance: float = 0.0
    block_chance: float = 0.0
    block_value: float = 0.0


def armor_constant(attacker_level: int) -> float:
    """Qualified Classic-era physical-mitigation constant for attacker level."""
    level=max(1.0,float(attacker_level))
    if level < 60.0:
        return 400.0 + 85.0 * level
    return 467.5 * level - 22167.5


def armor_reduction(armor: float, attacker_level: int) -> float:
    """Physical mitigation fraction against an ordinary attacker.

    Forever does not currently publish the server-side curve, so this is named
    and documented as a Classic-era proxy rather than Forever source truth.
    """
    armor = max(0.0, float(armor))
    denom = max(1.0, armor + armor_constant(attacker_level))
    return max(0.0, min(ARMOR_CAP, armor / denom))


def representative_player_hp(level: int, stamina_bonus: float = 0.0, *,
                             stamina_multiplier: float = 1.0,
                             total_hp_multiplier: float = 1.0) -> float:
    """Representative leveling HP with explicit Stamina propagation."""
    base = 140.0 + 18.0 * float(level)
    stamina = max(0.0, float(stamina_bonus)) * max(0.0, float(stamina_multiplier))
    return max(1.0, (base + HP_PER_STAMINA * stamina) * max(0.0, float(total_hp_multiplier)))


def defense_avoidance(defense_skill_bonus: float, *,
                      can_miss: bool = True,
                      can_dodge: bool = True,
                      can_parry: bool = True) -> float:
    """Additional complete-avoidance probability from bonus Defense skill."""
    channels = int(bool(can_miss)) + int(bool(can_dodge)) + int(bool(can_parry))
    return max(0.0, float(defense_skill_bonus)) * DEFENSE_CHANCE_PER_SKILL * channels


def defense_block_chance(defense_skill_bonus: float, *, has_shield: bool) -> float:
    """Additional block probability from bonus Defense skill."""
    if not has_shield:
        return 0.0
    return max(0.0, float(defense_skill_bonus)) * DEFENSE_CHANCE_PER_SKILL


def apply_armor(raw_damage: float, armor: float, attacker_level: int) -> float:
    return max(0.0, float(raw_damage)) * (1.0 - armor_reduction(armor, attacker_level))
