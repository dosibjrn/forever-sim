from __future__ import annotations

"""Ruleset/class-neutral pieces of the solo-leveling objective.

The target HP curve is the project's canonical ordinary-melee-mob reference.
Rulesets/classes may replace this later, but they must opt in explicitly rather
than reaching into another class engine.
"""

# CMaNGOS/mangoszero warrior-class BaseHealthExp0 canonical ordinary melee
# target curve. L1–10 were previously omitted and silently CLAMPED to L11
# (222 HP), making low-level full-cycle combat artificially impossible.
# Source: https://raw.githubusercontent.com/mangoszero/database/325948a78015794e6cc626212bc19fee70c805b2/World/Setup/FullDB/creature_template_classlevelstats.sql
# Unit class=1, BaseHealthExp0, rows 1–60. Classic proxy, NOT verified Forever
# server mob health; creature-specific multipliers and spawns remain unknown.
MOB_BASE_HP = {
    1:42,2:55,3:71,4:86,5:102,6:120,7:137,8:156,9:176,10:198,
    11:222,12:247,13:273,14:300,15:328,16:356,17:386,18:417,19:449,20:484,
    21:521,22:562,23:605,24:651,25:699,26:750,27:800,28:853,29:905,30:955,
    31:1006,32:1057,33:1110,34:1163,35:1220,36:1277,37:1336,38:1395,39:1459,40:1524,
    41:1585,42:1651,43:1716,44:1782,45:1848,46:1919,47:1990,48:2062,49:2138,50:2215,
    51:2292,52:2371,53:2453,54:2533,55:2614,56:2699,57:2784,58:2871,59:2961,60:3052,
    61:3144,62:3237,
}


def mob_hp(level: int) -> float:
    level = max(1, min(62, int(level)))
    return float(MOB_BASE_HP[level])


def representative_hp(level: int) -> float:
    """Default leveling target: one ordinary mob at the player's own level."""
    return mob_hp(level)


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
