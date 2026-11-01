from __future__ import annotations

from dataclasses import dataclass

from src.shared.talents import tree as talent_tree
from .profile import TREE_NAMES


@dataclass(frozen=True)
class Talents:
    improved_heroic_strike: int = 0
    improved_rend: int = 0
    deflection: int = 0

    def points(self) -> int:
        return sum(int(v) for v in self.__dict__.values())


# Deliberately thin Arms slice: enough legal ranks to prove a complete L10->20
# continuity path without pretending the rest of the Warrior tree is modeled.
TALENT_RULES = {
    "improved_heroic_strike": ("arms", 3, 0, None),
    "improved_rend": ("arms", 3, 0, None),
    "deflection": ("arms", 5, 0, None),
}


def tree_points(t, tree):
    return talent_tree.tree_points(t, tree, TALENT_RULES)


def legal_add(t, name):
    return talent_tree.legal_add(t, name, TALENT_RULES)


def add_point(t, name):
    return talent_tree.add_point(t, name, TALENT_RULES)


def final_allocation(t):
    return talent_tree.final_allocation(t, TREE_NAMES, TALENT_RULES)


def talent_preference_key(t):
    return talent_tree.preference_key(t, TREE_NAMES, TALENT_RULES)
