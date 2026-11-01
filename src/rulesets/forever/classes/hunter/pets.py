from __future__ import annotations

"""Canonical Forever Hunter pet-family capability data used by the scorer.

This module is deliberately data-first.  Runtime never scrapes the web: the
source URLs below document the public Forever facts captured for this release.
Only abilities whose damage/focus/cooldown contract is sufficiently pinned are
eligible for the bounded damage allocator; utility/opening abilities stay
visible as capabilities without receiving invented throughput credit.
"""

from typing import Any

FOREVER_PET_GUIDE_SOURCE = (
    "https://www.wowhead.com/forever/guide/classes/hunter/beast-mastery/dps-abilities"
)

# Current Forever spell pages used for the L21-L40 damage rows.
SPELL_SOURCES = {
    "bite_r4": "https://www.wowhead.com/forever/spell=17257/bite",
    "bite_r5": "https://www.wowhead.com/forever/spell=17258/bite",
    "bite_r6": "https://www.wowhead.com/forever/spell=17259/bite",
    "claw_r4": "https://www.wowhead.com/forever/spell=16830/claw",
    "claw_r5": "https://www.wowhead.com/forever/spell=16831/claw",
    "claw_r6": "https://www.wowhead.com/forever/spell=16832/claw",
    "lightning_breath_r3": "https://www.wowhead.com/forever/spell=25009/lightning-breath",
    "lightning_breath_r4": "https://www.wowhead.com/forever/spell=25010/lightning-breath",
    "charge_r3": "https://www.wowhead.com/forever/spell=26178/charge",
    "charge_r4": "https://www.wowhead.com/forever/spell=26179/charge",
    "shell_shield": "https://www.wowhead.com/forever/spell=26064/shell-shield",
    "dash_r1": "https://www.wowhead.com/forever/spell=23099/dash",
    "prowl_r1": "https://www.wowhead.com/forever/spell=24450/prowl",
    "furious_howl_r2": "https://www.wowhead.com/forever/spell=24605/furious-howl",
}

# Family baseline multipliers retained from the accepted Hunter model.  The
# important change in this increment is that active abilities are no longer
# silently universal: each family advertises its own legal skill set.
PET_FAMILIES: dict[str, dict[str, Any]] = {
    "cat": {
        "damage": 1.10, "health": 0.98, "armor": 1.00, "attack_speed": 2.0,
        "skills": ("bite", "claw", "dash", "prowl"),
    },
    "raptor": {
        "damage": 1.10, "health": 0.95, "armor": 1.03, "attack_speed": 2.0,
        "skills": ("bite", "claw", "dash"),
    },
    "wind_serpent": {
        "damage": 1.07, "health": 1.00, "armor": 1.00, "attack_speed": 2.0,
        "skills": ("bite", "dive", "lightning_breath"),
    },
    "spider": {
        "damage": 1.07, "health": 1.00, "armor": 1.00, "attack_speed": 2.0,
        "skills": ("bite", "dash"),
    },
    "wolf": {
        "damage": 1.00, "health": 1.00, "armor": 1.05, "attack_speed": 2.0,
        "skills": ("bite", "dash", "furious_howl"),
    },
    "bear": {
        "damage": 0.91, "health": 1.08, "armor": 1.05, "attack_speed": 2.0,
        "skills": ("bite", "claw", "dash"),
    },
    "boar": {
        "damage": 0.90, "health": 1.04, "armor": 1.09, "attack_speed": 2.0,
        "skills": ("bite", "dash", "charge"),
    },
    "turtle": {
        "damage": 0.90, "health": 1.00, "armor": 1.13, "attack_speed": 2.0,
        "skills": ("bite", "dash", "shell_shield"),
    },
}

# Rank rows are (minimum pet level, average base damage, Focus, cooldown_s,
# school, source-key).  The active model intentionally starts at L24 so the
# accepted L10-L20 baseline remains unchanged.  Current Forever spell pages:
# Bite 31-37 / 40-48 / 49-59; Claw 16-22 / 21-29 / 26-36;
# Lightning Breath 36-41 / 52-61.
PET_DAMAGE_SKILLS: dict[str, tuple[tuple[Any, ...], ...]] = {
    "bite": (
        (24, 34.0, 35.0, 10.0, "physical", "bite_r4"),
        (32, 44.0, 35.0, 10.0, "physical", "bite_r5"),
        (40, 54.0, 35.0, 10.0, "physical", "bite_r6"),
    ),
    "claw": (
        (24, 19.0, 25.0, 0.0, "physical", "claw_r4"),
        (32, 25.0, 25.0, 0.0, "physical", "claw_r5"),
        (40, 31.0, 25.0, 0.0, "physical", "claw_r6"),
    ),
    "lightning_breath": (
        (24, 38.5, 50.0, 0.0, "nature", "lightning_breath_r3"),
        (36, 56.5, 50.0, 0.0, "nature", "lightning_breath_r4"),
    ),
}

# Explicit family actives that are source-known but not yet throughput-priced in
# the steady-state scorer.  Keeping them here prevents a capability table from
# being mistaken for a claim that the effect is already modeled.
PET_UTILITY_SKILLS: dict[str, dict[str, Any]] = {
    "dash": {"min_level": 30, "modeled": False, "reason": "pet engage/movement policy not yet priced", "source": "dash_r1"},
    "dive": {"min_level": 30, "modeled": False, "reason": "pet engage/movement policy not yet priced", "source": FOREVER_PET_GUIDE_SOURCE},
    "prowl": {"min_level": 30, "modeled": False, "reason": "out-of-combat opener policy not yet priced", "source": "prowl_r1"},
    "furious_howl": {"min_level": 24, "modeled": False, "reason": "Forever aura target/applicability needs dedicated policy", "source": "furious_howl_r2"},
    "charge": {"min_level": 24, "modeled": False, "reason": "one-opener-per-pull AP transfer needs event policy", "source": "charge_r3"},
    "shell_shield": {"min_level": 20, "modeled": False, "reason": "defensive cooldown scheduling not yet priced", "source": "shell_shield"},
}

PET_BASE_FOCUS_REGEN_PER_S = 5.0
PET_GROWL_FOCUS = 15.0
PET_GROWL_COOLDOWN_S = 5.0
PET_GCD_S = 1.5


def family_data(family: str) -> dict[str, Any]:
    key = str(family)
    if key not in PET_FAMILIES:
        raise KeyError(f"unknown Hunter pet family: {family}")
    return PET_FAMILIES[key]


def family_skills(family: str) -> tuple[str, ...]:
    return tuple(family_data(family).get("skills") or ())


def latest_damage_rank(skill: str, level: int) -> dict[str, Any] | None:
    rows = PET_DAMAGE_SKILLS.get(str(skill)) or ()
    eligible = [r for r in rows if int(r[0]) <= int(level)]
    if not eligible:
        return None
    min_level, damage, focus, cooldown_s, school, source_key = eligible[-1]
    return {
        "skill": str(skill),
        "min_level": int(min_level),
        "damage": float(damage),
        "focus": float(focus),
        "cooldown_s": float(cooldown_s),
        "gcd_s": PET_GCD_S,
        "school": str(school),
        "source": SPELL_SOURCES[str(source_key)],
    }


def modeled_damage_skills(family: str, level: int) -> tuple[dict[str, Any], ...]:
    out: list[dict[str, Any]] = []
    for skill in family_skills(family):
        rank = latest_damage_rank(skill, level)
        if rank is not None:
            out.append(rank)
    return tuple(out)


def capability_payload(family: str, level: int) -> dict[str, Any]:
    skills = family_skills(family)
    modeled = modeled_damage_skills(family, level)
    utility = []
    for skill in skills:
        row = PET_UTILITY_SKILLS.get(skill)
        if row is not None and int(level) >= int(row.get("min_level", 1)):
            source = row.get("source")
            if source in SPELL_SOURCES:
                source = SPELL_SOURCES[source]
            utility.append({"skill": skill, **row, "source": source})
    return {
        "family": str(family),
        "source": FOREVER_PET_GUIDE_SOURCE,
        "skills": list(skills),
        "modeled_damage_skills": [dict(x) for x in modeled],
        "available_utility_skills": utility,
    }
