"""Source-legal talent neighbor frontier; no class-specific allocation tables.

Candidates are derived from the canonical GameIR talent tree. Unsupported
ranks are never silently converted to no-op states. The caller, not this
module, chooses which legal state receives an expensive simulation.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Mapping

from src.game.source_objective_relevance import solo_threat_exclusion


def allocation_key(selection: Mapping[str, int]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted((str(k), int(v)) for k, v in selection.items() if int(v) > 0))


@dataclass(frozen=True)
class Neighbor:
    allocation: tuple[tuple[str, int], ...]
    operation: str
    changed_ids: tuple[str, ...]

    def as_dict(self):
        return {'allocation': dict(self.allocation), 'operation': self.operation,
                'changed_ids': list(self.changed_ids)}


def source_legal_talent_neighbors(ir, allocation: Mapping[str, int], *, level: int, bonus_talent_points: int = 0) -> dict:
    """All one-point edits, transfers and legal full-rank macro proposals.

    A rank sweep is an acceleration *proposal*, not an instantaneous leveling
    transition. Each proposed allocation is validated against the full
    source-derived rank, prerequisite, tree row and total-point rules.
    """
    # Preserve the existing legacy legality check only when that old search
    # executes; importing the generic frontier identity must not load GameIR.
    from src.game.talents import validate_talent_selection, available_talent_points

    validate_talent_selection(ir, allocation, level=level, bonus_talent_points=bonus_talent_points)
    roster = tuple(ir.talents)
    current = dict(allocation_key(allocation))
    # Explicitly checked objective-neutral ranks remain legal optimizer options.
    # Unparsed ranks without such proof are still excluded from paid search.
    rank_rows = {t.id: {int(r.rank) for r in t.ranks
                        if r.modifiers or solo_threat_exclusion(ir, r) is not None}
                 for t in roster}
    blocked = tuple(t.id for t in roster if not rank_rows[t.id])
    candidates: dict[tuple, Neighbor] = {}
    rejected = Counter()
    generated = 0
    max_points = available_talent_points(level, bonus_talent_points=bonus_talent_points)

    def offer(proposal, op, changed):
        nonlocal generated
        key = allocation_key(proposal)
        if key == allocation_key(current):
            return
        generated += 1
        # A rank jump is legal only if all intermediate sourced executable
        # ranks exist. Never leap across an unknown/no-op rank.
        for family, rank in key:
            if any(i not in rank_rows[family] for i in range(1, rank+1)):
                rejected['missing_intermediate_executable_rank'] += 1
                return
        try:
            validate_talent_selection(ir, dict(key), level=level, bonus_talent_points=bonus_talent_points)
        except ValueError as exc:
            rejected[str(exc).split(':', 1)[0]] += 1
            return
        if key not in candidates:
            candidates[key] = Neighbor(key, op, tuple(changed))

    for talent in roster:
        old = current.get(talent.id, 0)
        if old < int(talent.max_rank):
            proposed = dict(current)
            proposed[talent.id] = old + 1
            offer(proposed, 'rank_up', (talent.id,))
            # Source-legal macro step: avoid spending five costly searches to
            # discover that 5/5 is better than 1/5. Intermediate ranks remain
            # in the frontier through the rank_up operation above.
            if old + 1 < int(talent.max_rank):
                proposed[talent.id] = min(int(talent.max_rank), old + max_points - sum(current.values()))
                if proposed[talent.id] > old + 1:
                    offer(proposed, 'rank_sweep', (talent.id,))
        if old:
            proposed = dict(current)
            if old == 1:
                proposed.pop(talent.id)
            else:
                proposed[talent.id] = old - 1
            offer(proposed, 'rank_down', (talent.id,))
    # Reallocate one point from any currently selected talent to every other
    # family, including ones that become legal only after the transfer.
    for donor in roster:
        if current.get(donor.id, 0) <= 0:
            continue
        for receiver in roster:
            if receiver.id == donor.id or current.get(receiver.id, 0) >= int(receiver.max_rank):
                continue
            proposed = dict(current)
            proposed[donor.id] -= 1
            if not proposed[donor.id]:
                proposed.pop(donor.id)
            proposed[receiver.id] = proposed.get(receiver.id, 0) + 1
            offer(proposed, 'point_transfer', (donor.id, receiver.id))
    return {'neighbors': tuple(candidates.values()), 'generated': generated,
            'legal': len(candidates), 'rejected_by_reason': dict(rejected),
            'unsupported_talent_ids': blocked,
            'source_talent_families': len(roster),
            'executable_talent_families': len(roster)-len(blocked)}
