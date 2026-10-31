from __future__ import annotations

"""Authoritative user-facing Mage build presentation semantics.

Search internals may use coarser diversity families, but anything persisted or
shown to the user should use these helpers so Fast/MC/cache labels agree.
"""

from src.engine_registry import eng

TREES = ('frost', 'arcane', 'fire')


def tree_points(talents: eng.Talents) -> dict[str, int]:
    return {tree: int(eng.tree_points(talents, tree)) for tree in TREES}


def school_family(talents: eng.Talents) -> tuple[str, str]:
    pts = tree_points(talents)
    ordered = sorted(pts.items(), key=lambda kv: (-kv[1], kv[0]))
    school = ordered[0][0]

    top = ordered[0][1]
    tied = [name for name, value in ordered if value == top and value > 0]
    if len(tied) >= 2:
        return school, '+'.join(sorted(tied))

    secondary = ordered[1][0] if ordered[1][1] >= 5 else 'none'
    return school, f'{school}+{secondary}'


def allocation(talents: eng.Talents) -> str:
    return eng.final_allocation(talents)


def policy(policy: eng.Policy | None, level: int) -> str:
    if policy is None:
        return '—'
    return eng.policy_desc(policy, int(level))
