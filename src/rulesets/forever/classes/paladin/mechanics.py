from __future__ import annotations

from functools import lru_cache
import math

from src.shared.leveling import objective as leveling
from src.shared.leveling.timing import between_pull_travel_s
from src.rulesets.forever.data.rules import default_rules
from src.rulesets.forever.data.catalogue import default_catalogue
from .gear import GearSetup, archetypes, gear_snapshot, gear_curve_status, reroll_body_items, apply_body_item_names
from src.rulesets.forever.shared.crafted_itemization import CRAFTED_ITEMS, PALADIN_AUDITED_ITEMS
from src.rulesets.forever.shared.item_budget import peer_exchange_budget_units, weapon_peer_exchange_budget_units
from src.rulesets.forever.items.runtime_selection import available_items as catalogue_available_items
from src.rulesets.forever.shared.defense import defense_block_chance
from .policy import POLICIES, MANA_PLANS, ManaPlan, PriorityPolicy
from .survival import (armor_reduction, player_base_hp, expected_redoubt_bonus_block, defense_avoidance, anticipation_defense_bonus,
                       expected_icd_proc_rate, replacing_absorb_dynamics, discrete_heal_sequence)
from ...shared.mobs import fixture_snapshot as mob_fixture_snapshot
from ...shared.recovery import HealOption, solve_recovery, RECOVERY_SOLVER_ID
from ...shared.base_stats import base_spirit, spirit_provenance, BASE_STAT_AUTHORITY_ID
from ...shared.pack_geometry import estimate_pack_exposure
from .talents import Talents
from .spells import (
    HOLY_STRIKE, SEAL_FURY, SEAL_RIGHTEOUSNESS, SEAL_COMMAND, CONSECRATION,
    HOLY_LIGHT, FLASH_OF_LIGHT, HAMMER_OF_JUSTICE, BLESSING_OF_PROTECTION,
    DIVINE_PROTECTION, RETRIBUTION_AURA, DEVOTION_AURA, latest,
)




def _divine_strength_pct(t:Talents) -> float:
    return default_rules().talent_value("paladin", "divine_strength", t.divine_strength, "stat_pct", target="strength") if t.divine_strength else 0.0


def _toughness_item_armor_pct(t:Talents) -> float:
    return default_rules().talent_value("paladin", "toughness", t.toughness, "item_armor_pct", target="item_armor") if t.toughness else 0.0

def _avg(row, lo: int, hi: int) -> float:
    return .5 * (float(row[lo]) + float(row[hi]))


# Rank-invariant public Forever modifiers are source-owned.  The canonical
# snapshot may carry only a representative rank/helper anchor, so these use
# the family-level interpreter which fails closed if captured ranks disagree.
def _family_sp_coeff(family_key: str, target: str) -> float:
    return default_rules().spell_family_value(
        "paladin", family_key, "spell_power_coefficient", target=target, school="holy"
    )


# Percentage-of-base-mana costs use the pinned class-level stat foundation in
# the Forever source snapshot. The snapshot records the exact inherited
# vanilla/classic row source and the explicit "no Forever override captured"
# assumption, instead of hiding that basis in a class-local handwritten table.
def _paladin_base_mana(level: int) -> float:
    level=max(1,min(60,int(level)))
    return float(default_catalogue().class_level_stat("paladin", level)["base_mana"])


def _paladin_melee_ap(level: int, strength: float) -> float:
    # Vanilla/Classic Paladin baseline: 3*level + 2*Strength - 20.
    # Forever-specific evidence can override this later if the core changed it.
    return max(0.0, 3.0*float(level) + 2.0*float(strength) - 20.0)


def _heal_model(level: int, t: Talents, gear: GearSetup, incoming_swings_per_s: float) -> dict:
    options=[]
    pushback_protection=min(.70,.35*int(t.spiritual_focus))
    # Deterministic pushback tax.  It disappears as Spiritual Focus approaches
    # full protection and grows smoothly with incoming swing frequency.
    pushback_tax=min(.55,.11*incoming_swings_per_s)*(1.0-pushback_protection)
    for name, rows in (("Holy Light",HOLY_LIGHT),("Flash of Light",FLASH_OF_LIGHT)):
        r=latest(rows,level)
        if not r: continue
        coeff=_family_sp_coeff("holy_light" if name == "Holy Light" else "flash_of_light", "heal")
        # Forever Paladin passive Divinity (level 1): +5% healing done and
        # +5% healing received.  Leveling heals here are self-heals, so both
        # modifiers apply.  Healing Light remains multiplicative on top.
        divinity_self_heal=1.05*1.05
        heal=(_avg(r,3,4)+gear.healing_bonus*coeff)*(1+.04*t.healing_light)*divinity_self_heal
        cast=float(r[2])*(1+pushback_tax)
        mana=float(r[1])
        options.append({"name":name,"heal":heal,"cast":cast,"mana":mana,
                        "hps":heal/cast,"hpm":heal/max(1.0,mana),"healing_coeff":coeff})
    if not options:
        return {"name":"none","heal":0.0,"cast":99.0,"mana":0.0,"hps":0.0,"hpm":0.0,"healing_coeff":0.0}
    # Prefer HPM among spells that retain useful throughput; Holy Light usually
    # wins sustained leveling, Flash remains available when its cast time matters.
    return max(options,key=lambda x:(x["hpm"]*min(1.0,x["hps"]/35.0),x["hps"]))


def _righteousness_onhit(level: int, speed: float, spell_damage: float = 0.0) -> float:
    # Current Forever tooltip envelopes by rank.  The public effect exposes a
    # 0.10 SP modifier while the server script retains slower-weapon scaling.
    # Use 2.4s as the explicit reference-speed proxy until the server formula is
    # captured directly.
    rank=latest(SEAL_RIGHTEOUSNESS,level)
    if not rank: return 0.0
    anchors={1:5.5,10:8.5,18:13.0,26:18.5,34:26.0,42:34.0,50:43.5,58:53.5}
    base=anchors[int(rank[0])]
    speed_scale=max(.65,min(1.65,float(speed)/2.4))
    return (base + max(0.0,float(spell_damage))*_family_sp_coeff("seal_of_righteousness", "seal_proc"))*speed_scale


def _base_damage(level:int,t:Talents,gear:GearSetup,profile:str) -> dict:
    base_strength=22.0+2.15*level
    strength=(base_strength+gear.strength_bonus)*(1+_divine_strength_pct(t))
    ap=_paladin_melee_ap(level,strength)
    hit=leveling.physical_hit_chance(level,level,t.precision)
    crit=.045+.01*t.conviction+.01*t.holy_power
    holy_mult=(1+.01*t.crusade)*(1+.02*t.champion_of_the_light)
    seal_mult=1+.05*t.improved_seals
    instant_cost_mult=max(.50,1-.02*t.benediction)
    weapon_avg=gear.weapon_dps*gear.weapon_speed+ap/14.0*gear.weapon_speed
    white=weapon_avg/gear.weapon_speed*hit*(1+crit*.5)
    if gear.weapon_style=="2h":
        white*=1+.03*t.two_handed_weapon_specialization
    else:
        white*=1+.033333*t.one_handed_weapon_specialization

    hs=latest(HOLY_STRIKE,level)
    hs_dps=hs_mps=hs_cost=0.0
    hs_cd=99.0
    if hs:
        hs_cd=max(4.0,float(hs[2])-1.0*t.improved_holy_strike)
        # Holy Strike is normalized weapon damage.  Normalized speed removes
        # artificial slow-weapon AP scaling while preserving the weapon's own
        # base damage.  Current Wowhead also exposes a 42.9% SP modifier on the
        # Holy component.
        normalized_speed=3.3 if gear.weapon_style=="2h" else 2.4
        weapon_base_avg=gear.weapon_dps*gear.weapon_speed
        normalized_weapon_avg=weapon_base_avg+ap/14.0*normalized_speed
        hs_hit=(float(hs[3])*normalized_weapon_avg+_avg(hs,4,5)+gear.spell_damage_bonus*_family_sp_coeff("holy_strike", "holy_damage"))*holy_mult*(1+.10*t.sacred_arbiter)
        hs_cost=float(hs[1])*instant_cost_mult
        hs_dps=hs_hit/hs_cd*hit
        hs_mps=hs_cost/hs_cd

    fury=latest(SEAL_FURY,level)
    sor=latest(SEAL_RIGHTEOUSNESS,level)
    soc=latest(SEAL_COMMAND,level) if t.seal_of_command else None
    use_fury=bool(profile=="protection" and gear.has_shield and fury)
    use_command=bool(profile=="retribution" and soc)
    if use_fury:
        seal_name="Seal of Fury"
        seal_cost=float(fury[1])*instant_cost_mult
        seal_hit=(gear.spell_damage_bonus*_family_sp_coeff("seal_of_fury", "seal_proc"))*seal_mult*holy_mult
        judgement=(gear.spell_damage_bonus*_family_sp_coeff("seal_of_fury", "judgement"))*seal_mult*holy_mult
        seal_dps=seal_hit/gear.weapon_speed*hit
    elif use_command:
        seal_name="Seal of Command"
        seal_cost=float(soc[1])*instant_cost_mult
        # M46: the rank ladder and damage facts are source-driven from the
        # pinned Forever snapshot.  The 7 PPM trigger frequency remains the
        # event-model assumption; the proc/judgement magnitudes no longer are.
        proc_rate=7.0/60.0
        proc_weapon_pct=default_rules().spell_value("paladin","seal_of_command",level,"weapon_damage_pct",target="seal_proc")
        proc_sp_coeff=default_rules().spell_value("paladin","seal_of_command",level,"spell_power_coefficient",target="seal_proc")
        judgement_base=default_rules().spell_value("paladin","seal_of_command",level,"judgement_base_damage",target="judgement")
        judgement_sp_coeff=default_rules().spell_value("paladin","seal_of_command",level,"spell_power_coefficient",target="judgement")
        judgement_stunned_multiplier=default_rules().spell_value("paladin","seal_of_command",level,"target_state_damage_multiplier",target="judgement")
        seal_hit=(proc_weapon_pct*weapon_avg + gear.spell_damage_bonus*proc_sp_coeff)*seal_mult*holy_mult
        judgement=(judgement_base + gear.spell_damage_bonus*judgement_sp_coeff)*seal_mult*holy_mult
        seal_dps=proc_rate*seal_hit*hit*(1+crit*.5)
    else:
        seal_name="Seal of Righteousness"
        seal_cost=float(sor[1])*instant_cost_mult if sor else 0.0
        seal_hit=_righteousness_onhit(level,gear.weapon_speed,gear.spell_damage_bonus)*seal_mult*holy_mult
        judgement=(gear.spell_damage_bonus*_family_sp_coeff("seal_of_righteousness", "judgement"))*seal_mult*holy_mult if sor else 0.0
        seal_dps=seal_hit/gear.weapon_speed*hit
    jcd=max(6.0,10.0-1.0*t.improved_judgement)
    judgement_dps=judgement/jcd
    # Forever Judgement costs 6% of *base* mana and is off the GCD.  Keep the
    # percentage cost uses class base mana, not the current total mana pool.
    # The inherited class-level foundation is pinned with provenance in the
    # source snapshot; a future Forever override can replace it there.
    base_mana=_paladin_base_mana(level)
    judgement_cost=.06*base_mana*instant_cost_mult
    # Sanctified Judgement refunds a fraction of the *judged seal's* mana cost
    # after Judgement is successfully paid.  Track expected refund separately
    # so affordability/event replay still requires the gross Judgement cost.
    seal_refund_fraction=0.0
    if t.sanctified_judgement:
        r=float(t.sanctified_judgement)
        proc_chance=(0.0,.33,.66,1.0)[max(0,min(3,int(r)))]
        refund_fraction=(0.0,.20,.40,.60)[max(0,min(3,int(r)))]
        seal_refund_fraction=proc_chance*refund_fraction
    judgement_refund=seal_cost*seal_refund_fraction
    judgement_net_cost=judgement_cost-judgement_refund
    judgement_mps=judgement_net_cost/jcd

    focus=white+seal_dps+hs_dps+judgement_dps
    expected_vengeance_stacks=min(5.0,max(0.0,crit*35.0))
    focus*=1+.01*t.vengeance*expected_vengeance_stacks
    return {
        "focus_dps":focus,"white_dps":white,"seal_dps":seal_dps,"hs_dps":hs_dps,
        "judgement_dps":judgement_dps,"base_mps":hs_mps+judgement_mps,
        "white_seal_dps":white+seal_dps,
        "hs_cost":hs_cost,"hs_cd":hs_cd,"judgement_cost":judgement_cost,"judgement_refund":judgement_refund,
        "judgement_net_cost":judgement_net_cost,"judgement_cd":jcd,
        "seal_name":seal_name,"seal_hit":seal_hit,"seal_cost":seal_cost,"weapon_avg":weapon_avg,"hit":hit,"crit":crit,
        "holy_mult":holy_mult,"instant_cost_mult":instant_cost_mult,
        "fury":fury if use_fury else None,"seal_duration_s":30.0,
        "sanctified_judgement_refund_fraction":seal_refund_fraction,
        "judgement_stunned_multiplier":judgement_stunned_multiplier if use_command else 1.0,
    }


def _incoming(level:int,t:Talents,gear:GearSetup,pull_size:int,aura:str,focus:dict) -> dict:
    devotion=latest(DEVOTION_AURA,level)
    devotion_armor=float(devotion[1]) if aura=="devotion" and devotion else 0.0
    item_armor=gear.item_armor*(1+_toughness_item_armor_pct(t))
    armor=item_armor+gear.shield_armor+devotion_armor
    defense_skill=anticipation_defense_bonus(t.anticipation)+max(0.0,float(gear.defense_bonus))
    base_avoid=.08+.01*t.deflection+defense_avoidance(t.anticipation,gear.defense_bonus)
    base_avoid=max(.04,min(.35,base_avoid))

    fixture=mob_fixture_snapshot(level)
    rows=fixture["rows"]
    # First compute attack frequency without block; Redoubt uptime depends on
    # how often damaging melee swings arrive, not on one arbitrary 2.0s mob.
    landed_swings_per_mob=sum(
        float(r["combined_weight"])*(1-base_avoid)/max(.1,float(r["swing_s"]))
        for r in rows
    )
    initial_swings=landed_swings_per_mob*pull_size
    block_chance=0.0
    block_value=0.0
    if gear.has_shield:
        block_chance=.05+defense_block_chance(defense_skill,has_shield=True)+expected_redoubt_bonus_block(t.redoubt,initial_swings)
        block_chance=max(0.0,min(.45,block_chance))
        block_value=gear.shield_block_value*(1+.10*t.shield_specialization)

    righteous_mult=max(.70,1-.02*t.improved_righteous_fury)
    damage_per_mob=0.0
    weighted_raw_dps=0.0
    weighted_reduction=0.0
    hit_event_weight=0.0
    hit_sum=0.0
    hit_second=0.0
    post_block_hit_sum=0.0
    sigma_second=0.0
    resolved=[]
    for r in rows:
        w=float(r["combined_weight"])
        mob_level=int(r["mob_level"])
        swing=max(.1,float(r["swing_s"]))
        raw_dps=float(r["raw_dps"])
        reduction=armor_reduction(armor,mob_level)
        raw_hit=raw_dps*swing
        mitigated_hit=raw_hit*(1-reduction)
        landed_rate=(1-base_avoid)/swing
        post_block=max(0.0,mitigated_hit-block_chance*block_value)
        dps=landed_rate*post_block*righteous_mult
        damage_per_mob+=w*dps
        weighted_raw_dps+=w*raw_dps
        weighted_reduction+=w*reduction
        ew=w*landed_rate
        hit_event_weight+=ew
        hit_sum+=ew*mitigated_hit
        hit_second+=ew*mitigated_hit*mitigated_hit
        post_block_hit_sum+=ew*post_block*righteous_mult
        sigma=float(r.get("damage_sigma_fraction",.35))*mitigated_hit
        sigma_second+=ew*sigma*sigma
        resolved.append({**r,"armor_reduction":reduction,"mitigated_hit":mitigated_hit,"landed_swings_per_s":landed_rate})

    mean_hit=hit_sum/max(1e-9,hit_event_weight)
    mean_post_block_hit=post_block_hit_sum/max(1e-9,hit_event_weight)
    hit_var=max(0.0,hit_second/max(1e-9,hit_event_weight)-mean_hit*mean_hit)
    intrinsic_var=sigma_second/max(1e-9,hit_event_weight)
    per_swing_sigma=math.sqrt(max(0.0,hit_var+intrinsic_var))

    # Seal of Fury's absorb shield is generated by successful own melee swings.
    fury_absorb_ps=0.0
    fury_absorb_per_shield=0.0
    fury_shields_per_s=0.0
    if focus.get("fury") and gear.has_shield:
        # Seal of Fury: every successful melee hit grants an absorb equal to 50%
        # of the Holy damage dealt by the Seal. Keep generation separate from
        # consumption so Improved Seal of Fury only returns mana when incoming
        # damage actually breaks the shield.
        fury_absorb_fraction=default_rules().spell_family_value(
            "paladin", "seal_of_fury", "damage_absorb_fraction", target="shield"
        )
        fury_absorb_per_shield=max(0.0,float(focus.get("seal_hit",focus["fury"][2]))*fury_absorb_fraction)
        fury_shields_per_s=(1.0/gear.weapon_speed)*focus["hit"]
        fury_absorb_ps=fury_shields_per_s*fury_absorb_per_shield  # stacking upper bound only
    return {
        "armor":armor,"armor_reduction":weighted_reduction,"avoidance":base_avoid,"defense_skill_bonus":defense_skill,"hit_damage":mean_hit,
        "per_swing_sigma":per_swing_sigma,"post_block_hit_damage":mean_post_block_hit,
        "block_chance":block_chance,"block_value":block_value,
        "landed_swings_per_mob":landed_swings_per_mob,
        "damage_per_mob":max(0.1,damage_per_mob),"raw_dps_per_mob":weighted_raw_dps,
        "fury_absorb_ps":fury_absorb_ps,
        "fury_absorb_per_shield":fury_absorb_per_shield,
        "fury_shields_per_s":fury_shields_per_s,
        "mob_fixture":{**fixture,"rows":resolved},
    }


def _aoe_dps(level:int,t:Talents,gear:GearSetup,pull_size:int,aura:str,focus:dict,policy:PriorityPolicy,incoming:dict) -> tuple[float,float,float]:
    # Return (aura_dps_per_alive_mob, consecration_dps_per_alive_mob, consecration_mps)
    ret=latest(RETRIBUTION_AURA,level)
    aura_dps=0.0
    if aura=="retribution" and ret:
        aura_dps=float(ret[1])*incoming["landed_swings_per_mob"]*focus["holy_mult"]
    con=latest(CONSECRATION,level)
    con_dps=con_mps=0.0
    if con and pull_size>=policy.consecration_min_mobs:
        base_total=float(con[2])
        first4_share=min(4,int(pull_size))/max(1.0,float(pull_size))
        sp_total=gear.spell_damage_bonus*(_family_sp_coeff("consecration", "first4_tick")*8.0)*first4_share
        per_target=(base_total+sp_total)/8.0*focus["holy_mult"]
        con_dps=per_target
        cost=float(con[1])*max(.20,1-.20*t.holy_conduit)*focus["instant_cost_mult"]
        con_mps=cost/8.0
    return aura_dps,con_dps,con_mps


def _paladin_mana_regen_decomposition(level:int, spirit_bonus:float=0.0, mp5_bonus:float=0.0) -> dict:
    """Out-of-5SR Paladin mana regeneration, base stats separated from gear."""
    base=float(base_spirit("paladin",level,race="undead"))
    item=max(0.0,float(spirit_bonus))
    base_regen=7.5
    spirit_regen=.1*(base+item)
    mp5_regen=max(0.0,float(mp5_bonus))/5.0
    return {
        "race":"undead", "base_spirit":base, "item_spirit":item,
        "total_spirit":base+item, "base_mana_regen_per_s":base_regen,
        "spirit_bonus":item, "spirit_recovery_mps":spirit_regen,
        "mp5_bonus":max(0.0,float(mp5_bonus)), "mp5_recovery_mps":mp5_regen,
        "passive_mana_regen_per_s":base_regen+spirit_regen+mp5_regen,
        "base_stat_authority_id":BASE_STAT_AUTHORITY_ID,
        "base_stat_provenance":spirit_provenance("paladin",level,race="undead"),
    }


def _recovery(level:int,hp_missing:float,mana_missing:float,mana_pool:float,heal:dict,
              spirit_bonus:float=0.0,mp5_bonus:float=0.0) -> tuple[float,str,dict]:
    """Shared full-resource recovery contract.

    Recovery timing uses the same level-appropriate ordinary food/water baseline
    as every Forever class. Paladin supplies class/race base Spirit, item Spirit
    and flat MP5 to the shared solver; no class-private sit-recovery math exists.
    """
    options=()
    if heal.get("heal",0.0)>0:
        options=(HealOption(str(heal.get("name","heal")),float(heal["heal"]),float(heal["mana"]),float(heal["cast"])),)
    regen=_paladin_mana_regen_decomposition(level,spirit_bonus,mp5_bonus)
    r=solve_recovery(
        level,hp_missing,mana_missing,options,
        passive_mana_regen_per_s=float(regen["passive_mana_regen_per_s"]),
    )
    return r.total_s,r.method,{
        "food_s":r.food_s,"water_s":r.water_s,"heal_cast_s":r.heal_cast_s,
        "recovery_heal_casts":r.heal_casts,"recovery_heal_name":r.heal_name,
        "food_tier":r.food_tier,"water_tier":r.water_tier,**regen,
    }


def _mana_plan_rows(focus:dict, con_dps:float, con_mps:float):
    """Yield canonical cadence plans from aggressive to conservative.

    No spell-order permutations are searched.  A plan only changes how often a
    priority ability is allowed to fire when resource pressure makes full cadence
    unattractive.
    """
    for plan in MANA_PLANS:
        hs_f=ManaPlan.factor(plan.holy_strike_every)
        j_f=ManaPlan.factor(plan.judgement_every)
        c_f=ManaPlan.factor(plan.consecration_every) if con_dps>0 else 0.0
        focus_dps=(focus["white_seal_dps"] + focus["hs_dps"]*hs_f + focus["judgement_dps"]*j_f)
        damage_mps=(focus["hs_dps"]*0.0 +
                    (focus["hs_cost"]/max(.1,focus["hs_cd"]))*hs_f +
                    (focus.get("judgement_net_cost",focus["judgement_cost"])/max(.1,focus["judgement_cd"]))*j_f +
                    con_mps*c_f)
        yield {
            "plan": plan,
            "focus_dps": focus_dps,
            "con_factor": c_f,
            "damage_mps": damage_mps,
            "hs_factor": hs_f,
            "judgement_factor": j_f,
        }


def _emergency_windows(level:int,t:Talents,policy:PriorityPolicy,avg_alive:float) -> tuple[tuple[str,float,float,float,float], ...]:
    """Fast emergency windows with pack-aware suppression and real cooldowns.

    The fifth field is residual incoming damage as a multiplier of pack-wide
    incoming while the utility is active.  HoJ stuns exactly one target; BoP and
    Divine Protection suppress physical incoming pack-wide.
    """
    rows=[]
    if policy.use_hoj_if_behind:
        r=latest(HAMMER_OF_JUSTICE,level)
        if r:
            active=max(1.0,float(avg_alive))
            residual=max(0.0,(active-1.0)/active)
            cd=max(0.0,float(r[3])-5.0*int(t.improved_hammer_of_justice))
            rows.append(("Hammer of Justice",float(r[2]),float(r[1]),cd,residual))
    if policy.use_immunity_if_critical:
        candidates=[]
        for name,table in (("Blessing of Protection",BLESSING_OF_PROTECTION),("Divine Protection",DIVINE_PROTECTION)):
            r=latest(table,level)
            if not r:
                continue
            if name=="Blessing of Protection":
                cd=max(0.0,float(r[3])-60.0*int(t.guardians_favor))
            else:
                cd=max(0.0,float(r[3])-30.0*int(t.sacred_duty))
            candidates.append((name,float(r[2]),float(r[1]),cd,0.0))
        if candidates:
            # Prefer the longest safe healing window.  At equal duration the
            # sustainable leveling choice is the shorter repeat cooldown, then
            # the lower mana cost.  This makes Guardian's Favor / Sacred Duty
            # matter to the same cooldown-floor objective they modify.
            rows.append(max(candidates,key=lambda x:(x[1],-x[3],-x[2])))
    return tuple(rows)


def _discrete_damage_kill_s(pack_hp:float,smooth_kill_s:float,avg_alive:float,
                            cadence:dict|None) -> float:
    """Deterministic outgoing packet scheduler for the Fast Paladin bound.

    Autos run on their own weapon timer and are never delayed by the GCD.
    Active abilities share the same decision/GCD ordering as the event replay:
    Seal maintenance -> Consecration -> Judgement (0 GCD) -> Holy Strike.
    Consecration deals eight one-second ticks to mobs still alive at each tick.

    ``pack_hp`` is retained for the public helper/test contract; callers may
    provide ``hp_per_mob``/``pull_size`` in cadence for exact equal-mob packs.
    """
    if not cadence:
        return float(smooth_kill_s)
    import heapq
    n=max(1,int(cadence.get("pull_size",1)))
    hp_each=float(cadence.get("hp_per_mob", float(pack_hp)/n))
    mobs=[hp_each for _ in range(n)]
    con_min=max(1,int(cadence.get("consecration_min_mobs",1)))
    horizon=max(30.0,float(smooth_kill_s)*3.0+10.0)
    q=[]; seq=0
    def push(t,kind,damage=0.0):
        nonlocal seq
        if t<=horizon+1e-9:
            heapq.heappush(q,(float(t),seq,kind,float(damage))); seq+=1
    def alive(): return sum(1 for x in mobs if x>1e-9)
    def focus(dmg):
        for i,x in enumerate(mobs):
            if x>1e-9:
                mobs[i]=max(0.0,x-dmg); return
    def even(per_target):
        for i,x in enumerate(mobs):
            if x>1e-9: mobs[i]=max(0.0,x-per_target)

    auto_p=float(cadence.get("auto_period",0.0)); auto_d=float(cadence.get("auto_damage",0.0))
    if auto_p>0 and auto_d>0: push(float(cadence.get("auto_first",auto_p)),"auto",auto_d)
    aura_p=float(cadence.get("aura_period",0.0)); aura_d=float(cadence.get("aura_damage",0.0))
    if aura_p>0 and aura_d>0: push(float(cadence.get("aura_first",aura_p)),"aura",aura_d)
    push(0.0,"decision")
    gcd_ready=0.0; seal_expires=0.0; con_ready=0.0; judge_ready=0.0; hs_ready=0.0
    seal_duration=float(cadence.get("seal_duration_s",30.0)); gcd=float(cadence.get("gcd_s",1.5))
    con_period=float(cadence.get("consecration_period",0.0)); con_tick=float(cadence.get("consecration_tick_damage",0.0))
    judge_period=float(cadence.get("judgement_period",0.0)); judge_damage=float(cadence.get("judgement_damage",0.0))
    hs_period=float(cadence.get("holy_strike_period",0.0)); hs_damage=float(cadence.get("holy_strike_damage",0.0))

    while q and alive()>0:
        t,_,kind,damage=heapq.heappop(q)
        if kind=="auto":
            focus(damage); push(t+auto_p,"auto",damage)
        elif kind=="aura":
            even(damage); push(t+aura_p,"aura",damage)
        elif kind=="con_tick":
            even(damage)
        elif kind=="decision":
            if t<gcd_ready-1e-9:
                push(gcd_ready,"decision"); continue
            # Canonical event-replay priority. Autos continue independently.
            if seal_expires<=t+1e-9:
                seal_expires=t+seal_duration; gcd_ready=t+gcd; push(gcd_ready,"decision"); continue
            if con_period>0 and con_tick>0 and alive()>=con_min and t>=con_ready-1e-9:
                con_ready=t+con_period; gcd_ready=t+gcd
                for tick in range(1,9): push(t+tick,"con_tick",con_tick)
                push(gcd_ready,"decision"); continue
            if judge_period>0 and judge_damage>0 and t>=judge_ready-1e-9:
                focus(judge_damage); judge_ready=t+judge_period
                # Judgement is 0-GCD: another decision may happen immediately.
                push(t,"decision"); continue
            if hs_period>0 and hs_damage>0 and t>=hs_ready-1e-9:
                focus(hs_damage); hs_ready=t+hs_period; gcd_ready=t+gcd; push(gcd_ready,"decision"); continue
            nxt=[x for x in (seal_expires,con_ready if con_period>0 else 1e99,judge_ready if judge_period>0 else 1e99,hs_ready if hs_period>0 else 1e99) if x>t+1e-9]
            if nxt: push(min(nxt),"decision")
        if alive()==0:
            return max(float(smooth_kill_s),float(t))
    return float(smooth_kill_s)


def _pack_damage_geometry(level:int,pull_size:int,focus_dps:float,aura_dps:float,
                          con_dps:float,con_factor:float,cadence:dict|None=None) -> dict:
    """Cheap deterministic damage geometry shared by plan bound + replay.

    This contains no survival/recovery assumptions.  ``base_kill_s + travel`` is
    therefore an optimistic lower bound for a cadence plan's cycle time and can
    be used for proof-safe branch-and-bound pruning.
    """
    n=max(1,int(pull_size))
    hp_per_mob=leveling.representative_hp(level)
    c_factor=float(con_factor)
    exposure=estimate_pack_exposure(
        n, float(focus_dps), float(aura_dps)+float(con_dps)*c_factor
    )
    avg_alive=float(exposure.avg_alive)
    background_per_target=float(aura_dps)+float(con_dps)*c_factor
    pack_dps=max(.1,float(focus_dps)+background_per_target*avg_alive)
    smooth_base_kill_s=hp_per_mob*n/pack_dps
    base_kill_s=_discrete_damage_kill_s(hp_per_mob*n,smooth_base_kill_s,avg_alive,cadence)
    first_target_dps=max(.1,float(focus_dps)+background_per_target)
    smooth_first_kill_s=hp_per_mob/first_target_dps
    first_kill_s=_discrete_damage_kill_s(hp_per_mob,smooth_first_kill_s,1.0,cadence)
    return {
        "avg_alive":avg_alive,
        "peak_alive":float(exposure.peak_alive),
        "sequential_avg_alive":float(exposure.sequential_avg_alive),
        "aoe_fraction":float(exposure.aoe_fraction),
        "pack_dps":pack_dps,
        "base_kill_s":base_kill_s,
        "first_kill_s":first_kill_s,
        "smooth_first_kill_s":smooth_first_kill_s,
        "smooth_base_kill_s":smooth_base_kill_s,
        "damage_cadence_quantized":base_kill_s>smooth_base_kill_s+1e-9,
        "hp_per_mob":hp_per_mob,
    }


def _score_one_mana_plan(level:int,t:Talents,profile:str,gear:GearSetup,pull_size:int,
                         policy:PriorityPolicy,aura:str,focus:dict,incoming:dict,
                         aura_dps:float,con_dps:float,con_mps:float,plan_row:dict,
                         start_hp:float,static:dict|None=None,geometry:dict|None=None) -> dict:
    n=max(1,int(pull_size))
    if static is None:
        player_hp=player_base_hp(level,gear.stamina_bonus)*(1+.02*t.sacred_duty)
        mana_pool=(180.0+18.0*level+15.0*gear.intellect_bonus)*(1+.02*t.divine_intellect)
        static={
            "hp_per_mob":leveling.representative_hp(level),
            "player_hp":player_hp,
            "mana_pool":mana_pool,
            "heal":_heal_model(level,t,gear,incoming["landed_swings_per_mob"]*n),
            "recovery_heal":_heal_model(level,t,gear,0.0),
            "gear_stats":gear_snapshot(gear),
            "travel_s":between_pull_travel_s(speed_multiplier=1+.04*t.pursuit_of_justice),
        }
    hp_per_mob=float(static["hp_per_mob"])
    player_hp=float(static["player_hp"])
    mana_pool=float(static["mana_pool"])
    heal=static["heal"]
    recovery_heal=static.get("recovery_heal",heal)

    c_factor=float(plan_row["con_factor"])
    geometry=geometry or _pack_damage_geometry(level,n,float(plan_row["focus_dps"]),aura_dps,con_dps,c_factor)
    avg_alive=float(geometry["avg_alive"])
    pack_dps=float(geometry["pack_dps"])
    base_kill_s=float(geometry["base_kill_s"])

    peak_alive=float(geometry.get("peak_alive",n))
    pre_fury_incoming_avg=incoming["damage_per_mob"]*avg_alive
    pre_fury_incoming_peak=incoming["damage_per_mob"]*peak_alive
    fury_dyn={"break_rate":0.0,"absorb_per_s":0.0,"hits_needed":0,"full_break_probability":0.0}
    fury_peak={"break_rate":0.0,"absorb_per_s":0.0,"hits_needed":0,"full_break_probability":0.0}
    if gear.has_shield and focus.get("fury"):
        fury_dyn=replacing_absorb_dynamics(
            incoming.get("fury_shields_per_s",0.0),
            incoming["landed_swings_per_mob"]*avg_alive,
            incoming.get("fury_absorb_per_shield",0.0),
            incoming.get("post_block_hit_damage",incoming.get("hit_damage",1.0)),
        )
        fury_peak=replacing_absorb_dynamics(
            incoming.get("fury_shields_per_s",0.0),
            incoming["landed_swings_per_mob"]*peak_alive,
            incoming.get("fury_absorb_per_shield",0.0),
            incoming.get("post_block_hit_damage",incoming.get("hit_damage",1.0)),
        )
    incoming_dps=max(0.0,pre_fury_incoming_avg-fury_dyn["absorb_per_s"])
    peak_incoming_dps=max(0.0,pre_fury_incoming_peak-fury_peak["absorb_per_s"])

    min_hp=player_hp*policy.min_hp_fraction
    safe_damage_budget=max(0.0,start_hp-min_hp)
    expected_damage=incoming_dps*base_kill_s
    expected_landed_swings=incoming["landed_swings_per_mob"]*avg_alive*base_kill_s
    per_swing_sigma=max(1.0,float(incoming.get("per_swing_sigma",.35*max(1.0,incoming["hit_damage"]))))
    damage_sigma=math.sqrt(max(0.0,expected_landed_swings))*per_swing_sigma
    risk_buffer=policy.risk_sigma*damage_sigma
    need=max(0.0,expected_damage+risk_buffer-safe_damage_budget)

    # Full-pack pressure bound until the first mob dies.  Total recovery uses
    # average exposure, but a 4-pack cannot borrow future lower pressure to
    # survive the opening window while all four attackers are still alive.
    first_kill_s=float(geometry.get("first_kill_s",base_kill_s))
    peak_window_swings=incoming["landed_swings_per_mob"]*peak_alive*first_kill_s
    peak_window_sigma=math.sqrt(max(0.0,peak_window_swings))*per_swing_sigma
    peak_window_risk=policy.risk_sigma*peak_window_sigma
    peak_window_damage=peak_incoming_dps*first_kill_s
    peak_window_need=max(0.0,peak_window_damage+peak_window_risk-safe_damage_budget)
    need=max(need,peak_window_need)

    heals=discrete_heal_sequence(
        need_hp=need,heal_amount=heal["heal"],cast_s=heal["cast"],mana_cost=heal["mana"],
        incoming_dps=peak_incoming_dps,start_hp=start_hp,min_hp=min_hp,
        emergency_windows=_emergency_windows(level,t,policy,peak_alive),
    )
    if not heals.get("feasible"):
        return {
            "total_s":1e9,"kill_s":1e9,"recovery_s":1e9,"travel_s":0.0,
            "dps":pack_dps,"mana_spent_per_mob":0.0,"profile":profile,
            "rotation":"infeasible pack","approximation_flags":["survival infeasible",str(heals.get("reason",""))],
            "pull_size":n,"gear":gear.name,"gear_stats":static["gear_stats"],"policy":policy.name,"aura":aura,
            "feasible":False,"mobs_per_hour":0.0,
        }

    heal_time=float(heals["heal_time_s"])+float(heals.get("emergency_gcd_s",0.0))
    heal_mana=float(heals["heal_mana"])+float(heals.get("emergency_mana",0.0))
    combat_s=base_kill_s+heal_time

    # Damage-resource cadence is discrete at the policy level (every cooldown,
    # every second cooldown, or skipped) while still using expected-value timing.
    damage_mana=float(plan_row["damage_mps"])*base_kill_s
    initial_seal=float(focus.get("seal_cost",0.0))
    seal_duration=max(.1,float(focus.get("seal_duration_s",30.0)))
    seal_refreshes=max(0,int(math.ceil(max(0.0,combat_s-1e-9)/seal_duration))-1)
    seal_maintenance_mana=initial_seal*(1+seal_refreshes)
    mana_spent=damage_mana+seal_maintenance_mana+heal_mana

    mana_return=0.0
    # Flat MP5 is true in-combat mana regeneration; one point of MP5 is
    # 0.2 mana/s and therefore directly reduces the pack's net mana deficit.
    mp5_combat_return=max(0.0,float(gear.mp5_bonus))/5.0*combat_s
    mana_return+=mp5_combat_return
    proc_rate=0.0
    if gear.has_shield and t.shield_specialization:
        blocks_ps=incoming["landed_swings_per_mob"]*avg_alive*incoming["block_chance"]
        rank=max(0,min(3,int(t.shield_specialization)))
        proc_chance=(0.0,.33,.66,1.0)[rank]
        proc_rate=expected_icd_proc_rate(blocks_ps,proc_chance,3.0)
        mana_return+=proc_rate*.06*mana_pool*combat_s
    if gear.has_shield and focus.get("fury") and t.improved_seal_of_fury:
        break_rate=float(fury_dyn.get("break_rate",0.0))
        mana_per_break=60.0*(1.0+.225)
        mana_return+=mana_per_break*break_rate*combat_s
    net_mana=mana_spent-mana_return

    # Peak-deficit proxy: returns accrue through combat, while Seal + emergency
    # actions and heals are chunky costs.  This gives a real minimum starting
    # mana requirement instead of assuming every pull begins at full mana.
    return_rate=mana_return/max(.1,combat_s)
    damage_net=max(0.0,(float(plan_row["damage_mps"])-return_rate)*base_kill_s)
    peak_deficit=max(initial_seal,initial_seal+damage_net+heal_mana)
    reserve=mana_pool*policy.mana_reserve_fraction
    start_mana_required=peak_deficit+reserve
    if start_mana_required>mana_pool+1e-9:
        return {
            "total_s":1e9,"kill_s":1e9,"recovery_s":1e9,"travel_s":0.0,
            "dps":pack_dps,"mana_spent_per_mob":max(0.0,net_mana)/n,"profile":profile,
            "rotation":"infeasible mana plan","approximation_flags":["mana peak infeasible"],
            "pull_size":n,"gear":gear.name,"gear_stats":static["gear_stats"],"policy":policy.name,"aura":aura,
            "feasible":False,"mobs_per_hour":0.0,
        }
    mana_positive=net_mana<=0.0
    # Shared recovery contract: every pack starts full and recovery pays the
    # complete deficit back to 100% before the next pull.
    start_mana=mana_pool
    end_mana=min(mana_pool,max(0.0,start_mana-net_mana))
    mana_missing=max(0.0,mana_pool-end_mana)

    total_damage=max(0.0,
        incoming_dps*base_kill_s + peak_incoming_dps*heal_time
        - float(heals.get("emergency_avoided_damage",0.0))
    )
    total_heal=float(heals.get("total_heal",0.0))
    end_hp=max(min_hp,min(player_hp,start_hp-total_damage+total_heal))
    next_start_hp=player_hp
    hp_missing=max(0.0,player_hp-end_hp)
    recovery_s,recovery_method,recovery_detail=_recovery(
        level,hp_missing,mana_missing,mana_pool,recovery_heal,
        gear.spirit_bonus,gear.mp5_bonus,
    )

    travel_s=float(static["travel_s"])
    base_cycle=combat_s+recovery_s+travel_s
    cooldown_floor=float(heals.get("cooldown_floor_s",0.0))
    cycle_s=max(base_cycle,cooldown_floor)
    cooldown_wait_s=max(0.0,cycle_s-base_cycle)
    per100=100.0/n

    plan=plan_row["plan"]
    actions=[f"{focus['seal_name']} up"]
    if c_factor>0: actions.append(f"Consecration (baseline L20) every {plan.consecration_every} CD" if plan.consecration_every>1 else "Consecration (baseline L20) on CD while pack >= threshold")
    if plan.judgement_every>0: actions.append(f"Judgement every {plan.judgement_every} CD" if plan.judgement_every>1 else "Judgement on CD")
    if plan.holy_strike_every>0: actions.append(f"Holy Strike every {plan.holy_strike_every} CD" if plan.holy_strike_every>1 else "Holy Strike on CD")
    actions.append("melee weave")
    if heals.get("casts",0):
        actions.append("heal if behind")
        actions.append(f"{heal['name']} x{int(heals['casts'])}")
    actions.extend(list(heals.get("emergency_actions") or []))
    rotation="; ".join(actions)
    flags=[
        "experimental deterministic pack policy",
        "shared full-HP/full-Mana recovery contract",
        "whole-cast healing / discrete emergency actions",
        "canonical mana cadence plans; no GCD permutation search",
        "Forever craft-calibrated normal gear floor; not BIS ownership",
        f"gear curve provenance: {gear_curve_status(level)}",
        "crafted Defense Rating persisted in gear snapshot but not converted to avoidance pending verified rating conversion",
                "same-level world-mob swing-family fixture",
        "expected-value incoming melee / block model",
        "shared pack exposure: average damage bookkeeping + full-pack peak heal-pressure bound",
        "Shield Specialization exact 3s ICD expected-renewal model",
        "Seal of Fury single-shield replacement semantics provisional",
    ]
    return {
        "total_s":per100*cycle_s,"kill_s":per100*combat_s,"recovery_s":per100*(recovery_s+cooldown_wait_s),
        "travel_s":per100*travel_s,"dps":pack_dps,"mana_spent_per_mob":max(0.0,net_mana)/n,
        "profile":profile,"rotation":rotation,"approximation_flags":flags,
        "pull_size":n,"gear":gear.name,"weapon_style":gear.weapon_style,"gear_stats":static["gear_stats"],
        "policy":policy.name,"aura":aura,"feasible":True,"mobs_per_hour":3600.0*n/max(.1,cycle_s),
        "cycle_s":cycle_s,"combat_s_per_pack":combat_s,"recovery_s_per_pack":recovery_s,"recovery_solver_id":RECOVERY_SOLVER_ID,
        "cooldown_wait_s_per_pack":cooldown_wait_s,"recovery_method":recovery_method,
        **recovery_detail,
        "player_hp":player_hp,"start_hp":start_hp,"next_start_hp":next_start_hp,"min_hp":min_hp,"end_hp":end_hp,
        "mana_pool":mana_pool,"start_mana":start_mana,"end_mana":end_mana,"mana_positive":mana_positive,
        "mana_peak_deficit":peak_deficit,"mana_recovery_needed":mana_missing,"mana_plan":plan.name,
        "net_mana_per_pack":net_mana,"mp5_combat_return":mp5_combat_return,
        "holy_strike_every":plan.holy_strike_every,"judgement_every":plan.judgement_every,
        "consecration_every":plan.consecration_every,
        "incoming_dps":incoming_dps,"peak_incoming_dps":peak_incoming_dps,
        "avg_alive_mobs":avg_alive,"peak_alive_mobs":peak_alive,"armor":incoming["armor"],
        "aura_dps_per_alive_mob":aura_dps,"aura_total_dps":aura_dps*avg_alive,
        "consecration_dps_per_alive_mob":con_dps*c_factor,
        "armor_reduction":incoming["armor_reduction"],"block_chance":incoming["block_chance"],
        "block_value":incoming["block_value"],"mob_raw_dps_per_mob":incoming["raw_dps_per_mob"],
        "mob_landed_swings_per_s":incoming["landed_swings_per_mob"],
        "mob_weighted_swing_s":incoming["mob_fixture"]["weighted_family_swing_s"],"mob_fixture":incoming["mob_fixture"],
        "seal_refreshes":seal_refreshes,"seal_maintenance_mana":seal_maintenance_mana,
        "sanctified_judgement_refund_fraction":focus.get("sanctified_judgement_refund_fraction",0.0),
        "fury_absorb_per_s":fury_dyn.get("absorb_per_s",0.0),"fury_break_rate":fury_dyn.get("break_rate",0.0),
        "fury_hits_needed":fury_dyn.get("hits_needed",0),"shield_spec_proc_rate":proc_rate,
        "heal_spell":heal["name"],"heal_casts":int(heals.get("casts",0)),"heal_time_s":float(heals.get("heal_time_s",0.0)),
        "emergency_actions":list(heals.get("emergency_actions") or []),"panic_dependent":bool(heals.get("emergency_actions")),
        "damage_sigma":damage_sigma,"risk_buffer_hp":risk_buffer,"risk_sigma":policy.risk_sigma,
        "first_kill_s":first_kill_s,"peak_window_damage":peak_window_damage,
        "peak_window_sigma":peak_window_sigma,"peak_window_risk_buffer_hp":peak_window_risk,
        "peak_window_need_hp":peak_window_need,
        "risk_adjusted_end_hp":end_hp-risk_buffer,"representative_mob_hp":hp_per_mob,
        "physical_hit":focus["hit"],"crit":focus["crit"],
        "smooth_base_kill_s":float(geometry.get("smooth_base_kill_s",base_kill_s)),
        "damage_cadence_quantized":bool(geometry.get("damage_cadence_quantized",False)),
    }


def smooth_pack_score(level:int,t:Talents,profile:str,gear:GearSetup,pull_size:int,policy:PriorityPolicy,aura:str,
                      _focus:dict|None=None,_incoming_row:dict|None=None) -> dict:
    """Best deterministic sustainable pack policy for a fixed strategic setup.

    Performance note: every mana plan shares the same gear/incoming/heal/static
    context.  Those values are computed once here.  Plans are branch-and-bound
    by a proof-safe zero-recovery throughput ceiling; no semantics are changed.
    """
    level=int(level); n=max(1,int(pull_size))
    focus=_focus if _focus is not None else _base_damage(level,t,gear,profile)
    incoming=_incoming_row if _incoming_row is not None else _incoming(level,t,gear,n,aura,focus)
    aura_dps,con_dps,con_mps=_aoe_dps(level,t,gear,n,aura,focus,policy,incoming)

    player_hp=player_base_hp(level,gear.stamina_bonus)*(1+.02*t.sacred_duty)
    mana_pool=(180.0+18.0*level+15.0*gear.intellect_bonus)*(1+.02*t.divine_intellect)
    start_hp=player_hp
    static={
        "hp_per_mob":leveling.representative_hp(level),
        "player_hp":player_hp,
        "mana_pool":mana_pool,
        "heal":_heal_model(level,t,gear,incoming["landed_swings_per_mob"]*n),
        "recovery_heal":_heal_model(level,t,gear,0.0),
        "gear_stats":gear_snapshot(gear),
        "travel_s":between_pull_travel_s(speed_multiplier=1+.04*t.pursuit_of_justice),
    }

    plan_candidates=[]
    for idx,plan_row in enumerate(_mana_plan_rows(focus,con_dps,con_mps)):
        plan=plan_row["plan"]
        hs_every=int(plan.holy_strike_every)
        judge_every=int(plan.judgement_every)
        con_every=int(plan.consecration_every)
        cadence={
            "auto_first":float(gear.weapon_speed),
            "auto_period":float(gear.weapon_speed),
            "auto_damage":float(focus["white_seal_dps"])*float(gear.weapon_speed),
            "holy_strike_first":1.5,
            "holy_strike_period":float(focus["hs_cd"])*hs_every if hs_every>0 else 0.0,
            "holy_strike_damage":float(focus["hs_dps"])*float(focus["hs_cd"]) if hs_every>0 else 0.0,
            "judgement_first":3.0,
            "judgement_period":float(focus["judgement_cd"])*judge_every if judge_every>0 else 0.0,
            "judgement_damage":float(focus["judgement_dps"])*float(focus["judgement_cd"]) if judge_every>0 else 0.0,
            "consecration_first":1.5,
            "consecration_period":float(8*con_every) if con_every>0 and con_dps>0 else 0.0,
            "consecration_damage":float(con_dps)*8.0 if con_every>0 else 0.0,
            "consecration_tick_damage":float(con_dps) if con_every>0 else 0.0,
            "consecration_min_mobs":int(policy.consecration_min_mobs),
            "seal_duration_s":float(focus.get("seal_duration_s",30.0)),
            "gcd_s":1.5,
            "pull_size":n,
            "hp_per_mob":float(leveling.representative_hp(level)),
            "aura_first":float(incoming["mob_fixture"]["weighted_family_swing_s"]),
            "aura_period":float(incoming["mob_fixture"]["weighted_family_swing_s"]),
            "aura_damage":float(aura_dps)*float(incoming["mob_fixture"]["weighted_family_swing_s"]),
        }
        geometry=_pack_damage_geometry(level,n,float(plan_row["focus_dps"]),aura_dps,con_dps,float(plan_row["con_factor"]),cadence)
        ideal_cycle=max(.1,float(geometry["base_kill_s"])+float(static["travel_s"]))
        upper_mph=3600.0*n/ideal_cycle
        plan_candidates.append((upper_mph,idx,plan_row,geometry))
    # Best bound first makes the later skip effective while preserving the
    # original MANA_PLANS index as the deterministic tie-break.
    plan_candidates.sort(key=lambda x:(-x[0],x[1]))

    evaluated=[]
    best_mph=-1.0
    for upper_mph,idx,plan_row,geometry in plan_candidates:
        if best_mph>=0.0 and upper_mph < best_mph-1e-12:
            continue
        row=_score_one_mana_plan(level,t,profile,gear,n,policy,aura,focus,incoming,
                                 aura_dps,con_dps,con_mps,plan_row,start_hp,static,geometry)
        evaluated.append((idx,row))
        if row.get("feasible"):
            best_mph=max(best_mph,float(row.get("mobs_per_hour",0.0)))

    if evaluated:
        feasible=[x for x in evaluated if x[1].get("feasible")]
        pool=feasible or evaluated
        # Preserve old semantics: total time first, panic dependence second,
        # original canonical mana-plan order as the final tie-break.
        return min(pool,key=lambda x:(x[1]["total_s"],x[1].get("panic_dependent",False),x[0]))[1]
    return {
        "total_s":1e9,"kill_s":1e9,"recovery_s":1e9,"travel_s":0.0,
        "dps":0.0,"mana_spent_per_mob":0.0,"profile":profile,"rotation":"infeasible pack",
        "approximation_flags":["no feasible mana/survival plan"],"pull_size":n,"gear":gear.name,
        "gear_stats":static["gear_stats"],"policy":policy.name,"aura":aura,"feasible":False,"mobs_per_hour":0.0,
    }


def _profile_gears(level:int, profile:str):
    """Return equipment styles that are mechanically coherent for a profile.

    Forever Protection is deliberately allowed to level with a 2H before L20
    (matching the current guide guidance), but from L20 onward the Protection
    profile means the shield/Seal-of-Fury package is actually equipped.  This
    keeps ``profile=protection`` semantically useful instead of letting the
    generic optimizer silently turn it into a 2H Righteousness build.
    """
    rows=archetypes(int(level))
    if profile == "protection" and int(level) >= 20:
        shield=tuple(g for g in rows if g.has_shield)
        return shield or rows
    return rows


def _configurations(level:int,profile:str,t:Talents):
    # Weapon setup and survival aggressiveness are optimizer decisions within
    # the profile's mechanically coherent equipment envelope.  Protection is
    # free to use 2H before L20; from L20 its profile contract is shield + Fury.
    gears=_profile_gears(level,profile)
    policies=POLICIES
    max_pull=4 if level>=30 else 3
    auras=("devotion","retribution") if level>=16 else ("devotion",)
    for gear in gears:
        for n in range(1,max_pull+1):
            for policy in policies:
                for aura in auras:
                    yield gear,n,policy,aura


_MODELED_TALENT_FIELDS = (
    "anticipation","benediction","champion_of_the_light","conviction","crusade",
    "deflection","divine_intellect","divine_strength","healing_light","holy_conduit",
    "holy_power","improved_holy_strike","improved_judgement","improved_righteous_fury",
    "improved_seal_of_fury","improved_seals","one_handed_weapon_specialization",
    "precision","pursuit_of_justice","redoubt","sacred_arbiter","sacred_duty",
    "sanctified_judgement","seal_of_command","shield_specialization","spiritual_focus",
    "toughness","two_handed_weapon_specialization","vengeance",
)


def _mechanics_signature(t:Talents) -> tuple[int,...]:
    return tuple(int(getattr(t,name)) for name in _MODELED_TALENT_FIELDS)


def _talents_from_signature(sig:tuple[int,...]) -> Talents:
    return Talents(**dict(zip(_MODELED_TALENT_FIELDS,sig)))


def _score_rows_for_gear(level:int,t:Talents,profile:str,gear:GearSetup) -> list[dict]:
    """Score all gameplay configurations for one already-chosen gear point."""
    rows=[]
    max_pull=4 if int(level)>=30 else 3
    auras=("devotion","retribution") if int(level)>=16 else ("devotion",)
    focus=_base_damage(int(level),t,gear,profile)
    for n in range(1,max_pull+1):
        incoming_by_aura={a:_incoming(int(level),t,gear,n,a,focus) for a in auras}
        for policy in POLICIES:
            for aura in auras:
                rows.append(smooth_pack_score(int(level),t,profile,gear,n,policy,aura,
                                              _focus=focus,_incoming_row=incoming_by_aura[aura]))
    return rows


def _best_scored_row(rows:list[dict]) -> dict:
    feasible=[r for r in rows if r.get("feasible")]
    return min(feasible or rows,key=lambda r:(r["total_s"],r.get("panic_dependent",False),-r.get("pull_size",1)))


def _score_local_rerolled_gear(level:int,t:Talents,profile:str,gear:GearSetup,base_best:dict) -> list[dict]:
    """Validate an analytic gear reroll in the local gameplay neighborhood.

    The reroll itself is a local-gradient move, so repeating the entire policy ×
    pull × aura cartesian product would turn a cheap analytical gear layer back
    into a large discrete search.  Re-check the selected policy at the baseline
    pull and its immediate pull-size neighbors, allowing aura to re-optimize.
    The untouched baseline gear remains fully searched and is always retained.
    """
    max_pull=4 if int(level)>=30 else 3
    n0=max(1,min(max_pull,int(base_best.get("pull_size") or 1)))
    pulls=sorted({n for n in (n0-1,n0,n0+1) if 1<=n<=max_pull})
    auras=("devotion","retribution") if int(level)>=16 else ("devotion",)
    policy=_policy_by_name(base_best.get("policy"))
    focus=_base_damage(int(level),t,gear,profile)
    rows=[]
    for n in pulls:
        incoming_by_aura={a:_incoming(int(level),t,gear,n,a,focus) for a in auras}
        for aura in auras:
            rows.append(smooth_pack_score(int(level),t,profile,gear,n,policy,aura,
                                          _focus=focus,_incoming_row=incoming_by_aura[aura]))
    return rows


def _score_rows(level:int,t:Talents,profile:str) -> list[dict]:
    """Score each legal gear style at a bounded per-level gear/stat fixed point.

    For each talent candidate the backend repeatedly chooses best gameplay for
    the current gear, derives local stat values at that gameplay optimum, and
    rerolls every SQL-backed body/accessory slot.  The surrounding beam then
    compares talent candidates at their own converged gear point.
    """
    from src.v2.per_level_fixed_point import optimize_level_fixed_point

    rows=[]
    for initial_gear in _profile_gears(int(level),profile):
        # Preserve the unmodified full-search baseline in the candidate pool as
        # a safety net and for diagnostics.
        baseline_rows=_score_rows_for_gear(int(level),t,profile,initial_gear)
        rows.extend(baseline_rows)

        base_best=_best_scored_row(baseline_rows)
        anchor=[base_best]
        initial_sig=(initial_gear.name,tuple(initial_gear.selected_body_items or ()))

        def score_with_gear(gear):
            sig=(gear.name,tuple(gear.selected_body_items or ()))
            if sig == initial_sig and anchor[0] is base_best:
                return base_best
            local=_score_local_rerolled_gear(int(level),t,profile,gear,anchor[0])
            anchor[0]=_best_scored_row(local)
            return anchor[0]

        def weights_for(score):
            return analytic_stat_gradient(int(level),t,baseline=score,profile=profile)

        def select_gear(gear,values):
            return reroll_body_items(gear,int(level),values)

        def signature(gear):
            body=tuple(gear.selected_body_items or ())
            return (gear.name,body)

        try:
            fp=optimize_level_fixed_point(
                initial_gear=initial_gear, score_with_gear=score_with_gear,
                stat_weights=weights_for, select_gear=select_gear,
                gear_signature=signature, max_iters=3,
            )
            final=dict(fp.score)
            # Keep convergence diagnostics on the actual candidate row.
            final["gear_fixed_point"]=dict(final.get("gear_fixed_point") or {})
            rows.append(final)
        except Exception as exc:
            # Baseline rows above remain valid if the optional coordination layer
            # cannot improve this candidate.
            base_best=_best_scored_row(baseline_rows)
            base_best=dict(base_best)
            base_best["gear_fixed_point_error"]=f"{type(exc).__name__}: {exc}"
            rows.append(base_best)
    return rows


@lru_cache(maxsize=50000)
def _cached_score_signature(level:int,sig:tuple[int,...],profile:str) -> dict:
    t=_talents_from_signature(sig)
    rows=_score_rows(level,t,profile)
    feasible=[r for r in rows if r.get("feasible")]
    return min(feasible or rows,key=lambda r:(r["total_s"],r.get("panic_dependent",False),-r.get("pull_size",1)))


def _cached_score(level:int,t:Talents,profile:str) -> dict:
    return _cached_score_signature(int(level),_mechanics_signature(t),profile)


def pull_envelope(level:int,t:Talents,profile:str="auto") -> list[dict]:
    """Best sustainable setup for each pull size for one talent allocation.

    This is intentionally a strategy envelope, not a GCD permutation search.
    Gear, aura, seal mode and priority thresholds are allowed to vary per pull.
    """
    profiles=["retribution","protection"] if profile in ("auto","all","holy") else [profile]
    profiles=[p for p in profiles if p in ("retribution","protection")] or ["retribution"]
    rows=[]
    for p in profiles:
        rows.extend(_score_rows(int(level),t,p))
    out=[]
    for n in sorted({int(r.get("pull_size",1)) for r in rows}):
        pool=[r for r in rows if int(r.get("pull_size",1))==n]
        feasible=[r for r in pool if r.get("feasible")]
        best=min(feasible or pool,key=lambda r:(r["total_s"],r.get("panic_dependent",False)))
        out.append({
            "pull_size":n,"feasible":bool(best.get("feasible")),
            "mobs_per_hour":float(best.get("mobs_per_hour",0.0)),
            "cycle_s":float(best.get("cycle_s",1e9)),
            "combat_s_per_pack":float(best.get("combat_s_per_pack",1e9)),
            "recovery_s_per_pack":float(best.get("recovery_s_per_pack",1e9)),
            "gear":best.get("gear"),"weapon_style":best.get("weapon_style"),"gear_stats":best.get("gear_stats"),
            "policy":best.get("policy"),"aura":best.get("aura"),
            "profile":best.get("profile"),"seal":best.get("rotation","").split(" up;",1)[0],
            "panic_dependent":bool(best.get("panic_dependent",False)),
        })
    return out


_STAT_WEIGHT_PROBES = (
    ("strength", 1.0),
    ("stamina", 1.0),
    ("intellect", 1.0),
    ("spirit", 1.0),
    ("mp5", 1.0),
    ("spell_power", 1.0),
    ("healing", 1.0),
    ("weapon_dps", 1.0),
    ("armor", 10.0),
    ("shield_armor", 10.0),
    ("block_value", 1.0),
)


def _curve_sensitivity_delta(gear:GearSetup, stat:str, fallback:float) -> float:
    """A comparable local nudge: ~10% of this normal gear curve's stat.

    This is deliberately *not* called item-budget normalization.  Forever 69893
    exposes per-item stat budget shares but not the server-side flat-amount formula.
    The 10% curve perturbation answers the practical question "which direction is
    this normal gear profile most sensitive to?" without pretending unlike stat
    units have equal item-budget cost.
    """
    fields={
        "strength":"strength_bonus","stamina":"stamina_bonus",
        "intellect":"intellect_bonus","spirit":"spirit_bonus","mp5":"mp5_bonus",
        "spell_power":"spell_damage_bonus","spell_damage":"spell_damage_bonus","healing":"healing_bonus",
        "weapon_dps":"weapon_dps","armor":"item_armor",
        "shield_armor":"shield_armor","block_value":"shield_block_value",
    }
    value=abs(float(getattr(gear,fields[stat],0.0)))
    return max(float(fallback),0.10*value)


def _best_for_fixed_gear(level:int,t:Talents,profile:str,gear:GearSetup) -> dict:
    """Re-optimize gameplay decisions while keeping one equipment style fixed."""
    profiles=["retribution","protection"] if profile in ("auto","all","holy") else [profile]
    profiles=[p for p in profiles if p in ("retribution","protection")] or ["retribution"]
    max_pull=4 if int(level)>=30 else 3
    auras=("devotion","retribution") if int(level)>=16 else ("devotion",)
    rows=[]
    for p in profiles:
        focus=_base_damage(int(level),t,gear,p)
        for n in range(1,max_pull+1):
            incoming_by_aura={a:_incoming(int(level),t,gear,n,a,focus) for a in auras}
            for policy in POLICIES:
                for aura in auras:
                    rows.append(smooth_pack_score(int(level),t,p,gear,n,policy,aura,
                                                  _focus=focus,_incoming_row=incoming_by_aura[aura]))
    feasible=[r for r in rows if r.get("feasible")]
    return min(feasible or rows,key=lambda r:(r["total_s"],r.get("panic_dependent",False),-r.get("pull_size",1)))



def _policy_by_name(name: str | None) -> PriorityPolicy:
    for row in POLICIES:
        if row.name == str(name or ""):
            return row
    return POLICIES[0]


def _paladin_spellcrit_per_int(level: int) -> float:
    """Provisional Vanilla-shaped Paladin Int -> spell-crit slope.

    The level-60 Paladin anchor is ~54.07 Int per 1% spell crit.  The low-level
    shape follows the same linear denominator already used by the mature Mage
    model, with the Paladin level-60 constant preserved.  This is deliberately
    isolated as a surrogate assumption so a future Forever base-stat capture can
    replace it without touching the shared optimizer contract.
    """
    denom=15.07 + .65*float(max(1,min(60,int(level))))
    return 1.0/(100.0*denom)


def _focus_damage_derivatives(level:int,t:Talents,gear:GearSetup,profile:str,focus:dict) -> dict[str,float]:
    """Closed-form local DPS derivatives for Paladin primary offensive stats."""
    base_strength=22.0+2.15*level
    strength=(base_strength+gear.strength_bonus)*(1+_divine_strength_pct(t))
    ap=_paladin_melee_ap(level,strength)
    d_ap_d_str=2.0*(1+_divine_strength_pct(t))
    hit=float(focus["hit"]); crit=float(focus["crit"])
    crit_factor=1.0+crit*.5
    holy_mult=float(focus["holy_mult"])
    seal_mult=1+.05*t.improved_seals
    weapon_speed=float(gear.weapon_speed)
    weapon_avg=float(focus["weapon_avg"])
    spec_mult=(1+.03*t.two_handed_weapon_specialization) if gear.weapon_style=="2h" else (1+.033333*t.one_handed_weapon_specialization)

    # White melee.
    dwhite_str=(d_ap_d_str/14.0)*hit*crit_factor*spec_mult
    dwhite_wdps=hit*crit_factor*spec_mult

    # Holy Strike (normalized AP term, weapon's own base damage keeps real speed).
    hs=latest(HOLY_STRIKE,level)
    dhs_str=dhs_sp=dhs_wdps=0.0
    if hs:
        hs_cd=max(4.0,float(hs[2])-1.0*t.improved_holy_strike)
        normalized_speed=3.3 if gear.weapon_style=="2h" else 2.4
        mult=holy_mult*(1+.10*t.sacred_arbiter)/hs_cd*hit
        dhs_str=float(hs[3])*(d_ap_d_str/14.0*normalized_speed)*mult
        dhs_wdps=float(hs[3])*weapon_speed*mult
        dhs_sp=_family_sp_coeff("holy_strike", "holy_damage")*mult

    # Seal + Judgement.
    fury=latest(SEAL_FURY,level)
    sor=latest(SEAL_RIGHTEOUSNESS,level)
    soc=latest(SEAL_COMMAND,level) if t.seal_of_command else None
    use_fury=bool(profile=="protection" and gear.has_shield and fury)
    use_command=bool(profile=="retribution" and soc)
    dseal_str=dseal_sp=dseal_wdps=0.0
    djudge_sp=0.0
    judgement_dps=float(focus.get("judgement_dps",0.0))
    if use_fury:
        dseal_sp=(_family_sp_coeff("seal_of_fury", "seal_proc")*seal_mult*holy_mult)/weapon_speed*hit
        djudge_sp=(_family_sp_coeff("seal_of_fury", "judgement")*seal_mult*holy_mult)/float(focus["judgement_cd"])
    elif use_command:
        proc_rate=7.0/60.0
        base_mult=proc_rate*seal_mult*holy_mult*hit*crit_factor
        proc_weapon_pct=default_rules().spell_value("paladin","seal_of_command",level,"weapon_damage_pct",target="seal_proc")
        proc_sp_coeff=default_rules().spell_value("paladin","seal_of_command",level,"spell_power_coefficient",target="seal_proc")
        judgement_sp_coeff=default_rules().spell_value("paladin","seal_of_command",level,"spell_power_coefficient",target="judgement")
        d_weapon_avg_str=d_ap_d_str/14.0*weapon_speed
        d_weapon_avg_wdps=weapon_speed
        dseal_str=proc_weapon_pct*d_weapon_avg_str*base_mult
        dseal_wdps=proc_weapon_pct*d_weapon_avg_wdps*base_mult
        dseal_sp=proc_sp_coeff*base_mult
        djudge_sp=(judgement_sp_coeff*seal_mult*holy_mult)/float(focus["judgement_cd"])
    else:
        speed_scale=max(.65,min(1.65,weapon_speed/2.4))
        dseal_sp=(_family_sp_coeff("seal_of_righteousness", "seal_proc")*speed_scale*seal_mult*holy_mult)/weapon_speed*hit
        djudge_sp=((_family_sp_coeff("seal_of_righteousness", "judgement")*seal_mult*holy_mult)/float(focus["judgement_cd"])) if sor else 0.0

    # Vengeance multiplies the complete focus package and therefore its local
    # stat derivatives too.  Its stack proxy depends on melee crit, not gear Int.
    vengeance_mult=1+.01*t.vengeance*min(5.0,max(0.0,crit*35.0))
    return {
        # Keep the pieces separate so the selected mana-plan cadence can scale
        # Holy Strike / Judgement exactly instead of valuing a spell that the
        # route intentionally casts only every second cooldown.
        "white_strength":dwhite_str*vengeance_mult,
        "holy_strike_strength":dhs_str*vengeance_mult,
        "seal_strength":dseal_str*vengeance_mult,
        "white_weapon_dps":dwhite_wdps*vengeance_mult,
        "holy_strike_weapon_dps":dhs_wdps*vengeance_mult,
        "seal_weapon_dps":dseal_wdps*vengeance_mult,
        "holy_strike_spell_power":dhs_sp*vengeance_mult,
        "seal_spell_power":dseal_sp*vengeance_mult,
        "judgement_spell_power":djudge_sp*vengeance_mult,
        "judgement_dps":judgement_dps*vengeance_mult,
        # Full-cadence compatibility totals for diagnostics/older callers.
        "strength":(dwhite_str+dhs_str+dseal_str)*vengeance_mult,
        "weapon_dps":(dwhite_wdps+dhs_wdps+dseal_wdps)*vengeance_mult,
        "spell_power":(dhs_sp+dseal_sp+djudge_sp)*vengeance_mult,
    }


def item_budget_units(level:int, *, baseline=None, profile:str="auto", stats=()) -> dict:
    """Publish separate body- and weapon-slot empirical budget domains.

    Body peer items remain the general stat-mix authority. Weapon DPS is *not*
    inserted into that model. Instead, real canonical weapons define a separate
    same-hand-count/same-ilvl/same-quality exchange domain so Ret 2H and Prot
    1H can compare weapon DPS to primary stats without crossing slot budgets.
    """
    level=int(level)
    body=peer_exchange_budget_units(
        CRAFTED_ITEMS + PALADIN_AUDITED_ITEMS, level,
        stats=stats or ("strength", "stamina", "intellect", "spirit", "mp5", "spell_power", "healing", "defense"),
    )
    base=dict(baseline or {})
    gear_name=str(base.get("gear") or "")
    selected_profile=str(base.get("profile") or profile or "").lower()
    hands=1 if ("shield" in gear_name or selected_profile=="protection") else 2
    # The budget estimator is calibration, analogous to the all-tier crafted
    # body peers above. It may inspect the pinned catalogue through L60 while
    # proximity-weighting the requested tier; it never equips future items.
    weapon_rows=[x for x in catalogue_available_items("paladin",60) if float(x.weapon_dps or 0.0)>0.0]
    weapon=weapon_peer_exchange_budget_units(
        weapon_rows, level, weapon_hands=hands,
        stats=("weapon_dps","strength","stamina","intellect","spirit","spell_power","healing","mp5"),
    )
    body=dict(body)
    body["domains"]={"weapon_slot":weapon}
    body["note"]=(str(body.get("note") or "") +
        " Weapon DPS is intentionally excluded from the body budget and compared only inside the weapon_slot domain.").strip()
    return body


def analytic_stat_gradient(level:int,t:Talents,*,baseline:dict,policy=None,cfg=None,
                           profile:str="auto",options=None) -> dict | None:
    """Smooth local gearing surrogate for Forever Paladin.

    The selected talents, weapon style, pull size, aura and canonical mana plan
    are frozen.  Offensive derivatives are closed-form from the current Forever
    Paladin equations; recovery/resource terms are continuous local elasticities.
    The deterministic pack/event scorer remains validation authority.
    """
    level=int(level); base=dict(baseline or {})
    if not base.get("feasible",True): return None
    gears={g.name:g for g in archetypes(level)}
    gear=gears.get(str(base.get("gear")))
    if gear is None: return None
    # Reconstruct the exact per-level body reroll used by the selected combat
    # row.  The analytical gradient must be taken at the same gear point the
    # listener and scorer expose, not at the baseline family proxy.
    gs=base.get("gear_stats") or {}
    selected_names=tuple(gs.get("selected_body_items") or ()) if isinstance(gs,dict) else ()
    if selected_names:
        gear=apply_body_item_names(
            gear, level, selected_names,
            selection_method=str(gs.get("gear_selection_method") or "per_level_analytic_named_slot_reroll_v1"),
            selection_weights=dict(gs.get("selection_weight_snapshot") or {}),
        )
    selected_profile=str(base.get("profile") or profile or "retribution")
    if selected_profile not in ("retribution","protection"):
        selected_profile="retribution"
    selected_policy=_policy_by_name(base.get("policy"))
    aura=str(base.get("aura") or "devotion")
    n=max(1,int(base.get("pull_size") or 1))

    focus=_base_damage(level,t,gear,selected_profile)
    incoming=_incoming(level,t,gear,n,aura,focus)
    aura_dps,con_dps,con_mps=_aoe_dps(level,t,gear,n,aura,focus,selected_policy,incoming)
    plan_rows=list(_mana_plan_rows(focus,con_dps,con_mps))
    selected_plan_name=str(base.get("mana_plan") or "")
    plan_row=next((x for x in plan_rows if x["plan"].name==selected_plan_name), plan_rows[0] if plan_rows else None)
    if plan_row is None: return None

    deriv=_focus_damage_derivatives(level,t,gear,selected_profile,focus)
    c_factor=float(plan_row["con_factor"])
    exposure=estimate_pack_exposure(n,float(plan_row["focus_dps"]),float(aura_dps)+float(con_dps)*c_factor)
    avg_alive=float(exposure.avg_alive)
    pack_dps=max(.1,float(plan_row["focus_dps"])+(float(aura_dps)+float(con_dps)*c_factor)*avg_alive)
    smooth_pack_kill=float(leveling.representative_hp(level))*n/pack_dps
    per100=100.0/n

    # Canonical mana-plan cadence scales the corresponding derivative pieces.
    # White/seal terms are always present while HS/Judgement may be deliberately
    # throttled by the selected sustainable route.
    hs_factor=float(plan_row.get("hs_factor",1.0)); j_factor=float(plan_row.get("judgement_factor",1.0))
    dfocus_str=(float(deriv["white_strength"]) +
                hs_factor*float(deriv["holy_strike_strength"]) +
                float(deriv["seal_strength"]))
    dfocus_wdps=(float(deriv["white_weapon_dps"]) +
                 hs_factor*float(deriv["holy_strike_weapon_dps"]) +
                 float(deriv["seal_weapon_dps"]))
    dfocus_sp=(hs_factor*float(deriv["holy_strike_spell_power"]) +
               float(deriv["seal_spell_power"]) +
               j_factor*float(deriv["judgement_spell_power"]))

    # Consecration SP coefficient: first four targets receive the bonus term.
    first4_share=min(4,n)/max(1.0,float(n))
    dcon_sp=_family_sp_coeff("consecration", "first4_tick")*first4_share*float(focus["holy_mult"])
    dpack={
        "strength":dfocus_str,
        "weapon_dps":dfocus_wdps,
        "spell_power":dfocus_sp + avg_alive*c_factor*dcon_sp,
    }
    dkill={k:(-smooth_pack_kill*d/pack_dps)*per100 for k,d in dpack.items()}

    # Intellect: closed-form spell-crit value on Judgement plus a bounded smooth
    # capacity term when the selected route is actually near its mana ceiling.
    dcrit_d_int=_paladin_spellcrit_per_int(level)*(1+.02*t.divine_intellect)
    judgement_per100=float(focus.get("judgement_dps",0.0))*smooth_pack_kill*j_factor*per100
    # A spell crit adds 50% expected Judgement damage; convert damage elasticity
    # to time through the same local pack-DPS slope.
    djudge_dint_dps=float(focus.get("judgement_dps",0.0))*j_factor*.5*dcrit_d_int
    dkill_int=(-smooth_pack_kill*djudge_dint_dps/pack_dps)*per100

    total_s=float(base.get("total_s",per100*(smooth_pack_kill+2.2)))
    recovery_per100=float(base.get("recovery_s",0.0) or 0.0)
    mana_pool=max(1.0,float(base.get("mana_pool",180.0+18.0*level+15.0*gear.intellect_bonus)))
    peak=max(0.0,float(base.get("mana_peak_deficit",0.0) or 0.0))
    pressure=max(0.0,min(1.0,(peak/mana_pool-.45)/.45))
    d_mana_d_int=15.0*(1+.02*t.divine_intellect)
    dint_capacity=-recovery_per100*.15*pressure*d_mana_d_int/mana_pool

    # Spirit: Classic/Forever-compatible out-of-5SR Paladin slope is 0.1 mana/s
    # per Spirit (Spirit/5 per 2-second tick).  During drinking it adds to the
    # vendor-water rate; only the water-limited recovery component is valued.
    try:
        from src.rulesets.forever.shared.recovery import water_tier
        water_rate=float(water_tier(level).rate_per_s)
    except Exception:
        water_rate=1.0
    water_pack=float(base.get("water_s",0.0) or 0.0)
    water_per100=water_pack*per100
    dregen_d_spirit=.1
    spirit_regen=_paladin_mana_regen_decomposition(level,gear.spirit_bonus,0.0)
    spirit_rate=float(spirit_regen["base_mana_regen_per_s"])+float(spirit_regen["spirit_recovery_mps"])
    drec_spirit=-water_per100*dregen_d_spirit/max(1e-9,water_rate+spirit_rate)

    # MP5 is flat regeneration and remains active in combat as well as while
    # drinking.  The smooth derivative therefore has two pieces when mana is
    # the recovery bottleneck: less deficit created during combat, and a faster
    # effective recovery rate afterwards.
    dregen_d_mp5=.2
    combat_pack=float(base.get("combat_s_per_pack",smooth_pack_kill) or smooth_pack_kill)
    mp5_rate=max(0.0,float(gear.mp5_bonus))*dregen_d_mp5
    recovery_rate=max(1e-9,water_rate+mp5_rate)
    water_is_bottleneck=float(base.get("water_s",0.0) or 0.0) >= float(base.get("food_s",0.0) or 0.0)-1e-9
    if water_is_bottleneck and water_pack>0.0:
        # d(deficit)/d(mp5) = -combat_time/5; d(rate)/d(mp5)=1/5.
        mana_deficit=max(0.0,float(base.get("mana_recovery_needed",0.0) or 0.0))
        dwater_pack_mp5=-(combat_pack*dregen_d_mp5)/recovery_rate - (mana_deficit*dregen_d_mp5)/(recovery_rate*recovery_rate)
        drec_mp5=dwater_pack_mp5*per100
    else:
        drec_mp5=0.0

    # M44: defensive/recovery stats use the same objective contract.  Keep the
    # selected combat profile/pull/policy/aura fixed, but let the canonical mana
    # plan reselect inside smooth_pack_score.  This is a cheap local derivative
    # at the exact named gear point, not a second gear optimizer.
    defensive_components={}
    stat_status={}
    def local_gear_gradient(stat:str,delta:float) -> float | None:
        if stat in ("shield_armor","block_value") and not gear.has_shield:
            stat_status[stat]={"status":"not_probeable","reason":"selected gear has no shield"}
            return None
        probe_gear=gear.with_delta(stat,delta)
        probe_focus=_base_damage(level,t,probe_gear,selected_profile)
        probe_incoming=_incoming(level,t,probe_gear,n,aura,probe_focus)
        probe=smooth_pack_score(level,t,selected_profile,probe_gear,n,selected_policy,aura,
                                _focus=probe_focus,_incoming_row=probe_incoming)
        if not probe.get("feasible") or not math.isfinite(float(probe.get("total_s",1e9))):
            stat_status[stat]={"status":"not_probeable","reason":"positive local probe was infeasible"}
            return None
        grad=(float(probe["total_s"])-total_s)/float(delta)
        stat_status[stat]={"status":"measured","probe_kind":"positive_local_fixed_playstyle","probe_delta":float(delta)}
        defensive_components[stat]={
            "local_probe_delta":float(delta),
            "local_probe_s_per_100":float(probe["total_s"]),
            "baseline_s_per_100":total_s,
            "incoming_damage_per_mob":float(probe_incoming.get("damage_per_mob",0.0)),
            "avoidance":float(probe_incoming.get("avoidance",0.0)),
            "block_chance":float(probe_incoming.get("block_chance",0.0)),
            "armor_reduction":float(probe_incoming.get("armor_reduction",0.0)),
        }
        return grad

    defensive_gradients={}
    for _stat,_delta in (("stamina",1.0),("armor",10.0),("defense",1.0),("healing",1.0),
                         ("shield_armor",10.0),("block_value",1.0)):
        _g=local_gear_gradient(_stat,_delta)
        if _g is not None:
            defensive_gradients[_stat]=_g

    objective_gradient={
        "strength":dkill["strength"],
        "weapon_dps":dkill["weapon_dps"],
        "spell_power":dkill["spell_power"],
        "intellect":dkill_int+dint_capacity,
        "spirit":drec_spirit,
        "mp5":drec_mp5,
        **defensive_gradients,
    }
    return {
        "method":"analytic_paladin_continuous_gearing_surrogate_v1",
        "baseline_s_per_100":total_s,
        "reference_stat":"spell_power",
        "objective_gradient":objective_gradient,
        "components":{
            "strength":{"kill_time_via_ap":dkill["strength"],"dap_per_strength":2.0*(1+_divine_strength_pct(t))},
            "weapon_dps":{"kill_time_via_weapon_damage":dkill["weapon_dps"]},
            "spell_power":{"kill_time_via_holy_damage":dkill["spell_power"],"consecration_dps_per_sp_per_alive":dcon_sp*c_factor},
            "intellect":{"kill_time_via_judgement_spell_crit":dkill_int,"mana_capacity":dint_capacity,"dcrit_per_int":dcrit_d_int,"dmana_per_int":d_mana_d_int,"mana_pressure":pressure},
            "spirit":{"drink_recovery":drec_spirit,"dregen_mps_per_spirit":dregen_d_spirit,"water_rate_mps":water_rate},
            "mp5":{"combat_and_drink_recovery":drec_mp5,"dregen_mps_per_mp5":dregen_d_mp5,"combat_s_per_pack":combat_pack,"water_rate_mps":water_rate},
            **defensive_components,
        },
        "stat_status":stat_status,
        "declared_stats":("strength","weapon_dps","spell_power","intellect","spirit","mp5",
                          "stamina","armor","defense","healing","shield_armor","block_value"),
        "metadata":{
            "profile":selected_profile,"gear_style":gear.name,"pull_size":n,"policy":selected_policy.name,"aura":aura,"mana_plan":plan_row["plan"].name,
            "smooth_pack_kill_s":smooth_pack_kill,"pack_dps":pack_dps,"avg_alive":avg_alive,
            "gradient_scope":"fixed talents + selected weapon style/pull/policy/aura/mana plan local surrogate",
            "spell_power_alias":"paladin GearSetup.spell_damage_bonus",
            "defense_model":"shared Forever defensive state; +Defense contributes miss/dodge/parry and shield block",
            "defense_source":"Wowhead Forever spell=204 plus qualified Classic combat-table relationship",
        },
        "note":"Paladin mixed local surrogate: closed-form offense/resource slopes plus fixed-playstyle local scorer probes for Stamina/armor/Defense/healing/block. A measured zero is distinct from not_probeable. Deterministic pack/event scoring remains validation authority.",
    }


def marginal_stat_weights(level:int,t:Talents,profile:str="auto",baseline:dict|None=None) -> dict:
    """Gameplay-aware marginal stat weights for the selected normal gear style.

    Talents and equipment *style* stay fixed, so this is not an item optimizer.
    For each stat nudge the smooth proxy re-optimizes pull size, priority policy,
    aura and (when ``profile=auto``) seal/profile mode.  That matches the actual
    leveling decision: better gear may justify a larger pull or a more aggressive
    policy.  It also avoids fixed-percent recovery artefacts where more Stamina
    could appear harmful merely because the old policy targeted more absolute HP.
    """
    base=dict(baseline or experimental_level_score(level,t,profile))
    if not base.get("feasible"):
        return {"base_mobs_per_hour":0.0,"weights":{},"note":"baseline infeasible"}
    gears={g.name:g for g in archetypes(int(level))}
    gear=gears.get(str(base.get("gear")))
    if gear is None:
        return {"base_mobs_per_hour":float(base.get("mobs_per_hour",0.0)),"weights":{},"note":"gear not found"}

    # Recompute the base on the same equipment style with the same optimization
    # freedom used by probes so finite differences compare like with like.
    base_row=_best_for_fixed_gear(int(level),t,profile,gear)
    base_rate=float(base_row.get("mobs_per_hour",0.0)) if base_row.get("feasible") else 0.0
    weights={}
    for stat,delta in _STAT_WEIGHT_PROBES:
        if stat in ("shield_armor","block_value") and not gear.has_shield:
            continue
        probe_gear=gear.with_delta(stat,delta)
        row=_best_for_fixed_gear(int(level),t,profile,probe_gear)
        raw_rate=float(row.get("mobs_per_hour",0.0)) if row.get("feasible") else 0.0
        # A free positive stat cannot rationally make the character worse: the
        # player can always preserve the previous behaviour.  Coarse percentage
        # recovery presets can otherwise create tiny negative STA/INT artefacts.
        # Preserve the raw derivative for diagnostics but expose the monotone
        # gameplay value as the gear-decision weight.
        rate=max(base_rate,raw_rate)
        gain=rate-base_rate
        raw_gain=raw_rate-base_rate
        weights[stat]={
            "probe_delta":delta,
            "delta_mobs_per_hour":gain,
            "per_unit_mobs_per_hour":gain/delta,
            "relative_percent_per_unit":((gain/delta)/base_rate*100.0 if base_rate>0 else 0.0),
            "raw_delta_mobs_per_hour":raw_gain,
            "raw_per_unit_mobs_per_hour":raw_gain/delta,
            "probe_context":{
                "profile":row.get("profile"),"pull_size":row.get("pull_size"),
                "policy":row.get("policy"),"aura":row.get("aura"),
            },
        }
    # A second ranking uses a ~10% perturbation of the *current normal gear
    # curve*.  This is more useful for practical stat-mix direction than raw
    # unlike units, while remaining honest that it is not equal item-budget.
    curve_sensitivity={}
    probe_defaults=dict(_STAT_WEIGHT_PROBES)
    for stat in weights:
        delta=_curve_sensitivity_delta(gear,stat,probe_defaults[stat])
        probe_gear=gear.with_delta(stat,delta)
        row=_best_for_fixed_gear(int(level),t,profile,probe_gear)
        raw_rate=float(row.get("mobs_per_hour",0.0)) if row.get("feasible") else 0.0
        rate=max(base_rate,raw_rate)
        gain=rate-base_rate
        curve_sensitivity[stat]={
            "probe_delta":delta,
            "delta_mobs_per_hour":gain,
            "relative_percent":(gain/base_rate*100.0 if base_rate>0 else 0.0),
            "probe_context":{
                "profile":row.get("profile"),"pull_size":row.get("pull_size"),
                "policy":row.get("policy"),"aura":row.get("aura"),
            },
        }
    positive=[(v["per_unit_mobs_per_hour"],k) for k,v in weights.items() if v["per_unit_mobs_per_hour"]>0]
    positive.sort(reverse=True)
    sensitivity_rank=sorted(curve_sensitivity,key=lambda k:curve_sensitivity[k]["relative_percent"],reverse=True)
    mix_stats=("strength","stamina","intellect","spirit","mp5","spell_power","healing")
    mix_rank=[k for k in sensitivity_rank if k in mix_stats]
    return {
        "base_mobs_per_hour":base_rate,
        "gear":gear_snapshot(gear),
        "base_context":{
            "profile":base_row.get("profile"),"pull_size":base_row.get("pull_size"),
            "policy":base_row.get("policy"),"aura":base_row.get("aura"),
        },
        "weights":weights,
        "positive_rank":[k for _,k in positive],
        "curve_sensitivity":curve_sensitivity,
        "curve_sensitivity_rank":sensitivity_rank,
        "stat_mix_guidance_rank":mix_rank,
        "note":"gameplay-reoptimized monotone local derivatives plus 10%-of-normal-curve sensitivity; talents + gear style fixed; not equal-budget item optimization",
    }


def experimental_level_score(level: int, t: Talents, profile: str = "auto") -> dict:
    profiles=["retribution","protection"] if profile in ("auto","all","holy") else [profile]
    rows=[_cached_score(int(level),t,p) for p in profiles if p in ("retribution","protection")]
    if not rows:
        rows=[_cached_score(int(level),t,"retribution")]
    return min(rows,key=lambda r:(r["total_s"],r.get("panic_dependent",False)))
