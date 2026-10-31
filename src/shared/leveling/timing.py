from __future__ import annotations

"""Shared timing buckets for cross-class solo-leveling evaluation.

The optimizer treats a mob cycle as three non-overlapping buckets:

    kill/combat -> recovery -> between-pull travel

`travel` is deliberately *not* allowed to silently subsidize recovery.  A class
may change the travel duration through a documented movement-speed multiplier,
but the baseline meaning and ordering are shared by every backend.
"""

BASE_BETWEEN_PULL_TRAVEL_S = 2.2
TIMING_CONTRACT_VERSION = "solo_leveling_timing_v1"


def between_pull_travel_s(*, speed_multiplier: float = 1.0) -> float:
    return BASE_BETWEEN_PULL_TRAVEL_S / max(0.1, float(speed_multiplier))
