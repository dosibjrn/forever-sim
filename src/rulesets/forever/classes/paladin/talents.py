from __future__ import annotations

from dataclasses import dataclass

from src.shared.talents import tree as talent_tree
from .profile import TREE_NAMES


@dataclass(frozen=True)
class Talents:
    # Holy
    improved_holy_strike: int = 0
    divine_strength: int = 0
    divine_intellect: int = 0
    healing_light: int = 0
    spiritual_focus: int = 0
    improved_seals: int = 0
    unyielding_faith: int = 0
    voice_of_truth: int = 0
    reverence: int = 0
    purifying_power: int = 0
    infusion_of_light: int = 0
    illumination: int = 0
    divine_favor: int = 0
    divine_precision: int = 0
    holy_shock: int = 0
    consecrated_ground: int = 0
    holy_power: int = 0
    lights_vigil: int = 0
    # Protection
    toughness: int = 0
    redoubt: int = 0
    precision: int = 0
    guardians_favor: int = 0
    anticipation: int = 0
    improved_seal_of_fury: int = 0
    improved_righteous_fury: int = 0
    shield_specialization: int = 0
    sacred_duty: int = 0
    swift_judgement: int = 0
    one_handed_weapon_specialization: int = 0
    improved_hammer_of_justice: int = 0
    templars_bulwark: int = 0
    reckoning: int = 0
    iron_creed: int = 0
    holy_shield: int = 0
    # Retribution
    deflection: int = 0
    benediction: int = 0
    improved_judgement: int = 0
    holy_conduit: int = 0
    conviction: int = 0
    vindication: int = 0
    sanctified_judgement: int = 0
    seal_of_command: int = 0
    pursuit_of_justice: int = 0
    eye_for_an_eye: int = 0
    sacred_arbiter: int = 0
    crusade: int = 0
    two_handed_weapon_specialization: int = 0
    vengeance: int = 0
    repentance: int = 0
    champion_of_the_light: int = 0
    instrument_of_law: int = 0
    twist_of_light: int = 0

    def points(self):
        return sum(int(v) for v in self.__dict__.values())


TALENT_RULES = {
    # Holy
    "improved_holy_strike": ("holy", 2, 0, None),
    "divine_strength": ("holy", 5, 0, None),
    "divine_intellect": ("holy", 5, 0, None),
    "healing_light": ("holy", 3, 5, None),
    "spiritual_focus": ("holy", 2, 5, None),
    "improved_seals": ("holy", 3, 5, None),
    "unyielding_faith": ("holy", 2, 5, None),
    "voice_of_truth": ("holy", 1, 10, None),
    "reverence": ("holy", 3, 10, None),
    "purifying_power": ("holy", 2, 10, None),
    "infusion_of_light": ("holy", 2, 15, None),
    "illumination": ("holy", 5, 15, None),
    "divine_favor": ("holy", 1, 15, None),
    "divine_precision": ("holy", 3, 20, None),
    "holy_shock": ("holy", 1, 20, None),
    "consecrated_ground": ("holy", 2, 20, None),
    "holy_power": ("holy", 5, 25, None),
    "lights_vigil": ("holy", 1, 30, ("holy_shock", 1)),
    # Protection
    "toughness": ("protection", 5, 0, None),
    "redoubt": ("protection", 5, 0, None),
    "precision": ("protection", 3, 5, None),
    "guardians_favor": ("protection", 2, 5, None),
    "anticipation": ("protection", 5, 5, None),
    "improved_seal_of_fury": ("protection", 1, 10, None),
    "improved_righteous_fury": ("protection", 3, 10, None),
    "shield_specialization": ("protection", 3, 10, ("redoubt", 5)),
    "sacred_duty": ("protection", 2, 10, None),
    "swift_judgement": ("protection", 1, 15, ("improved_seal_of_fury", 1)),
    "one_handed_weapon_specialization": ("protection", 3, 15, None),
    "improved_hammer_of_justice": ("protection", 3, 15, None),
    "templars_bulwark": ("protection", 1, 20, None),
    "reckoning": ("protection", 5, 20, None),
    "iron_creed": ("protection", 5, 25, None),
    "holy_shield": ("protection", 1, 30, ("templars_bulwark", 1)),
    # Retribution
    "deflection": ("retribution", 5, 0, None),
    "benediction": ("retribution", 5, 0, None),
    "improved_judgement": ("retribution", 2, 5, None),
    "holy_conduit": ("retribution", 2, 5, None),
    "conviction": ("retribution", 5, 5, None),
    "vindication": ("retribution", 3, 10, None),
    "sanctified_judgement": ("retribution", 3, 10, None),
    "seal_of_command": ("retribution", 1, 10, None),
    "pursuit_of_justice": ("retribution", 2, 10, None),
    "eye_for_an_eye": ("retribution", 2, 15, None),
    "sacred_arbiter": ("retribution", 1, 15, None),
    "crusade": ("retribution", 2, 15, None),
    "two_handed_weapon_specialization": ("retribution", 3, 20, None),
    "vengeance": ("retribution", 3, 20, ("sanctified_judgement", 3)),
    "repentance": ("retribution", 1, 20, None),
    "champion_of_the_light": ("retribution", 3, 25, None),
    "instrument_of_law": ("retribution", 2, 25, ("repentance", 1)),
    "twist_of_light": ("retribution", 1, 30, ("champion_of_the_light", 3)),
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
