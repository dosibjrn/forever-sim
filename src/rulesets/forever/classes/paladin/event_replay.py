from __future__ import annotations

"""Deterministic event replay validator for Forever Paladin pack policies.

The replay is intentionally a validator, not optimizer authority.  Fast/smooth
still chooses talents, gear, pull size, policy and canonical mana cadence.  The
event backend then asks whether that chosen policy survives an explicit timeline
of GCDs, autos, cooldowns, heals, utility windows, mana and world-mob swing
families.

Expected-value damage/block quantities are still used inside events.  That keeps
this backend deterministic and cheap while moving temporal semantics out of the
smooth algebra.  Stochastic hit/block/proc rolls remain a later MC layer.
"""

from dataclasses import dataclass, field
from typing import Any

from src.shared.combat import EventQueue
from src.shared.leveling import objective as leveling
from .gear import GearSetup, archetypes, apply_body_item_names
from .policy import ManaPlan, PriorityPolicy, MANA_PLANS, POLICIES
from .talents import Talents
from .spells import (
    CONSECRATION, RETRIBUTION_AURA, HAMMER_OF_JUSTICE,
    BLESSING_OF_PROTECTION, DIVINE_PROTECTION, latest,
)
from . import mechanics as smooth

GCD_S = 1.5
FORBEARANCE_S = 60.0


@dataclass
class ReplayState:
    t: float
    hp: float
    mana: float
    mana_pool: float
    mobs: list[float]
    gcd_ready: float = 0.0
    cast_until: float = 0.0
    holy_strike_ready: float = 0.0
    judgement_ready: float = 0.0
    consecration_ready: float = 0.0
    seal_expires: float = 0.0
    physical_immunity_until: float = 0.0
    physical_actions_disabled_until: float = 0.0
    forbearance_until: float = 0.0
    fury_absorb: float = 0.0
    shield_spec_icd_until: float = 0.0
    shield_spec_credit: float = 0.0
    dead: bool = False
    stunned_until: dict[int, float] = field(default_factory=dict)
    actions: list[dict[str, Any]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def alive(self) -> int:
        return sum(1 for x in self.mobs if x > 1e-9)

    def count(self, name: str) -> None:
        self.counts[name] = self.counts.get(name, 0) + 1

    def active_attackers(self) -> int:
        return sum(
            1 for i,hp in enumerate(self.mobs)
            if hp > 1e-9 and self.stunned_until.get(i, 0.0) <= self.t + 1e-9
        )


def _named(seq, name: str):
    return next(x for x in seq if x.name == name)


def _apply_focus_damage(state: ReplayState, amount: float) -> None:
    dmg=max(0.0,float(amount))
    if dmg <= 0.0:
        return
    for i,hp in enumerate(state.mobs):
        if hp <= 1e-9:
            continue
        used=min(hp,dmg)
        state.mobs[i]=hp-used
        dmg-=used
        if dmg <= 1e-9:
            break


def _focus_target_index(state: ReplayState) -> int | None:
    """Return the deterministic current focus target used by focus damage."""
    for i,hp in enumerate(state.mobs):
        if hp > 1e-9:
            return i
    return None


def _judgement_damage(state: ReplayState, focus: dict, base_damage: float) -> tuple[float, float, int | None]:
    """Resolve source-known target-state modifiers for the current Judgement."""
    amount=max(0.0,float(base_damage))
    multiplier=1.0
    target_idx=_focus_target_index(state)
    if focus.get("seal_name") == "Seal of Command" and target_idx is not None:
        if state.stunned_until.get(target_idx, 0.0) > state.t + 1e-9:
            multiplier=max(1.0,float(focus.get("judgement_stunned_multiplier",1.0)))
    return amount*multiplier,multiplier,target_idx


def _apply_even_damage(state: ReplayState, amount: float) -> None:
    dmg=max(0.0,float(amount))
    alive=[i for i,hp in enumerate(state.mobs) if hp>1e-9]
    if dmg<=0.0 or not alive:
        return
    each=dmg/len(alive)
    for i in alive:
        state.mobs[i]=max(0.0,state.mobs[i]-each)


def _log(state: ReplayState, kind: str, **extra) -> None:
    state.actions.append({"t":round(state.t,6),"action":kind,**extra})
    state.count(kind)


def _can_pay(state: ReplayState, amount: float) -> bool:
    return state.mana + 1e-9 >= max(0.0,float(amount))


def _spend(state: ReplayState, amount: float) -> None:
    state.mana=max(0.0,state.mana-max(0.0,float(amount)))


def _gain_mana(state: ReplayState, amount: float) -> float:
    old=state.mana
    state.mana=min(state.mana_pool,state.mana+max(0.0,float(amount)))
    return state.mana-old


def _next_decision_time(state: ReplayState, plan: ManaPlan) -> float | None:
    xs=[state.gcd_ready,state.cast_until,state.seal_expires]
    if plan.holy_strike_every>0: xs.append(state.holy_strike_ready)
    if plan.judgement_every>0: xs.append(state.judgement_ready)
    if plan.consecration_every>0: xs.append(state.consecration_ready)
    xs=[x for x in xs if x>state.t+1e-9]
    return min(xs) if xs else None


def _utility_row(level:int,talents:Talents,name:str) -> dict | None:
    if name=="Hammer of Justice":
        r=latest(HAMMER_OF_JUSTICE,level)
        if not r: return None
        cd=max(0.0,float(r[3])-5.0*int(talents.improved_hammer_of_justice))
        return {"name":name,"mana":float(r[1]),"duration":float(r[2]),"cooldown":cd,"kind":"stun"}
    if name=="Blessing of Protection":
        r=latest(BLESSING_OF_PROTECTION,level)
        if not r: return None
        cd=max(0.0,float(r[3])-60.0*int(talents.guardians_favor))
        return {"name":name,"mana":float(r[1]),"duration":float(r[2]),"cooldown":cd,"kind":"physical_immunity"}
    if name=="Divine Protection":
        r=latest(DIVINE_PROTECTION,level)
        if not r: return None
        cd=max(0.0,float(r[3])-30.0*int(talents.sacred_duty))
        return {"name":name,"mana":float(r[1]),"duration":float(r[2]),"cooldown":cd,"kind":"physical_immunity"}
    return None


def _use_emergency(state:ReplayState, level:int, talents:Talents, name:str) -> tuple[bool,str|None,float]:
    row=_utility_row(level,talents,name)
    if row is None:
        return False,"unavailable",0.0
    if not _can_pay(state,row["mana"]):
        return False,"oom",0.0
    if row["kind"]=="physical_immunity" and state.forbearance_until > state.t+1e-9:
        return False,"forbearance",0.0

    _spend(state,row["mana"])
    state.gcd_ready=max(state.gcd_ready,state.t+GCD_S)
    if row["kind"]=="stun":
        targets=[(hp,i) for i,hp in enumerate(state.mobs) if hp>1e-9]
        if not targets:
            return False,"no_target",0.0
        # Stun the healthiest remaining mob.  This is deterministic and tends to
        # preserve the full utility window instead of stunning a mob about to die.
        _,idx=max(targets)
        state.stunned_until[idx]=max(state.stunned_until.get(idx,0.0),state.t+row["duration"])
        _log(state,name,mana=row["mana"],duration=row["duration"],target_index=idx,cooldown=row["cooldown"])
    else:
        state.physical_immunity_until=max(state.physical_immunity_until,state.t+row["duration"])
        state.physical_actions_disabled_until=max(state.physical_actions_disabled_until,state.t+row["duration"])
        state.forbearance_until=max(state.forbearance_until,state.t+FORBEARANCE_S)
        _log(state,name,mana=row["mana"],duration=row["duration"],forbearance_s=FORBEARANCE_S,cooldown=row["cooldown"])
    return True,None,float(row["cooldown"])


def _current_incoming_dps(state:ReplayState, incoming:dict, talents:Talents) -> float:
    if state.physical_immunity_until > state.t+1e-9:
        return 0.0
    n_active=state.active_attackers()
    return max(0.0,float(incoming["damage_per_mob"])*float(n_active))


def replay_pack(level:int,talents:Talents,profile:str,gear:GearSetup,pull_size:int,
                policy:PriorityPolicy,aura:str,mana_plan:ManaPlan,*,
                start_hp:float|None=None,start_mana:float|None=None,
                heal_casts:int=0,heal_spell_name:str|None=None,
                emergency_actions:tuple[str,...]|list[str]=(),min_hp:float|None=None,
                max_time_s:float=180.0) -> dict:
    """Replay one fixed pack policy on a deterministic event timeline.

    ``heal_casts`` and ``emergency_actions`` are fixed strategy outputs chosen by
    the smooth policy.  The validator chooses *when* to spend them from current
    HP trajectory; it does not search alternative action permutations.
    """
    level=int(level); n=max(1,int(pull_size))
    focus=smooth._base_damage(level,talents,gear,profile)
    incoming=smooth._incoming(level,talents,gear,n,aura,focus)
    aura_dps,con_dps,con_mps=smooth._aoe_dps(level,talents,gear,n,aura,focus,policy,incoming)

    player_hp=smooth.player_base_hp(level,gear.stamina_bonus)*(1+.02*talents.sacred_duty)
    mana_pool=(180.0+18.0*level+15.0*gear.intellect_bonus)*(1+.02*talents.divine_intellect)
    state=ReplayState(
        t=0.0,
        hp=float(player_hp if start_hp is None else min(player_hp,max(0.0,start_hp))),
        mana=float(mana_pool if start_mana is None else min(mana_pool,max(0.0,start_mana))),
        mana_pool=float(mana_pool),
        mobs=[float(leveling.representative_hp(level)) for _ in range(n)],
    )
    floor=float(player_hp*policy.min_hp_fraction if min_hp is None else max(0.0,min(player_hp,min_hp)))
    heal_model=smooth._heal_model(level,talents,gear,incoming["landed_swings_per_mob"]*((n+1)/2.0))
    if heal_spell_name and heal_model.get("name")!=heal_spell_name:
        # The current smooth scorer exposes only its chosen healing spell.  Keep
        # validation explicit rather than silently pretending a different rank.
        requested_heal_mismatch=True
    else:
        requested_heal_mismatch=False
    heals_remaining=max(0,int(heal_casts))
    emergencies=list(emergency_actions or ())
    emergency_cooldown_floor=0.0
    emergency_failures=[]

    q=EventQueue()
    q.schedule(0.0,"decision")
    q.schedule(float(gear.weapon_speed),"auto")
    # Fractional fixture lanes are deterministic expected streams. A lane event
    # represents its weighted share of the currently active pack.
    for idx,row in enumerate(incoming["mob_fixture"]["rows"]):
        q.schedule(float(row["swing_s"]),"mob_swing",(idx,row))

    auto_damage=(float(focus["white_dps"])+float(focus["seal_dps"]))*float(gear.weapon_speed)
    hs_damage=float(focus["hs_dps"])*float(focus["hs_cd"])
    judge_damage=float(focus["judgement_dps"])*float(focus["judgement_cd"])
    con_cost=float(con_mps)*8.0
    ret=latest(RETRIBUTION_AURA,level)
    ret_hit=(float(ret[1])*float(focus["holy_mult"])) if aura=="retribution" and ret else 0.0
    righteous_mult=max(.70,1-.02*talents.improved_righteous_fury)

    notes=[
        "deterministic expected-value event replay; validator only",
        "exact GCD/cooldown/mana timeline for modeled damage and survival actions",
        "mob swing-family events use fractional expected lanes",
        "heals are whole casts; cast duration includes the smooth expected pushback tax",
        "Hammer of Justice suppresses one mob only; physical immunities suppress physical incoming pack-wide",
    ]
    if requested_heal_mismatch:
        notes.append(f"requested heal {heal_spell_name!r} differs from replay heal model {heal_model.get('name')!r}")
    if focus.get("seal_name")=="Seal of Command":
        notes.append("Seal of Command Judgement doubles against the current focus target while stunned")
    if talents.shield_specialization:
        notes.append("Shield Specialization uses deterministic expected-block credit with exact 3s ICD")
    if focus.get("fury"):
        notes.append("Seal of Fury is one replaceable expected-value absorb; full-break mana is event-timed")

    heal_casts_completed=0
    fury_breaks=0
    shield_spec_procs=0

    while len(q) and state.alive>0 and not state.dead and state.t<=float(max_time_s):
        ev=q.pop()
        if ev.time < state.t-1e-9:
            continue
        state.t=float(ev.time)

        if ev.kind=="decision":
            if state.t < state.cast_until-1e-9:
                q.schedule(state.cast_until,"decision")
                continue
            if state.t < state.gcd_ready-1e-9:
                q.schedule(state.gcd_ready,"decision")
                continue

            acted=False

            # Survival override.  Start healing when waiting another cast window
            # would cross the policy floor or when a useful (low-overheal) cast is
            # already available.  Emergency actions are only consumed when the
            # normal cast is not safe on the current trajectory.
            if heals_remaining>0 and heal_model.get("heal",0.0)>0.0:
                inc=_current_incoming_dps(state,incoming,talents)
                cast=float(heal_model["cast"])
                heal=float(heal_model["heal"])
                unsafe=state.hp-inc*cast < floor-1e-9
                useful=state.hp <= player_hp-.80*heal+1e-9
                if unsafe and emergencies:
                    name=emergencies.pop(0)
                    ok,reason,cd=_use_emergency(state,level,talents,name)
                    if ok:
                        emergency_cooldown_floor=max(emergency_cooldown_floor,cd)
                        acted=True
                    else:
                        emergency_failures.append({"t":state.t,"action":name,"reason":reason})
                if not acted and (unsafe or useful):
                    cost=float(heal_model["mana"])
                    if _can_pay(state,cost):
                        _spend(state,cost)
                        end=state.t+cast
                        state.cast_until=end
                        state.gcd_ready=max(state.gcd_ready,state.t+GCD_S)
                        _log(state,"Heal cast",name=heal_model["name"],mana=cost,cast_s=cast,hp_before=state.hp)
                        q.schedule(end,"heal_complete",{"name":heal_model["name"],"amount":heal})
                        acted=True
                    elif unsafe:
                        emergency_failures.append({"t":state.t,"action":"Heal cast","reason":"oom"})

            # Maintain the Seal as a canonical policy invariant.
            if not acted and state.seal_expires <= state.t+1e-9:
                cost=float(focus.get("seal_cost",0.0))
                if _can_pay(state,cost):
                    _spend(state,cost); state.seal_expires=state.t+float(focus.get("seal_duration_s",30.0))
                    state.gcd_ready=state.t+GCD_S
                    _log(state,"Seal",name=focus.get("seal_name"),mana=cost)
                    acted=True

            if not acted and mana_plan.consecration_every>0 and con_dps>0 and state.alive>=policy.consecration_min_mobs and state.t>=state.consecration_ready-1e-9 and _can_pay(state,con_cost):
                _spend(state,con_cost)
                state.consecration_ready=state.t+8.0*float(mana_plan.consecration_every)
                state.gcd_ready=state.t+GCD_S
                _log(state,"Consecration",mana=con_cost)
                for tick in range(1,9):
                    q.schedule(state.t+float(tick),"consecration_tick",float(con_dps))
                acted=True

            if not acted and mana_plan.judgement_every>0 and state.t>=state.judgement_ready-1e-9 and _can_pay(state,float(focus["judgement_cost"])):
                cost=float(focus["judgement_cost"]); _spend(state,cost)
                refund=max(0.0,float(focus.get("judgement_refund",0.0)))
                gained=_gain_mana(state,refund) if refund>0.0 else 0.0
                resolved_judge,judge_multiplier,target_idx=_judgement_damage(state,focus,judge_damage)
                _apply_focus_damage(state,resolved_judge)
                state.judgement_ready=state.t+float(focus["judgement_cd"])*float(mana_plan.judgement_every)
                # Forever Judgement has GCD 0; it must not lock Holy Strike,
                # Consecration, Seal maintenance, or heals behind 1.5 seconds.
                _log(state,"Judgement",mana=cost,mana_gained=gained,damage=resolved_judge,
                     target_index=target_idx,target_state_multiplier=judge_multiplier)
                acted=True

            if not acted and mana_plan.holy_strike_every>0 and state.t>=state.holy_strike_ready-1e-9 and _can_pay(state,float(focus["hs_cost"]) ) and state.physical_actions_disabled_until<=state.t+1e-9:
                cost=float(focus["hs_cost"]); _spend(state,cost)
                _apply_focus_damage(state,hs_damage)
                state.holy_strike_ready=state.t+float(focus["hs_cd"])*float(mana_plan.holy_strike_every)
                state.gcd_ready=state.t+GCD_S
                _log(state,"Holy Strike",mana=cost,damage=hs_damage)
                acted=True

            if acted and state.alive>0:
                q.schedule(max(state.gcd_ready,state.cast_until),"decision")
            elif state.alive>0:
                nxt=_next_decision_time(state,mana_plan)
                if nxt is not None:
                    q.schedule(nxt,"decision")

        elif ev.kind=="heal_complete":
            if state.dead:
                continue
            amount=float(ev.payload["amount"])
            before=state.hp
            state.hp=min(player_hp,state.hp+amount)
            heals_remaining=max(0,heals_remaining-1)
            heal_casts_completed+=1
            _log(state,"Heal complete",name=ev.payload["name"],heal=state.hp-before,hp_after=state.hp)
            if state.alive>0:
                q.schedule(max(state.t,state.gcd_ready),"decision")

        elif ev.kind=="auto":
            if state.alive<=0: continue
            if state.t < state.cast_until-1e-9:
                q.schedule(state.cast_until,"auto")
                continue
            if state.t < state.physical_actions_disabled_until-1e-9:
                q.schedule(state.physical_actions_disabled_until,"auto")
                continue
            _apply_focus_damage(state,auto_damage)
            _log(state,"Auto",damage=auto_damage)
            if gear.has_shield and focus.get("fury"):
                # Expected-value successful-hit shield: replacement, never stack.
                state.fury_absorb=max(0.0,float(incoming.get("fury_absorb_per_shield",0.0))*float(focus.get("hit",1.0)))
                _log(state,"Seal of Fury shield",absorb=state.fury_absorb)
            q.schedule(state.t+float(gear.weapon_speed),"auto")
            if state.gcd_ready<=state.t+1e-9 and state.cast_until<=state.t+1e-9:
                q.schedule(state.t,"decision")

        elif ev.kind=="consecration_tick":
            if state.alive>0:
                per_target=float(ev.payload)
                _apply_even_damage(state,per_target*state.alive)
                _log(state,"Consecration tick",damage=per_target*state.alive)

        elif ev.kind=="mob_swing":
            idx,row=ev.payload
            if state.alive<=0: continue
            active_count=state.active_attackers()
            expected_attackers=float(active_count)*float(row["combined_weight"])
            expected_landed=expected_attackers*(1.0-float(incoming["avoidance"]))
            expected_blocks=expected_landed*float(incoming["block_chance"]) if gear.has_shield else 0.0
            mitigated=float(row["mitigated_hit"])
            post_block=max(0.0,mitigated-float(incoming["block_chance"])*float(incoming["block_value"]))
            damage=expected_landed*post_block*righteous_mult
            if state.physical_immunity_until > state.t+1e-9:
                damage=0.0; expected_landed=0.0; expected_blocks=0.0

            # Seal of Fury is one replaceable absorb. Improved SoF mana occurs
            # exactly when this currently active shield is fully consumed.
            if state.fury_absorb>0.0 and damage>0.0:
                before=state.fury_absorb
                used=min(before,damage)
                state.fury_absorb-=used; damage-=used
                if before>1e-9 and state.fury_absorb<=1e-9:
                    fury_breaks+=1
                    if talents.improved_seal_of_fury:
                        bonus=min(.45,.15*max(0,int(row["mob_level"])-level))
                        gained=_gain_mana(state,60.0*(1.0+bonus))
                        _log(state,"Seal of Fury break",mana_gained=gained,attacker_level=int(row["mob_level"]))

            state.hp-=damage

            # Shield Spec: exact hard ICD, deterministic expected-block credit.
            rank=max(0,min(3,int(talents.shield_specialization)))
            if gear.has_shield and rank and expected_blocks>0.0:
                proc_chance=(0.0,.33,.66,1.0)[rank]
                state.shield_spec_credit+=expected_blocks*proc_chance
                if state.t>=state.shield_spec_icd_until-1e-9 and state.shield_spec_credit>=1.0-1e-9:
                    state.shield_spec_credit-=1.0
                    state.shield_spec_icd_until=state.t+3.0
                    gained=_gain_mana(state,.06*state.mana_pool)
                    shield_spec_procs+=1
                    _log(state,"Shield Specialization proc",mana_gained=gained,icd_until=state.shield_spec_icd_until)

            if ret_hit>0.0 and expected_landed>0.0:
                _apply_even_damage(state,ret_hit*expected_landed)
            _log(state,"Mob swing lane",damage=damage,lane=row["family"],expected_landed=expected_landed,expected_blocks=expected_blocks)
            if state.hp<=0.0:
                state.dead=True
            q.schedule(state.t+float(row["swing_s"]),"mob_swing",(idx,row))

    complete=state.alive==0 and not state.dead
    return {
        "complete":complete,
        "feasible":complete,
        "kill_s":float(state.t) if complete else float("inf"),
        "player_hp_end":max(0.0,float(state.hp)),
        "mana_end":max(0.0,float(state.mana)),
        "mana_start":float(mana_pool if start_mana is None else start_mana),
        "mobs_alive":int(state.alive),
        "pull_size":n,
        "gear":gear.name,
        "profile":profile,
        "policy":policy.name,
        "aura":aura,
        "mana_plan":mana_plan.name,
        "heal_spell":heal_model.get("name"),
        "heal_casts_requested":int(heal_casts),
        "heal_casts_completed":heal_casts_completed,
        "emergency_actions_requested":list(emergency_actions or ()),
        "emergency_actions_used":[x["action"] for x in state.actions if x["action"] in {"Hammer of Justice","Blessing of Protection","Divine Protection"}],
        "emergency_failures":emergency_failures,
        "emergency_cooldown_floor_s":emergency_cooldown_floor,
        "forbearance_until":state.forbearance_until,
        "fury_breaks":fury_breaks,
        "shield_spec_procs":shield_spec_procs,
        "action_counts":dict(state.counts),
        "timeline":state.actions,
        "notes":notes,
        "authority":"diagnostic_validator_only",
    }


def validate_smooth_row(level:int,talents:Talents,row:dict) -> dict:
    """Replay one smooth winner with matching named strategy components."""
    gear=next(g for g in archetypes(int(level)) if g.name==row.get("gear"))
    # Event validation must replay the exact published per-level rerolled gear,
    # not collapse it back to the display-name archetype. Otherwise combat,
    # mana and recovery are being compared at different stat points.
    gs=row.get("gear_stats") or {}
    selected_names=tuple(gs.get("selected_body_items") or ()) if isinstance(gs,dict) else ()
    if selected_names:
        gear=apply_body_item_names(
            gear, int(level), selected_names,
            selection_method=str(gs.get("gear_selection_method") or "per_level_analytic_named_slot_reroll_v1"),
            selection_weights=dict(gs.get("selection_weight_snapshot") or {}),
        )
    policy=_named(POLICIES,str(row.get("policy")))
    plan=_named(MANA_PLANS,str(row.get("mana_plan")))
    replay=replay_pack(
        int(level),talents,str(row.get("profile")),gear,int(row.get("pull_size",1)),
        policy,str(row.get("aura")),plan,
        start_hp=float(row.get("start_hp")) if row.get("start_hp") is not None else None,
        start_mana=float(row.get("start_mana")) if row.get("start_mana") is not None else None,
        heal_casts=int(row.get("heal_casts",0) or 0),
        heal_spell_name=str(row.get("heal_spell")) if row.get("heal_spell") else None,
        emergency_actions=tuple(row.get("emergency_actions") or ()),
        min_hp=float(row.get("min_hp")) if row.get("min_hp") is not None else None,
    )
    return {
        "supported":True,
        "smooth_combat_s_per_pack":float(row.get("combat_s_per_pack",0.0)),
        "smooth_end_hp":float(row.get("end_hp",0.0)),
        "smooth_end_mana":float(row.get("end_mana",0.0)),
        "smooth_heal_casts":int(row.get("heal_casts",0) or 0),
        "smooth_emergency_actions":list(row.get("emergency_actions") or ()),
        "event":replay,
    }
