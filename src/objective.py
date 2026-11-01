from __future__ import annotations

"""Authoritative Classic Era 11->60 leveling objective.

The combat workload used by both analytic and stochastic scorers alternates
between character-level+1 and character-level+2 mobs.  Objective weights must
therefore use the XP earned from that same workload, not equal-level mob XP.
"""

OBJECTIVE_VERSION = 'classic_era_lplus1_lplus2_xp_weight_v2'
TARGET_DING_LEVEL = 60
FIRST_XP_LEVEL = 11
LAST_XP_LEVEL = 59
WORKLOAD_OFFSETS = (1, 2)

XP_TO_NEXT_LEVEL = {
    11:8800,12:10100,13:11400,14:12900,15:14400,16:16000,17:17700,18:19400,19:21300,20:23200,
    21:25200,22:27300,23:29400,24:31700,25:34000,26:36400,27:38900,28:41400,29:44300,30:47400,
    31:50800,32:54500,33:58600,34:62800,35:67100,36:71600,37:76100,38:80800,39:85700,40:90700,
    41:95800,42:101000,43:106300,44:111800,45:117500,46:123200,47:129100,48:135100,49:141200,50:147500,
    51:153900,52:160400,53:167100,54:173900,55:180800,56:187900,57:195000,58:202300,59:209800,
}


def _round_xp(v: float) -> int:
    # In-game XP is integral. Positive values use ordinary half-up rounding;
    # avoid Python's bankers-rounding at exact .5 boundaries.
    return int(v + 0.5)


def xp_to_next(level: int) -> int:
    return int(XP_TO_NEXT_LEVEL.get(int(level), 0))


def same_level_mob_xp(level: int) -> float:
    return float(int(level) * 5 + 45)


def mob_xp(character_level: int, mob_level: int) -> int:
    """Solo outdoor Azeroth XP for same/higher-level mobs used by our workload.

    The optimizer only needs same-level and L+1/L+2 values. Higher-level XP is
    the mob-level base XP multiplied by +5% per level above the character.
    """
    cl = int(character_level)
    ml = int(mob_level)
    base = float(ml * 5 + 45)
    if ml >= cl:
        return _round_xp(base * (1.0 + 0.05 * (ml - cl)))
    raise ValueError('objective.mob_xp only models same/higher-level workload mobs')


def workload_xp_per_mob(level: int) -> float:
    vals = [mob_xp(level, int(level) + off) for off in WORKLOAD_OFFSETS]
    return sum(vals) / len(vals)


def estimated_workload_mobs(level: int) -> float:
    xp = xp_to_next(level)
    per_mob = workload_xp_per_mob(level) if xp > 0 else 0.0
    return xp / per_mob if per_mob > 0 else 0.0


def level_weight_per_100(level: int) -> float:
    return estimated_workload_mobs(level) / 100.0


def search_level_weight_per_100(level: int) -> float:
    level = int(level)
    if level >= FIRST_XP_LEVEL:
        return level_weight_per_100(level)
    if level == FIRST_XP_LEVEL - 1:
        w11 = level_weight_per_100(FIRST_XP_LEVEL)
        w12 = level_weight_per_100(FIRST_XP_LEVEL + 1)
        return max(0.0, 2.0 * w11 - w12)
    return 0.0


def objective_level_meta(level: int) -> dict:
    included = FIRST_XP_LEVEL <= int(level) <= LAST_XP_LEVEL
    return {
        'xp_to_next': xp_to_next(level),
        'workload_xp_per_mob': workload_xp_per_mob(level) if included else 0.0,
        'estimated_workload_mobs': estimated_workload_mobs(level),
        'objective_weight_per_100': level_weight_per_100(level),
        'search_weight_per_100': search_level_weight_per_100(level),
        'objective_included': included,
        'objective_version': OBJECTIVE_VERSION,
    }


# Compatibility aliases for persisted/viewer fields from pre-v2 objective state.
# Their values now reflect the authoritative L+1/L+2 workload.
def estimated_same_level_mobs(level: int) -> float:
    return estimated_workload_mobs(level)
