from __future__ import annotations

"""Deterministic Forever Druid solo-leveling model.

v0.11.7 replaces the old one-formula Druid proxy with explicit priority/cycle
models for Cat and Balance.  It is still an expected-value scorer rather than a
full event/MC engine, but rotations now consume real audited Forever ranks,
Energy/Combo Points, DoT maintenance, Eclipse alternation and Nature's Grace.
"""

from contextvars import ContextVar

from src.shared.leveling import objective as leveling
from src.shared.leveling.timing import between_pull_travel_s
from src.shared.leveling.spaced_pulls import SpacedPullLayout
from src.rulesets.forever.data.rules import default_rules
from src.rulesets.forever.shared.mobs import normal_world_raw_dps, WORLD_MELEE_FAMILIES
from src.rulesets.forever.shared.recovery import HealOption, solve_recovery, RECOVERY_SOLVER_ID
from src.rulesets.forever.shared.base_stats import base_spirit, spirit_provenance, BASE_STAT_AUTHORITY_ID
from src.rulesets.forever.shared.tuning import base_damage_multiplier, tuning_provenance
from src.rulesets.forever.shared.pack_geometry import estimate_pack_exposure
from src.rulesets.forever.shared.defense import armor_reduction, defense_avoidance, representative_player_hp
from src.game.data.forever.target_combat_source import physical_outgoing_expected_factors
from .talents import Talents, validate_current_schema
from .spells import CAT_FORM_LEVEL, PRIMAL_BITE_MODEL_LEVEL
from . import wowhead_facts as wh
from .rage import incoming_damage_rage_per_second, provenance as rage_provenance
from .weapon import (
    BEAR_FORM_SWING_S, form_white_dps, normal_form_hit, provenance as weapon_provenance,
)
from src.rulesets.forever.items.runtime_selection import (
    select_gear as catalogue_select_gear, item_payload as catalogue_item_payload,
    effective_level as catalogue_effective_level, item_vector as catalogue_item_vector,
    available_items as catalogue_available_items,
)
from .catalogue_gear import enrich_gear_metadata



# Request-local perturbations: concurrent listener/optimizer scoring cannot leak
# probe bonuses into another task, and source item rows remain untouched.
_GEAR_PROBE = ContextVar("druid_gear_probe", default=None)
_GEAR_SELECTION_OVERRIDE = ContextVar("druid_gear_selection_override", default=None)
_FIXED_POINT_DISABLED = ContextVar("druid_fixed_point_disabled", default=False)




def _improved_wrath_cast_delta_s(t:Talents) -> float:
    return default_rules().talent_value("druid", "improved_wrath", t.improved_wrath, "cast_time_delta_s", target="wrath") if t.improved_wrath else 0.0


def _improved_wrath_cost_pct(t:Talents) -> float:
    return default_rules().talent_value("druid", "improved_wrath", t.improved_wrath, "resource_cost_pct", target="wrath") if t.improved_wrath else 0.0

def _probe_gear(gear: dict) -> dict:
    for stat, amount in (_GEAR_PROBE.get() or {}).items():
        gear[stat] = float(gear.get(stat, 0.0)) + amount
    return gear


def _latest(rows, level: int):
    out = None
    for row in rows:
        if int(row[0]) <= int(level):
            out = row
        else:
            break
    return out


def _natural_reaction(t: Talents) -> tuple[float, float, float]:
    """Return (dodge chance, rage proc chance per dodge, rage per proc)."""
    rank=max(0,min(5,int(t.natural_reaction)))
    return (
        wh.NATURAL_REACTION_DODGE_PER_RANK*rank,
        min(1.0,wh.NATURAL_REACTION_RAGE_PROC_CHANCE_PER_RANK*rank),
        wh.NATURAL_REACTION_RAGE_PER_PROC,
    )


def _druid_defense_avoidance(gear: dict) -> float:
    """Bonus complete avoidance from +Defense skill for a Druid.

    Druids cannot parry in Cat/Bear form, so +Defense contributes only through
    the mob-miss and Druid-dodge channels.  Base miss/dodge are intentionally
    outside this delta helper; this scorer only needs the item/talent-sensitive
    bonus above the normal level Defense baseline.
    """
    return defense_avoidance(
        max(0.0,float(gear.get("defense",0.0))),
        can_miss=True, can_dodge=True, can_parry=False,
    )


def _thick_hide_base_armor(level: int, t: Talents, gear: dict) -> float:
    """Base Armor granted by Forever Thick Hide before form multipliers.

    Item ``defense`` is stored as bonus Defense skill above the normal 5*level
    baseline, which is exactly the quantity the tooltip keys off.
    """
    rank=max(0,min(3,int(t.thick_hide)))
    if rank <= 0:
        return 0.0
    excess_defense=max(0.0,float(gear.get("defense",0.0)))
    return (
        wh.THICK_HIDE_BASE_ARMOR_PER_LEVEL_BY_RANK[rank] * max(0,int(level))
        + wh.THICK_HIDE_ARMOR_PER_EXCESS_DEFENSE_BY_RANK[rank] * excess_defense
    )


def _feral_form_armor(level: int, t: Talents, gear: dict, *, bear: bool) -> tuple[float,float]:
    """Return (pre-form base armor, final armor) for Cat/Bear recovery."""
    base=(float(gear.get("armor",0.0))+float(gear.get("bonus_armor",0.0)))
    base += _thick_hide_base_armor(level,t,gear)
    mult=(5.0 if int(level)>=40 else 2.8) if bear else 1.0
    return base,base*mult


def _world_melee_attack_attempts_per_second() -> float:
    # Expected attack attempts, not 1 / mean swing time: each family contributes
    # its own rate so dodge-triggered effects remain frequency-sensitive.
    return sum(float(f.weight)/max(.1,float(f.swing_s)) for f in WORLD_MELEE_FAMILIES)


def _natural_reaction_rage_per_second(t: Talents, avg_alive: float) -> float:
    dodge,proc_chance,rage_per_proc=_natural_reaction(t)
    return (
        max(1.0,float(avg_alive))
        * _world_melee_attack_attempts_per_second()
        * dodge
        * proc_chance
        * rage_per_proc
    )


def _gear_from_catalogue(level: int, role: str) -> dict:
    """Return the exact SQL-selected equipment set consumed by Druid combat.

    No curated body/weapon anchor is permitted on this path.  A missing
    packaged catalogue or an empty legal selection is a hard runtime error so
    the simulator cannot silently materialize pseudo gear.
    """
    level=int(level)
    overrides=_GEAR_SELECTION_OVERRIDE.get() or {}
    selected=overrides.get(role) if isinstance(overrides, dict) else None
    if selected is None:
        selected=catalogue_select_gear("druid", level, role)
    if not selected:
        raise RuntimeError(f"canonical catalogue has no legal Druid gear for {role} at level {level}")

    totals={
        "strength":0.0,"agility":0.0,"stamina":0.0,"intellect":0.0,"spirit":0.0,
        "spell_power":0.0,"healing":0.0,"armor":0.0,"bonus_armor":0.0,
        "defense":0.0,"attack_power":0.0,"mp5":0.0,
    }
    slots={}
    for display_slot,item in selected.items():
        totals["strength"] += float(item.strength or 0.0)
        totals["agility"] += float(item.agility or 0.0)
        totals["stamina"] += float(item.stamina or 0.0)
        totals["intellect"] += float(item.intellect or 0.0)
        totals["spirit"] += float(item.spirit or 0.0)
        totals["spell_power"] += float(catalogue_item_vector(item)["spell_power"])
        totals["healing"] += float(item.healing or 0.0)
        totals["armor"] += float(item.armor or 0.0)
        totals["bonus_armor"] += float(item.bonus_armor or 0.0)
        totals["defense"] += float(item.defense or 0.0)
        totals["attack_power"] += float(item.attack_power or 0.0)
        totals["mp5"] += float(item.mp5 or 0.0)
        slots[display_slot]=catalogue_item_payload(
            item, display_slot=display_slot, effective_level=catalogue_effective_level(item)
        )

    weapon=selected.get("weapon")
    totals["weapon_dps"]=float(weapon.weapon_dps or 0.0) if weapon is not None else 0.0
    totals["weapon_speed"]=float(weapon.weapon_speed or 0.0) if weapon is not None else 0.0
    totals["slots"]=slots
    totals["crafted_items"]=[item.name for item in selected.values()]
    totals.update({
        "name":f"canonical_sqlite_{role}",
        "family":"canonical_sqlite_runtime_selection",
        "provenance":"sqlite_catalogue",
        "coverage":"selected equipment and displayed item vectors are the canonical SQLite rows consumed by combat",
        "gear_selection_method":"canonical_sqlite_runtime_selection_v1",
        "availability_rule":"class eligibility + observed reqlevel + robust ilvl lower-bound floor",
    })
    enrich_gear_metadata(totals, level, role=role, selected=selected)
    return _probe_gear(totals)


def _feral_gear(level: int) -> dict:
    return _gear_from_catalogue(level, "druid_feral")


def _balance_gear(level: int) -> dict:
    return _gear_from_catalogue(level, "druid_balance")


def _bear_gear(level: int) -> dict:
    return _gear_from_catalogue(level, "druid_bear")

def _feral_attack_power(level: int, t: Talents, *, bear: bool = False) -> tuple[float, float, float, dict]:
    gear = _bear_gear(level) if bear else _feral_gear(level)
    crit = .05 + .02 * t.sharpened_claws + .03 * t.leader_of_the_pack
    # Forever Heart of the Wild: +4% Intellect/rank, +4% Stamina/rank in Bear,
    # +4% Strength/rank in Cat.  Bear must not inherit the Cat Strength bonus.
    hotw_rank=max(0,min(5,int(t.heart_of_the_wild)))
    heart_strength_bonus = 0.0 if bear else 0.04*hotw_rank
    # Feed verified crafted Strength through the same 2 AP/Str path.  Cat Form
    # gets 1 AP/Agi; Bear does not.  Keeping that distinction here prevents the
    # tank-oriented Warden Agility/armor budget from being misread as Bear AP.
    strength = (18 + 1.75 * level + float(gear["strength"])) * (1 + heart_strength_bonus)
    agility_ap = 0.0 if bear else float(gear["agility"])
    ap = 2 * strength + agility_ap + float(gear.get("attack_power", 0.0)) + .5 * level * t.predatory_strikes
    return strength, ap, crit, gear


def _player_hp(level:int, gear:dict, *, bear:bool=False, talents:Talents|None=None) -> float:
    # Preserve the current Dire Bear proxy while routing Stamina through the
    # shared defensive-state contract. Heart of the Wild is source-backed in
    # Forever: +4% Stamina per rank while in Bear/Dire Bear.
    hp_mult=1.25 if bear and int(level)>=40 else 1.0
    hotw_rank=max(0,min(5,int(talents.heart_of_the_wild))) if (bear and talents is not None) else 0
    stamina_mult=1.0+0.04*hotw_rank
    return representative_player_hp(
        level,float(gear.get("stamina",0.0)),
        stamina_multiplier=stamina_mult,total_hp_multiplier=hp_mult,
    )


def _incoming_damage(level:int, combat_s:float, gear:dict, *, bear:bool=False, ranged_headstart_s:float=0.0, talents:Talents|None=None) -> tuple[float,float,float]:
    raw=.5*normal_world_raw_dps(int(level)+1)+.5*normal_world_raw_dps(int(level)+2)
    if talents is not None:
        _base_armor,armor=_feral_form_armor(level,talents,gear,bear=bear)
    else:
        armor=float(gear.get("armor",0.0))+float(gear.get("bonus_armor",0.0))
        if bear:
            armor*=5.0 if int(level)>=40 else 2.8
    red=armor_reduction(armor,int(level)+2)
    avoidance=_druid_defense_avoidance(gear)
    if bear and talents is not None:
        avoidance += _natural_reaction(talents)[0]
    avoidance=max(0.0,min(0.95,avoidance))
    contact=max(0.0,float(combat_s)-max(0.0,float(ranged_headstart_s)))
    damage=raw*(1.0-red)*(1.0-avoidance)*contact
    return damage,armor,red


def _healing_touch(level:int) -> HealOption | None:
    row=_latest(wh.HEALING_TOUCH_RANKS,level)
    if row is None:
        return None
    _lv,mana,cast,hmin,hmax,_coeff=row
    return HealOption("Healing Touch",(float(hmin)+float(hmax))/2.0,float(mana),float(cast))


def _rejuvenation(level:int, gear:dict) -> dict | None:
    row=_latest(wh.REJUVENATION_RANKS,level)
    if row is None:
        return None
    lv,mana,total,duration,tick_coeff=row
    ticks=max(1,int(round(float(duration)/wh.REJUVENATION_TICK_INTERVAL_S)))
    # Healing items scale each periodic tick. Keep the coefficient source-backed
    # and do not silently fold generic spell damage into healing.
    full_heal=float(total)+ticks*float(tick_coeff)*max(0.0,float(gear.get("healing",0.0)))
    return {
        "rank_level":int(lv),"mana":float(mana),"duration_s":float(duration),
        "tick_interval_s":wh.REJUVENATION_TICK_INTERVAL_S,"ticks":ticks,
        "full_heal":full_heal,"heal_per_tick":full_heal/ticks,
    }


def _rejuvenation_carry_heal(level:int, gear:dict, combat_s:float) -> tuple[float,dict | None]:
    """Steady-state heal carried from a pre-pull Rejuvenation.

    Policy casts Rejuvenation immediately before re-forming. Its first 3-second
    tick therefore lands 1.5 s into the next pull after the form GCD. Only
    ticks that occur while the next pull is still in combat are credited.
    """
    hot=_rejuvenation(level,gear)
    if hot is None:
        return 0.0,None
    t=wh.REJUVENATION_TICK_INTERVAL_S-wh.FERAL_FORM_GCD_S
    landed=0
    while landed < int(hot["ticks"]) and t <= max(0.0,float(combat_s))+1e-9:
        landed+=1
        t+=wh.REJUVENATION_TICK_INTERVAL_S
    return landed*float(hot["heal_per_tick"]),{**hot,"carry_ticks":landed}


def _feral_caster_recovery_candidates(level:int,t:Talents,gear:dict,combat_s:float,hp_missing:float,shift_cost:float) -> list[dict]:
    """Humanoid recovery policies, including a steady-state pre-HoT policy."""
    heal=_healing_touch(level)
    options=() if heal is None else (heal,)
    passive=_druid_out_of_combat_mana_regen_per_s(level,gear)
    out=[]

    base=solve_recovery(level,hp_missing,shift_cost,options,passive_mana_regen_per_s=passive)
    out.append({
        "recovery_s":base.total_s+wh.FERAL_FORM_GCD_S,
        "recovery_solver_id":RECOVERY_SOLVER_ID,
        "recovery_method":"caster_heal_food_water_reform",
        "shift_cost":shift_cost,"recovery_heal_casts":base.heal_casts,
        "food_s":base.food_s,"water_s":base.water_s,"reform_mana_wait_s":0.0,
        "food_tier":base.food_tier,"water_tier":base.water_tier,
        "passive_mana_regen_per_s":passive,"rejuvenation_carry_heal":0.0,
        "rejuvenation_carry_ticks":0,"rejuvenation_mana":0.0,
    })

    carry,hot=_rejuvenation_carry_heal(level,gear,combat_s)
    if hot is not None and int(hot["carry_ticks"]) > 0:
        # In steady state the previous cycle's HoT reduces this pull's deficit;
        # this cycle pays the mana/GCD to refresh the same state for the next.
        effective_hp=max(0.0,float(hp_missing)-carry)
        hot_rec=solve_recovery(
            level,effective_hp,shift_cost+float(hot["mana"]),options,
            passive_mana_regen_per_s=passive,
        )
        out.append({
            "recovery_s":hot_rec.total_s+wh.REJUVENATION_GCD_S+wh.FERAL_FORM_GCD_S,
            "recovery_solver_id":RECOVERY_SOLVER_ID,
            "recovery_method":"caster_rejuvenation_carry_reform",
            "shift_cost":shift_cost,"recovery_heal_casts":hot_rec.heal_casts,
            "food_s":hot_rec.food_s,"water_s":hot_rec.water_s,"reform_mana_wait_s":0.0,
            "food_tier":hot_rec.food_tier,"water_tier":hot_rec.water_tier,
            "passive_mana_regen_per_s":passive,"rejuvenation_carry_heal":carry,
            "rejuvenation_carry_ticks":int(hot["carry_ticks"]),
            "rejuvenation_mana":float(hot["mana"]),"rejuvenation_rank_level":int(hot["rank_level"]),
            "rejuvenation_source":wh.REJUVENATION_SOURCE,
        })
    return out


def _feral_recovery(level:int,t:Talents,gear:dict,combat_s:float,*,bear:bool) -> dict:
    return _amortize_feral_recovery(level,t,gear,combat_s,bear=bear)


def _chain_pulls_before_recovery(player_hp: float, hp_loss_per_pull: float) -> int:
    """Number of identical pulls safely completed before a full recovery.

    We carry HP across pulls. Recovery is triggered only when another identical
    pull would be unsafe. Keep one expected-damage pull strictly below zero HP;
    this is deterministic expected-value bookkeeping, not a fabricated safety
    margin.
    """
    hp=max(0.0,float(player_hp))
    loss=max(0.0,float(hp_loss_per_pull))
    if loss <= 1e-9:
        return 1
    return max(1,int((hp-1e-9)//loss))


def _amortize_feral_recovery(level:int,t:Talents,gear:dict,combat_s:float,*,bear:bool) -> dict:
    """Shared Cat/Bear single-target mob-chain recovery lifecycle.

    HP persists between kills. If another pull is survivable, the character
    simply continues; the full shared recovery contract runs only after the
    largest safe run of identical pulls. Returned recovery time is amortized per
    mob while the full event time remains published for listener diagnostics.
    """
    player_hp=_player_hp(level,gear,bear=bear,talents=t)
    damage,armor,red=_incoming_damage(level,combat_s,gear,bear=bear,talents=t)
    if damage>=player_hp:
        return {"feasible":False,"player_hp":player_hp,"hp_missing":damage,"incoming_damage":damage,"armor":armor,"armor_reduction":red,"recovery_s":1e9,"recovery_method":"survival_infeasible","pulls_per_recovery":1,"continue_without_recovery":False}
    pulls=_chain_pulls_before_recovery(player_hp,damage)
    accumulated=min(player_hp-1e-9,max(0.0,damage*pulls))
    spirit=float(gear.get("spirit",0.0))
    natural_hp_hps=max(.1,3.0+.125*spirit)
    stay_form_event_s=accumulated/natural_hp_hps
    base_mana=150.0+13.0*float(level)
    reduction=wh.NATURAL_SHAPESHIFTER_COST_REDUCTION_PER_RANK*max(0,min(3,int(t.natural_shapeshifter)))
    shift_cost=base_mana*wh.FERAL_FORM_BASE_MANA_PCT*(1.0-reduction)
    caster=min(_feral_caster_recovery_candidates(level,t,gear,combat_s,accumulated,shift_cost),key=lambda row:float(row["recovery_s"]))
    if stay_form_event_s<=float(caster["recovery_s"]):
        event={"recovery_event_s":stay_form_event_s,"recovery_method":"stay_form_natural_regen","shift_cost":0.0,"recovery_heal_casts":0,"food_s":0.0,"water_s":0.0,"rejuvenation_carry_heal":0.0,"rejuvenation_carry_ticks":0}
    else:
        event={**caster,"recovery_event_s":float(caster["recovery_s"])}
    event.pop("recovery_s",None)
    return {"feasible":True,"player_hp":player_hp,"hp_missing":accumulated,"hp_loss_per_pull":damage,"incoming_damage":damage,"armor":armor,"armor_reduction":red,"pulls_per_recovery":pulls,"continue_without_recovery":pulls>1,"recovery_trigger":"before_next_pull_would_be_unsafe","recovery_s":float(event["recovery_event_s"])/pulls,**event}


def _druid_mana_regen_decomposition(level: int, gear: dict) -> dict:
    """Out-of-5SR mana regeneration with base and item Spirit separated.

    Vanilla/Forever Druid mana regen is modeled as ``15 + Spirit/5`` per
    two-second tick, i.e. ``7.5 + 0.1 * Spirit`` mana/s.  ``Spirit`` here is
    character base Spirit plus item Spirit; flat MP5 is an independent term.
    """
    base = float(base_spirit("druid", level, race="tauren"))
    item = max(0.0, float(gear.get("spirit", 0.0)))
    base_regen = 7.5
    spirit_regen = 0.1 * (base + item)
    mp5_regen = max(0.0, float(gear.get("mp5", 0.0))) / 5.0
    return {
        "race":"tauren", "base_spirit":base, "item_spirit":item,
        "total_spirit":base+item, "base_mana_regen_per_s":base_regen,
        "spirit_recovery_mps":spirit_regen, "mp5_recovery_mps":mp5_regen,
        "passive_mana_regen_per_s":base_regen+spirit_regen+mp5_regen,
        "base_stat_authority_id":BASE_STAT_AUTHORITY_ID,
        "base_stat_provenance":spirit_provenance("druid", level, race="tauren"),
    }


def _druid_out_of_combat_mana_regen_per_s(level: int, gear: dict) -> float:
    return float(_druid_mana_regen_decomposition(level, gear)["passive_mana_regen_per_s"])


def _caster_recovery(level:int,gear:dict,combat_s:float,mana_spent:float,mana_pool:float) -> dict:
    player_hp=_player_hp(level,gear,bear=False)
    damage,armor,red=_incoming_damage(level,combat_s,gear,bear=False,ranged_headstart_s=2.5)
    if damage>=player_hp:
        return {"feasible":False,"player_hp":player_hp,"hp_missing":damage,"incoming_damage":damage,"armor":armor,"armor_reduction":red,"recovery_s":1e9,"recovery_method":"survival_infeasible"}
    hp_missing=max(0.0,damage)
    # Spirit-based mana regeneration is suppressed during ordinary mana-spending
    # casts by the 5SR; flat MP5 continues during combat and therefore reduces
    # the deficit before the shared OOC solver takes over.
    combat_mp5=max(0.0,float(gear.get("mp5",0.0)))/5.0*max(0.0,float(combat_s))
    mana_missing=min(max(0.0,float(mana_spent)-combat_mp5),max(0.0,float(mana_pool)))
    heal=_healing_touch(level)
    options=() if heal is None else (heal,)
    regen=_druid_mana_regen_decomposition(level,gear)
    passive_mana_regen=float(regen["passive_mana_regen_per_s"])
    r=solve_recovery(
        level,hp_missing,mana_missing,options,
        passive_mana_regen_per_s=passive_mana_regen,
    )
    return {"feasible":True,"player_hp":player_hp,"hp_missing":hp_missing,"mana_missing":mana_missing,"incoming_damage":damage,"armor":armor,"armor_reduction":red,"recovery_s":r.total_s,"recovery_solver_id":RECOVERY_SOLVER_ID,"recovery_method":r.method,"recovery_heal_casts":r.heal_casts,"food_s":r.food_s,"water_s":r.water_s,"food_tier":r.food_tier,"water_tier":r.water_tier,**regen,"combat_mp5_return":combat_mp5}



def _feral_pack_recovery(level:int,t:Talents,gear:dict,combat_s:float,*,pull_size:int,avg_alive:float,first_kill_s:float,rage_rate:float=0.0) -> dict:
    """Bear pack recovery with the same engaged-pack geometry as Paladin.

    No gather-time assumption is introduced.  Total HP bookkeeping uses average
    alive exposure; the opening window also records full-pack peak pressure.
    Bear currently has no in-combat heal policy in this smooth backend, so a
    pack is feasible only if the expected full-fight damage remains below the
    HP pool.  Post-pack recovery then reuses the shared full-HP/full-Mana
    contract, including the optional unshift/heal/re-form path.
    """
    n=max(1,int(pull_size))
    player_hp=_player_hp(level,gear,bear=True,talents=t)
    raw=.5*normal_world_raw_dps(int(level)+1)+.5*normal_world_raw_dps(int(level)+2)
    base_armor,armor=_feral_form_armor(level,t,gear,bear=True)
    red=armor_reduction(armor,int(level)+2)
    natural_reaction_dodge,_,_=_natural_reaction(t)
    defense_avoidance_bonus=_druid_defense_avoidance(gear)
    total_avoidance=max(0.0,min(0.95,natural_reaction_dodge+defense_avoidance_bonus))
    per_mob_dps=raw*(1.0-red)*(1.0-total_avoidance)
    avg_incoming_dps=per_mob_dps*max(1.0,float(avg_alive))
    peak_incoming_dps=per_mob_dps*float(n)
    damage=max(0.0,avg_incoming_dps*max(0.0,float(combat_s)))
    peak_window_damage=max(0.0,peak_incoming_dps*max(0.0,float(first_kill_s)))
    lethal_pressure=max(damage,peak_window_damage)
    if lethal_pressure>=player_hp:
        return {
            "feasible":False,"player_hp":player_hp,"hp_missing":damage,
            "incoming_damage":damage,"armor":armor,"armor_reduction":red,
            "recovery_s":1e9,"recovery_method":"survival_infeasible",
            "avg_incoming_dps":avg_incoming_dps,"peak_incoming_dps":peak_incoming_dps,
            "peak_window_damage":peak_window_damage,"lethal_pressure":lethal_pressure,
        }

    # Frenzied Regeneration is a real Bear leveling recovery tool from level 36.
    # Keep lethality conservative (the cooldown is not assumed available for
    # every dangerous opener), but amortize its source-backed Rage->HP conversion
    # over the long-run recovery deficit.
    fr_heal=0.0
    fr_activation_heal=0.0
    fr_ev_uses=0.0
    if int(level)>=wh.FRENZIED_REGEN_LEVEL and float(rage_rate)>0.0:
        rage_per_activation=min(
            wh.FRENZIED_REGEN_RAGE_PER_S_CAP*wh.FRENZIED_REGEN_DURATION_S,
            max(0.0,float(rage_rate))*wh.FRENZIED_REGEN_DURATION_S,
        )
        fr_activation_heal=player_hp*rage_per_activation*wh.FRENZIED_REGEN_HP_PER_RAGE_FRACTION
        fr_ev_uses=min(1.0,max(0.0,float(combat_s))/wh.FRENZIED_REGEN_COOLDOWN_S)
        fr_heal=min(damage,fr_activation_heal*fr_ev_uses)

    hp_loss_per_pack=max(0.0,damage-fr_heal)
    pulls=_chain_pulls_before_recovery(player_hp,hp_loss_per_pack)
    hp_missing=min(player_hp-1e-9,hp_loss_per_pack*pulls)
    spirit=float(gear.get("spirit",0.0))
    natural_hp_hps=max(.1,3.0+.125*spirit)
    stay_form_event_s=hp_missing/natural_hp_hps

    base_mana=150.0+13.0*float(level)
    reduction=wh.NATURAL_SHAPESHIFTER_COST_REDUCTION_PER_RANK*max(0,min(3,int(t.natural_shapeshifter)))
    shift_cost=base_mana*wh.FERAL_FORM_BASE_MANA_PCT*(1.0-reduction)
    caster=min(
        _feral_caster_recovery_candidates(level,t,gear,combat_s,hp_missing,shift_cost),
        key=lambda row:float(row["recovery_s"]),
    )

    common={
        "feasible":True,"player_hp":player_hp,"hp_missing":hp_loss_per_pack,
        "recovery_hp_missing_event":hp_missing,
        "incoming_damage":damage,"armor":armor,"armor_reduction":red,
        "avg_incoming_dps":avg_incoming_dps,"peak_incoming_dps":peak_incoming_dps,
        "peak_window_damage":peak_window_damage,"lethal_pressure":lethal_pressure,
        "frenzied_regeneration_heal_ev":fr_heal,
        "hp_loss_per_pull":hp_loss_per_pack,"pulls_per_recovery":pulls,
        "continue_without_recovery":pulls>1,"recovery_trigger":"before_next_pull_would_be_unsafe",
        "frenzied_regeneration_heal_per_activation":fr_activation_heal,
        "frenzied_regeneration_ev_uses_per_pack":fr_ev_uses,
        "frenzied_regeneration_source":wh.FRENZIED_REGEN_SOURCE,
        "natural_reaction_dodge_chance":natural_reaction_dodge,
        "defense_skill_bonus":max(0.0,float(gear.get("defense",0.0))),
        "defense_avoidance_bonus":defense_avoidance_bonus,
        "total_avoidance":total_avoidance,
        "thick_hide_rank":max(0,min(3,int(t.thick_hide))),
        "thick_hide_base_armor":_thick_hide_base_armor(level,t,gear),
        "pre_form_armor":base_armor,
        "thick_hide_source":wh.THICK_HIDE_SOURCE,
    }
    if stay_form_event_s<=float(caster["recovery_s"]):
        return {**common,"recovery_s":stay_form_event_s/pulls,"recovery_event_s":stay_form_event_s,"recovery_method":"stay_form_natural_regen",
                "shift_cost":0.0,"recovery_heal_casts":0,"food_s":0.0,"water_s":0.0,
                "rejuvenation_carry_heal":0.0,"rejuvenation_carry_ticks":0}
    return {**common,**caster,"recovery_event_s":float(caster["recovery_s"]),"recovery_s":float(caster["recovery_s"])/pulls}

def _simulate_cat_rotation(*, hp: float, white_dps: float, energy_regen_per_s: float,
                           builder_cost: float, builder_damage: float, cp_per_builder: float,
                           rake: tuple | None, use_rake: bool, finisher: str,
                           rip: tuple | None, bite: tuple | None, t: Talents,
                           builder_crit_ev: float, start_energy: float = 100.0,
                           physical_direct_multiplier: float = 1.0,
                           application_hit: float = 1.0) -> dict:
    """Bounded deterministic Cat resource/CP simulation for one solo mob.

    Energy is continuous and obeys a 1 s Cat ability GCD. ``start_energy`` is
    supplied by the between-mob lifecycle; it is not implicitly reset per mob.
    Combo points are generated only by landed modeled builders/Rake and are
    consumed by a five-CP finisher. Bleeds tick continuously only for their
    remaining duration on this finite target. This deliberately does not invent
    an Omen proc rate or behind-target Shred uptime.
    """
    energy=max(0.0,min(100.0,float(start_energy)))
    cp=0.0
    now=0.0
    gcd_ready=0.0
    damage=0.0
    rake_until=0.0
    rake_dps=0.0
    rip_until=0.0
    rip_dps=0.0
    rake_used=False
    casts=[]
    energy_spent=0.0
    dt=0.02
    max_s=180.0
    while now < max_s and damage < hp:
        # continuous white + active bleed damage
        step=min(dt,max_s-now)
        active_dot=(rake_dps if now < rake_until else 0.0)+(rip_dps if now < rip_until else 0.0)
        damage += (white_dps+active_dot)*step
        energy=min(100.0,energy+energy_regen_per_s*step)
        now += step
        if damage >= hp:
            break
        if now + 1e-9 < gcd_ready:
            continue

        action=None
        cost=0.0
        instant=0.0
        # Optional Rake opener. Its CP is expected-value compatible with Blood
        # Frenzy because it is a non-periodic CP-generating Cat ability.
        if use_rake and not rake_used and rake is not None:
            _, rcost, direct, dot_total, duration=rake
            cost=float(rcost)
            if energy+1e-9 >= cost:
                action='Rake'
                instant=float(direct)*(1.0+builder_crit_ev*.5)*(1.0+.05*t.savage_fury)*physical_direct_multiplier
                # Bleed ticks bypass Armor; only the application is hit-gated.
                rake_dps=float(dot_total)*(1.0+.05*t.savage_fury)*application_hit/max(.1,float(duration))
                rake_until=now+float(duration)
                rake_used=True
                cp=min(5.0,cp+cp_per_builder*application_hit)
        elif cp >= 5.0-1e-9 and finisher == 'Rip' and rip is not None:
            _, rcost, total, duration=rip
            cost=float(rcost)
            if energy+1e-9 >= cost:
                action='Rip'
                bleed_bonus=1.0+.03*t.predatory_instincts+.04*t.rend_and_tear
                rip_dps=float(total)*bleed_bonus*application_hit/max(.1,float(duration))
                rip_until=now+float(duration)
                cp=0.0
        elif cp >= 5.0-1e-9 and finisher == 'Ferocious Bite' and bite is not None:
            _, bcost, bmin, bmax, extra_per_energy=bite
            cost=float(bcost)
            if energy+1e-9 >= cost:
                extra=max(0.0,energy-cost)
                action='Ferocious Bite'
                instant=(((float(bmin)+float(bmax))/2.0)+extra*float(extra_per_energy))*(1.0+.03*t.predatory_instincts)*physical_direct_multiplier
                # Bite consumes remaining Energy according to the public tooltip.
                cost=energy
                cp=0.0
        else:
            cost=float(builder_cost)
            if energy+1e-9 >= cost:
                action='Claw'
                instant=float(builder_damage)
                cp=min(5.0,cp+cp_per_builder*application_hit)

        if action is not None:
            energy=max(0.0,energy-cost)
            energy_spent += cost
            damage += instant
            casts.append(action)
            gcd_ready=now+1.0

    return {
        'combat_s':now, 'dps':hp/max(.001,now), 'casts':casts,
        'energy_spent':energy_spent, 'ending_energy':energy, 'ending_cp':cp,
        'rake_used':rake_used, 'finisher':finisher,
    }


def _simulate_cat_chain(*, pulls:int, travel_s:float, sim_kwargs:dict) -> dict:
    """Repeat one Cat policy while carrying Energy between ordinary mobs."""
    energy=100.0
    rows=[]
    for i in range(max(1,int(pulls))):
        row=_simulate_cat_rotation(**sim_kwargs,start_energy=energy)
        rows.append(row)
        if i+1 < max(1,int(pulls)):
            energy=min(100.0,float(row["ending_energy"])+float(sim_kwargs["energy_regen_per_s"])*max(0.0,float(travel_s)))
    return {
        "rows":rows,
        "combat_s":sum(float(r["combat_s"]) for r in rows)/len(rows),
        "dps":sum(float(sim_kwargs["hp"]) for _ in rows)/max(.001,sum(float(r["combat_s"]) for r in rows)),
        "start_energy_first":100.0,
        "start_energy_after_first": (min(100.0,float(rows[0]["ending_energy"])+float(sim_kwargs["energy_regen_per_s"])*max(0.0,float(travel_s))) if len(rows)>1 else None),
        "ending_energy":float(rows[-1]["ending_energy"]),
        "energy_spent":sum(float(r["energy_spent"]) for r in rows)/len(rows),
        "casts":rows[-1]["casts"],
        "ending_cp":float(rows[-1]["ending_cp"]),
        "rake_used":bool(rows[-1]["rake_used"]),
        "finisher":str(rows[-1]["finisher"]),
    }


def _cat_single(level: int, t: Talents) -> dict:
    hp = leveling.representative_hp(level)
    _strength, ap, crit, gear = _feral_attack_power(level, t)
    nat = 1 + .01 * t.naturalist

    base_mana = 150.0 + 13.0 * float(level)
    mana_regen_per_s = 8.0 + .45 * float(level)
    shifting_power_rank = max(0, min(1, int(t.shifting_power)))
    improved_shifting_power_rank = max(0, min(2, int(t.improved_shifting_power))) if shifting_power_rank else 0
    shifting_power_cd_s = max(1.0, wh.SHIFTING_POWER_COOLDOWN_S - wh.IMPROVED_SHIFTING_POWER_CD_REDUCTION_PER_RANK_S * improved_shifting_power_rank) if shifting_power_rank else 0.0
    shapeshift_reduction = wh.NATURAL_SHAPESHIFTER_COST_REDUCTION_PER_RANK * max(0, min(3, int(t.natural_shapeshifter)))
    shifting_power_mana_cost = base_mana * wh.SHIFTING_POWER_BASE_MANA_PCT * (1.0 - shapeshift_reduction) if shifting_power_rank else 0.0
    shifting_power_casts_per_s = 0.0
    if shifting_power_rank and shifting_power_mana_cost > 0.0:
        shifting_power_casts_per_s = min(1.0 / shifting_power_cd_s, mana_regen_per_s / shifting_power_mana_cost)
    shifting_power_energy_per_s = wh.SHIFTING_POWER_ENERGY * shifting_power_casts_per_s
    energy_regen_per_s = 10.0 + shifting_power_energy_per_s

    # Same canonical qualified Classic-proxy target profile as generic IR.
    # It MUST NOT be silently treated as verified Forever target defense.
    target_defense=physical_outgoing_expected_factors(level)
    direct_mult=float(target_defense['direct_multiplier'])
    hit=float(target_defense['application_hit'])
    normal_hit = normal_form_hit(weapon_dps=float(gear.get('weapon_dps', 0.0)), attack_power=ap, bear=False) * nat
    white_dps = form_white_dps(weapon_dps=float(gear.get('weapon_dps', 0.0)), attack_power=ap) * nat * (1 + crit * .5)*direct_mult
    claw = _latest(wh.CLAW_RANKS, level)
    rake = _latest(wh.RAKE_RANKS, level)
    bite = _latest(wh.FEROCIOUS_BITE_RANKS_5CP, level)
    rip = _latest(wh.RIP_RANKS_5CP, level)
    if claw is None:
        raise ValueError('Cat score requested before Claw/Cat Form availability')

    _, claw_cost0, claw_mult, claw_flat = claw
    builder_cost = max(20.0, float(claw_cost0) - float(t.ferocity))
    base_builder_damage = (claw_mult * normal_hit + claw_flat) * (1 + .05 * t.savage_fury)
    blood_frenzy_rank = max(0, min(2, int(t.effective_blood_frenzy)))
    berserk_available = bool(t.berserk)
    berserk_uptime = (wh.BERSERK_DURATION_S / wh.BERSERK_COOLDOWN_S) if berserk_available else 0.0
    builder_crit_ev = min(1.0, crit + berserk_uptime * (1.0 - crit))
    builder_damage = base_builder_damage * (1.0 + builder_crit_ev * .5)*direct_mult
    cp_per_builder = 1.0 + builder_crit_ev * (0.5 * blood_frenzy_rank)

    candidates=[]
    candidate_specs=[]
    finisher_options=[]
    if rip is not None: finisher_options.append('Rip')
    if bite is not None: finisher_options.append('Ferocious Bite')
    if not finisher_options: finisher_options=['none']
    for use_rake in ([False, True] if rake is not None else [False]):
        for finisher in finisher_options:
            spec=dict(
                hp=hp, white_dps=white_dps, energy_regen_per_s=energy_regen_per_s,
                builder_cost=builder_cost, builder_damage=builder_damage, cp_per_builder=cp_per_builder,
                rake=rake, use_rake=use_rake, finisher=finisher, rip=rip, bite=bite, t=t,
                builder_crit_ev=builder_crit_ev,
                physical_direct_multiplier=direct_mult,application_hit=hit,
            )
            candidate_specs.append(spec)
            candidates.append(_simulate_cat_rotation(**spec))
    best_idx=min(range(len(candidates)),key=lambda i:(float(candidates[i]['combat_s']), len(candidates[i]['casts'])))
    best=candidates[best_idx]
    combat_s=float(best['combat_s'])
    finisher_name=str(best['finisher'])
    if best['casts']:
        rotation = ('Rake → ' if best['rake_used'] else '') + 'Claw to 5 CP'
        if finisher_name != 'none':
            rotation += ' → ' + finisher_name
    else:
        rotation='white attacks'
    if shifting_power_rank: rotation += ' · Shifting Power on sustainable CD'
    if berserk_available: rotation += ' · Berserk on CD'

    travel = between_pull_travel_s(speed_multiplier=1 + .15 * t.feral_swiftness)
    recovery=_feral_recovery(level,t,gear,combat_s,bear=False)
    chain=_simulate_cat_chain(pulls=int(recovery.get('pulls_per_recovery',1)),travel_s=travel,sim_kwargs=candidate_specs[best_idx])
    combat_s=float(chain['combat_s'])
    dps=float(chain['dps'])
    # One refinement: changed combat time changes expected incoming damage and
    # therefore how many mobs fit before recovery. Recompute once, then rerun.
    recovery=_feral_recovery(level,t,gear,combat_s,bear=False)
    chain=_simulate_cat_chain(pulls=int(recovery.get('pulls_per_recovery',1)),travel_s=travel,sim_kwargs=candidate_specs[best_idx])
    combat_s=float(chain['combat_s'])
    dps=float(chain['dps'])
    best={**best,'ending_energy':chain['ending_energy'],'ending_cp':chain['ending_cp'],'energy_spent':chain['energy_spent'],'casts':chain['casts']}
    flags=[
        'first-class Cat finite-target rotation search',
        'stateful Energy carry between mobs + explicit combo-point spend cycle',
        'bounded candidates: Claw; optional Rake; Rip/Bite/none finisher',
        'real Forever Claw/Rake/Rip/Bite ranks',
        'Shred excluded from solo default because behind-target uptime is not established',
        'Omen semantics known but proc rate not credited',
        'build 1.60.1.70170: Tiger\'s Fury and King of the Jungle removed',
        'Shifting Power modeled as cooldown- and mana-sustainable Energy input',
        'Berserk averaged over continuous leveling cycle',
        'Forever weapon DPS carried into Cat form',
    ]
    if not recovery['feasible']:
        flags.append('survival infeasible under shared HP bookkeeping')
    return leveling.combat_result(
        level=level, dps=dps, mana_spent=0.0, mana_pool=base_mana,
        regen_per_s=mana_regen_per_s, travel_s=travel, rotation=rotation,
        profile='cat', flags=flags, recovery_s_override=recovery['recovery_s'],
        details={
            **{k:v for k,v in recovery.items() if k != 'recovery_s'},
            'representative_mob_hp':hp, 'crit':crit, 'attack_power_proxy':ap,
            'normal_weapon_hit':normal_hit, 'weapon_dps':float(gear.get('weapon_dps',0.0)),
            'outgoing_target_combat':target_defense,
            'weapon_scaling_provenance':weapon_provenance(), 'feral_builder':'Claw',
            'feral_finisher':finisher_name, 'rake_used':bool(best['rake_used']),
            'combo_points_per_builder_ev':cp_per_builder, 'builder_crit_chance_ev':builder_crit_ev,
            'cat_rotation_candidates':len(candidates), 'cat_selected_casts':best['casts'],
            'cat_energy_spent':best['energy_spent'], 'cat_ending_energy':best['ending_energy'],
            'cat_ending_combo_points':best['ending_cp'], 'cat_resource_model':'finite_target_energy_cp_v1',
            'cat_chain_model':'stateful_energy_between_mobs_v1','cat_chain_pulls':int(recovery.get('pulls_per_recovery',1)),
            'cat_chain_first_start_energy':chain['start_energy_first'],'cat_chain_second_start_energy':chain['start_energy_after_first'],
            'berserk_available':berserk_available, 'berserk_uptime_ev':berserk_uptime, 'berserk_source':wh.BERSERK_SOURCE,
            'druid_talent_schema_build':wh.DRUID_TALENT_SCHEMA_BUILD,
            'shifting_power_rank':shifting_power_rank, 'improved_shifting_power_rank':improved_shifting_power_rank,
            'shifting_power_cooldown_s':shifting_power_cd_s, 'shifting_power_mana_cost':shifting_power_mana_cost,
            'shifting_power_casts_per_s_ev':shifting_power_casts_per_s,
            'shifting_power_energy_per_s_ev':shifting_power_energy_per_s, 'energy_regen_per_s':energy_regen_per_s,
            'shifting_power_source':wh.SHIFTING_POWER_SOURCE, 'improved_shifting_power_source':wh.IMPROVED_SHIFTING_POWER_SOURCE,
            'tigers_fury_status':wh.TIGERS_FURY_CURRENT_STATUS, 'king_of_the_jungle_status':wh.KING_OF_THE_JUNGLE_CURRENT_STATUS,
            'pull_size':1, 'improved_swipe_used':False, 'gear':gear['name'], 'gear_stats':gear,
        },
    )



def _cat(level:int,t:Talents) -> dict:
    # The recorded Forever Beta spellbook (2026-09-24, client 1.60.1.70009)
    # does not contain Swipe (Cat) / Improved Swipe. Wowhead's spell 439510 is
    # inherited Season-of-Discovery rune data and is not enough to establish
    # availability in Forever. Keep Cat production single-target until an
    # actual Forever acquisition/spellbook source says otherwise.
    return _cat_single(level,t)


def _lacerate_cycle(
    level:int, t:Talents, *, rage_budget_per_s:float, gcd_budget_per_s:float,
    target_lifetime_s:float, bear_normal_hit:float, crit:float,
) -> dict:
    """Smooth finite-target Lacerate ramp for Bear leveling.

    Each application adds one bleed stack (max five).  The bleed contributes
    the verified rank total over 15 seconds, and the cast also deals 10% weapon
    damage for each *existing* stack.  Applications are limited by both Rage
    and the shared 1.5 s GCD budget; finite mob lifetime keeps short fights from
    receiving impossible five-stack steady-state damage.
    """
    row=_latest(wh.LACERATE_RANKS,level)
    if row is None or rage_budget_per_s <= 0.0 or gcd_budget_per_s <= 0.0:
        return {
            "available":row is not None, "rank_level":None if row is None else int(row[0]),
            "rage_cost":0.0 if row is None else max(1.0,float(row[1])-wh.SHREDDING_ATTACKS_LACERATE_RAGE_REDUCTION_PER_RANK*max(0,min(3,int(t.shredding_attacks)))),
            "cast_rate_per_s":0.0, "applications_per_target":0.0, "avg_stacks":0.0,
            "dps":0.0, "bleed_dps":0.0, "direct_dps":0.0, "rage_per_s":0.0,
        }
    rank_level,base_cost,bleed_total,duration,max_stacks,weapon_per_existing=row
    cost=max(1.0,float(base_cost)-wh.SHREDDING_ATTACKS_LACERATE_RAGE_REDUCTION_PER_RANK*max(0,min(3,int(t.shredding_attacks))))
    lifetime=max(.1,float(target_lifetime_s))
    cast_rate=min(1.0/wh.LACERATE_GCD_S,float(gcd_budget_per_s),float(rage_budget_per_s)/cost)
    applications=min(float(max_stacks),lifetime*cast_rate)
    if applications <= 0.0 or cast_rate <= 0.0:
        return {
            "available":True, "rank_level":int(rank_level), "rage_cost":cost,
            "cast_rate_per_s":0.0, "applications_per_target":0.0, "avg_stacks":0.0,
            "dps":0.0, "bleed_dps":0.0, "direct_dps":0.0, "rage_per_s":0.0,
        }
    # Linear expected ramp until the attained stack count, then plateau.
    ramp_s=applications/cast_rate
    stack_seconds=.5*applications*ramp_s + applications*max(0.0,lifetime-ramp_s)
    avg_stacks=stack_seconds/lifetime
    crit_mult=1.0+max(0.0,float(crit))*.5
    bleed_dps=(float(bleed_total)/float(duration))*avg_stacks*crit_mult
    # Existing-stack weapon component: sum 0+1+... over the applications.
    existing_stack_sum=max(0.0,applications*(applications-1.0)/2.0)
    direct_total=float(weapon_per_existing)*float(bear_normal_hit)*existing_stack_sum*crit_mult
    direct_dps=direct_total/lifetime
    actual_cast_rate=applications/lifetime
    return {
        "available":True, "rank_level":int(rank_level), "rage_cost":cost,
        "cast_rate_per_s":actual_cast_rate, "applications_per_target":applications,
        "avg_stacks":avg_stacks, "dps":bleed_dps+direct_dps,
        "bleed_dps":bleed_dps, "direct_dps":direct_dps,
        "rage_per_s":actual_cast_rate*cost,
    }


def _blood_frenzy_bear_rage_per_second(
    t: Talents, *, crit: float, white_swing_rate: float, ability_crit_rate: float
) -> float:
    """Expected Bear rage from current Forever Blood Frenzy.

    Rank 1/2: each Bear critical strike has a 50/100% chance to grant 5 Rage.
    ``ability_crit_rate`` is the rate of crit-capable non-periodic Bear ability
    events per second; white swings are supplied separately.
    """
    rank=max(0,min(2,int(t.effective_blood_frenzy)))
    if rank<=0:
        return 0.0
    proc_chance=0.5*rank
    crit_events_per_s=max(0.0,float(crit))*(max(0.0,float(white_swing_rate))+max(0.0,float(ability_crit_rate)))
    return crit_events_per_s*proc_chance*5.0


def _bear_pack(level: int, t: Talents, pull_size: int, *,
               mob_spacing_yards: float = 20.0,
               movement_speed_yards_s: float = 7.0) -> dict:
    requested_n=max(1,min(wh.SWIPE_MAX_TARGETS,int(pull_size)))
    hp=leveling.representative_hp(level)
    _strength, ap, crit, gear = _feral_attack_power(level, t, bear=True)
    nat=1 + .01 * t.naturalist

    white=form_white_dps(
        weapon_dps=float(gear.get("weapon_dps", 0.0)), attack_power=ap,
    ) * nat * (1 + crit * .5)
    bear_normal_hit=normal_form_hit(
        weapon_dps=float(gear.get("weapon_dps", 0.0)), attack_power=ap, bear=True,
    ) * nat
    base_rage_rate=max(2.5,white/8.0)

    maul_row=_latest(wh.MAUL_RANKS,level)
    if maul_row is None:
        raise ValueError("Bear score requested before Maul availability")
    _maul_level,maul_cost0,maul_flat=maul_row
    maul_cost=max(10.0,float(maul_cost0)-float(t.ferocity))
    # White damage is already counted continuously. Maul adds the verified rank
    # flat to a normal Bear swing, so only its incremental damage belongs here.
    maul_damage=float(maul_flat) * (1 + .05 * t.savage_fury) * nat

    swipe=_latest(wh.SWIPE_RANKS,level)
    # Bounded multi-pull authority: production may only score >1 engaged mob
    # once a verified multi-target Bear action exists at the selected level.
    # This prevents a talent/gear-only Bear row from manufacturing multi-pull
    # throughput before Swipe is actually available.
    multipull_supported = swipe is not None
    n=requested_n if (requested_n == 1 or multipull_supported) else 1
    layout=SpacedPullLayout(n,spacing_yards=mob_spacing_yards,
                            movement_speed_yards_s=movement_speed_yards_s)
    # This legacy expectation scorer assumes eventual assembly to melee after
    # the movement charge; it NEVER assumes 20-yard targets are in Swipe range
    # at the initial position. Combat during gathering and real threat are
    # still unmodeled: do not use as spatially validated P4-P6 evidence.
    gather_s=layout.minimum_walk_to_tag_farthest_s if n>1 else 0.0
    swipe_cost=0.0
    swipe_rank_level=None
    swipe_base_damage=0.0
    if n>1 and swipe is not None:
        _lv,swipe_cost0,swipe_base,_max_targets=swipe
        swipe_rank_level=int(_lv)
        swipe_base_damage=float(swipe_base)
        swipe_cost=max(15.0,float(swipe_cost0)-float(t.ferocity))

    primal_bite_damage=0.0
    primal_bite_cost=0.0
    primal_bite_flat=0.0
    primal_bite_rank_level=None
    primal_bite_row=_latest(wh.PRIMAL_BITE_RANKS,level) if t.mangle and level>=PRIMAL_BITE_MODEL_LEVEL else None
    if primal_bite_row is not None:
        _lv,_rage,mult,flat=primal_bite_row
        primal_bite_rank_level=int(_lv)
        primal_bite_flat=float(flat)
        primal_bite_cost=float(_rage)
        primal_bite_damage=(float(mult)*bear_normal_hit+float(flat))*(1 + .05*t.savage_fury)*nat

    berserk_available = bool(t.berserk) and primal_bite_row is not None
    berserk_uptime = (wh.BERSERK_DURATION_S / wh.BERSERK_COOLDOWN_S) if berserk_available else 0.0

    def _offense_for_rage(rage_budget:float,target_lifetime:float) -> dict:
        # Shared-GCD Bear priority for leveling: Primal Bite on cooldown; Swipe
        # on packs; Lacerate on the focus target; Maul only with leftover Rage.
        # Maul is on-next-swing and therefore does not consume this GCD budget.
        rage_left=max(0.0,float(rage_budget))
        gcd_left=1.0/wh.LACERATE_GCD_S

        primal_rate=0.0
        berserk_primal_rate=0.0
        if primal_bite_row is not None and primal_bite_cost>0.0:
            base_cap=1.0/6.0
            berserk_cap=1.0/wh.LACERATE_GCD_S
            primal_cap=base_cap*(1.0-berserk_uptime)+berserk_cap*berserk_uptime
            primal_rate=min(primal_cap,gcd_left,rage_left/primal_bite_cost)
            if berserk_uptime>0.0 and primal_cap>0.0:
                berserk_share=(berserk_cap*berserk_uptime)/primal_cap
                berserk_primal_rate=primal_rate*min(1.0,max(0.0,berserk_share))
            rage_left=max(0.0,rage_left-primal_rate*primal_bite_cost)
            gcd_left=max(0.0,gcd_left-primal_rate)
        primal_dps=primal_bite_damage*primal_rate
        berserk_primal_extra_dps=primal_bite_damage*berserk_primal_rate

        local_swipe_rate=0.0
        local_swipe_dps=0.0
        if n>1 and swipe is not None and swipe_cost>0.0:
            local_swipe_rate=min(gcd_left,rage_left/swipe_cost)
            local_swipe_dps=float(swipe_base)*(1 + crit*.5)*nat*local_swipe_rate
            rage_left=max(0.0,rage_left-local_swipe_rate*swipe_cost)
            gcd_left=max(0.0,gcd_left-local_swipe_rate)

        lacerate=_lacerate_cycle(
            level,t,rage_budget_per_s=rage_left,gcd_budget_per_s=gcd_left,
            target_lifetime_s=target_lifetime,bear_normal_hit=bear_normal_hit,crit=crit,
        )
        rage_left=max(0.0,rage_left-float(lacerate["rage_per_s"]))

        local_maul_rate=min(1.0/BEAR_FORM_SWING_S,rage_left/max(1.0,maul_cost))
        local_maul=maul_damage*local_maul_rate
        local_focus=max(.1,white+primal_dps+float(lacerate["dps"])+local_maul)
        return {
            "primal_rate":primal_rate,"primal_dps":primal_dps,
            "berserk_primal_rate":berserk_primal_rate,
            "berserk_primal_extra_dps":berserk_primal_extra_dps,
            "swipe_rate":local_swipe_rate,"swipe_dps":local_swipe_dps,
            "lacerate":lacerate,"maul_rate":local_maul_rate,"maul_dps":local_maul,
            "focus_dps":local_focus,"rage_left":rage_left,
        }

    # Incoming-damage rage is server behavior, not a spell-row fact. Public
    # Forever data does not expose that formula, so use the pinned Classic 1.12
    # CMaNGOS RewardRage formula as an explicit proxy. Because pack exposure
    # depends on our own DPS, solve the smooth expectation by a tiny deterministic
    # fixed-point iteration instead of assuming all targets remain alive forever.
    rage_rate=base_rage_rate
    incoming_rage_rate=0.0
    natural_reaction_rage_rate=0.0
    blood_frenzy_rage_rate=0.0
    target_lifetime_est=hp/max(.1,white)
    offense=_offense_for_rage(rage_rate,target_lifetime_est)
    berserk_extra_targets=max(0,min(wh.BERSERK_PRIMAL_BITE_MAX_TARGETS-1,n-1))
    berserk_bg_equiv=float(offense.get("berserk_primal_extra_dps",0.0))*berserk_extra_targets/max(1,n)
    exposure=estimate_pack_exposure(n,offense["focus_dps"],float(offense["swipe_dps"])+berserk_bg_equiv)
    for _ in range(6):
        offense=_offense_for_rage(rage_rate,target_lifetime_est)
        focus_dps=float(offense["focus_dps"])
        swipe_per_target_dps=float(offense["swipe_dps"])
        berserk_extra_targets=max(0,min(wh.BERSERK_PRIMAL_BITE_MAX_TARGETS-1,n-1))
        berserk_bg_equiv=float(offense.get("berserk_primal_extra_dps",0.0))*berserk_extra_targets/max(1,n)
        exposure=estimate_pack_exposure(n,focus_dps,swipe_per_target_dps+berserk_bg_equiv)
        avg_alive=float(exposure.avg_alive)
        target_lifetime_est=hp/max(.1,focus_dps+swipe_per_target_dps)
        raw=.5*normal_world_raw_dps(int(level)+1)+.5*normal_world_raw_dps(int(level)+2)
        _base_armor,armor=_feral_form_armor(level,t,gear,bear=True)
        red=armor_reduction(armor,int(level)+2)
        natural_reaction_dodge,_,_=_natural_reaction(t)
        defense_avoidance_bonus=_druid_defense_avoidance(gear)
        total_avoidance=max(0.0,min(0.95,natural_reaction_dodge+defense_avoidance_bonus))
        incoming_dps=raw*(1.0-red)*(1.0-total_avoidance)*max(1.0,avg_alive)
        # Forever keeps the original damage-taken Rage formula but evaluates
        # Armor as a fixed 50% reduction. Real Armor therefore affects
        # survivability, not Rage income; avoidance still removes the hit.
        rage_pre_armor_dps=raw*max(1.0,avg_alive)
        incoming_rage_rate=incoming_damage_rage_per_second(
            level,rage_pre_armor_dps,successful_hit_fraction=(1.0-total_avoidance),
        )
        natural_reaction_rage_rate=_natural_reaction_rage_per_second(t,avg_alive)
        # Blood Frenzy rage is part of the same feedback loop: more Rage can
        # fund more crit-capable abilities, which can in turn return Rage.
        ability_crit_rate=(
            float(offense["primal_rate"])
            # Each Swipe target has its own crit event. Pack exposure gives the
            # expected targets alive/hit by a cast in this smooth model.
            + float(offense["swipe_rate"])*max(1.0,avg_alive)
            + float(offense["lacerate"].get("cast_rate_per_s",0.0))
            + float(offense.get("berserk_primal_rate",0.0))*berserk_extra_targets
        )
        blood_frenzy_rage_rate=_blood_frenzy_bear_rage_per_second(
            t,crit=crit,white_swing_rate=1.0/BEAR_FORM_SWING_S,ability_crit_rate=ability_crit_rate,
        )
        next_rage_rate=base_rage_rate+incoming_rage_rate+natural_reaction_rage_rate+blood_frenzy_rage_rate
        if abs(next_rage_rate-rage_rate)<1e-6:
            rage_rate=next_rage_rate
            break
        rage_rate=next_rage_rate

    # One final evaluation at the converged rage budget and current focus TTK.
    offense=_offense_for_rage(rage_rate,target_lifetime_est)
    primal_bite_rate=float(offense["primal_rate"])
    primal_bite=float(offense["primal_dps"])
    swipe_rate=float(offense["swipe_rate"])
    swipe_per_target_dps=float(offense["swipe_dps"])
    lacerate=offense["lacerate"]
    maul_rate=float(offense["maul_rate"])
    maul=float(offense["maul_dps"])
    focus_dps=float(offense["focus_dps"])
    berserk_primal_rate=float(offense.get("berserk_primal_rate",0.0))
    berserk_primal_extra_dps=float(offense.get("berserk_primal_extra_dps",0.0))
    berserk_extra_targets=max(0,min(wh.BERSERK_PRIMAL_BITE_MAX_TARGETS-1,n-1))
    berserk_bg_equiv=berserk_primal_extra_dps*berserk_extra_targets/max(1,n)
    exposure=estimate_pack_exposure(n,focus_dps,swipe_per_target_dps+berserk_bg_equiv)
    avg_alive=float(exposure.avg_alive)
    berserk_extra_alive=min(float(berserk_extra_targets),max(0.0,avg_alive-1.0))
    pack_dps=max(.1,focus_dps+swipe_per_target_dps*avg_alive+berserk_primal_extra_dps*berserk_extra_alive)
    combat_s=hp*n/pack_dps
    first_target_dps=max(.1,focus_dps+swipe_per_target_dps)
    first_kill_s=hp/first_target_dps
    recovery=_feral_pack_recovery(
        level,t,gear,combat_s,pull_size=n,avg_alive=avg_alive,first_kill_s=first_kill_s,rage_rate=rage_rate,
    )
    # Keep survival/mitigation as an explicit throughput input rather than
    # hiding it inside offensive DPS.  This makes Bear closure auditable: armor,
    # avoidance and HP change recovery/lethality; post-mitigation incoming
    # damage also feeds the separately parameterized rage income.
    survival_model={
        "authority":"bear_survival_pressure_v1",
        "player_hp":float(recovery.get("player_hp",0.0)),
        "armor":float(recovery.get("armor",0.0)),
        "armor_reduction":float(recovery.get("armor_reduction",0.0)),
        "total_avoidance":float(recovery.get("total_avoidance",0.0)),
        "avg_incoming_dps":float(recovery.get("avg_incoming_dps",0.0)),
        "peak_incoming_dps":float(recovery.get("peak_incoming_dps",0.0)),
        "lethal_pressure":float(recovery.get("lethal_pressure",0.0)),
        "incoming_damage":float(recovery.get("incoming_damage",0.0)),
        "incoming_rage_per_s":float(incoming_rage_rate),
        "frenzied_regeneration_heal_ev":float(recovery.get("frenzied_regeneration_heal_ev",0.0)),
        "feasible":bool(recovery.get("feasible",False)),
    }

    travel_s=between_pull_travel_s()
    cycle_s=combat_s+float(recovery["recovery_s"])+travel_s+gather_s
    per100=100.0/n
    rotation_parts=[]
    if primal_bite_row is not None:
        rotation_parts.append("Primal Bite on CD")
    if berserk_available:
        rotation_parts.append("Berserk on CD")
    if n>1 and swipe is not None:
        rotation_parts.append("Swipe (3-target cap) on pack")
    if bool(lacerate.get("available")) and float(lacerate.get("cast_rate_per_s",0.0))>0.0:
        rotation_parts.append("Lacerate ramp/maintain on focus")
    rotation_parts.extend(["Maul with excess rage","Bear autos"])
    rotation=" → ".join(rotation_parts)

    flags=[
        "Bear multi-pull deterministic pack model (1-3 engaged mobs)",
        "20-yard source-independent spatial scenario: gathering movement charged before AoE",
        "PROVISIONAL: incoming damage and threat during gathering not yet event-modeled",
        "shared pack exposure: avg_alive total damage + full-pack peak diagnostics",
        "stateful HP carry; shared full recovery only when next pull would be unsafe",
        "Forever Swipe verified 3-target cap and rank base damage",
        "Forever Maul verified 15-rage base cost; Ferocity reduction applied",
        "Forever Primal Bite rank flats / 20 rage / 6s cooldown; Rage and shared GCD budget enforced",
        "Forever Berserk 15s / 180s: Primal Bite cooldown removed during window and up to 3 targets credited",
        "Forever Lacerate finite-target 5-stack ramp; Shredding Attacks Rage reduction applied",
        "Forever Blood Frenzy: Bear crits return expected Rage; Cat builder crits can add CP",
        "Forever Bear Swipe verified flat rank damage; Cat-form Swipe weapon scaling is a separate mechanic",
        "Forever incoming-damage Rage: original formula with fixed 50% Armor assumption; real Armor/absorbs do not reduce Rage",
        "+Defense contributes generic miss+dodge avoidance in Cat/Bear; Druids do not parry",
        "Natural Reaction: verified rank dodge + rank-scaled 5-Rage-on-dodge proc",
        "verified Brawler→Warden Leatherworking tank ladder through required level 50",
        "Forever weapon DPS carried into Bear form; fixed form-speed parameter is explicit",
    ]
    feasible=bool(recovery["feasible"])
    return {
        "total_s":per100*cycle_s if feasible else 1e9,
        "kill_s":per100*combat_s if feasible else 1e9,
        "recovery_s":per100*float(recovery["recovery_s"]) if feasible else 1e9,
        "travel_s":per100*travel_s if feasible else 0.0,
        "pack_assembly_s":per100*gather_s if feasible else 0.0,
        "mob_spacing_yards":layout.spacing_yards,
        "mob_positions_yards":layout.positions_yards,
        "initial_melee_targets":len(layout.initial_melee_targets()),
        "spatial_multi_pull_fidelity":"PROVISIONAL_MOVEMENT_AND_GROUPING_PROXY",
        "dps":pack_dps,
        "mana_spent_per_mob":0.0,
        "profile":"bear",
        "rotation":rotation if feasible else "infeasible Bear pack",
        "approximation_flags":flags + ([] if feasible else ["survival infeasible"]),
        "pull_size":n,
        "requested_pull_size":requested_n,
        "multipull_supported":bool(multipull_supported),
        "multipull_prerequisite":"Swipe rank available" if multipull_supported else "single-target only: no verified Swipe rank",
        "bear_survival_model":survival_model,
        "mobs_per_hour":3600.0*n/max(.1,cycle_s) if feasible else 0.0,
        "cycle_s":cycle_s,
        "combat_s_per_pack":combat_s,
        "recovery_s_per_pack":float(recovery["recovery_s"]),"recovery_solver_id":RECOVERY_SOLVER_ID,
        "first_kill_s":first_kill_s,
        "avg_alive_mobs":avg_alive,
        "peak_alive_mobs":float(exposure.peak_alive),
        "sequential_avg_alive_mobs":float(exposure.sequential_avg_alive),
        "aoe_fraction":float(exposure.aoe_fraction),
        "focus_dps":focus_dps,
        "swipe_dps_per_alive_target":swipe_per_target_dps,
        "swipe_rate_per_s":swipe_rate,
        "swipe_rage_cost":swipe_cost,
        "swipe_rank_level":swipe_rank_level,
        "swipe_base_damage":swipe_base_damage,
        "swipe_scaling_credited":"verified_flat_bear_rank",
        "lacerate_rank_level":lacerate.get("rank_level"),
        "lacerate_rage_cost":float(lacerate.get("rage_cost",0.0)),
        "lacerate_cast_rate_per_s":float(lacerate.get("cast_rate_per_s",0.0)),
        "lacerate_applications_per_target":float(lacerate.get("applications_per_target",0.0)),
        "lacerate_avg_stacks":float(lacerate.get("avg_stacks",0.0)),
        "lacerate_dps":float(lacerate.get("dps",0.0)),
        "lacerate_bleed_dps":float(lacerate.get("bleed_dps",0.0)),
        "lacerate_direct_dps":float(lacerate.get("direct_dps",0.0)),
        "lacerate_source":wh.LACERATE_SOURCE,
        "shredding_attacks_lacerate_source":wh.SHREDDING_ATTACKS_SOURCE,
        "primal_bite_rank_level":primal_bite_rank_level,
        "primal_bite_rage_cost":primal_bite_cost,
        "primal_bite_rate_per_s":primal_bite_rate,
        "primal_bite_flat_damage":primal_bite_flat,
        "berserk_available":berserk_available,
        "berserk_uptime_ev":berserk_uptime,
        "berserk_primal_bite_rate_per_s":berserk_primal_rate,
        "berserk_primal_bite_extra_dps_per_target":berserk_primal_extra_dps,
        "berserk_primal_bite_extra_targets":berserk_extra_targets,
        "berserk_source":wh.BERSERK_SOURCE,
        # Compatibility detail keys for old consumers; values are Primal Bite.
        "mangle_rank_level":primal_bite_rank_level,
        "mangle_flat_damage":primal_bite_flat,
        "maul_rage_cost":maul_cost,
        "maul_rank_level":int(_maul_level),
        "maul_flat_damage":float(maul_flat),
        "maul_rate_per_s":maul_rate,
        "bear_normal_weapon_hit":bear_normal_hit,
        "weapon_dps":float(gear.get("weapon_dps",0.0)),
        "weapon_scaling_provenance":weapon_provenance(),
        "rage_rate_proxy":rage_rate,
        "base_rage_rate_proxy":base_rage_rate,
        "incoming_damage_rage_rate_proxy":incoming_rage_rate,
        "incoming_damage_rage_fixed_armor_fraction":0.5,
        "blood_frenzy_rage_rate":blood_frenzy_rage_rate,
        "blood_frenzy_rank":max(0,min(2,int(t.effective_blood_frenzy))),
        "incoming_damage_rage_provenance":rage_provenance(),
        "natural_reaction_rank":max(0,min(5,int(t.natural_reaction))),
        "natural_reaction_dodge_chance":_natural_reaction(t)[0],
        "defense_skill_bonus":max(0.0,float(gear.get("defense",0.0))),
        "defense_avoidance_bonus":_druid_defense_avoidance(gear),
        "total_avoidance":max(0.0,min(0.95,_natural_reaction(t)[0]+_druid_defense_avoidance(gear))),
        "natural_reaction_rage_proc_chance":_natural_reaction(t)[1],
        "natural_reaction_rage_per_proc":_natural_reaction(t)[2],
        "natural_reaction_rage_rate":natural_reaction_rage_rate,
        "natural_reaction_source":wh.NATURAL_REACTION_SOURCE,
        **{k:v for k,v in recovery.items() if k != "recovery_s"},
        "representative_mob_hp":hp,
        "crit":crit,"attack_power_proxy":ap,
        "gear":gear["name"],"gear_stats":gear,
        "feasible":feasible,
    }


def _bear(level: int, t: Talents) -> dict:
    # Swipe is the production prerequisite for >1 engaged target. Search 1-3
    # only when a verified Swipe rank exists; otherwise Bear is strictly single
    # target. No gather-time assumption or non-Swipe pseudo-AoE is manufactured.
    max_pull=wh.SWIPE_MAX_TARGETS if _latest(wh.SWIPE_RANKS,level) is not None else 1
    rows=[_bear_pack(level,t,n) for n in range(1,max_pull+1)]
    return min(rows,key=lambda r:float(r["total_s"]))

def _spell_damage(avg_base: float, coeff: float, sp: float, crit: float, crit_bonus: float,
                  hit: float = 1.0) -> float:
    return float(hit) * (float(avg_base) + float(coeff) * float(sp)) * (1.0 + float(crit) * float(crit_bonus))


def _balance(level: int, t: Talents) -> dict:
    hp = leveling.representative_hp(level)
    wrath = _latest(wh.WRATH_RANKS, level)
    starfire = _latest(wh.STARFIRE_RANKS, level)
    moonfire = _latest(wh.MOONFIRE_RANKS, level)
    insect = _latest(wh.INSECT_SWARM_RANKS, level) if t.insect_swarm else None

    # Verified Totemic -> Skycaller Leatherworking pieces provide a conservative
    # spell-power floor through the current audited required-level-50 ladder.
    # This is a designed craft baseline, not a BIS assumption.
    gear = _balance_gear(level)
    sp = float(gear["spell_power"])
    crit = .05 + .02 * t.natures_majesty + (.03 if t.moonkin_form and level >= wh.MOONKIN_FORM_LEVEL else 0.0)
    crit_bonus = .5 + .1 * t.vengeance
    dmg_mod = 1.0 + .02 * t.moonfury
    mana_pool = (170 + 16 * level) * (1 + .02 * t.living_spirit) + 15.0 * float(gear["intellect"])
    regen = 8 + .55 * level
    # Same-level representative target; unlike the previous Balance proxy this
    # must not grant every harmful spell a guaranteed hit.
    spell_hit = leveling.spell_hit_chance(level, level)
    wrath_base_mult = base_damage_multiplier("druid", "wrath")
    wrath_tuning = tuning_provenance("druid", "wrath")

    candidates = []

    if wrath is not None:
        _lv, mana0, cast0, dmin, dmax, coeff = wrath
        cast = max(1.5, float(cast0) + _improved_wrath_cast_delta_s(t))
        mana = float(mana0) * max(0.5, 1.0 + _improved_wrath_cost_pct(t))
        # Beta build tuning is applied to *base* damage before spell power. The
        # raw Wowhead tooltip row remains untouched because public pages can lag
        # the active server build. Do not multiply the SP contribution.
        base_avg = ((float(dmin) + float(dmax)) / 2.0) * wrath_base_mult
        dmg = _spell_damage(base_avg, coeff, sp, crit, crit_bonus, spell_hit) * dmg_mod
        candidates.append({"name":"Wrath", "dps":dmg/cast, "mps":mana/cast, "cast":cast, "damage":dmg, "mana":mana,
                           "raw_base_damage_avg":(float(dmin)+float(dmax))/2.0,
                           "base_damage_multiplier":wrath_base_mult})

    if starfire is not None:
        _lv, mana, cast, dmin, dmax, coeff = starfire
        dmg = _spell_damage((dmin + dmax) / 2.0, coeff, sp, crit, crit_bonus, spell_hit) * dmg_mod
        candidates.append({"name":"Starfire", "dps":dmg/cast, "mps":mana/cast, "cast":float(cast), "damage":dmg, "mana":float(mana)})

    # Eclipse is a real alternating Wrath -> Starfire mechanic in Forever.  The
    # current server-side charge script is only partly exposed, so use the
    # conservative one-Wrath + two accelerated-Starfires cycle documented here.
    if t.eclipse and wrath is not None and starfire is not None:
        w = next(x for x in candidates if x["name"] == "Wrath")
        s = next(x for x in candidates if x["name"] == "Starfire")
        reduction = wh.ECLIPSE_STARFIRE_CAST_REDUCTION_BY_RANK[max(0, min(3, t.eclipse))]
        sf_cast = max(1.5, s["cast"] - reduction)
        cyc_t = w["cast"] + 2.0 * sf_cast
        cyc_dmg = w["damage"] + 2.0 * s["damage"]
        cyc_mana = w["mana"] + 2.0 * s["mana"]
        candidates.append({"name":"Eclipse: Wrath → Starfire ×2", "dps":cyc_dmg/cyc_t, "mps":cyc_mana/cyc_t, "cast":cyc_t/3.0, "damage":cyc_dmg/3.0, "mana":cyc_mana/3.0})

    if not candidates:
        # L11-13 fallback where audited higher-rank facts are not yet complete.
        cast = max(1.5, 2.0 + _improved_wrath_cast_delta_s(t))
        dmg = (22 + 3.0 * level) * dmg_mod * (1 + crit * crit_bonus)
        candidates.append({"name":"Wrath (low-level fallback)", "dps":dmg/cast, "mps":0.0, "cast":cast, "damage":dmg, "mana":0.0})

    # Nature's Grace: current Forever buff = +10% cast speed and -10% GCD for 3s.
    # Use expected uptime from crit frequency on the filler, capped at 100%.
    for c in candidates:
        if t.natures_grace:
            casts_per_s = 1.0 / max(1.0, c["cast"])
            uptime = min(1.0, crit * casts_per_s * wh.NATURES_GRACE_DURATION_S)
            haste = 1.0 + wh.NATURES_GRACE_HASTE * uptime
            c["dps"] *= haste
            c["mps"] *= haste
            c["ng_uptime_ev"] = uptime
        else:
            c["ng_uptime_ev"] = 0.0

    # Pick the filler with minimum total leveling time, not raw DPS.  DoTs are
    # then layered on if the mob is expected to live long enough to realize them.
    def score_filler(c):
        kill = hp / max(0.1, c["dps"])
        mana = c["mps"] * kill
        recovery = max(0.0, mana - .18 * mana_pool) / max(.1, regen)
        return kill + recovery

    filler = min(candidates, key=score_filler)
    base_kill = hp / max(.1, filler["dps"])
    dot_damage = 0.0
    dot_mana = 0.0
    dot_gcd = 0.0
    rotation_parts = []

    if moonfire is not None and base_kill >= 5.0:
        _lv, mana, dmin, dmax, dot_total, duration, direct_coeff, tick_coeff = moonfire
        base_duration = float(duration)
        duration = base_duration + (3.0 if t.natures_splendor else 0.0)
        direct = _spell_damage((dmin+dmax)/2.0, direct_coeff, sp, crit + .05*t.improved_moonfire, crit_bonus, spell_hit)
        # Forever exposes a separate SP modifier for each 3-second Moonfire tick.
        # The old scorer carried tick_coeff in the data but never applied it,
        # effectively deleting the DoT's spell-power scaling.  Model fractional
        # expected ticks over the realized uptime so Nature's Splendor can also
        # add the appropriate extra tick rather than merely diluting the DoT.
        base_ticks = max(1.0, base_duration / wh.MOONFIRE_TICK_INTERVAL_S)
        base_per_tick = float(dot_total) / base_ticks
        realized_ticks = min(float(duration), base_kill) / wh.MOONFIRE_TICK_INTERVAL_S
        periodic = (base_per_tick + float(tick_coeff) * sp) * realized_ticks
        periodic *= spell_hit * (1.0 + .05 * t.genesis + .05 * t.improved_moonfire)
        dot_damage += direct + periodic
        dot_mana += float(mana) * max(0.0, 1.0 - .03 * t.moonglow)
        dot_gcd += 1.5
        rotation_parts.append("keep Moonfire up")

    if insect is not None and base_kill >= 7.0:
        _lv, mana, dot_total, duration, tick_coeff = insect
        base_duration = float(duration)
        duration = base_duration + (2.0 if t.natures_splendor else 0.0)
        base_ticks = max(1.0, base_duration / wh.INSECT_SWARM_TICK_INTERVAL_S)
        base_per_tick = float(dot_total) / base_ticks
        realized_ticks = min(float(duration), base_kill) / wh.INSECT_SWARM_TICK_INTERVAL_S
        periodic = (base_per_tick + float(tick_coeff) * sp) * realized_ticks
        periodic *= spell_hit * (1.0 + .05*t.genesis)
        dot_damage += periodic
        dot_mana += float(mana) * max(0.0, 1.0 - .03 * t.moonglow)
        dot_gcd += 1.5
        rotation_parts.append("keep Insect Swarm up")

    # One-pass recomposition: DoTs reduce the amount of filler time needed.
    remaining = max(1.0, hp - dot_damage)
    filler_time = remaining / max(.1, filler["dps"])
    total_cast_time = dot_gcd + filler_time
    filler_mana = filler["mps"] * filler_time
    mana_spent = dot_mana + filler_mana
    effective_dps = hp / max(.25, total_cast_time)

    rotation_parts.append(filler["name"])
    if t.natures_grace:
        rotation_parts.append("Nature's Grace proc → faster Starfire/Wrath")
    # Forever grants Omen/Clearcasting at level 20; do not advertise a
    # reactive proc policy before the capability exists. Proc frequency remains
    # intentionally unpriced, so this is a legality/rotation label only.
    clearcasting_available = int(level) >= 20
    if clearcasting_available:
        rotation_parts.append("Clearcasting → most expensive useful cast")

    flags = [
        "single-target Balance priority model",
        "stateful HP carry; shared full recovery only when next pull would be unsafe",
        "rank-specific Forever spell modifiers for Wrath/Starfire/Moonfire/Insect Swarm",
        "dated Forever beta tuning overrides applied separately from public tooltip facts",
        "Eclipse alternation modeled from current Forever trait values",
        "Nature's Grace expected-value haste modeled",
        "Omen/Clearcasting semantics known but proc rate not credited",
        "verified Totemic→Skycaller Leatherworking spell-power ladder through required level 50",
    ]

    recovery=_caster_recovery(level,gear,total_cast_time,mana_spent,mana_pool)
    return leveling.combat_result(
        level=level, dps=effective_dps, mana_spent=mana_spent,
        mana_pool=mana_pool, regen_per_s=regen, travel_s=between_pull_travel_s(),
        rotation="; ".join(rotation_parts), profile="balance", flags=flags,
        recovery_s_override=recovery["recovery_s"],
        details={
            **{k:v for k,v in recovery.items() if k != "recovery_s"},
            "representative_mob_hp": hp,
            "crit": crit,
            "spell_hit_chance": spell_hit,
            "spell_power_proxy": sp,
            "gear": gear["name"],
            "gear_stats": gear,
            "balance_filler": filler["name"],
            "wrath_base_damage_multiplier": wrath_base_mult,
            "wrath_raw_base_damage_avg": filler.get("raw_base_damage_avg"),
            "wrath_tuned_base_damage_avg": (filler.get("raw_base_damage_avg") * wrath_base_mult) if filler.get("raw_base_damage_avg") is not None else None,
            "wrath_tuning_provenance": wrath_tuning,
            "natures_grace_uptime_ev": filler.get("ng_uptime_ev", 0.0),
            "dot_damage_per_mob": dot_damage,
            "clearcasting_available": clearcasting_available,
        },
    )


def _experimental_level_score_once(level: int, t: Talents, profile: str = "auto") -> dict:
    """Score gameplay once using the currently selected role gear.

    This is intentionally below the gear/stat fixed point so marginal probes can
    re-optimize gameplay without recursively launching another gear search.
    """
    rows = []
    if profile in ("auto", "all"):
        if level >= CAT_FORM_LEVEL:
            rows.append(_cat(level, t))
        rows.append(_bear(level, t))
    elif profile == "feral":
        rows.append(_cat(level, t) if level >= CAT_FORM_LEVEL else _bear(level, t))
    elif profile == "bear":
        rows.append(_bear(level, t))
    if profile in ("auto", "all", "balance"):
        rows.append(_balance(level, t))
    return min(rows, key=lambda r: r["total_s"])


def _gear_role_for_profile(level: int, profile: str) -> tuple[str, str]:
    if profile == "balance":
        return "balance", "druid_balance"
    if profile == "bear" or (profile == "feral" and int(level) < CAT_FORM_LEVEL):
        return "bear", "druid_bear"
    return "feral", "druid_feral"


def _selection_signature(selected: dict) -> tuple:
    return tuple(sorted((str(slot), int(item.item_id)) for slot,item in (selected or {}).items()))


def _optimize_profile_fixed_point(level: int, t: Talents, profile: str) -> dict:
    from src.v2.per_level_fixed_point import optimize_level_fixed_point

    combat_profile,role=_gear_role_for_profile(level,profile)
    initial=catalogue_select_gear("druid", int(level), role)

    def score_with_gear(selected):
        token=_GEAR_SELECTION_OVERRIDE.set({role:selected})
        guard=_FIXED_POINT_DISABLED.set(True)
        try:
            return _experimental_level_score_once(int(level),t,combat_profile)
        finally:
            _FIXED_POINT_DISABLED.reset(guard)
            _GEAR_SELECTION_OVERRIDE.reset(token)

    def derive_weights(score):
        token=_GEAR_SELECTION_OVERRIDE.set({role: selected_holder[0]})
        guard=_FIXED_POINT_DISABLED.set(True)
        try:
            return marginal_stat_weights(int(level),t,combat_profile,baseline=dict(score))
        finally:
            _FIXED_POINT_DISABLED.reset(guard)
            _GEAR_SELECTION_OVERRIDE.reset(token)

    selected_holder=[initial]
    def select_next(_gear, values):
        nxt=catalogue_select_gear("druid",int(level),role,weights=values)
        selected_holder[0]=nxt
        return nxt

    # stat_weights needs to see the same equipment that produced ``score``.
    # Keep the holder synchronized before every score/derivative pair.
    def score_sync(selected):
        selected_holder[0]=selected
        return score_with_gear(selected)

    try:
        from src.v2.runtime_progress import progress_scope, emit_runtime_progress
        scope = progress_scope(profile=combat_profile)
    except Exception:
        from contextlib import nullcontext
        scope = nullcontext()
    with scope:
        try:
            emit_runtime_progress(stage="profile", profile=combat_profile)
        except Exception:
            pass
        fp=optimize_level_fixed_point(
            initial_gear=initial, score_with_gear=score_sync, stat_weights=derive_weights,
            select_gear=select_next, gear_signature=_selection_signature, max_iters=4,
        )
    out=dict(fp.score)
    out["gear_fixed_point"]=dict(out.get("gear_fixed_point") or {})
    out["gear_fixed_point"].update({"class":"druid","combat_profile":combat_profile,"role":role})
    return out


def experimental_level_score(level: int, t: Talents, profile: str = "auto") -> dict:
    validate_current_schema(t)
    if _FIXED_POINT_DISABLED.get():
        return _experimental_level_score_once(level,t,profile)

    profiles=[]
    if profile in ("auto","all"):
        if int(level) >= CAT_FORM_LEVEL:
            profiles.append("feral")
        profiles.extend(("bear","balance"))
    elif profile == "feral":
        profiles.append("feral")
    elif profile == "bear":
        profiles.append("bear")
    elif profile == "balance":
        profiles.append("balance")
    else:
        return _experimental_level_score_once(level,t,profile)
    rows=[_optimize_profile_fixed_point(int(level),t,p) for p in profiles]
    out=dict(min(rows,key=lambda r:r["total_s"]))
    if int(level) > 30:
        out["approximation_flags"] = list(out.get("approximation_flags") or ()) + [
            "Druid L31-L40 bounded planning range: Balance/Cat/Bear core leveling mechanics are modeled; capability_matrix names remaining unpriced/fail-closed mechanics"
        ]
        out["verified_level_cap"] = 30
        out["planning_level_cap"] = 40
        if int(level) > 40:
            out["approximation_flags"].append("above Druid bounded planning cap L40; L41-L60 full-fidelity closure not yet claimed")
    return out




def _selection_from_baseline(level: int, role: str, baseline: dict | None) -> dict | None:
    """Reconstruct the exact published SQL selection for standalone stat probes."""
    slots=((baseline or {}).get("gear_stats") or {}).get("slots") or {}
    ids={str(slot): int(row.get("item_id")) for slot,row in slots.items() if isinstance(row,dict) and row.get("item_id") is not None}
    if not ids:
        return None
    by_id={int(item.item_id):item for item in catalogue_available_items("druid",int(level))}
    selected={slot:by_id[item_id] for slot,item_id in ids.items() if item_id in by_id}
    return selected or None


def score_external_build(level: int, t: Talents, profile: str = "all", gear_stats: dict | None = None) -> dict:
    """Canonical fixed-talent scorer used by explicit external-build comparison.

    No comparison formula lives outside the Druid backend: this function routes
    the challenger through the same expected-value scorer, policy selection,
    gear fixed point and marginal-stat implementation as normal optimization.
    With ``gear_stats`` the exact published item IDs are reconstructed and held
    fixed, giving an apples-to-apples talent/policy comparison.
    """
    validate_current_schema(t)
    profile = "feral" if str(profile) == "cat" else str(profile or "all")
    if profile not in {"all", "auto", "feral", "bear", "balance"}:
        raise ValueError(f"Druid external-build comparison does not model profile {profile!r}")

    if gear_stats is None:
        row = dict(experimental_level_score(int(level), t, profile))
        actual = str(row.get("profile") or profile)
        actual = "feral" if actual == "cat" else actual
        row["stat_weights"] = marginal_stat_weights(int(level), t, actual, baseline=row)
        row["comparison_gear_mode"] = "independent_fixed_point"
        return row

    # Same-gear mode needs one concrete profile/role; an unconstrained ``all``
    # row already records which profile won, and the caller passes that profile.
    if profile in {"all", "auto"}:
        raise ValueError("same-gear external comparison requires a concrete Druid profile")
    combat_profile, role = _gear_role_for_profile(int(level), profile)
    baseline = {"gear_stats": dict(gear_stats)}
    selected = _selection_from_baseline(int(level), role, baseline)
    if not selected:
        raise ValueError("cannot reconstruct published Druid gear for same-gear comparison")
    wanted = {
        str(slot): int(item.get("item_id"))
        for slot, item in dict(gear_stats.get("slots") or {}).items()
        if isinstance(item, dict) and item.get("item_id") is not None
    }
    got = {str(slot): int(item.item_id) for slot, item in selected.items()}
    missing = sorted(set(wanted) - set(got))
    if missing:
        raise ValueError("published Druid gear contains item IDs unavailable to current catalogue: " + ", ".join(missing))

    selection_token = _GEAR_SELECTION_OVERRIDE.set({role: selected})
    guard = _FIXED_POINT_DISABLED.set(True)
    try:
        row = dict(_experimental_level_score_once(int(level), t, combat_profile))
        row["stat_weights"] = marginal_stat_weights(int(level), t, combat_profile, baseline=row)
    finally:
        _FIXED_POINT_DISABLED.reset(guard)
        _GEAR_SELECTION_OVERRIDE.reset(selection_token)
    row["comparison_gear_mode"] = "fixed_optimizer_gear"
    return row

def marginal_stat_weights(level: int, t: Talents, profile: str = "auto", baseline: dict | None = None) -> dict:
    """Finite differences through the existing scorer, with talents fixed.

    Gameplay is reselected within the requested profile. These are native stat
    values of the current expected-value model, not a new analytic surrogate.
    Zero means the current model has no marginal benefit, not a game-mechanic
    claim. Forward probes keep every gear amount nonnegative.
    """
    from src.v2.stat_weight_model import normalize_objective_gradient
    base = baseline or (_experimental_level_score_once(level, t, profile) if _FIXED_POINT_DISABLED.get() else experimental_level_score(level, t, profile))
    # A caller may pass the converged fixed-point baseline outside the coordination
    # loop. Reconstruct that exact SQL selection so finite differences perturb the
    # same equipment instead of falling back to the role-default gear.
    role_profile=str((base or {}).get("profile") or profile)
    probe_profile = "feral" if role_profile == "cat" else (role_profile if role_profile in ("feral","bear","balance") else profile)
    _,probe_role=_gear_role_for_profile(level, probe_profile)
    baseline_selection=None if (_GEAR_SELECTION_OVERRIDE.get() or {}).get(probe_role) is not None else _selection_from_baseline(level,probe_role,base)
    selection_token=_GEAR_SELECTION_OVERRIDE.set({probe_role:baseline_selection}) if baseline_selection is not None else None
    increment = 4.0 + (max(10, min(60, level)) - 10) * 36.0 / 50.0
    gradients, probes = {}, {}
    for stat in ("strength", "agility", "stamina", "intellect", "spirit", "mp5", "spell_power", "armor", "weapon_dps", "defense"):
        # One-sided probes avoid negative gear and form-dependent lower bounds.
        token = _GEAR_PROBE.set({stat: increment})
        try:
            # Stat derivatives are local to the converged equipment/gameplay point;
            # do not launch another gear fixed point for each finite-difference probe.
            plus = _experimental_level_score_once(level, t, probe_profile)
        finally:
            _GEAR_PROBE.reset(token)
        gradients[stat] = (float(plus["total_s"]) - float(base["total_s"])) / increment
        probes[stat] = {"increment": increment, "plus_s_per_100": plus["total_s"]}
    if selection_token is not None:
        _GEAR_SELECTION_OVERRIDE.reset(selection_token)
    result = normalize_objective_gradient(
        baseline_s_per_100=base["total_s"], objective_gradient=gradients,
        method="finite_difference_druid_gameplay_reoptimized",
        reference_stat="spell_power" if gradients["spell_power"] < -1e-12 else "strength",
        note="Forward finite differences of the existing Druid expected-value scorer; talents fixed, gameplay re-optimized. Availability is explicit: a measured zero is not the same as an unmodeled stat.",
        metadata={"probes": probes, "profile": profile},
        declared_stats=("strength", "agility", "stamina", "intellect", "spirit", "mp5", "spell_power", "armor", "weapon_dps", "defense", "shield_armor", "block_value"),
        stat_status={
            "defense": {"status": "measured", "reason": "Measured through the scorer. Bonus Defense contributes generic miss+dodge avoidance in Cat/Bear, and with Thick Hide selected also contributes bonus Armor."},
            "shield_armor": {"status": "not_modeled", "reason": "Druid leveling forms do not use shields."},
            "block_value": {"status": "not_modeled", "reason": "Druid leveling forms do not use shield block."},
        },
    )
    result["analytical"] = False
    return result
