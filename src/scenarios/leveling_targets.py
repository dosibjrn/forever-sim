from __future__ import annotations

"""Scenario-owned Classic-proxy ordinary-melee target HP reference.

This CMaNGOS/mangoszero curve is an explicit Classic proxy, NOT verified Forever
server mob health. It is a scenario input only; it does not prove the health of
any particular Forever creature or establish source legality.
"""

# CMaNGOS/mangoszero warrior-class BaseHealthExp0 canonical ordinary melee
# target curve. L1–10 were previously omitted and silently CLAMPED to L11
# (222 HP), making low-level full-cycle combat artificially impossible.
# Source: https://raw.githubusercontent.com/mangoszero/database/325948a78015794e6cc626212bc19fee70c805b2/World/Setup/FullDB/creature_template_classlevelstats.sql
# Unit class=1, BaseHealthExp0, supported levels 1–62. Classic proxy, NOT verified Forever
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
