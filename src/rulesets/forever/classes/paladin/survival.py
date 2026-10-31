from __future__ import annotations

"""Deterministic expected-value survival helpers for Paladin pack leveling."""

import math

from ...shared.mobs import normal_world_raw_dps
from ...shared.defense import (armor_reduction, representative_player_hp, defense_avoidance as defense_skill_avoidance)
from src.rulesets.forever.data.rules import default_rules


def player_base_hp(level: int, stamina_bonus: float) -> float:
    """Compatibility wrapper over the shared M44 HP/Stamina contract."""
    return representative_player_hp(level, stamina_bonus)


def mob_raw_dps(level: int) -> float:
    # Backward-compatible alias for callers/tests. New pack modeling consumes
    # the ruleset-level same-level mob-family fixture directly.
    return normal_world_raw_dps(level)


def expected_redoubt_bonus_block(rank: int, incoming_swings_per_s: float) -> float:
    if rank <= 0 or incoming_swings_per_s <= 0:
        return 0.0
    # Forever 69893: damaging melee attacks have a 10% proc chance at every
    # rank; the granted block chance scales +6 percentage points per rank.
    proc_chance = .10
    bonus_block = .06 * min(5, int(rank))
    # Expected 10-second buff uptime from a Poisson stream of damaging swings.
    # The 5-block charge limit is ignored in this smooth proxy for now.
    uptime = 1.0 - math.exp(-incoming_swings_per_s * proc_chance * 10.0)
    return bonus_block * uptime



def expected_icd_proc_rate(event_rate: float, proc_chance: float, icd_s: float) -> float:
    """Expected proc rate for Poisson-approximated eligible events + hard ICD.

    Successful trigger opportunities arrive at lambda=event_rate*proc_chance.
    After each proc, the process pays the hard ICD and then waits 1/lambda on
    average for the next success, giving lambda/(1+lambda*ICD).
    """
    lam=max(0.0,float(event_rate))*max(0.0,min(1.0,float(proc_chance)))
    if lam <= 0.0:
        return 0.0
    return lam/(1.0+lam*max(0.0,float(icd_s)))


def replacing_absorb_dynamics(shield_gen_rate: float, incoming_hit_rate: float,
                               shield_amount: float, mean_hit: float) -> dict:
    """Exact steady-state expectation for one replaceable Seal-of-Fury absorb.

    Conditional on the explicit *replacement* interpretation used by Fast and
    event replay, shield grants and incoming hits are competing Poisson streams.
    A new own-melee grant resets the shield to ``shield_amount``; an incoming hit
    consumes up to ``mean_hit`` from the current shield.  The public Forever
    tooltip establishes a per-attack shield grant and its 50% magnitude, while
    stacking-vs-replacement remains a server-semantic uncertainty tracked in the
    fidelity inventory.

    The old approximation credited only shields that survived all the way to a
    full break and dropped partial absorption when a later own swing replaced the
    remainder.  Here the geometric run of incoming hits since the last grant is
    integrated exactly, so Fast matches event replay for the chosen replacement
    semantics instead of using a conservative floor.
    """
    g=max(0.0,float(shield_gen_rate)); h=max(0.0,float(incoming_hit_rate))
    a=max(0.0,float(shield_amount)); hit=max(1e-9,float(mean_hit))
    if g<=0.0 or h<=0.0 or a<=0.0:
        return {"break_rate":0.0,"absorb_per_s":0.0,"hits_needed":0,"full_break_probability":0.0}
    hits_needed=max(1,int(math.ceil(a/hit)))
    q=h/(h+g)
    r=1.0-q
    p_full=q**hits_needed
    break_rate=g*p_full

    # At an arbitrary instant, n consecutive incoming hits since the last grant
    # has probability r*q**n for n < hits_needed.  The next incoming hit consumes
    # min(hit, remaining shield).  Multiplying by incoming hit rate gives the
    # exact steady-state absorbed damage rate for deterministic mean-sized hits.
    expected_absorb_per_hit=0.0
    for n in range(hits_needed):
        remaining=max(0.0,a-n*hit)
        expected_absorb_per_hit += r*(q**n)*min(hit,remaining)
    absorb_ps=min(h*hit,h*expected_absorb_per_hit)
    return {
        "break_rate":break_rate,"absorb_per_s":absorb_ps,
        "hits_needed":hits_needed,"full_break_probability":p_full,
    }

def anticipation_defense_bonus(anticipation_rank: int) -> float:
    """Source-driven Forever Anticipation Defense skill bonus."""
    rank=max(0,min(5,int(anticipation_rank)))
    if rank <= 0:
        return 0.0
    return default_rules().talent_value(
        "paladin", "anticipation", rank, "skill_bonus", target="defense"
    )


def defense_avoidance(anticipation_rank: int, gear_defense: float = 0.0) -> float:
    """Anticipation + item Defense -> shared combat-table avoidance."""
    defense = anticipation_defense_bonus(anticipation_rank) + max(0.0, float(gear_defense))
    return defense_skill_avoidance(defense)


def discrete_heal_sequence(*, need_hp: float, heal_amount: float, cast_s: float,
                           mana_cost: float, incoming_dps: float,
                           start_hp: float, min_hp: float,
                           emergency_windows: tuple[tuple, ...] = ()) -> dict:
    """Find a small deterministic whole-cast survival sequence.

    ``emergency_windows`` rows are either the legacy
    ``(name, duration_s, mana_cost, cooldown_s)`` shape (meaning a full incoming
    pause) or ``(..., incoming_multiplier)``.  The latter matters for Hammer of
    Justice: it stuns one attacker, not the whole pack, so residual attackers
    continue dealing damage while the heal is cast.

    They are considered in caller-provided priority order (HoJ, then physical
    immunity in the Paladin policy).  The function never invents fractional
    heals: every heal consumes one full cast time and one full mana cost.  The
    emergency action itself consumes a 1.5 s GCD, which also consumes part of
    the utility window before a heal can complete.

    The model is deliberately compact rather than a free-form action search.
    Outside an emergency window a heal cast loses ``incoming_dps * cast_s`` HP
    while casting; inside a window it receives the full heal amount.  Long-CD
    dependence is returned explicitly so the pack cycle can respect it.
    """
    need=max(0.0,float(need_hp)); heal=max(0.0,float(heal_amount)); cast=max(.01,float(cast_s))
    mana=max(0.0,float(mana_cost)); inc=max(0.0,float(incoming_dps))
    if need <= 1e-9:
        return {
            "feasible": True, "casts": 0, "heal_time_s": 0.0, "heal_mana": 0.0,
            "total_heal": 0.0, "emergency_actions": [], "emergency_mana": 0.0,
            "emergency_gcd_s": 0.0, "cooldown_floor_s": 0.0,
        }
    if heal <= 0.0:
        return {"feasible": False, "reason": "no heal spell"}

    actions=[]; emergency_mana=0.0; emergency_gcd=0.0; cooldown_floor=0.0
    emergency_avoided_damage=0.0
    safe_heal=heal-inc*cast
    # If the first normal cast would cross the policy floor, first create a safe
    # window.  Likewise, if incoming damage fully erases a normal heal, all
    # required casts must fit in emergency windows.
    current=float(start_hp)
    remaining=need
    emergency_casts=0
    for row in emergency_windows:
        if len(row) >= 5:
            name,duration,cost,cooldown,incoming_mult=row[:5]
        else:
            name,duration,cost,cooldown=row[:4]
            incoming_mult=0.0
        duration=max(0.0,float(duration))
        incoming_mult=max(0.0,min(1.0,float(incoming_mult)))
        first_cast_unsafe=(current-inc*cast < float(min_hp)-1e-9)
        if remaining <= 1e-9 or (safe_heal > 1e-9 and not first_cast_unsafe):
            break
        # Utility is instant but consumes the GCD.  During that GCD the utility
        # already applies, so only residual incoming damage lands.  The GCD also
        # shortens the remaining window available for completed heal casts.
        gcd=1.5
        residual_inc=inc*incoming_mult
        after_gcd=current-residual_inc*gcd
        if after_gcd < float(min_hp)-1e-9:
            continue
        usable=max(0.0,duration-gcd)
        capacity=max(0,int(math.floor(usable/cast+1e-9)))
        if capacity <= 0:
            continue
        net_per_cast=heal-residual_inc*cast
        if net_per_cast <= 1e-9:
            continue
        needed=int(math.ceil(remaining/net_per_cast))
        used=min(capacity,needed)
        if used <= 0:
            continue
        # Every completed cast must stay above the configured policy floor until
        # the heal lands.  This catches a HoJ window that is long enough in time
        # but not safe enough against the unstunned remainder of the pack.
        probe=after_gcd
        completed=0
        for _ in range(used):
            if probe-residual_inc*cast < float(min_hp)-1e-9:
                break
            probe=probe-residual_inc*cast+heal
            completed+=1
        used=completed
        if used <= 0:
            continue
        actions.append(name)
        emergency_mana+=max(0.0,float(cost)); emergency_gcd+=gcd
        cooldown_floor=max(cooldown_floor,max(0.0,float(cooldown)))
        active_time=min(duration,gcd+used*cast)
        emergency_avoided_damage += inc*(1.0-incoming_mult)*active_time
        current=probe
        gain=used*net_per_cast
        remaining=max(0.0,remaining-gain)
        emergency_casts+=used

    normal_casts=0
    if remaining > 1e-9:
        if safe_heal <= 1e-9:
            return {"feasible": False, "reason": "healing cannot outpace incoming damage"}
        normal_casts=int(math.ceil(remaining/safe_heal))
        # A normal cast must be survivable at the floor.  Subsequent casts become
        # safer because each one adds a positive net amount.
        if current-inc*cast < float(min_hp)-1e-9:
            return {"feasible": False, "reason": "no safe heal window"}

    casts=emergency_casts+normal_casts
    total_heal=casts*heal
    return {
        "feasible": True,
        "casts": casts,
        "emergency_casts": emergency_casts,
        "normal_casts": normal_casts,
        "heal_time_s": casts*cast,
        "heal_mana": casts*mana,
        "total_heal": total_heal,
        "emergency_actions": actions,
        "emergency_mana": emergency_mana,
        "emergency_gcd_s": emergency_gcd,
        "emergency_avoided_damage": emergency_avoided_damage,
        "cooldown_floor_s": cooldown_floor,
        "net_heal_per_normal_cast": safe_heal,
    }
