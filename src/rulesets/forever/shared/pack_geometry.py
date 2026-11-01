from __future__ import annotations

"""Shared deterministic pack-exposure helpers for Forever leveling proxies.

The leveling models intentionally avoid inventing a world-spawn layout.  This
module therefore separates two questions:

* damage geometry: how many already-engaged mobs are alive while damage is dealt;
* acquisition geometry: how long it took to gather those mobs in the first place.

Only damage geometry is modeled here.  Acquisition time remains class/model
specific until there is a defensible route/world assumption.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PackExposure:
    pull_size: int
    avg_alive: float
    peak_alive: float
    sequential_avg_alive: float
    aoe_fraction: float

    def as_dict(self) -> dict:
        return {
            "pull_size": int(self.pull_size),
            "avg_alive": float(self.avg_alive),
            "peak_alive": float(self.peak_alive),
            "sequential_avg_alive": float(self.sequential_avg_alive),
            "aoe_fraction": float(self.aoe_fraction),
        }


def estimate_pack_exposure(
    pull_size: int,
    focus_dps: float,
    background_dps_per_alive: float,
    *,
    aoe_fraction_cap: float = 0.85,
    aoe_lifetime_credit: float = 0.55,
    iterations: int = 2,
) -> PackExposure:
    """Estimate average and peak simultaneous attackers for an engaged pack.

    ``focus_dps`` is damage concentrated on the kill target.  ``background`` is
    damage each currently alive mob receives from true AoE/retaliation effects.
    With no background damage, average alive count is the exact sequential-kill
    result ``(n+1)/2`` for equal-HP mobs.  AoE keeps more mobs alive for less of
    the encounter, so average alive count moves upward toward ``n`` only by the
    fraction of throughput that is genuinely spread across the pack.

    ``peak_alive`` is deliberately the full already-engaged pack.  It is the
    appropriate pressure bound for cast pushback and "can I safely get this heal
    off?" checks.  Average exposure remains appropriate for total expected
    damage/recovery bookkeeping.
    """
    n = max(1, int(pull_size))
    focus = max(0.0, float(focus_dps))
    bg = max(0.0, float(background_dps_per_alive))
    sequential = (n + 1.0) / 2.0
    avg_alive = sequential
    aoe_fraction = 0.0
    for _ in range(max(1, int(iterations))):
        background = bg * avg_alive
        pack_dps = max(1e-9, focus + background)
        aoe_fraction = min(float(aoe_fraction_cap), max(0.0, background / pack_dps))
        avg_alive = sequential + (n - sequential) * aoe_fraction * float(aoe_lifetime_credit)
    avg_alive = max(1.0, min(float(n), float(avg_alive)))
    return PackExposure(
        pull_size=n,
        avg_alive=avg_alive,
        peak_alive=float(n),
        sequential_avg_alive=sequential,
        aoe_fraction=aoe_fraction,
    )
