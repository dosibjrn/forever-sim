from __future__ import annotations

"""Source-anchored L10-L20 Forever Hunter leveling model.

The current verified contract is deliberately bounded to L20. Source-known
spell/talent deltas and canonical SQLite gear are consumed directly; unresolved
mechanics stay explicit in MODEL_FIDELITY rather than being hidden behind
placeholder gear or display-only labels.
"""

from contextvars import ContextVar
from functools import lru_cache
from math import ceil

from src.shared.leveling.objective import representative_hp, physical_hit_chance
from src.shared.leveling.timing import between_pull_travel_s
from src.v2.stat_weight_model import normalize_objective_gradient
from src.rulesets.forever.shared.recovery import solve_recovery, RECOVERY_SOLVER_ID
from src.rulesets.forever.items.runtime_selection import select_gear as catalogue_select_gear, item_payload as catalogue_item_payload, item_vector as catalogue_item_vector, effective_level as catalogue_effective_level
from src.rulesets.forever.items.gear_requirements import enrich_catalogue_metadata
from .talents import Talents

_GEAR_PROBE: ContextVar[dict[str, float]] = ContextVar("hunter_gear_probe", default={})
_GEAR_SELECTION_WEIGHTS: ContextVar[dict[str, float] | None] = ContextVar("hunter_gear_selection_weights", default=None)

# Exact public spell facts used by this L10-L20 scorer.
ARCANE_SHOT = (
    # min level, damage, mana, cooldown
    (6, 20.0, 25.0, 6.0),
    (12, 26.0, 35.0, 6.0),
    (20, 39.0, 50.0, 6.0),
    (28, 65.0, 80.0, 6.0),
    (36, 94.0, 105.0, 6.0),
)
SERPENT_STING = (
    # min level, total damage, mana, duration
    (10, 30.0, 30.0, 15.0),
    (18, 60.0, 50.0, 15.0),
    (26, 110.0, 80.0, 15.0),
    (34, 170.0, 115.0, 15.0),
)
ASPECT_HAWK = (
    (10, 20.0),
    (18, 35.0),
    (28, 50.0),
    (38, 70.0),
)

# Forever Summon Hawk trained ranks.  Client/Wowhead/ForeverDiff facts:
# rank 1 L25: 32 base, 80 mana; rank 2 L36: 47 base, 105 mana;
# rank 3 L48: 85 base, 135 mana; rank 4 L60: 108 base, 190 mana.
# Every rank is instant, 6s cooldown, +5% RAP initial Physical hit, 18s hawk
# duration, max 2 active, and shares its cooldown with Arcane Shot.
# The spawned hawk's *continuing assault* attack table is server-side and still
# not source-pinned, so this scorer intentionally credits only the exact initial
# strike as a lower-bound contribution instead of inventing sustained DPS.
SUMMON_HAWK = (
    # min level, base initial damage, mana
    (25, 32.0, 80.0),
    (36, 47.0, 105.0),
    (48, 85.0, 135.0),
    (60, 108.0, 190.0),
)
SUMMON_HAWK_RAP_COEFF = 0.05
SUMMON_HAWK_COOLDOWN_S = 6.0
SUMMON_HAWK_DURATION_S = 18.0
SUMMON_HAWK_ACTIVE_CAP = 2

# Forever baseline Aimed Shot ranks: min level, normalized weapon bonus, mana, cast, cooldown.
RAPID_FIRE = {"min_level": 26, "mana": 100.0, "duration_s": 15.0, "cooldown_s": 300.0, "attack_speed_bonus": 0.40}

SNIPER_SHOT = {"min_level": 40, "bonus_damage": 160.0, "mana": 365.0, "cast_s": 4.0, "cooldown_s": 15.0}


# Bounded source-backed Survival melee/trap policy facts (Forever 1.60.1).
RAPTOR_STRIKE = (
    # min level, bonus damage, mana, cooldown
    (16, 21.0, 35.0, 6.0),
    (24, 34.0, 45.0, 6.0),
    (32, 50.0, 55.0, 6.0),
    (40, 80.0, 70.0, 6.0),
)
MONGOOSE_BITE = (
    # min level, bonus damage, mana, cooldown
    (16, 15.0, 30.0, 5.0),
    (30, 22.0, 40.0, 5.0),
)
IMMOLATION_TRAP = (
    # min level, total damage over 15s, mana, baseline cooldown
    (16, 105.0, 50.0, 30.0),
    (26, 215.0, 90.0, 30.0),
    (36, 340.0, 135.0, 30.0),
)

AIMED_SHOT = (
    (20, 20.0, 75.0, 2.0, 6.0),
    (28, 34.0, 115.0, 2.0, 6.0),
    (36, 55.0, 160.0, 2.0, 6.0),
)

# Canonical family/active-skill authority lives in pets.py.  Keeping the
# capability table out of the scorer prevents another all-families Bite+Claw
# approximation from becoming implicit runtime truth.
from .pets import (
    PET_FAMILIES, PET_BASE_FOCUS_REGEN_PER_S, PET_GROWL_FOCUS,
    PET_GROWL_COOLDOWN_S, PET_GCD_S, capability_payload,
    modeled_damage_skills,
)

# Compatibility aliases retained for older focused regressions/tools.  The
# canonical rank authority is pets.PET_DAMAGE_SKILLS.
from .pets import PET_DAMAGE_SKILLS as _PET_DAMAGE_SKILLS
PET_BITE = tuple((r[0], r[1], r[2], r[3]) for r in _PET_DAMAGE_SKILLS["bite"])
PET_CLAW = tuple((r[0], r[1], r[2], r[3]) for r in _PET_DAMAGE_SKILLS["claw"])


def _latest(rows, level):
    eligible = [r for r in rows if int(r[0]) <= int(level)]
    return eligible[-1] if eligible else None


@lru_cache(maxsize=32)
def _selected_catalogue_gear(level: int):
    return catalogue_select_gear("hunter", int(level), "hunter")


def _gear_from_catalogue(level: int, probe: dict[str, float]) -> dict:
    """Canonical Hunter equipment plus conservative naked/base stat curve.

    The base-stat curve remains explicit until a pinned Hunter level-stat table
    is added, but every equipment contribution and the ranged weapon itself come
    from the packaged SQLite catalogue.
    """
    level = int(level)
    selection_weights = _GEAR_SELECTION_WEIGHTS.get()
    selected = (
        catalogue_select_gear("hunter", level, "hunter", weights=selection_weights)
        if selection_weights is not None
        else _selected_catalogue_gear(level)
    )
    if not selected or "ranged" not in selected:
        raise RuntimeError(f"canonical catalogue has no legal Hunter ranged weapon at level {level}")

    # Existing L10-L20 baseline represents naked/base attributes only from .61
    # onward; equipment is summed independently below.
    gear = {
        "strength": 18.0 + 1.10 * level,
        "agility": 20.0 + 1.55 * level,
        "intellect": 16.0 + 1.10 * level,
        "spirit": 15.0 + 0.95 * level,
        "stamina": 19.0 + 1.20 * level,
        "mp5": 0.0,
        "attack_power": 0.0,
        "armor": 0.0,
    }
    slots = {}
    for display_slot, item in selected.items():
        v = catalogue_item_vector(item)
        for key in ("strength", "agility", "intellect", "spirit", "stamina", "mp5", "attack_power", "armor"):
            gear[key] += float(v.get(key, 0.0) or 0.0)
        slots[display_slot] = catalogue_item_payload(
            item, display_slot=display_slot, effective_level=catalogue_effective_level(item)
        )

    ranged = selected["ranged"]
    gear["weapon_dps"] = float(ranged.weapon_dps or 0.0)
    gear["weapon_speed"] = float(ranged.weapon_speed or 0.0) or 2.8
    for key, value in probe.items():
        gear[key] = float(gear.get(key, 0.0)) + float(value or 0.0)
    gear["slots"] = slots
    gear["name"] = "canonical_sqlite_hunter"
    gear["family"] = "canonical_sqlite_runtime_selection"
    gear["provenance"] = "sqlite_catalogue"
    enrich_catalogue_metadata(gear, class_key="hunter", role="hunter", level=level, selected=selected)
    return gear


def _ranged_profile(level: int, t: Talents, *, no_pet: bool, pet_family: str = "cat") -> dict:
    level = int(level)
    probe = dict(_GEAR_PROBE.get() or {})
    gear = _gear_from_catalogue(level, probe)

    hawk = _latest(ASPECT_HAWK, level)
    hawk_rap = float(hawk[1]) if hawk else 0.0
    # Lightning Reflexes is policy-independent: +2% Agility per rank.
    effective_agility = gear["agility"] * (1.0 + 0.02 * max(0, min(5, int(t.lightning_reflexes))))
    intellect = gear["intellect"]
    careful_aim_ap = intellect * 0.20 * int(t.careful_aim)
    trueshot_rap = 30.0 if int(t.trueshot_aura) > 0 else 0.0
    rap = 2.0 * effective_agility + gear.get("attack_power", 0.0) + hawk_rap + careful_aim_ap + trueshot_rap
    weapon_dps = gear["weapon_dps"] + rap / 14.0

    hit = physical_hit_chance(level, level, bonus_pct=float(t.surefooted))
    crit = min(0.45, 0.05 + 0.01 * float(t.lethal_attacks) + 0.00035 * effective_agility)
    # Mortal Shots increases the critical-strike damage bonus on ranged abilities
    # by 6% per rank. Base ranged crits are 200% damage, so expected multiplier is
    # 1 + crit * (1 + bonus), not a flat crit-chance increase.
    mortal_crit_bonus = 0.06 * max(0, min(5, int(t.mortal_shots)))
    crit_ev = 1.0 + crit * (1.0 + mortal_crit_bonus)

    # Deadly Aspects: 2% proc/rank from Auto Shot, 30% ranged haste for 12s.
    auto_rate = 1.0 / gear["weapon_speed"]
    proc_rate = auto_rate * (0.02 * int(t.deadly_aspects))
    quick_shots_uptime = min(1.0, proc_rate * 12.0)
    haste_mult = 1.0 + 0.30 * quick_shots_uptime

    # Rapid Fire is a baseline Hunter ability from L26: 100 mana, 15 s duration,
    # 5 min cooldown, +40% ranged/melee attack speed. Rapid Killing reduces
    # that cooldown by 1/2 minutes at rank 1/2. For this single-target ranged
    # policy, conservatively credit the attack-speed window to Auto Shot only;
    # instant-shot cooldowns are unchanged and Aimed Shot occupancy is not yet
    # explicitly scheduled by this expected-value scorer.
    rapid_rank = max(0, min(2, int(t.rapid_killing)))
    rapid_fire_cd_s = 0.0
    rapid_fire_uptime = 0.0
    rapid_fire_mps = 0.0
    if level >= int(RAPID_FIRE["min_level"]):
        rapid_fire_cd_s = max(60.0, float(RAPID_FIRE["cooldown_s"]) - 60.0 * rapid_rank)
        rapid_fire_uptime = min(1.0, float(RAPID_FIRE["duration_s"]) / rapid_fire_cd_s)
        rapid_fire_mps = float(RAPID_FIRE["mana"]) / rapid_fire_cd_s
    rapid_fire_haste_mult = 1.0 + float(RAPID_FIRE["attack_speed_bonus"]) * rapid_fire_uptime
    ranged_weapon_mult = 1.0 + 0.01 * max(0, min(5, int(t.ranged_weapon_specialization)))
    auto_dps = weapon_dps * hit * crit_ev * haste_mult * rapid_fire_haste_mult * ranged_weapon_mult

    tracking_mult = 1.0 + 0.01 * int(t.improved_tracking)
    lone_wolf_mult = 1.20 if (no_pet and int(t.lone_wolf) > 0) else 1.0
    # Forever Focused Fire is 1%/rank to hunter + pet while pet is active.
    focused_fire_mult = 1.0 + (0.01 * int(t.focused_fire) if not no_pet else 0.0)

    arc = _latest(ARCANE_SHOT, level)
    arcane_dps = arcane_mps = arcane_damage = 0.0
    arc_cd = None
    arcane_mana = 0.0
    if arc:
        _, arc_damage, arc_mana, base_cd = arc
        arcane_damage = float(arc_damage)
        arcane_mana = float(arc_mana)
        arc_cd = max(2.0, float(base_cd) - 0.3 * int(t.improved_arcane_shot))
        arcane_dps = arcane_damage / arc_cd
        arcane_mps = arcane_mana / arc_cd

    # Summon Hawk is a real BM action from L25 when talented.  The exact
    # source-backed cadence is two hawks then one Arcane Shot over the 18s hawk
    # window (max 2 active; shared 6s cooldown).  Credit the initial strike only
    # until the spawned hawk's sustained attack table is pinned.  Ferocity adds
    # hawk crit chance and Unleashed Fury increases hawk damage by 3%/rank.
    hawk_rank = _latest(SUMMON_HAWK, level) if int(t.summon_hawk) > 0 else None
    summon_hawk_rank_level = 0
    summon_hawk_base_damage = 0.0
    summon_hawk_mana = 0.0
    summon_hawk_initial_damage_ev = 0.0
    summon_hawk_initial_dps_floor = 0.0
    summon_hawk_casts_per_s = 0.0
    summon_hawk_mana_per_s = 0.0
    summon_hawk_arcane_casts_per_s = 0.0
    summon_hawk_credited_crit_chance = 0.0
    if hawk_rank is not None:
        summon_hawk_rank_level, summon_hawk_base_damage, summon_hawk_mana = hawk_rank
        # Ferocity explicitly increases hawk crit chance by 2%/rank.  The
        # spawned hawk's baseline crit inheritance is not pinned, so the lower
        # bound credits only the source-known Ferocity increment rather than
        # borrowing the regular pet's full Hunter-crit inheritance.
        summon_hawk_credited_crit_chance = 0.02 * max(0, min(5, int(t.ferocity)))
        hawk_crit_ev = 1.0 + summon_hawk_credited_crit_chance
        hawk_damage_mult = 1.0 + 0.03 * max(0, min(5, int(t.unleashed_fury)))
        summon_hawk_initial_damage_ev = (
            (float(summon_hawk_base_damage) + SUMMON_HAWK_RAP_COEFF * rap)
            * hawk_crit_ev
            * hawk_damage_mult
        )
        # Guide/client cadence: H, H, Arcane, repeat.  This is 2 hawks and one
        # Arcane cast per 18s while respecting both the active cap and shared CD.
        summon_hawk_casts_per_s = float(SUMMON_HAWK_ACTIVE_CAP) / SUMMON_HAWK_DURATION_S
        summon_hawk_arcane_casts_per_s = 1.0 / SUMMON_HAWK_DURATION_S
        summon_hawk_initial_dps_floor = summon_hawk_initial_damage_ev * summon_hawk_casts_per_s
        summon_hawk_mana_per_s = float(summon_hawk_mana) * summon_hawk_casts_per_s
        if arc:
            arcane_dps = arcane_damage * summon_hawk_arcane_casts_per_s
            arcane_mps = arcane_mana * summon_hawk_arcane_casts_per_s

    sting = _latest(SERPENT_STING, level)
    sting_dps = sting_mps = 0.0
    if sting:
        _, sting_total, sting_mana, duration = sting
        sting_mult = (1.0, 1.06, 1.13, 1.20)[max(0, min(3, int(t.improved_stings)))]
        sting_dps = (float(sting_total) * sting_mult / float(duration)) * (1.0 + 0.5 * crit)
        sting_mps = float(sting_mana) / float(duration)

    aimed_dps = aimed_mps = aimed_damage = 0.0
    aimed = _latest(AIMED_SHOT, level)
    if aimed:
        _lvl, bonus, mana, _cast, cd = aimed
        normalized_hit = gear["weapon_dps"] * gear["weapon_speed"] + rap / 14.0 * gear["weapon_speed"]
        barrage_mult = (1.0, 1.03, 1.07, 1.10)[max(0, min(3, int(t.barrage)))]
        aimed_damage = (normalized_hit + bonus) * hit * crit_ev * barrage_mult * ranged_weapon_mult
        aimed_dps = aimed_damage / cd
        aimed_mps = mana / cd

    sniper_dps = sniper_mps = sniper_damage = 0.0
    if level >= int(SNIPER_SHOT["min_level"]) and int(t.sniper_shot) > 0:
        normalized_hit = gear["weapon_dps"] * gear["weapon_speed"] + rap / 14.0 * gear["weapon_speed"]
        sniper_damage = (normalized_hit + float(SNIPER_SHOT["bonus_damage"])) * hit * crit_ev * ranged_weapon_mult
        sniper_dps = sniper_damage / float(SNIPER_SHOT["cooldown_s"])
        sniper_mps = float(SNIPER_SHOT["mana"]) / float(SNIPER_SHOT["cooldown_s"])

    hunter_dps = (auto_dps + arcane_dps + sting_dps + aimed_dps + sniper_dps) * tracking_mult * lone_wolf_mult * focused_fire_mult
    # Keep the Hawk floor outside generic Hunter/pet multipliers unless the
    # Forever source explicitly says they affect hawks.  Its own calculation
    # already includes the directly sourced Unleashed Fury/Ferocity effects.
    hunter_dps += summon_hawk_initial_dps_floor

    pet_family_key = str(pet_family) if str(pet_family) in PET_FAMILIES else "cat"
    family = PET_FAMILIES[pet_family_key]
    pet_capability = capability_payload(pet_family_key, level)
    pet_raw_dps = pet_dps = pet_uptime = pet_death_probability = pet_revive_s = 0.0
    pet_white_dps = pet_active_dps = pet_focus_regen_per_s = pet_damage_focus_per_s = 0.0
    pet_bite_rate = pet_claw_rate = 0.0
    pet_skill_rates: dict[str, float] = {}
    pet_skill_dps: dict[str, float] = {}
    pet_health = pet_armor_mult = 0.0
    if not no_pet:
        # Base curve remains an explicit L10-20 approximation, but family multipliers,
        # Endurance Training and Improved Revive Pet now flow through the scorer.
        # Forever pet panel scaling: pets inherit 10% of the hunter's highest AP
        # source and 100% of the hunter's crit chance. Keep the existing explicit
        # base-pet curve as the unsourced baseline, but put source-backed player
        # stat scaling on top instead of the old direct Agility->pet-DPS shortcut.
        pet_base = 4.8 + 0.46 * level
        pet_inherited_ap = 0.10 * max(rap, gear.get("attack_power", 0.0))
        pet_ap_dps = pet_inherited_ap / 14.0
        pet_crit = min(0.75, crit + 0.02 * int(t.ferocity))
        pet_crit_ev = 1.0 + pet_crit
        unleashed_mult = 1.0 + 0.03 * int(t.unleashed_fury)
        # Frenzy: each pet crit has 20% proc chance per rank for +30% attack
        # speed for 8s. The pet white/skill split is not modeled yet, so use a
        # bounded expected-value uptime against the existing aggregate pet DPS.
        frenzy_rank = max(0, min(5, int(t.frenzy)))
        pet_swing_rate = 1.0 / max(0.1, float(family["attack_speed"]))
        frenzy_proc_rate = pet_swing_rate * pet_crit * (0.20 * frenzy_rank)
        frenzy_uptime = min(1.0, frenzy_proc_rate * 8.0)
        frenzy_mult = 1.0 + 0.30 * frenzy_uptime

        # Bestial Wrath: +50% pet damage for 18s on a 120s cooldown. Credit
        # source-visible damage uptime; base-mana cost is intentionally not
        # charged until Hunter base-mana tables are pinned.
        bestial_wrath_uptime = 0.15 if int(t.bestial_wrath) else 0.0
        bestial_wrath_mult = 1.0 + 0.50 * bestial_wrath_uptime

        pet_white_dps = (pet_base + pet_ap_dps) * pet_crit_ev * float(family["damage"]) * unleashed_mult * focused_fire_mult * frenzy_mult * bestial_wrath_mult

        # Bounded pet focus/active-skill policy for L24-L40. Pets regenerate
        # 5 focus/s baseline. Solo leveling reserves Growl's 15 focus / 5 s,
        # then spends the remainder on source-pinned Bite first (better damage
        # per focus) and Claw second. The shared 1.5s pet GCD bounds total
        # active casts. Bestial Discipline is +10/+20% focus regeneration.
        bestial_discipline_rank = max(0, min(2, int(t.bestial_discipline)))
        pet_focus_regen_per_s = PET_BASE_FOCUS_REGEN_PER_S * (1.0 + 0.10 * bestial_discipline_rank)
        growl_focus_per_s = PET_GROWL_FOCUS / PET_GROWL_COOLDOWN_S
        pet_damage_focus_per_s = max(0.0, pet_focus_regen_per_s - growl_focus_per_s)
        pet_active_dps = 0.0
        pet_bite_rate = pet_claw_rate = 0.0
        pet_skill_rates: dict[str, float] = {}
        pet_skill_dps: dict[str, float] = {}
        focus_left = pet_damage_focus_per_s
        gcd_budget = 1.0 / PET_GCD_S

        # Family-constrained bounded allocator.  Maximize source-pinned base
        # damage per Focus, respecting skill cooldown and the shared pet GCD.
        # Physical Bite/Claw retain the accepted pet-crit EV behavior.
        # Lightning Breath is conservatively not granted a crit multiplier until
        # Forever pet-spell crit behavior is source-pinned.
        skills = sorted(
            modeled_damage_skills(pet_family_key, level),
            key=lambda x: (float(x["damage"]) / max(1e-9, float(x["focus"])), str(x["skill"])),
            reverse=True,
        )
        for skill in skills:
            if focus_left <= 0.0 or gcd_budget <= 0.0:
                break
            cooldown_s = float(skill["cooldown_s"])
            cd_cap = (1.0 / cooldown_s) if cooldown_s > 0.0 else float("inf")
            rate = min(cd_cap, focus_left / float(skill["focus"]), gcd_budget)
            if rate <= 0.0:
                continue
            focus_left = max(0.0, focus_left - rate * float(skill["focus"]))
            gcd_budget = max(0.0, gcd_budget - rate)
            crit_mult = pet_crit_ev if str(skill["school"]) == "physical" else 1.0
            raw = rate * float(skill["damage"]) * crit_mult
            pet_skill_rates[str(skill["skill"])] = rate
            pet_skill_dps[str(skill["skill"])] = raw
            pet_active_dps += raw

        pet_bite_rate = float(pet_skill_rates.get("bite", 0.0))
        pet_claw_rate = float(pet_skill_rates.get("claw", 0.0))
        pet_active_dps *= float(family["damage"]) * unleashed_mult * focused_fire_mult * frenzy_mult * bestial_wrath_mult
        pet_skill_dps = {
            k: v * float(family["damage"]) * unleashed_mult * focused_fire_mult * frenzy_mult * bestial_wrath_mult
            for k, v in pet_skill_dps.items()
        }
        pet_raw_dps = pet_white_dps + pet_active_dps

        endurance_mult = 1.0 + 0.03 * int(t.endurance_training)
        inherited_health = 2.0 * gear["stamina"]
        pet_health = ((150.0 + 12.0 * level) + inherited_health) * float(family["health"]) * endurance_mult
        inherited_armor = 0.30 * gear.get("armor", 0.0)
        base_pet_armor_proxy = max(1.0, 100.0 + 8.0 * level)
        pet_armor_mult = float(family["armor"]) * endurance_mult * (1.0 + inherited_armor / base_pet_armor_proxy)

        # Engage delay is a real uptime loss in solo leveling. Bestial Swiftness'
        # +30% pet move speed directly reduces that gap.
        engage_s = 0.85 / (1.30 if int(t.bestial_swiftness) else 1.0)
        preliminary = representative_hp(level) / max(1.0, hunter_dps + pet_raw_dps)
        engage_uptime = max(0.0, min(1.0, (preliminary - engage_s) / max(0.01, preliminary)))

        # Bounded expected-value pet attrition. Armor/health/endurance reduce death
        # pressure; Improved Revive Pet reduces the expected downtime when it happens.
        pet_incoming = (8.0 + 0.48 * level) / max(0.65, pet_armor_mult)
        pressure = pet_incoming * preliminary / max(1.0, pet_health)
        pet_death_probability = min(0.08, 0.006 + 0.055 * pressure)
        revive_rank = int(t.improved_revive_pet)
        revive_cast_s = max(4.0, 10.0 - 3.0 * revive_rank)
        revive_mana = 35.0 * max(0.0, 1.0 - 0.20 * revive_rank)
        pet_revive_s = pet_death_probability * (revive_cast_s + revive_mana / 20.0)
        survival_uptime = max(0.0, 1.0 - 0.5 * pet_death_probability)
        pet_uptime = engage_uptime * survival_uptime
        pet_dps = pet_raw_dps * pet_uptime

    # Rapid Killing is a chain-level effect: after each non-trivial kill, the next
    # Shot gets +10%/+20%. Approximate one buffed Aimed Shot (or Arcane Shot) per mob.
    rapid_rank = max(0, min(2, int(t.rapid_killing)))
    rapid_bonus_per_mob = 0.0
    if rapid_rank > 0:
        next_shot = sniper_damage if sniper_damage > 0 else (aimed_damage if aimed_damage > 0 else arcane_damage * hit * crit_ev)
        rapid_bonus_per_mob = next_shot * (0.10 * rapid_rank)

    hp = representative_hp(level)
    base_dps = max(1.0, hunter_dps + pet_dps)
    kill_s = hp / base_dps
    if rapid_bonus_per_mob > 0:
        kill_s = hp / max(1.0, base_dps + rapid_bonus_per_mob / max(1.0, kill_s))
    dps = hp / max(0.01, kill_s)

    efficiency = max(0.0, 1.0 - 0.03 * int(t.efficiency))
    # Efficiency names Shots, Stings and melee abilities; Summon Hawk is not
    # silently granted that reduction.
    mana_per_s = ((arcane_mps + sting_mps + aimed_mps + sniper_mps) * efficiency) + summon_hawk_mana_per_s + rapid_fire_mps
    mana_spent = mana_per_s * kill_s
    mana_pool = 120.0 + 11.5 * level + 15.0 * gear["intellect"]
    # Classic/Forever mana semantics: Spirit regen is suppressed by the 5SR
    # after mana-spending shots, while flat MP5 continues in combat.  Hunter
    # gear carries an explicit naked/base Spirit approximation, so the ordinary
    # Druid/Paladin/Hunter OOC formula can use total modeled Spirit here.
    spirit_regen_per_s = 7.5 + 0.10 * gear["spirit"]
    mp5_regen_per_s = gear["mp5"] / 5.0
    rapid_recup_rank = max(0, min(2, int(t.rapid_recuperation)))
    # Serpent Sting is maintained in this policy, so its 15s Rapid Recuperation
    # window is treated as continuous after the opener. Consuming Rapid Killing
    # raises the preserved Spirit-regeneration fraction to 50%/100% at ranks 1/2.
    rapid_recup_fraction = 0.0
    if rapid_recup_rank > 0 and sting:
        rapid_recup_fraction = 0.25 * rapid_recup_rank
        if int(t.rapid_killing) > 0:
            rapid_recup_fraction = 0.50 * rapid_recup_rank
    # Forever Bestial Discipline also preserves 25%/50% of Spirit mana regen
    # while spending mana. This is independent of the pet active-skill budget.
    bestial_discipline_regen_fraction = 0.25 * max(0, min(2, int(t.bestial_discipline)))
    # Resourcefulness: each crit has a 30/60% chance to enable 50% Spirit
    # regeneration while casting for 30s. Use a bounded Poisson-style uptime
    # approximation from ranged attack/shot crit opportunities; the mana-cost
    # reduction half applies only to traps/melee abilities and is deferred.
    resource_rank = max(0, min(2, int(t.resourcefulness)))
    resourcefulness_fraction = 0.0
    resourcefulness_uptime = 0.0
    if resource_rank > 0:
        crit_event_rate = max(0.0, (1.0 / max(0.1, gear["weapon_speed"])) + (1.0 / max(2.0, arc_cd or 6.0))) * crit
        proc_rate = crit_event_rate * (0.30 * resource_rank)
        resourcefulness_uptime = min(1.0, proc_rate * 30.0)
        resourcefulness_fraction = 0.50 * resourcefulness_uptime
    combat_mana_regen_per_s = mp5_regen_per_s + spirit_regen_per_s * max(rapid_recup_fraction, resourcefulness_fraction, bestial_discipline_regen_fraction)
    ooc_mana_regen_per_s = spirit_regen_per_s + mp5_regen_per_s

    travel_speed = (1.30 + 0.03 * int(t.pathfinding)) if level >= 20 else 1.0
    travel = between_pull_travel_s(speed_multiplier=travel_speed)

    # Price long-run resource continuity, but route the actual sit recovery
    # through the same ruleset-wide solver as Mage/Druid/Paladin.  Combat mana
    # regeneration remains a Hunter mechanic; once the pull ends, HP and mana
    # deficits recover concurrently under the canonical food/water contract.
    combat_regen = combat_mana_regen_per_s * kill_s
    mana_deficit = max(0.0, mana_spent - combat_regen)

    # Ranged/pet leveling exposure. Survivalist and Deflection reduce the HP
    # deficit presented to the shared recovery solver. Deterrence is amortized
    # over its 5-minute cooldown.
    exposure = 0.16 if not no_pet else 0.34
    avoidance = min(0.35, 0.02 * int(t.deflection))
    if int(t.deterrence):
        # Survivalist's Discipline reduces Deterrence cooldown by 20/40%.
        det_cd = 300.0 * (1.0 - 0.20 * max(0, min(2, int(t.survivalists_discipline))))
        avoidance += (10.0 / max(1.0, det_cd)) * 0.25
    player_hp = (180.0 + 10.0 * gear["stamina"]) * (1.0 + 0.02 * int(t.survivalist))
    incoming = (7.0 + 0.42 * level) * kill_s * exposure * max(0.0, 1.0 - avoidance)
    # Spirit Bond contributes passive player healing while a pet is active.
    # Rank 1 = 1% max HP / 10s; rank 2 = 1% / 5s. Apply only the healing that
    # can occur during combat before the shared recovery solver sees the deficit.
    spirit_bond_hps = 0.0
    if not no_pet and int(t.spirit_bond) > 0:
        spirit_bond_hps = player_hp * (0.001 if int(t.spirit_bond) == 1 else 0.002)
        incoming = max(0.0, incoming - spirit_bond_hps * kill_s)
    resource_recovery = solve_recovery(
        level, incoming, mana_deficit,
        passive_mana_regen_per_s=ooc_mana_regen_per_s,
    )
    # Pet revival is a Hunter-specific serial action. Its expected cast/mana tax
    # stays outside the generic player resource solver rather than teaching the
    # shared layer about pets.
    recovery_s = resource_recovery.total_s + pet_revive_s

    total = max(0.25, kill_s + recovery_s + travel)
    per100 = 100.0
    rotation = "Aspect of the Hawk; Serpent Sting; Aimed Shot on CD; Arcane Shot on CD; Auto Shot"
    if level >= int(RAPID_FIRE["min_level"]):
        rotation = "Rapid Fire on CD; " + rotation
    if hawk_rank is not None:
        rotation = rotation.replace(
            "Arcane Shot on CD; ",
            "Summon Hawk; Summon Hawk; Arcane Shot shared-CD cycle; ",
        )
    if no_pet:
        rotation = "Lone Wolf; " + rotation
    else:
        rotation = f"{pet_family_key.replace('_',' ').title()} pet attack; " + rotation
    if level < 20:
        rotation = rotation.replace("Aimed Shot on CD; ", "")

    inactive = []
    # These talents are source-known but intentionally outside this ranged
    # single-target ranged policy. Publish that fact instead of silently implying
    # they are simulated.
    if int(t.improved_aspect_of_the_monkey): inactive.append("improved_aspect_of_the_monkey: Aspect of the Hawk active")
    if int(t.hawk_eye): inactive.append("hawk_eye: range does not change same-level stationary single-target cycle")
    if int(t.improved_concussive_shot): inactive.append("improved_concussive_shot: Concussive Shot not in damage priority")
    if int(t.entrapment): inactive.append("entrapment: traps not yet in current rotation")
    if int(t.savage_strikes): inactive.append("savage_strikes: melee weaving not yet in current rotation")
    if int(t.improved_wing_clip): inactive.append("improved_wing_clip: melee escape not yet in current rotation")
    if int(t.clever_traps): inactive.append("clever_traps: traps not yet in current rotation")
    if int(t.improved_mend_pet): inactive.append("improved_mend_pet: Mend Pet/cleanse policy not yet modeled")
    if int(t.summon_hawk) and hawk_rank is not None:
        inactive.append("summon_hawk_sustained_assault: source-backed initial strike/shared-CD cadence modeled; spawned hawk 18s sustained attack table remains unpriced")
        if int(t.improved_arcane_shot) > 0:
            inactive.append("summon_hawk_improved_arcane_shared_cd: H/H/Arcane 18s source cadence retained; exact interaction with reduced Arcane Shot cooldown is not separately pinned")
    if int(t.intimidation): inactive.append("intimidation: control/threat utility not priced in stationary single-target cycle")
    if int(t.scatter_shot): inactive.append("scatter_shot: control/disorient utility not priced in stationary single-target cycle")
    if int(t.survival_tactics): inactive.append("survival_tactics: Trap/Feign Death hit is outside current ranged damage policy")
    if int(t.predators_edge): inactive.append("predators_edge: melee crit/off-hand effect requires melee Survival policy")
    if int(t.counterattack): inactive.append("counterattack: reactive melee strike requires parry/melee scheduling")
    if int(t.resourcefulness): inactive.append("resourcefulness: mana-regeneration proc modeled; trap/melee mana-cost reduction deferred")
    if int(t.expose_prey): inactive.append("expose_prey: Mongoose Bite activation requires melee Survival policy")
    if int(t.survivalists_discipline): inactive.append("survivalists_discipline: Deterrence cooldown modeled; Trap cooldown requires trap policy")
    if int(t.strider_kick): inactive.append("strider_kick: melee weapon strike/movement utility requires melee Survival policy")
    if int(t.lacerating_strikes): inactive.append("lacerating_strikes: Mongoose Bite bleed requires melee Survival policy")

    return {
        "total_s": per100 * total,
        "kill_s": per100 * kill_s,
        "recovery_s": per100 * recovery_s,
        "travel_s": per100 * travel,
        "dps": dps,
        "mobs_per_hour": 3600.0 / total,
        "profile": "lone_wolf_ranged" if no_pet else "pet_ranged",
        "combat_profile": "ranged",
        "rotation": rotation,
        "policy": "single_target_ranged_priority",
        "gear": gear["name"],
        "gear_stats": {"model": gear["family"], **gear, "ranged_attack_power": rap},
        "pull_size": 1,
        "mana_pool": mana_pool,
        "mana_spent_per_mob": mana_spent,
        "mana_regen_per_s": ooc_mana_regen_per_s,
        "ooc_mana_regen_per_s": ooc_mana_regen_per_s,
        "combat_mana_regen_per_s": combat_mana_regen_per_s,
        "spirit_regen_per_s": spirit_regen_per_s,
        "mp5_regen_per_s": mp5_regen_per_s,
        "combat_mana_regen_per_mob": combat_regen,
        "mana_deficit_per_mob": mana_deficit,
        "drink_s_per_mob": resource_recovery.water_s,
        "food_s_per_mob": resource_recovery.food_s,
        "recovery_method": resource_recovery.method,
        "recovery_solver_id": RECOVERY_SOLVER_ID,
        "player_hp": player_hp,
        "incoming_damage": incoming,
        "resource_recovery_s_per_mob": resource_recovery.total_s,
        "pet_recovery_s_per_mob": pet_revive_s,
        "pet_family": None if no_pet else pet_family_key,
        "pet_family_capability": None if no_pet else pet_capability,
        "pet_available_active_skills": [] if no_pet else list(pet_capability.get("skills") or ()),
        "pet_modeled_damage_skills": [] if no_pet else [x.get("skill") for x in (pet_capability.get("modeled_damage_skills") or ())],
        "pet_skill_casts_per_s": {} if no_pet else dict(pet_skill_rates),
        "pet_active_skill_dps_by_skill": {} if no_pet else dict(pet_skill_dps),
        "pet_family_damage_mult": None if no_pet else float(family["damage"]),
        "pet_family_health_mult": None if no_pet else float(family["health"]),
        "pet_family_armor_mult": None if no_pet else float(family["armor"]),
        "pet_attack_speed": None if no_pet else float(family["attack_speed"]),
        "pet_raw_dps": pet_raw_dps,
        "pet_white_dps": 0.0 if no_pet else pet_white_dps,
        "pet_active_skill_dps": 0.0 if no_pet else pet_active_dps,
        "pet_focus_regen_per_s": 0.0 if no_pet else pet_focus_regen_per_s,
        "pet_damage_focus_per_s": 0.0 if no_pet else pet_damage_focus_per_s,
        "pet_bite_casts_per_s": 0.0 if no_pet else pet_bite_rate,
        "pet_claw_casts_per_s": 0.0 if no_pet else pet_claw_rate,
        "pet_inherited_attack_power": 0.0 if no_pet else pet_inherited_ap,
        "pet_inherited_crit_chance": 0.0 if no_pet else crit,
        "pet_effective_crit_chance": 0.0 if no_pet else pet_crit,
        "frenzy_uptime_ev": 0.0 if no_pet else frenzy_uptime,
        "bestial_wrath_uptime_ev": 0.0 if no_pet else bestial_wrath_uptime,
        "spirit_bond_hps": spirit_bond_hps,
        "pet_inherited_health_from_stamina": 0.0 if no_pet else 2.0 * gear["stamina"],
        "pet_inherited_armor": 0.0 if no_pet else 0.30 * gear.get("armor", 0.0),
        "pet_dps": pet_dps,
        "pet_uptime": pet_uptime,
        "pet_death_probability": pet_death_probability,
        "pet_expected_revive_s": pet_revive_s,
        "pet_health": pet_health,
        "pet_armor_mult": pet_armor_mult,
        "hunter_dps": hunter_dps,
        "hit_chance": hit,
        "crit_chance": crit,
        "effective_agility": effective_agility,
        "lightning_reflexes_agility_mult": 1.0 + 0.02 * max(0, min(5, int(t.lightning_reflexes))),
        "resourcefulness_combat_regen_fraction": resourcefulness_fraction,
        "resourcefulness_uptime_ev": resourcefulness_uptime,
        "quick_shots_uptime_ev": quick_shots_uptime,
        "rapid_killing_bonus_per_mob": rapid_bonus_per_mob,
        "trueshot_aura_rap": trueshot_rap,
        "mortal_shots_crit_bonus": mortal_crit_bonus,
        "rapid_recuperation_combat_regen_fraction": rapid_recup_fraction,
        "bestial_discipline_combat_regen_fraction": bestial_discipline_regen_fraction,
        "barrage_aimed_damage_mult": (1.0, 1.03, 1.07, 1.10)[max(0, min(3, int(t.barrage)))],
        "ranged_weapon_specialization_mult": ranged_weapon_mult,
        "sniper_shot_damage": sniper_damage,
        "sniper_shot_dps": sniper_dps,
        "sniper_shot_mana_per_s": sniper_mps,
        "rapid_fire_available": bool(level >= int(RAPID_FIRE["min_level"])),
        "rapid_fire_effective_cooldown_s": rapid_fire_cd_s,
        "rapid_fire_uptime_ev": rapid_fire_uptime,
        "rapid_fire_attack_speed_bonus": float(RAPID_FIRE["attack_speed_bonus"]),
        "rapid_fire_mana_per_s": rapid_fire_mps,
        "summon_hawk_available": bool(hawk_rank is not None),
        "summon_hawk_rank_min_level": int(summon_hawk_rank_level),
        "summon_hawk_base_initial_damage": float(summon_hawk_base_damage),
        "summon_hawk_rap_coefficient": float(SUMMON_HAWK_RAP_COEFF),
        "summon_hawk_initial_damage_ev": float(summon_hawk_initial_damage_ev),
        "summon_hawk_initial_dps_floor": float(summon_hawk_initial_dps_floor),
        "summon_hawk_casts_per_s": float(summon_hawk_casts_per_s),
        "summon_hawk_arcane_casts_per_s": float(summon_hawk_arcane_casts_per_s),
        "summon_hawk_mana_per_s": float(summon_hawk_mana_per_s),
        "summon_hawk_credited_crit_chance": float(summon_hawk_credited_crit_chance),
        "summon_hawk_ferocity_crit_bonus": float(0.02 * max(0, min(5, int(t.ferocity)))) if hawk_rank is not None else 0.0,
        "summon_hawk_duration_s": float(SUMMON_HAWK_DURATION_S),
        "summon_hawk_active_cap": int(SUMMON_HAWK_ACTIVE_CAP),
        "summon_hawk_shared_cooldown_s": float(SUMMON_HAWK_COOLDOWN_S),
        "summon_hawk_sustained_assault_modeled": False,
        "summon_hawk_scoring_mode": "source_backed_initial_strike_lower_bound" if hawk_rank is not None else "unavailable",
        "inactive_talent_effects": inactive,
        "approximation_flags": [
            "verified L10-L20 Hunter talent legality/effects where credited",
            "verified Auto/Arcane/Serpent/Aimed/Hawk spell facts through the sourced post-L20 ranks present in this model",
            "Rapid Fire L26 baseline and Rapid Killing cooldown reduction are source-backed; expected-value scorer credits Rapid Fire to Auto Shot haste only",
            "BM L21-L40 legality is source-backed through Improved Mend Pet, Ferocity, Summon Hawk, Spirit Bond, Intimidation, Bestial Discipline, Frenzy and Bestial Wrath",
            "MM L21-L40 legality/effects are source-backed through Trueshot Aura, Mortal Shots, Rapid Recuperation, Barrage, Scatter Shot, Ranged Weapon Specialization and Sniper Shot",
            "Survival L21-L40 legality is source-backed through Survival Tactics, Predator's Edge, Counterattack, Resourcefulness, Expose Prey, Survivalist's Discipline, Strider Kick, Lightning Reflexes and Lacerating Strikes",
            "Survival melee/trap bounded policy prices Raptor Strike, Immolation Trap, Expose Prey Mongoose Bite, Clever Traps, Resourcefulness, Survivalist's Discipline, Savage Strikes, Predator's Edge and Lacerating Strikes; Counterattack/Strider Kick remain fail-closed where cadence/base-mana authority is missing",
            "Ferocity, Spirit Bond, Frenzy and Bestial Wrath have bounded expected-value scorer effects; family-constrained L24-L40 Bite/Claw plus Wind Serpent Lightning Breath focus budgeting and Bestial Discipline focus/Spirit regen are modeled",
            "Summon Hawk L25/L36 ranks, 5% RAP initial strike, 18s duration, 2-hawk cap, 6s Arcane shared cooldown and two-Hawk/one-Arcane cadence are source-backed; scorer credits the exact initial-strike lower bound while the spawned hawk sustained attack table remains explicitly unpriced",
            "source-backed pet family capability table plus Forever player->pet Stamina/Armor/AP/Crit scaling; Charge/Prowl/Dash/Dive/Furious Howl/Shell Shield remain explicit capability-only effects until their pull/utility policies are modeled",
            "pet base curve, attrition probability and engage timing remain explicit expected-value approximations",
            "ranged and bounded Survival melee/trap single-target policies compete without GCD permutation search",
        ],
    }


def _survival_melee_profile(level: int, t: Talents, *, pet_family: str = "cat") -> dict:
    """Bounded Survival single-target melee/trap archetype.

    This intentionally avoids GCD permutation search.  It prices the source-pinned
    core: melee autos, Raptor Strike, Immolation Trap, Expose-Prey Mongoose Bite,
    Clever Traps, Resourcefulness, Survivalist's Discipline, Savage Strikes,
    Predator's Edge and Lacerating Strikes.  Reactive Counterattack and Strider
    Kick's base-mana cost stay explicit/unpriced where the required cadence/base-
    mana authority is not pinned.
    """
    level = int(level)
    ranged = _ranged_profile(level, t, no_pet=False, pet_family=pet_family)
    gear = _gear_from_catalogue(level, dict(_GEAR_PROBE.get() or {}))
    main = dict((gear.get("slots") or {}).get("weapon") or {})
    melee_dps = float(main.get("weapon_dps") or 0.0)
    melee_speed = float(main.get("weapon_speed") or 0.0)
    if level < 16 or melee_dps <= 0.0 or melee_speed <= 0.0:
        out = dict(ranged)
        out["total_s"] = float("inf")
        out["mobs_per_hour"] = 0.0
        out["profile"] = "survival_melee_trap_unavailable"
        out["combat_profile"] = "melee"
        out["policy"] = "survival_melee_trap_bounded"
        return out

    effective_agility = gear["agility"] * (1.0 + 0.02 * max(0, min(5, int(t.lightning_reflexes))))
    melee_ap = float(gear.get("strength", 0.0)) + effective_agility + float(gear.get("attack_power", 0.0))
    hit = physical_hit_chance(level, level, bonus_pct=float(t.surefooted))
    base_crit = min(0.45, 0.05 + 0.00035 * effective_agility)
    ability_crit = min(0.60, base_crit + 0.02 * max(0, min(2, int(t.savage_strikes))))
    predator_bonus = 0.06 * max(0, min(5, int(t.predators_edge)))
    auto_crit_ev = 1.0 + base_crit * (1.0 + predator_bonus)
    ability_crit_ev = 1.0 + ability_crit * (1.0 + predator_bonus)
    tracking_mult = 1.0 + 0.01 * int(t.improved_tracking)

    weapon_swing = melee_dps * melee_speed + melee_ap / 14.0 * melee_speed
    auto_dps = (melee_dps + melee_ap / 14.0) * hit * auto_crit_ev

    resource_mult = 1.0 - 0.30 * max(0, min(2, int(t.resourcefulness)))
    raptor = _latest(RAPTOR_STRIKE, level)
    raptor_dps = raptor_mps = 0.0
    if raptor:
        _, bonus, mana, cd = raptor
        raptor_dps = (weapon_swing + float(bonus)) * hit * ability_crit_ev / float(cd)
        raptor_mps = float(mana) * resource_mult / float(cd)

    trap = _latest(IMMOLATION_TRAP, level)
    trap_dps = trap_mps = trap_cd = trap_damage = 0.0
    if trap:
        _, damage, mana, base_cd = trap
        trap_cd = float(base_cd) * (1.0 - 0.20 * max(0, min(2, int(t.survivalists_discipline))))
        trap_hit = min(1.0, physical_hit_chance(level, level) + 0.05 * max(0, min(2, int(t.survival_tactics))))
        trap_damage = float(damage) * (1.0 + 0.15 * max(0, min(2, int(t.clever_traps)))) * trap_hit
        trap_dps = trap_damage / max(1.0, trap_cd)
        trap_mps = float(mana) * resource_mult / max(1.0, trap_cd)

    mongoose = _latest(MONGOOSE_BITE, level)
    mongoose_rate = mongoose_dps = mongoose_mps = lacerate_dps = 0.0
    expose_rank = max(0, min(2, int(t.expose_prey)))
    if mongoose and expose_rank > 0:
        _, bonus, mana, cd = mongoose
        # Expose Prey procs from attacks against Hunter's Mark.  Bound activation
        # by the 5s Mongoose cooldown and by an expected melee attack opportunity
        # rate; no dodge-only activations are invented here.
        attack_events = (1.0 / melee_speed) + (1.0 / float(raptor[3]) if raptor else 0.0)
        proc_rate = attack_events * (0.05 * expose_rank)
        mongoose_rate = min(1.0 / float(cd), proc_rate)
        mongoose_hit = (weapon_swing + float(bonus)) * hit * ability_crit_ev
        mongoose_dps = mongoose_rate * mongoose_hit
        mongoose_mps = mongoose_rate * float(mana) * resource_mult
        if int(t.lacerating_strikes) > 0:
            lacerate_dps = mongoose_rate * mongoose_hit * 0.40

    pet_dps = float(ranged.get("pet_dps") or 0.0)
    hunter_melee_dps = (auto_dps + raptor_dps + trap_dps + mongoose_dps + lacerate_dps) * tracking_mult
    total_dps = max(1.0, hunter_melee_dps + pet_dps)
    hp = representative_hp(level)
    kill_s = hp / total_dps

    mana_spent = (raptor_mps + trap_mps + mongoose_mps) * kill_s
    mana_pool = 120.0 + 11.5 * level + 15.0 * gear["intellect"]
    spirit_regen_per_s = 7.5 + 0.10 * gear["spirit"]
    mp5_regen_per_s = gear["mp5"] / 5.0
    resource_rank = max(0, min(2, int(t.resourcefulness)))
    crit_event_rate = max(0.0, (1.0 / melee_speed) + (1.0 / float(raptor[3]) if raptor else 0.0)) * ability_crit
    proc_rate = crit_event_rate * (0.30 * resource_rank)
    resourcefulness_uptime = min(1.0, proc_rate * 30.0)
    combat_regen = (mp5_regen_per_s + spirit_regen_per_s * 0.50 * resourcefulness_uptime) * kill_s
    mana_deficit = max(0.0, mana_spent - combat_regen)

    # Melee receives full contact exposure; Deflection and Deterrence reduce it.
    avoidance = min(0.35, 0.01 * int(t.deflection))
    if int(t.deterrence):
        det_cd = 300.0 * (1.0 - 0.20 * max(0, min(2, int(t.survivalists_discipline))))
        avoidance += (10.0 / max(1.0, det_cd)) * 0.25
    player_hp = (180.0 + 10.0 * gear["stamina"]) * (1.0 + 0.02 * int(t.survivalist))
    incoming = (7.0 + 0.42 * level) * kill_s * 0.42 * max(0.0, 1.0 - avoidance)
    recovery = solve_recovery(level, incoming, mana_deficit, passive_mana_regen_per_s=spirit_regen_per_s + mp5_regen_per_s)
    recovery_s = recovery.total_s + float(ranged.get("pet_recovery_s_per_mob") or 0.0)
    travel = between_pull_travel_s(speed_multiplier=1.0)
    total = max(0.25, kill_s + recovery_s + travel)

    inactive = []
    if int(t.counterattack): inactive.append("counterattack: reactive parry cadence remains unpriced; no fabricated proc rate")
    if int(t.strider_kick): inactive.append("strider_kick: 100% weapon damage is source-backed, but 5.81% base-mana cost is not priced until Hunter base-mana authority is pinned")
    if int(t.improved_wing_clip): inactive.append("improved_wing_clip: control utility not priced in single-target throughput")
    if int(t.entrapment): inactive.append("entrapment: root utility not priced in single-target throughput")

    return {
        **ranged,
        "total_s": 100.0 * total, "kill_s": 100.0 * kill_s, "recovery_s": 100.0 * recovery_s, "travel_s": 100.0 * travel,
        "dps": total_dps, "mobs_per_hour": 3600.0 / total,
        "profile": "survival_melee_trap", "combat_profile": "melee",
        "rotation": "Immolation Trap on CD; Raptor Strike on CD; Expose Prey -> Mongoose Bite; melee auto attack",
        "policy": "survival_melee_trap_bounded", "gear": gear["name"],
        "gear_stats": {"model": gear["family"], **gear, "melee_attack_power": melee_ap, "melee_weapon_dps": melee_dps, "melee_weapon_speed": melee_speed},
        "pull_size": 1, "mana_pool": mana_pool, "mana_spent_per_mob": mana_spent,
        "mana_deficit_per_mob": mana_deficit, "drink_s_per_mob": recovery.water_s, "food_s_per_mob": recovery.food_s,
        "recovery_method": recovery.method, "recovery_solver_id": RECOVERY_SOLVER_ID, "player_hp": player_hp, "incoming_damage": incoming,
        "resource_recovery_s_per_mob": recovery.total_s,
        "survival_auto_dps": auto_dps, "survival_raptor_dps": raptor_dps, "survival_trap_dps": trap_dps,
        "survival_mongoose_dps": mongoose_dps, "survival_lacerating_dps": lacerate_dps, "survival_mongoose_rate": mongoose_rate,
        "survival_trap_cooldown_s": trap_cd, "survival_trap_damage_per_cast": trap_damage,
        "resourcefulness_uptime": resourcefulness_uptime,
        "inactive_talent_effects": inactive,
        "approximation_flags": list(ranged.get("approximation_flags") or ()) + [
            "bounded Survival melee/trap candidate: source-pinned Raptor Strike, Immolation Trap, Expose Prey Mongoose Bite and directly modifying talents",
            "Counterattack reactive parry cadence and Strider Kick base-mana cost remain fail-closed/unpriced",
        ],
    }

def _score(level: int, t: Talents, profile: str = "all") -> dict:
    level = int(level)
    p = str(profile or "all").lower()
    pet_candidates = [_ranged_profile(level, t, no_pet=False, pet_family=f) for f in PET_FAMILIES]
    best_pet = min(pet_candidates, key=lambda r: float(r["total_s"]))
    candidates = list(pet_candidates)
    if int(t.lone_wolf) > 0:
        candidates.append(_ranged_profile(level, t, no_pet=True))

    if p == "beast_mastery":
        return best_pet
    if p == "survival":
        melee_candidates = [_survival_melee_profile(level, t, pet_family=f) for f in PET_FAMILIES]
        return min([best_pet, *melee_candidates], key=lambda r: float(r["total_s"]))
    if p == "marksmanship" and int(t.lone_wolf) > 0:
        return min(candidates, key=lambda r: float(r["total_s"]))
    return min(candidates, key=lambda r: float(r["total_s"]))


def _gear_signature(score: dict) -> tuple[tuple[str, int], ...]:
    slots = ((score.get("gear_stats") or {}).get("slots") or {})
    return tuple(sorted((str(slot), int((row or {}).get("item_id", 0) or 0)) for slot, row in slots.items()))


def _selection_weights_from_stat_model(model: dict) -> dict[str, float]:
    """Turn measured native marginal values into discrete item-score weights.

    Item scoring only needs relative positive values. Harmful/zero stats are not
    rewarded. Unmodelled stats stay absent rather than inheriting old presets.
    """
    out: dict[str, float] = {}
    for stat, row in (model.get("stats") or {}).items():
        if (row or {}).get("status", "measured") != "measured":
            continue
        value = (row or {}).get("seconds_saved_per_100_per_point")
        if value is None:
            continue
        value = max(0.0, float(value))
        if value > 1e-12:
            out[str(stat)] = value
    return out


def _marginal_stat_weights_fixed_gear(level: int, t: Talents, profile: str, baseline: dict, selection_weights: dict[str, float] | None) -> dict:
    increments = {
        "strength": 2.0,
        "agility": 2.0,
        "attack_power": 4.0,
        "intellect": 2.0,
        "spirit": 2.0,
        "mp5": 2.0,
        "stamina": 2.0,
        "weapon_dps": 1.0,
    }
    gradients: dict[str, float] = {}
    probes: dict[str, dict] = {}
    selection_token = _GEAR_SELECTION_WEIGHTS.set(selection_weights)
    try:
        for stat, inc in increments.items():
            token = _GEAR_PROBE.set({stat: inc})
            try:
                plus = _score(level, t, profile)
            finally:
                _GEAR_PROBE.reset(token)
            gradients[stat] = (float(plus["total_s"]) - float(baseline["total_s"])) / inc
            probes[stat] = {"increment": inc, "plus_s_per_100": plus["total_s"]}
    finally:
        _GEAR_SELECTION_WEIGHTS.reset(selection_token)
    result = normalize_objective_gradient(
        baseline_s_per_100=float(baseline["total_s"]),
        objective_gradient=gradients,
        method="finite_difference_hunter_fixed_gear",
        reference_stat="weapon_dps",
        metadata={"probes": probes, "profile": profile},
        note="Hunter native marginal values at the converged discrete gear set.",
        declared_stats=("strength", "agility", "intellect", "spirit", "mp5", "stamina", "weapon_dps", "attack_power", "armor"),
        stat_status={
            "armor": {"status": "not_modeled", "reason": "current ranged pet/kiting model does not consume item armor directly"},
        },
    )
    result["analytical"] = False
    return result


def _fixed_point_score(level: int, t: Talents, profile: str = "all", *, max_iterations: int = 4) -> dict:
    """Bounded gear/stat-weight fixed point for Hunter.

    Start from the legacy role preset only as a seed. Every subsequent equipment
    selection is driven by scorer-derived native marginal values. Convergence is
    defined by the discrete item-ID set, not tiny floating-point weight changes.
    """
    weights: dict[str, float] | None = None
    previous_signature = None
    trace: list[dict] = []
    final = None
    converged = False
    for iteration in range(1, max(1, int(max_iterations)) + 1):
        token = _GEAR_SELECTION_WEIGHTS.set(weights)
        try:
            score = _score(level, t, profile)
        finally:
            _GEAR_SELECTION_WEIGHTS.reset(token)
        signature = _gear_signature(score)
        model = _marginal_stat_weights_fixed_gear(level, t, profile, score, weights)
        derived = _selection_weights_from_stat_model(model)
        trace.append({
            "iteration": iteration,
            "item_ids": dict(signature),
            "objective_s_per_100": float(score["total_s"]),
            "selection_weights": dict(weights or {}),
            "derived_weights": dict(derived),
        })
        final = score
        if previous_signature is not None and signature == previous_signature:
            converged = True
            weights = dict(weights or {})
            break
        previous_signature = signature
        weights = derived or weights

    # Publish the weights actually used to choose the final discrete set, while
    # keeping the final local marginal model available to the generic caller.
    gs = dict((final or {}).get("gear_stats") or {})
    gs["gear_selection_method"] = "hunter_stat_weight_fixed_point"
    gs["gear_selection_iterations"] = len(trace)
    gs["gear_selection_converged"] = bool(converged)
    gs["selection_weights"] = dict(trace[-1]["selection_weights"] if trace else {})
    gs["derived_stat_weights"] = dict(trace[-1]["derived_weights"] if trace else {})
    gs["gear_selection_trace"] = trace
    final = dict(final or {})
    final["gear_stats"] = gs
    return final


def experimental_level_score(level: int, t: Talents, profile: str = "all") -> dict:
    level = int(level)
    out = _fixed_point_score(level, t, profile)
    if level > 20:
        out = dict(out)
        out["approximation_flags"] = list(out.get("approximation_flags") or ()) + [
            "provisional Hunter planning range L21-L40: talent legality and major single-target spec mechanics are source-backed/bounded; unresolved unpriced mechanics remain explicit in model_fidelity.capability_matrix"
        ]
        out["post20_fallback"] = "hunter_l21_l40_planning_range_source_backed_bounded"
        out["verified_level_cap"] = 20
        out["planning_level_cap"] = 40
    return out


def marginal_stat_weights(level: int, t: Talents, profile: str = "all", baseline: dict | None = None) -> dict:
    base = baseline or _fixed_point_score(int(level), t, profile)
    selection_weights = dict(((base.get("gear_stats") or {}).get("selection_weights") or {})) or None
    return _marginal_stat_weights_fixed_gear(int(level), t, profile, base, selection_weights)

