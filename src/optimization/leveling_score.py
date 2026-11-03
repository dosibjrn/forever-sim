"""Game-model-independent expected-value scoring for leveling combat cycles.

Callers supply scenario target HP and estimated combat/resource inputs. This
module does not derive Warcraft facts, source legality, or scenario data.
"""

from __future__ import annotations


SUSTAINABLE_MANA_FRACTION = 0.18


def score_combat_cycle(
    *,
    target_hp: float,
    dps: float,
    mana_spent: float,
    mana_pool: float,
    regen_per_s: float,
    travel_s: float,
    rotation: str,
    profile: str,
    flags: list[str],
    details: dict | None = None,
    recovery_s_override: float | None = None,
) -> dict:
    """Score one expected kill/recovery/travel cycle in centiseconds."""
    kill_s = float(target_hp) / max(0.1, float(dps))
    sustainable = max(0.0, SUSTAINABLE_MANA_FRACTION * float(mana_pool))
    recovery_s = (
        max(0.0, float(mana_spent) - sustainable)
        / max(0.1, float(regen_per_s))
        if recovery_s_override is None
        else max(0.0, float(recovery_s_override))
    )
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
