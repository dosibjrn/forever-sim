from __future__ import annotations

"""Forever Feral weapon-scaling inputs.

Current Forever guides agree on the material rule: equipped *weapon DPS* is
carried into both Cat and Bear form and weapon speed itself is irrelevant to
auto-attack DPS because forms swing at fixed speeds.  Public sources do not
currently expose the fixed form-speed constants, so the long-standing 1.0 s
Cat / 2.5 s Bear values are explicit ruleset parameters rather than hidden in
the scorer.

The named weapon rows below are conservative attainable calibration anchors,
not a BIS optimizer.  They exist so the scorer consumes real weapon DPS instead
of a level-shaped pseudo weapon term.
"""

from dataclasses import asdict, dataclass


CAT_FORM_SWING_S = 1.0
BEAR_FORM_SWING_S = 2.5
FORM_SPEED_PROVENANCE = (
    "Forever guides: equipped weapon DPS carries into Cat/Bear and equipped weapon speed is irrelevant; "
    "form swing constants 1.0s Cat / 2.5s Bear remain explicit Classic-derived parameters pending target-server probe"
)


@dataclass(frozen=True)
class FeralWeapon:
    name: str
    required_level: int
    weapon_dps: float
    weapon_speed: float
    strength: float = 0.0
    agility: float = 0.0
    stamina: float = 0.0
    intellect: float = 0.0
    attack_power: float = 0.0
    source_url: str = ""
    note: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


# Conservative named anchors.  We deliberately do not interpolate imaginary
# weapons between these rows: the latest actually available anchor stays
# equipped until the next audited row.
FERAL_WEAPON_PROGRESSION: tuple[FeralWeapon, ...] = (
    FeralWeapon(
        "Hammerbone", 10, 20.44, 3.40, strength=10, stamina=7,
        source_url="https://www.wowhead.com/forever/item=270018/hammerbone",
        note="Current L20 Forever Feral guide quest-reward recommendation.",
    ),
    FeralWeapon(
        "Manual Crowd Pummeler", 29, 29.00, 2.00, strength=16, agility=5,
        source_url="https://www.wowhead.com/forever/item=9449/manual-crowd-pummeler",
        note="Weapon body used as a DPS/stat anchor; finite-use haste active is not credited.",
    ),
    FeralWeapon(
        "Whiteout Staff", 60, 41.29, 3.10, stamina=25, intellect=16,
        source_url="https://www.wowhead.com/forever/item=19101/whiteout-staff",
        note="Level-60 attainable weapon-DPS anchor; not asserted to be Feral BIS.",
    ),
)


def weapon_for_level(level: int) -> FeralWeapon | None:
    rows = [w for w in FERAL_WEAPON_PROGRESSION if w.required_level <= int(level)]
    return max(rows, key=lambda w: (w.required_level, w.weapon_dps)) if rows else None


def normal_form_hit(*, weapon_dps: float, attack_power: float, bear: bool) -> float:
    """Average normal form hit before crit/talent multipliers.

    Weapon DPS is carried into form; AP contributes AP/14 DPS.  Multiplying by
    the fixed form swing converts DPS to the ``normal weapon damage`` consumed
    by abilities such as Claw/Primal Bite.
    """
    swing = BEAR_FORM_SWING_S if bear else CAT_FORM_SWING_S
    return (max(0.0, float(weapon_dps)) + max(0.0, float(attack_power)) / 14.0) * swing


def form_white_dps(*, weapon_dps: float, attack_power: float) -> float:
    return max(0.0, float(weapon_dps)) + max(0.0, float(attack_power)) / 14.0


def provenance() -> dict:
    return {
        "scaling": "equipped_weapon_dps_carried_into_cat_and_bear",
        "form_speed": FORM_SPEED_PROVENANCE,
        "cat_swing_s": CAT_FORM_SWING_S,
        "bear_swing_s": BEAR_FORM_SWING_S,
        "weapon_rows": [w.as_dict() for w in FERAL_WEAPON_PROGRESSION],
    }
