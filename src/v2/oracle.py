from __future__ import annotations

"""Adapter to the frozen v1 stochastic simulator.

Nothing in v2 search should depend on v1 internals beyond this adapter.  It is
used for differential tests / calibration and final candidate validation.
"""

from src.engine_registry import eng


def score_fixed_policy(level: int, talents: eng.Talents, policy: eng.Policy,
                       cfg: eng.SimConfig, *, mobs: int = 100, seed: int = 1) -> dict:
    return eng.simulate_chain(level, talents, policy, cfg, n=int(mobs), seed=int(seed))
