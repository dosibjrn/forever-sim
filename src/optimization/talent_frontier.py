"""Game-model-independent talent allocation neighbors and candidate identities.

Source-backed options and legality stay in src.game.talent_frontier. This module
owns the generic mutation walk and stable neighbor representation.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping


def allocation_key(selection: Mapping[str, int]) -> tuple[tuple[str, int], ...]:
    """Return a deterministic, positive-rank identity for a talent allocation."""
    return tuple(sorted((str(k), int(v)) for k, v in selection.items() if int(v) > 0))


@dataclass(frozen=True)
class Neighbor:
    allocation: tuple[tuple[str, int], ...]
    operation: str
    changed_ids: tuple[str, ...]

    def as_dict(self):
        return {'allocation': dict(self.allocation), 'operation': self.operation,
                'changed_ids': list(self.changed_ids)}


@dataclass(frozen=True)
class TalentNeighborOption:
    """Minimal caller-supplied option data; supported ranks need no game semantics."""

    talent_id: str
    max_rank: int
    supported_ranks: frozenset[int]


TalentSelectionValidator = Callable[[Mapping[str, int]], None]


def generate_talent_neighbors(
    options: Iterable[TalentNeighborOption],
    allocation: Mapping[str, int],
    *,
    max_points: int,
    validate_selection: TalentSelectionValidator,
) -> dict:
    """Generate bounded rank-up/down, rank-sweep and point-transfer proposals.

    The caller supplies options in its deterministic order and validates the
    current allocation before calling. supported_ranks is caller-derived; the
    callback owns all legality of each proposed complete allocation.
    """
    definitions = tuple(options)
    current = dict(allocation_key(allocation))
    rank_rows = {option.talent_id: option.supported_ranks for option in definitions}
    blocked = tuple(option.talent_id for option in definitions if not rank_rows[option.talent_id])
    candidates: dict[tuple, Neighbor] = {}
    rejected = Counter()
    generated = 0
    max_points = int(max_points)

    def offer(proposal: Mapping[str, int], operation: str, changed: tuple[str, ...]) -> None:
        nonlocal generated
        key = allocation_key(proposal)
        if key == allocation_key(current):
            return
        generated += 1
        # A rank jump is legal only if every intermediate caller-supported rank
        # exists. Full source/build legality remains the validator's authority.
        for family, rank in key:
            if any(i not in rank_rows[family] for i in range(1, rank + 1)):
                rejected['missing_intermediate_executable_rank'] += 1
                return
        try:
            validate_selection(dict(key))
        except ValueError as exc:
            rejected[str(exc).split(':', 1)[0]] += 1
            return
        if key not in candidates:
            candidates[key] = Neighbor(key, operation, changed)

    for talent in definitions:
        talent_id = talent.talent_id
        old = current.get(talent_id, 0)
        max_rank = int(talent.max_rank)
        if old < max_rank:
            proposed = dict(current)
            proposed[talent_id] = old + 1
            offer(proposed, 'rank_up', (talent_id,))
            # Source-legal macro step: avoid spending multiple costly searches
            # to discover that the maximum affordable rank is better.
            if old + 1 < max_rank:
                proposed[talent_id] = min(
                    max_rank, old + max_points - sum(current.values())
                )
                if proposed[talent_id] > old + 1:
                    offer(proposed, 'rank_sweep', (talent_id,))
        if old:
            proposed = dict(current)
            if old == 1:
                proposed.pop(talent_id)
            else:
                proposed[talent_id] = old - 1
            offer(proposed, 'rank_down', (talent_id,))

    # Reallocate one point from any selected option to every other option,
    # including options that become admissible only after the transfer.
    for donor in definitions:
        if current.get(donor.talent_id, 0) <= 0:
            continue
        for receiver in definitions:
            if (
                receiver.talent_id == donor.talent_id
                or current.get(receiver.talent_id, 0) >= int(receiver.max_rank)
            ):
                continue
            proposed = dict(current)
            proposed[donor.talent_id] -= 1
            if not proposed[donor.talent_id]:
                proposed.pop(donor.talent_id)
            proposed[receiver.talent_id] = proposed.get(receiver.talent_id, 0) + 1
            offer(proposed, 'point_transfer', (donor.talent_id, receiver.talent_id))

    return {
        'neighbors': tuple(candidates.values()),
        'generated': generated,
        'legal': len(candidates),
        'rejected_by_reason': dict(rejected),
        'unsupported_option_ids': blocked,
        'option_count': len(definitions),
        'supported_option_count': len(definitions) - len(blocked),
    }


__all__ = (
    "Neighbor",
    "TalentNeighborOption",
    "TalentSelectionValidator",
    "allocation_key",
    "generate_talent_neighbors",
)
