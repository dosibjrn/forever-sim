from __future__ import annotations

"""Small priority-policy search space for Paladin smooth pack leveling.

The Fast model searches strategy parameters, not GCD permutations.  The policy
means "keep damage priorities rolling; survival controller overrides if behind".
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PriorityPolicy:
    name: str
    min_hp_fraction: float
    recovery_target_fraction: float
    mana_reserve_fraction: float
    consecration_min_mobs: int
    risk_sigma: float
    use_hoj_if_behind: bool = True
    use_immunity_if_critical: bool = True


@dataclass(frozen=True)
class ManaPlan:
    """Canonical ability cadences for the smooth Paladin policy.

    These plans intentionally *do not* encode spell ordering.  They only answer
    strategic questions such as "can I afford Holy Strike every cooldown, or
    every second cooldown?".  This keeps the Fast search on the North-Star side
    of the line: optimize priorities/resource pressure, not GCD permutations.
    A cadence of 0 means the ability is skipped.
    """

    name: str
    holy_strike_every: int = 1
    judgement_every: int = 1
    consecration_every: int = 1

    @staticmethod
    def factor(every: int) -> float:
        return 0.0 if int(every) <= 0 else 1.0 / float(every)


POLICIES = (
    PriorityPolicy("aggressive", .18, .58, .10, 2, 1.0),
    PriorityPolicy("balanced", .26, .68, .16, 2, 1.5),
    PriorityPolicy("safe", .34, .78, .22, 2, 2.0),
)


# Ordered from highest throughput / highest resource pressure toward increasingly
# conservative resource use.  The evaluator may prune suffixes once even a
# zero-recovery best case cannot beat an already-found plan.
MANA_PLANS = (
    ManaPlan("full", 1, 1, 1),
    ManaPlan("skip_consecration", 1, 1, 0),
    ManaPlan("holy_strike_2", 2, 1, 1),
    ManaPlan("judgement_2", 1, 2, 1),
    ManaPlan("both_2", 2, 2, 1),
    ManaPlan("lean", 3, 2, 0),
    ManaPlan("melee_seal_only", 0, 0, 0),
)
