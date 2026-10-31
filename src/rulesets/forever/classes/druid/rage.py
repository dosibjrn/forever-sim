from __future__ import annotations

"""Source-backed rage-from-damage-taken semantics for Forever Druid.

Blizzard states that Forever keeps the original incoming-damage Rage formula,
but Armor is ignored: the original formula is evaluated as if the player always
had 50% Armor damage reduction. Absorbs also do not reduce Rage gain. The
classic RewardRage conversion coefficients remain pinned with provenance while
the Forever-specific fixed-Armor rule is first-party authority.
"""

from .server_profile import CURRENT_TARGET_SERVER_PROFILE, DruidServerProfile

CMANGOS_REPO = "cmangos/mangos-classic"
CMANGOS_COMMIT = "8ec338a1704e7dcb1c0213eb7ed58f9231ade40f"
CMANGOS_PATH = "src/game/Entities/Player.cpp"
CMANGOS_FUNCTION = "Player::RewardRage"
CMANGOS_URL = (
    "https://github.com/cmangos/mangos-classic/blob/"
    f"{CMANGOS_COMMIT}/{CMANGOS_PATH}"
)


def rage_conversion(level: int, profile: DruidServerProfile = CURRENT_TARGET_SERVER_PROFILE) -> float:
    """Server-profiled rage conversion term for a player level."""
    lvl = max(1.0, float(level))
    return (
        float(profile.incoming_rage_level2_coeff) * lvl * lvl
        + float(profile.incoming_rage_level_coeff) * lvl
        + float(profile.incoming_rage_constant)
    )


def rage_from_damage_taken(
    level: int,
    damage: float,
    profile: DruidServerProfile = CURRENT_TARGET_SERVER_PROFILE,
) -> float:
    """Expected visible rage points from formula-equivalent damage taken."""
    conversion = rage_conversion(level, profile)
    if conversion <= 0:
        raise ValueError("incoming rage conversion must stay positive")
    return (
        max(0.0, float(damage))
        / conversion
        * float(profile.incoming_rage_damage_multiplier)
        * float(profile.incoming_rage_income_rate)
    )


def forever_rage_equivalent_damage_per_second(
    pre_armor_incoming_dps: float,
    *,
    successful_hit_fraction: float = 1.0,
    profile: DruidServerProfile = CURRENT_TARGET_SERVER_PROFILE,
) -> float:
    """Convert raw incoming physical DPS to Forever's Rage-formula damage.

    Real Armor is deliberately absent. Avoided attacks still deal no damage, so
    callers pass the successful-hit fraction separately. Blizzard's fixed 50%
    Armor assumption is represented by the server-profile fraction.
    """
    return (
        max(0.0, float(pre_armor_incoming_dps))
        * max(0.0, min(1.0, float(successful_hit_fraction)))
        * float(profile.incoming_rage_fixed_armor_damage_taken_fraction)
    )


def incoming_damage_rage_per_second(
    level: int,
    pre_armor_incoming_dps: float,
    *,
    successful_hit_fraction: float = 1.0,
    profile: DruidServerProfile = CURRENT_TARGET_SERVER_PROFILE,
) -> float:
    equivalent = forever_rage_equivalent_damage_per_second(
        pre_armor_incoming_dps,
        successful_hit_fraction=successful_hit_fraction,
        profile=profile,
    )
    return rage_from_damage_taken(level, equivalent, profile)


def provenance(profile: DruidServerProfile = CURRENT_TARGET_SERVER_PROFILE) -> dict[str, object]:
    return {
        "status": "forever_source_backed_fixed_armor_rule",
        "profile": profile.key,
        "provenance": profile.incoming_rage_provenance,
        "repository": CMANGOS_REPO,
        "commit": CMANGOS_COMMIT,
        "path": CMANGOS_PATH,
        "function": CMANGOS_FUNCTION,
        "url": CMANGOS_URL,
        "parameters": {
            "level2_coeff": profile.incoming_rage_level2_coeff,
            "level_coeff": profile.incoming_rage_level_coeff,
            "constant": profile.incoming_rage_constant,
            "damage_multiplier": profile.incoming_rage_damage_multiplier,
            "income_rate": profile.incoming_rage_income_rate,
            "fixed_armor_damage_taken_fraction": profile.incoming_rage_fixed_armor_damage_taken_fraction,
        },
        "forever_first_party_source": "https://worldofwarcraft.blizzard.com/en-us/news/24301514",
    }
