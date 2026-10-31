from __future__ import annotations

from dataclasses import dataclass
from src.shared.talents import tree as talent_tree
from .profile import TREE_NAMES


@dataclass(frozen=True)
class Talents:
    # Beast Mastery, rows reachable by L20 (11 points total).
    deadly_aspects: int = 0
    endurance_training: int = 0
    focused_fire: int = 0
    improved_aspect_of_the_monkey: int = 0
    pathfinding: int = 0
    improved_revive_pet: int = 0
    bestial_swiftness: int = 0
    unleashed_fury: int = 0
    improved_mend_pet: int = 0
    ferocity: int = 0
    summon_hawk: int = 0
    spirit_bond: int = 0
    intimidation: int = 0
    bestial_discipline: int = 0
    frenzy: int = 0
    bestial_wrath: int = 0

    # Marksmanship, rows reachable by L20.
    hawk_eye: int = 0
    improved_concussive_shot: int = 0
    lethal_attacks: int = 0
    improved_stings: int = 0
    efficiency: int = 0
    careful_aim: int = 0
    rapid_killing: int = 0
    improved_arcane_shot: int = 0
    lone_wolf: int = 0
    trueshot_aura: int = 0
    mortal_shots: int = 0
    rapid_recuperation: int = 0
    barrage: int = 0
    scatter_shot: int = 0
    ranged_weapon_specialization: int = 0
    sniper_shot: int = 0

    # Survival, rows reachable by L20.
    improved_tracking: int = 0
    deflection: int = 0
    entrapment: int = 0
    savage_strikes: int = 0
    survivalist: int = 0
    improved_wing_clip: int = 0
    clever_traps: int = 0
    surefooted: int = 0
    deterrence: int = 0
    survival_tactics: int = 0
    predators_edge: int = 0
    counterattack: int = 0
    resourcefulness: int = 0
    expose_prey: int = 0
    survivalists_discipline: int = 0
    strider_kick: int = 0
    lightning_reflexes: int = 0
    lacerating_strikes: int = 0

    def points(self) -> int:
        return sum(int(v) for v in self.__dict__.values())


# Source: Talents Forever Hunter talents page, beta client build 1.60.1.70009.
# Rule tuple = tree, max rank, points already required in tree, prerequisite.
TALENT_RULES = {
    "deadly_aspects": ("beast_mastery", 5, 0, None),
    "endurance_training": ("beast_mastery", 5, 0, None),
    "focused_fire": ("beast_mastery", 2, 5, None),
    "improved_aspect_of_the_monkey": ("beast_mastery", 3, 5, None),
    "pathfinding": ("beast_mastery", 2, 5, None),
    "improved_revive_pet": ("beast_mastery", 2, 5, None),
    "bestial_swiftness": ("beast_mastery", 1, 10, None),
    "unleashed_fury": ("beast_mastery", 5, 10, None),
    "improved_mend_pet": ("beast_mastery", 2, 15, None),
    "ferocity": ("beast_mastery", 5, 15, None),
    "summon_hawk": ("beast_mastery", 1, 15, None),
    "spirit_bond": ("beast_mastery", 2, 20, None),
    "intimidation": ("beast_mastery", 1, 20, ("bestial_swiftness", 1)),
    "bestial_discipline": ("beast_mastery", 2, 20, None),
    "frenzy": ("beast_mastery", 5, 25, ("ferocity", 5)),
    "bestial_wrath": ("beast_mastery", 1, 30, ("intimidation", 1)),

    "hawk_eye": ("marksmanship", 3, 0, None),
    "improved_concussive_shot": ("marksmanship", 5, 0, None),
    "lethal_attacks": ("marksmanship", 5, 0, None),
    "improved_stings": ("marksmanship", 3, 5, None),
    "efficiency": ("marksmanship", 5, 5, None),
    "careful_aim": ("marksmanship", 5, 5, None),
    "rapid_killing": ("marksmanship", 2, 10, None),
    "improved_arcane_shot": ("marksmanship", 5, 10, None),
    "lone_wolf": ("marksmanship", 1, 10, None),
    "trueshot_aura": ("marksmanship", 1, 15, None),
    "mortal_shots": ("marksmanship", 5, 15, ("careful_aim", 5)),
    "rapid_recuperation": ("marksmanship", 2, 20, ("rapid_killing", 2)),
    "barrage": ("marksmanship", 3, 20, None),
    "scatter_shot": ("marksmanship", 1, 20, None),
    "ranged_weapon_specialization": ("marksmanship", 5, 25, None),
    "sniper_shot": ("marksmanship", 1, 30, ("trueshot_aura", 1)),

    "improved_tracking": ("survival", 5, 0, None),
    "deflection": ("survival", 5, 0, None),
    "entrapment": ("survival", 5, 5, None),
    "savage_strikes": ("survival", 2, 5, None),
    "survivalist": ("survival", 5, 5, None),
    "improved_wing_clip": ("survival", 3, 5, None),
    "clever_traps": ("survival", 2, 10, None),
    "surefooted": ("survival", 3, 10, None),
    "deterrence": ("survival", 1, 10, None),
    "survival_tactics": ("survival", 2, 15, None),
    "predators_edge": ("survival", 5, 15, None),
    "counterattack": ("survival", 1, 15, ("deterrence", 1)),
    "resourcefulness": ("survival", 2, 20, None),
    "expose_prey": ("survival", 2, 20, None),
    "survivalists_discipline": ("survival", 2, 20, None),
    "strider_kick": ("survival", 1, 20, None),
    "lightning_reflexes": ("survival", 5, 25, None),
    "lacerating_strikes": ("survival", 1, 30, ("expose_prey", 2)),
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
