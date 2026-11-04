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


def cold_talent_string(template: str, rng: random.Random) -> str:
    """Draw a cold rank string within the template's point-search budget.

    Points are distributed across every serialized position. No per-position
    maximum, tree budget, prerequisite, or other game legality is inferred.
    Values stay single-digit only because that is the request's string format.
    """
    parts, template_digits = _decode(template)
    budget = sum(template_digits)
    if budget <= 0:
        raise ValueError("TALENT_PROPOSAL_SEARCH_BUDGET_EMPTY")
    proposed = [0] * len(template_digits)
    for _ in range(budget):
        available = [index for index, value in enumerate(proposed) if value < 9]
        if not available:
            raise ValueError("TALENT_PROPOSAL_SEARCH_BUDGET_EXCEEDS_STRING_FORMAT")
        proposed[rng.choice(available)] += 1
    return _encode(parts, proposed)


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
    """Offer rank-preserving, one-point source edits for native evaluation.

    Changing one position at a time keeps the source's point budget and avoids
    arbitrary multi-rank random proposals. Same-tree edits come first; this
    ordering is a search heuristic, NOT a talent-tree eligibility rule.
    MythicSim alone decides which of these proposed strings are legal.
    """
    parts, digits = _decode(parent)
    if limit < 0:
        raise ValueError("TALENT_PROPOSAL_LIMIT_NEGATIVE")
    boundaries = []
    offset = 0
    for part in parts:
        boundaries.append(range(offset, offset + len(part)))
        offset += len(part)
    result = []

    def propose(donors, recipients):
        for donor in reversed(list(donors)):
            if digits[donor] == 0:
                continue
            for recipient in recipients:
                if donor == recipient or digits[recipient] >= 9:
                    continue
                modified = digits.copy()
                modified[donor] -= 1
                modified[recipient] += 1
                result.append(_encode(parts, modified))
                if len(result) >= limit:
                    return True
        return False

    if limit == 0:
        return result
    for tree in reversed(boundaries):
        if propose(tree, tree):
            return result
    for donor_tree in reversed(boundaries):
        for recipient_tree in reversed(boundaries):
            if donor_tree is recipient_tree:
                continue
            if propose(donor_tree, recipient_tree):
                return result
    return result
