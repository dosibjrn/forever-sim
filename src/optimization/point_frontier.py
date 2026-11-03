"""Backend-independent bounded one-point talent allocation frontier.

Only the caller owns talent rank availability and full legality. This module
walks caller-supplied options without importing GameIR or Warcraft facts.
"""
from __future__ import annotations

from typing import Callable, Iterable, Mapping

from src.optimization.talent_search import TalentAllocationOption, talent_candidate_id


def generate_point_frontier(
    options: Iterable[TalentAllocationOption],
    allocation: Mapping[str, int],
    *,
    max_points: int,
    validate_selection: Callable[[Mapping[str, int]], None],
    allow_transfers: bool = True,
) -> list[dict[str, int]]:
    """Return legal +1 edits and, at cap, -1/+1 transfers in source order.

    Preserve the existing traversal: initial state is validated, transfers
    follow the supplied option order, and only ValueError rejects a candidate.
    """
    validate_selection(allocation)
    definitions = tuple(options)
    spent = sum(int(value) for value in allocation.values())
    seen: set[str] = set()
    out: list[dict[str, int]] = []
    original_id = talent_candidate_id(allocation)
    bases = [dict(allocation)]
    if allow_transfers and spent >= max_points:
        for old in definitions:
            rank = int(allocation.get(old.talent_id, 0))
            if rank:
                base = dict(allocation)
                if rank == 1:
                    del base[old.talent_id]
                else:
                    base[old.talent_id] = rank - 1
                bases.append(base)

    for base in bases:
        if sum(base.values()) >= max_points:
            continue
        for talent in definitions:
            next_rank = int(base.get(talent.talent_id, 0)) + 1
            if next_rank > int(talent.max_rank):
                continue
            if next_rank not in talent.executable_ranks:
                continue
            candidate = dict(base)
            candidate[talent.talent_id] = next_rank
            candidate_id = talent_candidate_id(candidate)
            if candidate_id == original_id or candidate_id in seen:
                continue
            try:
                validate_selection(candidate)
            except ValueError:
                continue
            seen.add(candidate_id)
            out.append(candidate)
    return out
