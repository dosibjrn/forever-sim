"""Class-neutral talent-string proposal operators for native P7 search.

This module defines candidate search operations only. It has no talent-tree,
rank-cap, prerequisite, class, level, or source-spellbook rules. The input
string contributes only its serialization shape and total search budget;
the selected MythicSim native response decides VALID/INVALID/UNSUPPORTED/ERROR.
"""
from __future__ import annotations

import random


def _decode(value: str) -> tuple[list[str], list[int]]:
    if not isinstance(value, str) or not value:
        raise ValueError("TALENT_PROPOSAL_STRING_MISSING")
    parts = value.split("-")
    if any(char not in "0123456789" for part in parts for char in part):
        raise ValueError("TALENT_PROPOSAL_STRING_FORMAT_INVALID")
    digits = [int(char) for part in parts for char in part]
    if not digits:
        raise ValueError("TALENT_PROPOSAL_STRING_HAS_NO_POSITIONS")
    return parts, digits


def _encode(parts: list[str], digits: list[int]) -> str:
    result = []
    offset = 0
    for part in parts:
        width = len(part)
        result.append("".join(str(value) for value in digits[offset:offset + width]))
        offset += width
    if offset != len(digits):
        raise ValueError("TALENT_PROPOSAL_SHAPE_MISMATCH")
    return "-".join(result)


def cold_talent_string(template: str, rng: random.Random, *, rank_ceiling: int = 9) -> str:
    """Draw an independent cold rank string with a configurable search ceiling.

    The ceiling is an exploration parameter, NOT a claim about any talent's
    legal rank. Native MythicSim still decides whether the resulting build
    is executable. A sparse draw may intentionally leave points unspent.
    """
    parts, template_digits = _decode(template)
    if type(rank_ceiling) is not int or not 1 <= rank_ceiling <= 9:
        raise ValueError("TALENT_PROPOSAL_RANK_CEILING_INVALID")
    budget = min(sum(template_digits), rank_ceiling * len(template_digits))
    if budget <= 0:
        raise ValueError("TALENT_PROPOSAL_SEARCH_BUDGET_EMPTY")
    proposed = [0] * len(template_digits)
    for _ in range(budget):
        available = [index for index, value in enumerate(proposed)
                     if value < rank_ceiling]
        if not available:
            raise ValueError("TALENT_PROPOSAL_SEARCH_BUDGET_EXCEEDS_STRING_FORMAT")
        proposed[rng.choice(available)] += 1
    return _encode(parts, proposed)



class ColdRankLadderExplorer:
    """Vary cold-search rank density without duplicating native rank rules.

    The selected pinned engine has no talent-options CLI. Native prepare has
    refused random 3/4-rank proposals in 2/3-rank ladders; try sparse cold
    allocations first, then broaden the same independent search. These are
    proposal heuristics, never a legality filter or a saved-build seed.
    """

    def __init__(self) -> None:
        self.cold_draws = 0

    def cold_talent_string(self, template: str, rng: random.Random) -> str:
        ceiling = (1, 2, 3, 5, 9)[self.cold_draws % 5]
        self.cold_draws += 1
        return cold_talent_string(template, rng, rank_ceiling=ceiling)

    def mutate_talent_string(self, parent: str, rng: random.Random) -> str:
        return mutate_talent_string(parent, rng)


def mutate_talent_string(parent: str, rng: random.Random) -> str:
    """Move search-budget points between serialized positions without rule checks."""
    parts, parent_digits = _decode(parent)
    if len(parent_digits) < 2 or sum(parent_digits) <= 0:
        return cold_talent_string(parent, rng)
    proposed = parent_digits.copy()
    max_moves = max(1, min(4, len(proposed) // 2))
    for _ in range(rng.randint(1, max_moves)):
        donors = [index for index, value in enumerate(proposed) if value > 0]
        recipients = [index for index, value in enumerate(proposed) if value < 9]
        if not donors or len(recipients) < 2:
            break
        donor = rng.choice(donors)
        recipients = [index for index in recipients if index != donor]
        if not recipients:
            break
        recipient = rng.choice(recipients)
        proposed[donor] -= 1
        proposed[recipient] += 1
    candidate = _encode(parts, proposed)
    return candidate if candidate != parent else cold_talent_string(parent, rng)


def lower_one_rank_neighbors(parent: str) -> list[str]:
    """Enumerate minimal rank-removal proposals from a runnable source build.

    This is a class-neutral string mutation, NOT a legality judgement: some
    resulting allocations may violate native rules, and MythicSim alone
    accepts or refuses them. Trying one less point avoids the destructive
    random redistribution of all points on the first P7.3 probe.
    """
    parts, digits = _decode(parent)
    alternatives = []
    for index in range(len(digits) - 1, -1, -1):
        if digits[index] == 0:
            continue
        changed = digits.copy()
        changed[index] -= 1
        alternatives.append(_encode(parts, changed))
    return alternatives



def one_point_transfer_neighbors(parent: str, *, limit: int = 48) -> list[str]:
    """Sample both within-tree and cross-tree one-point transfers.

    A bounded search must not exhaust its entire candidate budget in the
    first tree. The two proposal streams are interleaved without inferring
    Warcraft prerequisites or rank caps; selected native Rust alone decides
    which changed allocation is legal.
    """
    parts, digits = _decode(parent)
    if limit < 0:
        raise ValueError("TALENT_PROPOSAL_LIMIT_NEGATIVE")
    if limit == 0:
        return []
    boundaries = []
    offset = 0
    for part in parts:
        boundaries.append(range(offset, offset + len(part)))
        offset += len(part)

    def collect(*, within_tree: bool) -> list[str]:
        proposals = []
        for donor_tree in reversed(boundaries):
            for recipient_tree in reversed(boundaries):
                if (donor_tree is recipient_tree) != within_tree:
                    continue
                for donor in reversed(donor_tree):
                    if digits[donor] == 0:
                        continue
                    for recipient in recipient_tree:
                        if donor == recipient or digits[recipient] >= 9:
                            continue
                        modified = digits.copy()
                        modified[donor] -= 1
                        modified[recipient] += 1
                        proposals.append(_encode(parts, modified))
                        if len(proposals) >= limit:
                            return proposals
        return proposals

    within = collect(within_tree=True)
    across = collect(within_tree=False)
    result = []
    for index in range(max(len(within), len(across))):
        if index < len(within):
            result.append(within[index])
            if len(result) == limit:
                break
        if index < len(across):
            result.append(across[index])
            if len(result) == limit:
                break
    return result
