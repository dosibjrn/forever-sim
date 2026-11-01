from __future__ import annotations

"""Current public Wowhead Forever facts for the experimental Druid backend.

These are audit anchors.  Unknown/ambiguous values stay absent instead of being
silently borrowed from another ruleset.

Audit date: 2026-09-21.
"""

WOWHEAD_DRUID_ABILITIES = "https://www.wowhead.com/forever/spells/abilities/druid"
BALANCE_GUIDE = "https://www.wowhead.com/forever/guide/classes/druid/balance/overview-pve-dps"

CAT_FORM_LEVEL = 20
CAT_FORM_BASE_MANA_PCT = 0.55
CAT_FORM_AP_FLAT = 12.0
CAT_FORM_AP_PER_AGILITY = 1.0
CAT_ENERGY_CAPACITY = 100.0
CAT_ENERGY_REGEN_PER_S = 10.0

# (learn level, energy, normal-weapon-damage multiplier, flat damage)
CLAW_RANKS = (
    (20, 45, 1.10, 27),
    (28, 45, 1.10, 39),
    (38, 45, 1.10, 57),
    (48, 45, 1.10, 88),
    (58, 45, 1.10, 115),
)
CLAW_R1 = {
    "level": 20, "energy": 45, "normal_damage_mult": 1.10,
    "flat_damage": 27, "combo_points": 1, "gcd_s": 1.0,
}

# Solo mobs normally face the player, so Shred is kept as a factual anchor and
# is not assumed to be available continuously in the solo-leveling rotation.
SHRED_RANKS = (
    (22, 60, 1.55, 54),
    (30, 60, 2.25, 72),
    (38, 60, 1.55, 99),
    (46, 60, 1.55, 144),
    (54, 60, 2.25, 180),
)
SHRED_R1 = {
    "level": 22, "energy": 60, "normal_damage_mult": 1.55,
    "flat_damage": 54, "combo_points": 1, "requires_behind": True,
    "gcd_s": 1.0,
}

# (learn level, energy, direct, dot total, duration)
RAKE_RANKS = (
    (24, 40, 19, 39, 9.0),
    (34, 40, 28, 57, 9.0),
    (44, 40, 43, 75, 9.0),
    (54, 40, 58, 96, 9.0),
)
RAKE_L34 = {
    "level": 34, "energy": 40, "direct_damage": 28,
    "dot_total": 57, "dot_duration_s": 9.0, "combo_points": 1,
}

# Current public Forever Rank 1 values (checked 2026-10-07).  G26 needs the
# explicit 1-5 combo-point ladder because the generic policy search varies the
# finisher threshold instead of assuming five points.
RIP_R1 = {
    "level": 20, "energy": 30,
    "damage_by_combo_points": ((1, 44), (2, 71), (3, 97), (4, 124), (5, 150)),
    "duration_s": 12.0, "tick_interval_s": 2.0,
    "periodic_can_crit": True,
    "attack_power_scaling": "server_scripted_not_yet_normalized",
}

# Rip rows are 5-combo-point totals.  Lower CP rows are deliberately not
# synthesized because the leveling scorer spends at 5 CP when possible.
# (learn level, energy, five-CP total damage, duration)
RIP_RANKS_5CP = (
    (20, 30, 150, 12.0),
    (28, 30, 234, 12.0),
    (36, 30, 306, 12.0),
    (44, 30, 474, 12.0),
    (52, 30, 672, 12.0),
    (60, 30, 942, 12.0),
)

# (learn level, energy, 5CP min, 5CP max, extra damage per extra energy)
FEROCIOUS_BITE_RANKS_5CP = (
    (32, 35, 194, 210, 1.0),
    (40, 35, 315, 339, 1.5),
    (56, 35, 670, 720, 2.0),
)
FEROCIOUS_BITE_L40 = {
    "level": 40, "energy": 35,
    "damage_by_combo_points": ((79,103),(138,162),(197,221),(256,280),(315,339)),
    "extra_energy_damage_per_energy": 1.5,
}

# Balance rank anchors. These are raw public Wowhead Forever tooltip facts, not
# the final server-tuned values. Beta tuning changes can land before public spell
# pages catch up; dated build overrides are applied separately in
# ``src.rulesets.forever.shared.tuning``. Rows whose public page hides base damage
# remain omitted rather than reconstructed from another ruleset.
# Wrath raw tooltip row: (level, mana, cast, dmin, dmax, SP coefficient)
WRATH_RANKS = (
    # Public Forever trainable rows with full explicit tooltip values.
    (1, 10, 1.5, 15, 18, 0.429),
    (6, 20, 1.7, 25, 28, 0.486),
    (14, 40, 2.0, 32, 37, 0.571),
    (22, 50, 2.0, 41, 46, 0.571),
    (30, 70, 2.0, 47, 53, 0.571),
    (38, 80, 2.0, 56, 63, 0.571),
    # Rank 7 / level 46 hides its base-damage range on the public page, so it
    # is deliberately omitted. Rank 8 exposes the full raw tooltip row.
    (54, 120, 2.0, 92, 102, 0.571),
)
WRATH_L38 = {
    "level": 38, "mana": 80, "cast_s": 2.0,
    "damage_min": 56, "damage_max": 63, "sp_coeff": 0.571,
}
# Alias documents semantics for callers that need to distinguish raw tooltip
# facts from build tuning. Keep WRATH_RANKS for backwards compatibility.
WRATH_RAW_TOOLTIP_RANKS = WRATH_RANKS

WRATH_CURRENT_SOURCE_URLS = {
    1: "https://www.wowhead.com/forever/spell=5176/wrath",
    6: "https://www.wowhead.com/forever/spell=5177/wrath",
    14: "https://www.wowhead.com/forever/spell=5178/wrath",
    22: "https://www.wowhead.com/forever/spell=5179/wrath",
    30: "https://www.wowhead.com/forever/spell=5180/wrath",
    38: "https://www.wowhead.com/forever/spell=6780/wrath",
    54: "https://www.wowhead.com/forever/spell=9912/wrath",
}

# Current Forever rank-by-rank spell-power modifiers from the public spell pages.
# Keep this ladder separate from WRATH_RANKS because several Forever Wrath pages
# expose the coefficient reliably while their server-scaled base damage is hidden.
WRATH_SP_COEFF_LADDER = (
    (1, 0.429),
    (6, 0.486),
    (14, 0.571),
    (22, 0.571),
    (30, 0.571),
    (38, 0.571),
    (46, 0.571),
    (54, 0.571),
)

# Starfire: (level, mana, cast, dmin, dmax, SP coefficient)
STARFIRE_RANKS = (
    (20, 95, 3.5, 95, 115, 1.0),
    (26, 135, 3.5, 146, 177, 1.0),
    (34, 180, 3.5, 212, 253, 1.0),
    (42, 230, 3.5, 293, 348, 1.0),
    (50, 275, 3.5, 378, 445, 1.0),
    (58, 315, 3.5, 451, 531, 1.0),
    (60, 340, 3.5, 496, 584, 1.0),
)
STARFIRE_SP_COEFF_LADDER = tuple((row[0], 1.0) for row in STARFIRE_RANKS)


# Moonfire: (level, mana, direct min, direct max, dot total, duration,
# direct SP coeff, per-tick SP coeff).  Public Forever pages expose the full
# trainable Moonfire ladder through required level 58, including base totals and
# rank-specific spell-power modifiers.
MOONFIRE_RANKS = (
    (10, 50, 17, 21, 32, 12.0, 0.094, 0.081),
    (16, 75, 30, 37, 52, 12.0, 0.128, 0.111),
    (22, 105, 47, 55, 80, 12.0, 0.15, 0.13),
    (28, 150, 70, 82, 124, 12.0, 0.15, 0.13),
    (34, 190, 91, 108, 164, 12.0, 0.15, 0.13),
    (40, 235, 117, 137, 212, 12.0, 0.15, 0.13),
    (46, 280, 143, 168, 264, 12.0, 0.15, 0.13),
    (52, 325, 172, 200, 320, 12.0, 0.15, 0.13),
    (58, 375, 195, 228, 384, 12.0, 0.15, 0.13),
)

# Rank-development audit: direct coefficient / coefficient per 3-second tick.
# The full periodic coefficient is tick_coeff * number_of_ticks.
MOONFIRE_SP_COEFF_LADDER = (
    (4, 0.060, 0.052),
    (10, 0.094, 0.081),
    (16, 0.128, 0.111),
    (22, 0.150, 0.130),
    (28, 0.150, 0.130),
    (34, 0.150, 0.130),
    (40, 0.150, 0.130),
    (46, 0.150, 0.130),
    (52, 0.150, 0.130),
    (58, 0.150, 0.130),
)
MOONFIRE_TICK_INTERVAL_S = 3.0

# Exact public Forever Moonfire rank anchors used by generic Game IR rank selection.
MOONFIRE_CURRENT_SOURCE_URLS = {
    10: "https://www.wowhead.com/forever/spell=8924/moonfire",
    16: "https://www.wowhead.com/forever/spell=8925/moonfire",
    22: "https://www.wowhead.com/forever/spell=8926/moonfire",
    28: "https://www.wowhead.com/forever/spell=8927/moonfire",
    34: "https://www.wowhead.com/forever/spell=8928/moonfire",
    40: "https://www.wowhead.com/forever/spell=8929/moonfire",
    46: "https://www.wowhead.com/forever/spell=9833/moonfire",
    52: "https://www.wowhead.com/forever/spell=9834/moonfire",
    58: "https://www.wowhead.com/forever/spell=9835/moonfire",
}

# G11 maintenance anchors. These are deliberately separate from executable
# damage Actions: long-lived buffs are not charged once per mob, and Thorns'
# reactive damage needs the later generic incoming-hit Trigger primitive.
MARK_OF_THE_WILD_L20 = {
    "level": 20, "mana": 100, "duration_s": 3600.0, "armor": 142,
    "all_attributes": 5, "all_resistances": 0,
    "source_url": "https://www.wowhead.com/forever/spell=6756/mark-of-the-wild",
}
THORNS_L24 = {
    "level": 24, "mana": 105, "duration_s": 600.0, "reactive_nature_damage": 11,
    "source_url": "https://www.wowhead.com/forever/spell=1075/thorns",
}
MOONFIRE_L28 = {
    "level": 28, "mana": 150, "direct_min": 70, "direct_max": 82,
    "dot_total": 124, "duration_s": 12.0,
    "direct_sp_coeff": 0.15, "tick_sp_coeff": 0.13,
}

# Insect Swarm: (level, mana, dot total, duration, per-tick SP coeff)
INSECT_SWARM_RANKS = (
    (30, 85, 138, 12.0, 0.158),
    (40, 100, 174, 12.0, 0.158),
    (50, 140, 264, 12.0, 0.158),
    (60, 160, 192, 12.0, 0.158),
)
INSECT_SWARM_TICK_INTERVAL_S = 2.0
INSECT_SWARM_TICK_SP_COEFF = 0.158
INSECT_SWARM_FULL_DURATION_SP_COEFF = 0.948

# Improved Wrath current trait scaling: -0.1s cast and -10% mana per point.
# Improved Wrath cast-time and mana-cost rank values are source-driven in
# data/fixtures + data.rules as of v0.11.43; do not duplicate them here.

# Eclipse trait values exposed by the current Forever spell page.  Wrath makes
# the next Starfires faster; exact server-side charge consumption remains partly
# scripted, so mechanics.py uses a conservative one-Wrath/two-Starfire cycle.
ECLIPSE_STARFIRE_CAST_REDUCTION_BY_RANK = (0.0, 0.17, 0.33, 0.50)
ECLIPSE_MAX_CHARGES = 4
ECLIPSE_DURATION_S = 15.0

NATURES_GRACE_HASTE = 0.10
NATURES_GRACE_GCD_REDUCTION = 0.10
NATURES_GRACE_DURATION_S = 3.0


# Healing Touch: (learn level, mana, cast_s, heal_min, heal_max, SP coefficient).
# Current Forever public rank pages; used by the shared recovery contract only.
# Rejuvenation: (learn level, mana, full-duration heal, duration_s, per-tick healing coeff).
# Current Forever rank pages. Ticks occur every 3 s; the periodic heal can
# continue after the Druid re-enters Cat/Bear form, which is important for
# solo-leveling recovery.
REJUVENATION_RANKS = (
    (4, 25, 32, 12.0, 0.080),
    (10, 40, 56, 12.0, 0.125),
    (16, 75, 116, 12.0, 0.170),
    (22, 105, 180, 12.0, 0.200),
    (28, 135, 244, 12.0, 0.200),
    (34, 160, 304, 12.0, 0.200),
    (40, 195, 284, 12.0, 0.200),
    (46, 235, 488, 12.0, 0.200),
    (52, 280, 608, 12.0, 0.200),
    (58, 335, 756, 12.0, 0.200),
    (60, 360, 888, 12.0, 0.200),
)
REJUVENATION_TICK_INTERVAL_S = 3.0
REJUVENATION_GCD_S = 1.5
REJUVENATION_SOURCE = "https://www.wowhead.com/forever/spells/abilities/druid"
HEALING_TOUCH_SOURCE = "https://www.wowhead.com/forever/spells/abilities/druid/restoration"

HEALING_TOUCH_RANKS = (
    (1, 25, 1.5, 40, 55, 0.123),
    (8, 55, 2.0, 94, 119, 0.314),
    (14, 110, 2.5, 204, 253, 0.554),
    (20, 185, 3.0, 376, 459, 0.857),
    (26, 270, 3.5, 589, 712, 1.000),
    (32, 335, 3.5, 762, 914, 1.000),
    (38, 405, 3.5, 958, 1143, 1.000),
    (44, 495, 3.5, 1225, 1453, 1.000),
    (50, 600, 3.5, 1545, 1826, 1.000),
    (56, 720, 3.5, 1916, 2257, 1.000),
    (60, 800, 3.5, 2267, 2677, 1.000),
)

# Natural Reaction (Forever beta 2026-09-24 talent export).
# Rank N grants N% dodge in Bear/Dire Bear and a (20*N)% chance to gain
# 5 Rage each time the player dodges.
NATURAL_REACTION_DODGE_PER_RANK = 0.01
NATURAL_REACTION_RAGE_PROC_CHANCE_PER_RANK = 0.20
NATURAL_REACTION_RAGE_PER_PROC = 5.0
NATURAL_REACTION_SOURCE = "https://wowforevertalent.com/druid/reference/"

# Thick Hide (Forever beta snapshot, 2026-09-24). The talent grants base
# Armor before form multipliers: rank N adds N Armor per character level, plus
# the listed Armor for each point of Defense skill above 5 * level.
THICK_HIDE_BASE_ARMOR_PER_LEVEL_BY_RANK = (0.0, 1.0, 2.0, 3.0)
THICK_HIDE_ARMOR_PER_EXCESS_DEFENSE_BY_RANK = (0.0, 0.67, 1.33, 2.00)
THICK_HIDE_SOURCE = "https://wowforevertalent.com/druid/reference/"


# Build 1.60.1.70170 Feral schema correction.
# Tiger's Fury is removed from the current Forever Druid spellbook and King of
# the Jungle is removed from the tree. Their replacement is Shifting Power:
# Cat Form only, 55% base mana -> 40 Energy, 16 s cooldown; Natural Shapeshifter
# also reduces its mana cost. Improved Shifting Power reduces the cooldown by
# 4/8 seconds. Runtime is offline; these URLs are provenance only.
DRUID_TALENT_SCHEMA_BUILD = "1.60.1.70170"
DRUID_TALENT_SCHEMA_SOURCE = "https://talentsforever.com/druid/talents"
SHIFTING_POWER_BASE_MANA_PCT = 0.55
SHIFTING_POWER_ENERGY = 40.0
SHIFTING_POWER_COOLDOWN_S = 16.0
IMPROVED_SHIFTING_POWER_CD_REDUCTION_PER_RANK_S = 4.0
SHIFTING_POWER_SOURCE = "https://talentsforever.com/druid/talents/shifting-power"
IMPROVED_SHIFTING_POWER_SOURCE = "https://talentsforever.com/druid/talents/improved-shifting-power"
TIGERS_FURY_CURRENT_STATUS = "removed_in_1.60.1.70170"
KING_OF_THE_JUNGLE_CURRENT_STATUS = "removed_in_1.60.1.70170"

# Berserk (current Forever Feral talent). 3 min cooldown, 15 s duration.
# Cat: CP-generating abilities gain +100 percentage points crit chance.
# Bear: Primal Bite loses its cooldown and can hit up to 3 targets.
BERSERK_COOLDOWN_S = 180.0
BERSERK_DURATION_S = 15.0
BERSERK_CP_BUILDER_CRIT_BONUS = 1.0
BERSERK_PRIMAL_BITE_MAX_TARGETS = 3
BERSERK_SOURCE = "https://www.wowhead.com/forever/spell=417141/berserk"

# Frenzied Regeneration (Forever): level 36, 3 min cooldown, 10 s duration.
# In Bear it converts up to 10 Rage/s into health; each Rage is 1% max health.
FRENZIED_REGEN_LEVEL = 36
FRENZIED_REGEN_COOLDOWN_S = 180.0
FRENZIED_REGEN_DURATION_S = 10.0
FRENZIED_REGEN_RAGE_PER_S_CAP = 10.0
FRENZIED_REGEN_HP_PER_RAGE_FRACTION = 0.01
FRENZIED_REGEN_SOURCE = "https://www.wowhead.com/forever/spell=22842/frenzied-regeneration"

NATURAL_SHAPESHIFTER_COST_REDUCTION_PER_RANK = 0.10
FERAL_FORM_BASE_MANA_PCT = 0.55
FERAL_FORM_GCD_S = 1.5
BEAR_FORM_LEVEL = 10
ENRAGE_LEVEL = 12
ENRAGE_INITIAL_RAGE = 10.0
ENRAGE_PERIODIC_RAGE_PER_S = 2.0
ENRAGE_DURATION_S = 10.0
ENRAGE_COOLDOWN_S = 60.0

# Bear multi-pull audit anchors (Forever public spell pages, refreshed 2026-09-26).
# Bear Swipe is an unchanged 3-target physical school-damage spell in Forever.
# The public rank pages expose a flat physical-damage effect only; the separate
# changed ``SwipeCat`` helper / Improved Swipe talent is a Cat-form weapon-damage
# mechanic and must not be projected onto baseline Bear Swipe.  Therefore Bear
# Swipe correctly credits the verified flat rank damage only.
# (learn level, rage, base damage, max targets)
SWIPE_RANKS = (
    (16, 20, 19, 3),
    (24, 20, 25, 3),
    (34, 20, 36, 3),
    (44, 20, 60, 3),
    (54, 20, 84, 3),
)
SWIPE_MAX_TARGETS = 3

# Improved Swipe / Swipe (Cat) is NOT enabled in the current Forever model.
# Wowhead exposes spell 439510 under the Forever namespace, but the recorded
# 2026-09-24 Forever Beta spellbook (client 1.60.1.70009) does not contain
# Improved Swipe or Swipe (Cat), and the current Forever talent tree does not
# contain it either. The same spell is a Season-of-Discovery rune. Treat the
# Wowhead page as insufficient availability evidence until a Forever-specific
# acquisition/spellbook source appears.
IMPROVED_SWIPE_AVAILABLE = False
IMPROVED_SWIPE_SOURCE = "https://www.wowhead.com/forever/spell=439510/improved-swipe"
SWIPE_CAT_SOURCE = "https://www.wowhead.com/forever/spell=411128/swipe"
FOREVER_DRUID_SPELLBOOK_SOURCE = "https://wowforevertalent.com/abilities/druid/"

# Primal Bite (formerly Mangle Bear): (learn level, rage, normal-weapon multiplier, flat damage).
# Current Forever client/Wowhead names spell 407995 and follow-up ranks Primal Bite.
PRIMAL_BITE_RANKS = (
    (25, 20, 1.00, 26),
    (36, 20, 1.00, 38),
    (48, 20, 1.00, 59),
    (60, 20, 1.00, 77),
)

# Compatibility alias for persisted/internal callers from pre-v0.11.46.13.
MANGLE_BEAR_RANKS = PRIMAL_BITE_RANKS

# Maul is an on-next-swing attack: verified Forever rank flat additions.
# (learn level, rage, flat damage added to the normal Bear swing)
MAUL_RANKS = (
    (10, 15, 18),
    (18, 15, 27),
    (26, 15, 37),
    (34, 15, 49),
    (42, 15, 71),
    (50, 15, 101),
    (58, 15, 128),
)
MAUL_BASE_RAGE = 15.0
SWIPE_BASE_RAGE = 20.0

# Lacerate is a baseline Forever Bear/Dire Bear ability, trained at 42/50/58.
# Tooltip: 15 Rage, 15 s bleed, 5 stacks; each application adds the listed
# bleed total and deals 10% weapon damage per existing application.  The
# periodic component is explicitly allowed to crit.
# (learn level, rage, bleed total over 15 s, duration s, max stacks, weapon damage per existing stack)
LACERATE_RANKS = (
    (42, 15, 50, 15.0, 5, 0.10),
    (50, 15, 60, 15.0, 5, 0.10),
    (58, 15, 75, 15.0, 5, 0.10),
)
LACERATE_GCD_S = 1.5
LACERATE_TICK_S = 3.0
# Shredding Attacks ranks 1/2/3 reduce Lacerate Rage by 1/2/3.
SHREDDING_ATTACKS_LACERATE_RAGE_REDUCTION_PER_RANK = 1.0
LACERATE_SOURCE = "https://www.wowhead.com/forever/spell=414644/lacerate"
SHREDDING_ATTACKS_SOURCE = "https://www.wowhead.com/forever/spell=16966/shredding-attacks"

OMEN_OF_CLARITY_MANA = 120
OMEN_OF_CLARITY_BUFF_DURATION_S = 600.0
OMEN_OF_CLARITY_PROC_ICD_S = 10.0
CLEARCASTING_COST_REDUCTION = 1.00
CLEARCASTING_DURATION_S = 15.0

MOONKIN_FORM_LEVEL = 40
MOONKIN_FORM_BASE_MANA_PCT = 0.35
MOONKIN_ITEM_ARMOR_INCREASE = 3.60
MOONKIN_OMEN_PROC_CHANCE_INCREASE = 1.00
MOONKIN_PARTY_CRIT_BONUS = 0.03
MOONKIN_OMEN_ICD_REDUCTION = 0.49

# Current build correction.  The generic 409828 grant page still carries old
# "replace Claw with Mangle (Cat)" text, but the current Forever client diff
# marks Mangle Cat 407993 removed.  Rank 1 spell 407995 is Primal Bite: a
# Bear/Dire Bear 20-rage, 6-second-cooldown ability.  Never synthesize a Cat
# Mangle replacement from the stale grant/helper relation.
PRIMAL_BITE_PUBLIC_FACT = {
    "spell_id": 407995,
    "forms": ("bear", "dire_bear"),
    "rage_cost": 20,
    "cooldown_s": 6.0,
    "normal_damage_mult": 1.00,
    "flat_damage_rank1": 26,
    "cat_mangle_spell_id": 407993,
    "cat_mangle_current_build_status": "removed",
    "stale_grant_spell_id": 409828,
}

# Compatibility view: old callers can inspect this name, but it now records the
# resolved current-build fact instead of advertising an unknown Cat rank.
MANGLE_PUBLIC_FACT = {
    "replaces_claw": False,
    "benefits_from_claw_and_maul_effects": False,
    "displayed_normal_damage_mult": 1.00,
    "displayed_flat_damage": 26,
    "cat_rank_cost_verified": False,
    "cat_mangle_current_build_status": "removed",
}

SOURCES = {
    "balance_guide": BALANCE_GUIDE,
    "bear_form": "https://www.wowhead.com/forever/spell=5487/bear-form",
    "enrage": "https://www.wowhead.com/forever/spell=5229/enrage",
    "cat_form": "https://www.wowhead.com/forever/spell=768/cat-form",
    "claw_r1": "https://www.wowhead.com/forever/spell=1082/claw",
    "shred_r1": "https://www.wowhead.com/forever/spell=5221/shred",
    "rake_l34": "https://www.wowhead.com/forever/spell=1823/rake",
    "rip_r1": "https://www.wowhead.com/forever/spell=1079/rip",
    "ferocious_bite_l40": "https://www.wowhead.com/forever/spell=22827/ferocious-bite",
    "wrath_l38": "https://www.wowhead.com/forever/spell=6780/wrath",
    "moonfire_l28": "https://www.wowhead.com/forever/spell=8927/moonfire",
    "starfire": "https://www.wowhead.com/forever/spell=2912/starfire",
    "insect_swarm": "https://www.wowhead.com/forever/spell=24974/insect-swarm",
    "improved_wrath": "https://www.wowhead.com/forever/spell=16814/improved-wrath",
    "eclipse": "https://www.wowhead.com/forever/spell=408248/eclipse",
    "natures_grace": "https://www.wowhead.com/forever/spell=16886/natures-grace",
    "omen_of_clarity": "https://www.wowhead.com/forever/spell=16864/omen-of-clarity",
    "clearcasting": "https://www.wowhead.com/forever/spell=16870/clearcasting",
    "moonkin_form": "https://www.wowhead.com/forever/spell=24858/moonkin-form",
    "mangle_grant_stale_helper": "https://www.wowhead.com/forever/spell=409828/mangle",
    "primal_bite_r1": "https://www.wowhead.com/forever/spell=407995/primal-bite",
    "druid_client_diff": "https://foreverdiff.com/classes/druid/",
    "swipe_r1": "https://www.wowhead.com/forever/spell=779/swipe",
    "maul_r1": "https://www.wowhead.com/forever/spell=6807/maul",
    "lacerate_r1": LACERATE_SOURCE,
    "shredding_attacks": SHREDDING_ATTACKS_SOURCE,
}
