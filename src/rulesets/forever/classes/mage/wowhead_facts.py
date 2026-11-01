from __future__ import annotations

"""Current public Wowhead Forever facts that are not yet fully in the Mage kernel.

This module is deliberately data-only.  A fact living here does *not* imply the
optimizer currently uses the mechanic in rotation search; MODEL_FIDELITY and the
audit document make that distinction explicit.

Audit date: 2026-09-21.
"""

WOWHEAD_MAGE_ABILITIES = "https://www.wowhead.com/forever/spells/abilities/mage"

# Wand schools are not represented in the canonical SQLite schema yet. Keep
# current public Forever school facts separate from item selection so combat can
# preserve the SQL-selected item while avoiding a silent Arcane default. Unknown
# items remain explicit/unknown and may fall back to an older audited fixture by
# name in ``engine.best_wand``.
WAND_SCHOOL_BY_ITEM_ID = {
    11287: "arcane",  # Lesser Magic Wand
    5198: "arcane",   # Cookie's Stirring Rod
    8071: "fire",     # Sizzle Stick; current L20 SQL selection
}
WAND_SCHOOL_SOURCE_URLS = {
    11287: "https://www.wowhead.com/forever/item=11287/lesser-magic-wand",
    5198: "https://www.wowhead.com/forever/item=5198/cookies-stirring-rod",
    8071: "https://www.wowhead.com/forever/item=8071/sizzle-stick",
}

# Forever spell-power modifiers are rank data, not Classic-derived coefficient
# formulas.  Wowhead exposes these directly on the current Forever spell pages.
# Keep them explicit so low-level ranks cannot silently regain Classic's pre-20
# coefficient penalty.
FROSTBOLT_SP_COEFF_BY_RANK = (
    0.407, 0.489, 0.597, 0.706, 0.814, 0.814, 0.814, 0.814, 0.814, 0.814, 0.814,
)
FIREBALL_SP_COEFF_BY_RANK = (
    0.429, 0.571, 0.714, 0.857, 1.000, 1.000, 1.000, 1.000, 1.000, 1.000, 1.000, 1.000,
)
SCORCH_SP_COEFF_BY_RANK = (0.429,) * 7
FIRE_BLAST_SP_COEFF_BY_RANK = (0.429,) * 7
FROST_NOVA_SP_COEFF_BY_RANK = (0.029,) * 4
PYROBLAST_DIRECT_SP_COEFF_BY_RANK = (1.000,) * 8
PYROBLAST_DOT_SP_COEFF_TOTAL_BY_RANK = (0.600,) * 8
# Current Forever spell rows explicitly carry the "Periodic Can Crit" flag.
# This establishes tick damage crit capability only; proc side effects from
# periodic crits remain unmodeled until separately sourced.
PERIODIC_CAN_CRIT_SPELLS = frozenset(("fireball", "pyroblast"))
ARCANE_MISSILES_SP_COEFF_PER_TICK = 0.286

# Ice Lance coefficient is intentionally NOT stored as a universal Forever fact.
# The public Forever row does not expose an SP modifier; target-server/profile
# parameterization lives in ``server_profile.py`` with provenance.

# Arcane Blast: current Forever rank pages.  Damage is the tooltip's single
# base value, not a min/max range.  Cost is 15% base mana at every listed rank.
ARCANE_BLAST_RANKS = (
    (20, 55),
    (30, 131),
    (40, 170),
    (50, 275),
    (60, 395),
)
ARCANE_BLAST_BASE_MANA_PCT = 0.15
ARCANE_BLAST_CAST_S = 2.5
ARCANE_BLAST_RANGE_YD = 30.0
ARCANE_BLAST_OTHER_SPELL_DAMAGE_BONUS_PER_STACK = 0.10
ARCANE_BLAST_MANA_COST_INCREASE_PER_STACK = 1.75
ARCANE_BLAST_MAX_STACKS = 4
ARCANE_BLAST_STACK_DURATION_S = 8.0

# Ice Lance: current Forever rank pages.  Frozen multiplier semantics are kept
# in the target-server profile so the public wording and server behavior are not
# conflated with the rank's base damage data.
ICE_LANCE_RANKS = (
    (20, 45, 30),
    (28, 55, 38),
    (34, 70, 48),
    (42, 105, 83),
    (48, 120, 104),
    (56, 160, 152),
)
ICE_LANCE_RANGE_YD = 30.0

FINGERS_OF_FROST_CHILL_PROC_CHANCE = 0.15
FINGERS_OF_FROST_DURATION_S = 15.0
# Frostbite: each Chill effect has 5/10/15% chance by talent rank to root for 5s.
FROSTBITE_PROC_CHANCE_PER_RANK = 0.05
FROSTBITE_ROOT_DURATION_S = 5.0

MISSILE_BARRAGE_ARCANE_BLAST_PROC_CHANCE = 0.40
MISSILE_BARRAGE_OTHER_TRIGGER_PROC_CHANCE = 0.20
MISSILE_BARRAGE_CHANNEL_DURATION_MULT = 0.50
MISSILE_BARRAGE_MANA_COST_REDUCTION = 1.00
MISSILE_BARRAGE_MISSILE_INTERVAL_S = 0.50
MISSILE_BARRAGE_DURATION_S = 15.0

# Rank 1 Blizzard is enough to prove that the single-target-only Forever Mage
# objective omits a real leveling AoE lane.
BLIZZARD_R1_LEVEL = 20
BLIZZARD_R1_MANA = 320
BLIZZARD_R1_CHANNEL_S = 8.0
BLIZZARD_R1_RADIUS_YD = 8.0
BLIZZARD_R1_SP_COEFF_PER_TICK = 0.042
BLIZZARD_R1_TICKS = 8

SOURCES = {
    "frostbolt_r1_modifier": "https://www.wowhead.com/forever/spell=116/frostbolt",
    "fireball_r1_modifier": "https://www.wowhead.com/forever/spell=133/fireball",
    "fire_blast_r1_modifier": "https://www.wowhead.com/forever/spell=2136/fire-blast",
    "frost_nova_r1_modifier": "https://www.wowhead.com/forever/spell=122/frost-nova",
    "arcane_missiles_r1_modifier": "https://www.wowhead.com/forever/spell=5143/arcane-missiles",
    "pyroblast_r1_modifier": "https://www.wowhead.com/forever/spell=11366/pyroblast",
    "arcane_blast_l20": "https://www.wowhead.com/forever/spell=400574/arcane-blast",
    "arcane_blast_l30": "https://www.wowhead.com/forever/spell=1239696/arcane-blast",
    "arcane_blast_l40": "https://www.wowhead.com/forever/spell=1239697/arcane-blast",
    "arcane_blast_l50": "https://www.wowhead.com/forever/spell=1239699/arcane-blast",
    "arcane_blast_l60": "https://www.wowhead.com/forever/spell=1239700/arcane-blast",
    "ice_lance_l20": "https://www.wowhead.com/forever/spell=1312002/ice-lance",
    "fingers_of_frost": "https://www.wowhead.com/forever/spell=400647/fingers-of-frost",
    "frostbite": "https://www.wowhead.com/forever/spell=12497/frostbite",
    "missile_barrage": "https://www.wowhead.com/forever/spell=400588/missile-barrage",
    # 401736 is the actionbar/grant helper, not the talent entity itself.
    "missile_barrage_grant_helper": "https://www.wowhead.com/forever/spell=401736/missile-barrage",
    "blizzard_l20": "https://www.wowhead.com/forever/spell=10/blizzard",
}
