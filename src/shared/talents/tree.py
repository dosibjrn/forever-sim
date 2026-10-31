from __future__ import annotations

"""Ruleset-agnostic talent-tree helpers.

This module knows only the structural contract used by simulator talent tables:
``name -> (tree, max_rank, points_required_in_tree, prerequisite)``.
It deliberately contains no Classic/Forever or class-specific knowledge.
"""

from dataclasses import replace
from typing import Iterable, Mapping

TalentRule = tuple[str, int, int, tuple[str, int] | None]
TalentRules = Mapping[str, TalentRule]


def tree_fields(rules: TalentRules, tree: str) -> tuple[str, ...]:
    return tuple(name for name, (tr, _mx, _need, _pre) in rules.items() if tr == tree)


def tree_points(talents, tree: str, rules: TalentRules) -> int:
    return sum(int(getattr(talents, name)) for name in tree_fields(rules, tree))


def legal_add(talents, name: str, rules: TalentRules) -> bool:
    tree, max_rank, need_tree, prerequisite = rules[name]
    if int(getattr(talents, name)) >= int(max_rank):
        return False
    if tree_points(talents, tree, rules) < int(need_tree):
        return False
    if prerequisite and int(getattr(talents, prerequisite[0])) < int(prerequisite[1]):
        return False
    return True


def add_point(talents, name: str, rules: TalentRules):
    if not legal_add(talents, name, rules):
        raise ValueError(f"illegal talent point: {name}")
    return replace(talents, **{name: int(getattr(talents, name)) + 1})


def final_allocation(talents, tree_names: Iterable[str], rules: TalentRules) -> str:
    chunks: list[str] = []
    for tree in tree_names:
        pts = tree_points(talents, tree, rules)
        selected = [
            f"{name}:{getattr(talents, name)}"
            for name in tree_fields(rules, tree)
            if getattr(talents, name)
        ]
        chunks.append(f"{tree}({pts})" + ("[" + ",".join(selected) + "]" if selected else ""))
    return " / ".join(chunks)


def preference_key(talents, tree_names: Iterable[str], rules: TalentRules) -> tuple:
    """Stable tie-break: coherent deep trees first, then deterministic field vector."""
    pts = sorted((tree_points(talents, tree, rules) for tree in tree_names), reverse=True)
    return tuple(-x for x in pts) + tuple(-int(v) for v in talents.__dict__.values())
