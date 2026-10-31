from __future__ import annotations

"""Modeled Paladin spell ranks from Forever beta client 1.60.1.69893.

Only fields needed by the current level-30 smooth leveling model are stored.
"""

from src.rulesets.forever.data.catalogue import default_catalogue

# Holy Strike: learn, mana, cooldown, weapon coefficient, bonus min, bonus max.
HOLY_STRIKE = (
    # Wowhead Forever spellbook values (build-current public DB). Bonus damage
    # is fixed per rank; keep min=max so the rest of the deterministic scorer
    # can continue using the historical average helper.
    (6, 5, 12.0, .25, 13, 13),
    (12, 9, 12.0, .25, 18, 18),
    (20, 12, 12.0, .30, 20, 20),
    (28, 14, 12.0, .30, 26, 26),
    (36, 16, 12.0, .35, 36, 36),
    (44, 17, 12.0, .35, 61, 61),
    (52, 19, 12.0, .40, 82, 82),
    (60, 20, 12.0, .40, 109, 109),
)

# Seal of Fury: learn, mana, legacy placeholders.  Forever 1.60.1
# changed both damage components to pure Spell Power scaling: 10% SP per
# successful melee swing and 45% SP on Judgement.  Keep the tuple shape
# stable for callers/tests, but the three damage fields are intentionally zero.
SEAL_FURY = (
    (10, 40, 0, 0, 0),
    (18, 60, 0, 0, 0),
    (25, 90, 0, 0, 0),
    (34, 120, 0, 0, 0),
    (42, 140, 0, 0, 0),
    (50, 170, 0, 0, 0),
    (58, 200, 0, 0, 0),
)

# Seal of Righteousness: learn, mana, legacy Judgement placeholders.  The
# Forever Judgement is pure 50% SP; on-hit base damage is speed-sensitive and
# is handled by mechanics.py from the current rank tooltip envelope.
SEAL_RIGHTEOUSNESS = (
    (1, 20, 0, 0),
    (10, 40, 0, 0),
    (18, 60, 0, 0),
    (26, 90, 0, 0),
    (34, 120, 0, 0),
    (42, 140, 0, 0),
    (50, 170, 0, 0),
    (58, 200, 0, 0),
)

# Seal of Command is an M46 source-driven projection.  The canonical snapshot
# owns the five rank IDs, learn levels and mana costs; this compatibility tuple
# stays only because older scorer/tests consume the historical ``latest`` API.
def _seal_command_rows():
    rows=[]
    for row in default_catalogue().spell_family("paladin", "seal_of_command"):
        cost=dict(row.resource_cost or {})
        mana=float(cost.get("amount", 0.0))
        rows.append((int(row.required_level), mana, 0, 0))
    return tuple(rows)


SEAL_COMMAND = _seal_command_rows()

# Consecration is baseline from level 20 in Forever. Rows remain
# (learn, mana, base_total_over_8s, base_total_over_8s) for compatibility.
# Spell Power is a separate 9.5% per tick for eight ticks, capped to the first
# four enemies.  The old model incorrectly applied that SP term to every mob.
CONSECRATION = (
    (20, 135, 16, 16),
    (30, 235, 24, 24),
    (40, 320, 48, 48),
    (50, 435, 64, 64),
    (60, 565, 96, 96),
)

# Healing spells: learn, mana, cast seconds, heal min/max.  Rank bases are
# current Forever values; scaling is 71.4% SP for Holy Light and 42.9% SP for
# Flash of Light in mechanics.py.
HOLY_LIGHT = (
    (1, 35, 2.5, 42, 51),
    (6, 60, 2.5, 81, 96),
    (14, 110, 2.5, 167, 196),
    (22, 190, 2.5, 322, 368),
    (30, 275, 2.5, 506, 569),
    (38, 365, 2.5, 717, 799),
    (46, 465, 2.5, 968, 1076),
    (54, 580, 2.5, 1272, 1414),
    (60, 660, 2.5, 1590, 1770),
)
FLASH_OF_LIGHT = (
    (20, 35, 1.5, 67, 77),
    (26, 50, 1.5, 102, 117),
    (34, 70, 1.5, 153, 171),
    (42, 90, 1.5, 206, 231),
    (50, 115, 1.5, 278, 310),
    (58, 140, 1.5, 348, 389),
)

# Utility / aura rows needed by the smooth survival controller.
# learn, mana, duration, cooldown
HAMMER_OF_JUSTICE = ((8, 30, 3.0, 60.0), (24, 50, 4.0, 60.0))
BLESSING_OF_PROTECTION = ((10, 25, 6.0, 300.0), (24, 45, 8.0, 300.0))
DIVINE_PROTECTION = ((6, 15, 6.0, 300.0), (18, 35, 8.0, 300.0))
# learn, reflected holy damage per landed incoming hit
RETRIBUTION_AURA = ((16, 5), (26, 8), (36, 12), (46, 16), (56, 20))
# learn, bonus armor
DEVOTION_AURA = ((1, 55), (10, 160), (20, 275), (30, 390), (40, 505), (50, 620), (60, 735))


def latest(rows, level):
    xs = [x for x in rows if x[0] <= level]
    return xs[-1] if xs else None
