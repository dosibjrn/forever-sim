from __future__ import annotations

"""Pinned player base-stat authority used by Forever class scorers and Game IR.

Race/class level-1 anchors come from Forever target-server data.  Level growth
uses the inherited vanilla class progression already used by the simulator.
Item stats remain separate in the canonical item catalogue.

G05 expands the existing Druid Spirit authority to the full Tauren Druid
primary-stat vector so the generic backend can construct a source-backed actor
starting state without copying class scorer constants.
"""

from dataclasses import dataclass


BASE_STAT_AUTHORITY_ID = "forever_base_stats_v1"
BASE_STAT_AUTHORITY_AS_OF = "2026-10-02"
PRIMARY_STAT_AUTHORITY_AS_OF = "2026-10-05"


@dataclass(frozen=True)
class BaseSpiritProfile:
    class_name: str
    race: str
    level1_spirit: int
    source_kind: str
    source_note: str


# Forever target-server Tauren Druid level-1 primary stats.
# These are source anchors; subsequent growth is the inherited vanilla Druid
# class progression encoded below.  Keeping the anchor here preserves the
# existing Spirit authority while making the whole vector reusable by Game IR.
_DRUID_TAUREN_LEVEL1_STATS = {
    "strength": 23,
    "agility": 18,
    "stamina": 22,
    "intellect": 20,
    "spirit": 22,
}

_PROFILES: dict[tuple[str, str], BaseSpiritProfile] = {
    ("druid", "tauren"): BaseSpiritProfile(
        class_name="druid",
        race="tauren",
        level1_spirit=22,
        source_kind="forever_target_server_starting_stat",
        source_note="WoW Forever Tauren starting stats: Druid Spirit 22",
    ),
    ("paladin", "undead"): BaseSpiritProfile(
        class_name="paladin",
        race="undead",
        level1_spirit=21,
        source_kind="forever_target_server_starting_stat_plus_vanilla_class_progression",
        source_note="WoW Forever Undead Paladin starting Spirit 21; vanilla Paladin Spirit growth thereafter",
    ),
}

DEFAULT_RACE_BY_CLASS = {"druid": "tauren", "paladin": "undead"}


def _druid_primary_gain_for_target_level(stat: str, target_level: int) -> int:
    """Inherited vanilla Druid primary-stat gain when advancing to a level.

    This uses the same target-level convention as the existing production
    Spirit authority.  It is source/ruleset normalization, not combat scoring.
    """
    level = int(target_level)
    key = str(stat).lower()
    if key == "strength":
        return 2 if level > 38 else (1 if level > 6 and level % 2 else 0)
    if key == "stamina":
        return 2 if level > 32 else (1 if level > 4 else 0)
    if key == "agility":
        return 2 if level > 38 else (1 if level > 8 and level % 2 else 0)
    if key == "intellect":
        return 3 if level > 38 else (1 if level > 4 else 0)
    if key == "spirit":
        return 3 if level > 38 else (1 if level > 5 else 0)
    raise KeyError(f"unsupported Druid primary stat: {stat!r}")


def base_primary_stats(class_name: str, level: int, *, race: str | None = None) -> dict[str, int]:
    """Return source-backed naked primary stats for a supported Forever actor."""
    cls = str(class_name).lower()
    lvl = max(1, int(level))
    race_name = str(race or DEFAULT_RACE_BY_CLASS.get(cls, "")).lower()
    if (cls, race_name) != ("druid", "tauren"):
        raise KeyError(f"no pinned Forever primary-stat profile for {cls}/{race_name}")
    values = dict(_DRUID_TAUREN_LEVEL1_STATS)
    for target in range(2, lvl + 1):
        for stat in tuple(values):
            values[stat] += _druid_primary_gain_for_target_level(stat, target)
    return values


def primary_stats_provenance(class_name: str, level: int, *, race: str | None = None) -> dict:
    cls = str(class_name).lower()
    race_name = str(race or DEFAULT_RACE_BY_CLASS.get(cls, "")).lower()
    values = base_primary_stats(cls, level, race=race_name)
    return {
        "authority_id": BASE_STAT_AUTHORITY_ID,
        "authority_as_of": PRIMARY_STAT_AUTHORITY_AS_OF,
        "class": cls,
        "race": race_name,
        "level": int(level),
        "level1_stats": dict(_DRUID_TAUREN_LEVEL1_STATS),
        "base_stats": dict(values),
        "source_kind": "forever_target_server_starting_stats_plus_vanilla_class_progression",
        "source_note": "WoW Forever Tauren Druid level-1 primary stats anchored to target-server data",
        "progression_source": "CMaNGOS vanilla ObjectMgr::BuildPlayerLevelInfo Druid class stat thresholds",
    }


def _spirit_gain_for_target_level(class_name: str, target_level: int) -> int:
    level = int(target_level)
    cls = str(class_name).lower()
    if cls == "druid":
        return _druid_primary_gain_for_target_level("spirit", level)
    if cls == "paladin":
        return 1 if level > 7 else 0
    raise KeyError(f"unsupported base Spirit class: {class_name!r}")


def base_spirit(class_name: str, level: int, *, race: str | None = None) -> int:
    cls = str(class_name).lower()
    lvl = max(1, int(level))
    race_name = str(race or DEFAULT_RACE_BY_CLASS.get(cls, "")).lower()
    if (cls, race_name) == ("druid", "tauren"):
        return int(base_primary_stats(cls, lvl, race=race_name)["spirit"])
    profile = _PROFILES.get((cls, race_name))
    if profile is None:
        raise KeyError(f"no pinned Forever base Spirit profile for {cls}/{race_name}")
    spirit = int(profile.level1_spirit)
    for target in range(2, lvl + 1):
        spirit += _spirit_gain_for_target_level(cls, target)
    return spirit


def spirit_provenance(class_name: str, level: int, *, race: str | None = None) -> dict:
    cls = str(class_name).lower()
    race_name = str(race or DEFAULT_RACE_BY_CLASS.get(cls, "")).lower()
    profile = _PROFILES[(cls, race_name)]
    return {
        "authority_id": BASE_STAT_AUTHORITY_ID,
        "authority_as_of": BASE_STAT_AUTHORITY_AS_OF,
        "class": cls,
        "race": race_name,
        "level": int(level),
        "level1_spirit": int(profile.level1_spirit),
        "base_spirit": int(base_spirit(cls, level, race=race_name)),
        "source_kind": profile.source_kind,
        "source_note": profile.source_note,
        "progression_source": "CMaNGOS vanilla ObjectMgr::BuildPlayerLevelInfo class Spirit thresholds",
    }
