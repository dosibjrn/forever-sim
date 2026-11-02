"""Opt-in WF612/WF613-style adaptive + compatibility-repair controller.

Historical source: docs/evidence/druid-p7/recovered/raw/WF612/wf613_repair.py
and the WF612/WF613 handovers. This is a port of their search policy to
the current *paid* MythicSim Rust <-> gsim 2D executor, not a replay of
the old Go binary or a claim of identical historical random trajectories.
The shared source gear/talent/APL generator and native scorer are unchanged.

Every parent is a successfully paid local candidate; the first proposal
has no parent. Repair batches preserve one paid parent and explore the same
six axes combinations as WF613, each subject to source legality and a
separate paid native/world evaluation.
"""
from __future__ import annotations

import copy
import math

REPAIR_MOVES = (
    ("talents",),
    ("talents", "rotation"),
    ("gear",),
    ("gear", "rotation"),
    ("rotation",),
    ("gear", "talents", "rotation"),
)

# WF612's exploration families; WF613 adds bounded structural repair.
OPERATORS = (
    "fresh", "gear_large", "talent_rebuild", "apl_rebuild",
    "coupled_talent_apl", "coupled_gear_apl", "coupled_all",
    "destroy_repair", "structural_repair",
)

AXES = {
    "gear_large": ("gear", "gear", "gear"),
    "talent_rebuild": ("talents_rebuild",),
    "apl_rebuild": ("rotation_rebuild",),
    "coupled_talent_apl": ("talents", "rotation"),
    "coupled_gear_apl": ("gear", "rotation"),
    "coupled_all": ("gear", "talents", "rotation"),
    "destroy_repair": ("gear_rebuild", "talents_rebuild", "rotation_rebuild"),
}


class WF613Controller:
    """Diversified paid archive + adaptive exploration + WF613 repair batches."""

    def __init__(self):
        self.paid = []          # (measured balanced live DPS, request, fingerprint)
        self.pending = []       # (operator, SAME paid parent, move axes)
        self.tries = {x: 0 for x in OPERATORS}
        self.gains = {x: 0 for x in OPERATORS}
        self.best = float("-inf")
        self.stagnation = 0
        self.last_operator = None

    @staticmethod
    def _signature(q):
        player = q["raid"]["parties"][0]["players"][0]
        items = tuple(int(x["id"]) for x in player["equipment"]["items"])
        return (items, player["talentsString"],
                repr(player["rotation"]["priorityList"]))

    def _parent(self, rng):
        # Greedy top performers and a diversity archive, not a single elite.
        ranked = sorted(self.paid, key=lambda t: t[0], reverse=True)
        if rng.random() < 0.65:
            shortlist = ranked[:min(8, len(ranked))]
            weights = list(range(len(shortlist), 0, -1))
            return copy.deepcopy(rng.choices(shortlist, weights=weights)[0][1])
        # Novelty parent: sample from less frequently represented gear/talent
        # basins without assigning an unmeasured score.
        by_basin = {}
        for record in self.paid:
            sig = record[2]
            key = (sig[0][:4], sig[1])
            current = by_basin.get(key)
            if current is None or current[0] < record[0]:
                by_basin[key] = record
        return copy.deepcopy(rng.choice(list(by_basin.values()))[1])

    def propose(self, rng):
        """Return (already-paid parent or None, forced axes, family).

        No candidate is marked paid here. Caller validates and executes
        actual source/Rust/2D evaluation before calling observe().
        """
        if not self.paid:
            self.tries["fresh"] += 1
            return None, None, "fresh"
        if self.pending:
            operator, parent, axes = self.pending.pop(0)
            self.tries[operator] += 1
            return copy.deepcopy(parent), axes, operator

        # Reward actually improving operators; 3% selection floor for all
        # nine WF612 operator families, as in the historical handover.
        weights = []
        for operator in OPERATORS:
            tries = self.tries[operator]
            reward = self.gains[operator] / max(1, tries)
            weight = 0.03 + 0.6 * reward
            if operator in ("fresh", "destroy_repair", "structural_repair"):
                weight += min(0.9, self.stagnation / 100.0)
            else:
                weight += 0.25
            weights.append(weight)
        operator = rng.choices(OPERATORS, weights=weights)[0]
        if operator == "fresh":
            self.tries[operator] += 1
            return None, None, operator
        parent = self._parent(rng)
        if operator == "structural_repair":
            moves = list(REPAIR_MOVES)
            rng.shuffle(moves)
            # Same parent across all bounded legal neighbors. Any invalid
            # proposal is dropped by the shared source validator, never paid.
            self.pending = [(operator, parent, axes) for axes in moves[:5]]
            name, parent, axes = self.pending.pop(0)
            self.tries[name] += 1
            return copy.deepcopy(parent), axes, name
        self.tries[operator] += 1
        return parent, AXES[operator], operator

    def observe(self, request, world_dps, operator):
        """Only caller-verified paid native/world results enter the archive."""
        if operator not in self.tries:
            raise ValueError("WF613_UNKNOWN_OPERATOR")
        if type(world_dps) not in (float, int) or not math.isfinite(world_dps) or world_dps < 0:
            raise ValueError("WF613_UNPAID_OR_INVALID_SCORE")
        before = self.best
        if world_dps > self.best:
            self.best = world_dps
            self.gains[operator] += 1
            self.stagnation = 0
        else:
            self.stagnation += 1
        signature = self._signature(request)
        self.paid.append((float(world_dps), copy.deepcopy(request), signature))
        # Bound archive by strongest candidates plus nonredundant basins.
        if len(self.paid) > 48:
            ranked = sorted(self.paid, key=lambda t: t[0], reverse=True)
            archive = ranked[:12]
            seen = {(row[2][0][:4], row[2][1]) for row in archive}
            for row in ranked[12:]:
                key = (row[2][0][:4], row[2][1])
                if key not in seen:
                    seen.add(key)
                    archive.append(row)
                if len(archive) >= 32:
                    break
            self.paid = archive

    def diagnostics(self):
        return {"strategy": "wf613",
                "operator_attempts": dict(self.tries),
                "operator_best_improvements": dict(self.gains),
                "paid_archive_size": len(self.paid),
                "best_paid_balanced_world_dps": (self.best if self.paid else None)}
