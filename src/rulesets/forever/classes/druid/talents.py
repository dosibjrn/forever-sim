from __future__ import annotations

from dataclasses import dataclass

from src.shared.talents import tree as talent_tree
from .profile import TREE_NAMES


TALENT_SCHEMA_BUILD = "1.60.1.70170"
TALENT_SCHEMA_SOURCE = "https://talentsforever.com/druid/talents"
TALENT_SCHEMA_CHANGE_SOURCE = "https://talentsforever.com/druid/talents/shifting-power"


@dataclass(frozen=True)
class Talents:
    # Balance
    improved_wrath: int = 0
    genesis: int = 0
    moonglow: int = 0
    improved_moonfire: int = 0
    natures_majesty: int = 0
    natures_reach: int = 0
    improved_entangling_roots: int = 0
    natures_splendor: int = 0
    insect_swarm: int = 0
    vengeance: int = 0
    improved_starfire: int = 0
    overgrowth: int = 0
    natures_grace: int = 0
    eclipse: int = 0
    moonfury: int = 0
    moonkin_form: int = 0
    # Feral
    ferocity: int = 0
    heart_of_the_wild: int = 0
    feral_swiftness: int = 0
    feral_instinct: int = 0
    brutal_impact: int = 0
    thick_hide: int = 0
    savage_fury: int = 0
    feral_charge: int = 0
    sharpened_claws: int = 0
    shredding_attacks: int = 0
    mangle: int = 0
    predatory_strikes: int = 0
    blood_frenzy: int = 0
    # Deprecated pre-2026-09-24 snapshot name; retained only so old serialized
    # fixtures can still be loaded. Current search never allocates this field.
    primal_fury: int = 0
    predatory_instincts: int = 0
    leader_of_the_pack: int = 0
    shifting_power: int = 0
    improved_shifting_power: int = 0
    # Removed in Forever client build 1.60.1.70170. Retained only so old
    # serialized fixtures fail explicitly instead of becoming unreadable.
    king_of_the_jungle: int = 0
    natural_reaction: int = 0
    rend_and_tear: int = 0
    berserk: int = 0
    # Restoration
    natures_focus: int = 0
    furor: int = 0
    naturalist: int = 0
    subtlety: int = 0
    natural_shapeshifter: int = 0
    reflection: int = 0
    gift_of_nature: int = 0
    gift_of_earthmother: int = 0
    tranquil_spirit: int = 0
    improved_rejuvenation: int = 0
    swiftmend: int = 0
    natures_swiftness: int = 0
    living_spirit: int = 0
    improved_tranquility: int = 0
    improved_regrowth: int = 0
    wild_growth: int = 0

    def points(self):
        # Removed/legacy aliases are not current talent points. Search never
        # allocates them, and current-schema validation rejects non-zero values.
        return sum(int(v) for k, v in self.__dict__.items() if k not in {"primal_fury", "king_of_the_jungle"})

    @property
    def effective_blood_frenzy(self):
        """Current Blood Frenzy rank, accepting the old Primal Fury fixture key."""
        return max(int(self.blood_frenzy), int(self.primal_fury))


TALENT_RULES = {
    # Balance
    "improved_wrath": ("balance", 5, 0, None),
    "genesis": ("balance", 5, 0, None),
    "moonglow": ("balance", 3, 5, None),
    "improved_moonfire": ("balance", 2, 5, None),
    "natures_majesty": ("balance", 2, 5, None),
    "natures_reach": ("balance", 2, 5, None),
    "improved_entangling_roots": ("balance", 3, 10, None),
    "natures_splendor": ("balance", 1, 10, None),
    "insect_swarm": ("balance", 1, 15, None),
    "vengeance": ("balance", 5, 15, None),
    "improved_starfire": ("balance", 5, 15, None),
    "overgrowth": ("balance", 2, 20, None),
    "natures_grace": ("balance", 1, 20, None),
    "eclipse": ("balance", 3, 20, None),
    "moonfury": ("balance", 5, 25, None),
    "moonkin_form": ("balance", 1, 30, None),
    # Feral
    "ferocity": ("feral", 5, 0, None),
    "heart_of_the_wild": ("feral", 5, 0, None),
    "feral_swiftness": ("feral", 2, 5, None),
    "feral_instinct": ("feral", 3, 5, None),
    "brutal_impact": ("feral", 2, 5, None),
    "thick_hide": ("feral", 3, 5, None),
    "shredding_attacks": ("feral", 3, 10, None),
    "savage_fury": ("feral", 2, 10, None),
    "feral_charge": ("feral", 1, 10, None),
    "sharpened_claws": ("feral", 2, 10, None),
    "shifting_power": ("feral", 1, 15, ("shredding_attacks", 3)),
    "mangle": ("feral", 1, 15, ("savage_fury", 2)),
    "predatory_strikes": ("feral", 3, 15, None),
    "blood_frenzy": ("feral", 2, 15, ("sharpened_claws", 2)),
    "improved_shifting_power": ("feral", 2, 20, ("shifting_power", 1)),
    "leader_of_the_pack": ("feral", 1, 20, None),
    "predatory_instincts": ("feral", 2, 20, None),
    "natural_reaction": ("feral", 5, 25, None),
    "rend_and_tear": ("feral", 5, 25, ("predatory_strikes", 3)),
    "berserk": ("feral", 1, 30, ("leader_of_the_pack", 1)),
    # Restoration
    "natures_focus": ("restoration", 5, 0, None),
    "furor": ("restoration", 5, 0, None),
    "naturalist": ("restoration", 5, 5, None),
    "subtlety": ("restoration", 3, 5, None),
    "natural_shapeshifter": ("restoration", 3, 5, None),
    "reflection": ("restoration", 3, 10, None),
    "gift_of_nature": ("restoration", 5, 10, None),
    "gift_of_earthmother": ("restoration", 1, 10, None),
    "tranquil_spirit": ("restoration", 5, 15, None),
    "improved_rejuvenation": ("restoration", 3, 15, None),
    "swiftmend": ("restoration", 1, 15, None),
    "natures_swiftness": ("restoration", 1, 20, None),
    "living_spirit": ("restoration", 3, 20, None),
    "improved_tranquility": ("restoration", 2, 20, None),
    "improved_regrowth": ("restoration", 5, 25, None),
    "wild_growth": ("restoration", 1, 30, None),
}



def current_schema_errors(t: Talents) -> tuple[str, ...]:
    """Return current-build schema violations for an externally supplied build.

    Search-generated builds cannot contain removed fields because they are not
    present in ``TALENT_RULES``. This check exists for persisted/URL/reference
    inputs so a pre-70170 King of the Jungle build cannot be silently scored as
    if it meant Shifting Power. There is no one-to-one semantic translation.
    """
    errors: list[str] = []
    if int(getattr(t, "king_of_the_jungle", 0) or 0):
        errors.append("king_of_the_jungle_removed_in_1.60.1.70170")
    return tuple(errors)


def validate_current_schema(t: Talents) -> Talents:
    errors = current_schema_errors(t)
    if errors:
        raise ValueError("invalid current Druid talent schema: " + ", ".join(errors))
    return t


def allocation_schema_errors(t: Talents) -> tuple[str, ...]:
    """Validate one finished current-build allocation without reconstructing order."""
    errors = list(current_schema_errors(t))
    for name, (tree, max_rank, need_tree, prerequisite) in TALENT_RULES.items():
        rank = int(getattr(t, name, 0) or 0)
        if rank < 0 or rank > int(max_rank):
            errors.append(f"{name}_rank_{rank}_outside_0_{max_rank}")
            continue
        if rank <= 0:
            continue
        if tree_points(t, tree) < int(need_tree):
            errors.append(f"{name}_requires_{need_tree}_{tree}_points")
        if prerequisite and int(getattr(t, prerequisite[0], 0) or 0) < int(prerequisite[1]):
            errors.append(f"{name}_requires_{prerequisite[0]}_{prerequisite[1]}")
    return tuple(errors)


def expected_points_for_level(level: int) -> int:
    return max(0, min(51, int(level) - 9))


def level_points_complete(level: int, t: Talents) -> bool:
    return int(t.points()) == expected_points_for_level(level)

def tree_points(t, tree):
    return talent_tree.tree_points(t, tree, TALENT_RULES)


def legal_add(t, name):
    return talent_tree.legal_add(t, name, TALENT_RULES)


def add_point(t, name):
    return talent_tree.add_point(t, name, TALENT_RULES)


def final_allocation(t):
    # Keep the persisted dataclass field ``mangle`` for cache/state compatibility,
    # but current Forever names this Bear-only talent/spell family Primal Bite.
    return talent_tree.final_allocation(t, TREE_NAMES, TALENT_RULES).replace("mangle:", "primal_bite:")


def talent_preference_key(t):
    return talent_tree.preference_key(t, TREE_NAMES, TALENT_RULES)
