"""Mage policy, fight-chain and talent-search layer.

Extracted from ``engine.py`` in v0.11.46.8.  The module deliberately depends
on the already-defined combat/data primitives in ``engine``; ``engine`` then
re-exports this public surface for backwards compatibility.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, Iterable, List, Optional, Tuple
import math
import random

from src.shared.leveling.timing import between_pull_travel_s

from . import wowhead_facts as wh
from .resources import best_mage_water, mana_gem_tier, ooc_mana_regen_per_s
from .engine import (
    ARCANE_BLAST, ARCANE_MISSILES, FIREBALL, FIRE_BLAST, FROSTBOLT, FROST_NOVA,
    ICE_LANCE, MOB_BASE_HP, PYROBLAST, SCORCH, SPELLS, TALENT_RULES,
    EPS, HP_EPS, TIME_EPS,
    FightMetrics, Mob, Rank, SimConfig, State, Stats, Talents, Wand,
    _hot_streak_active_stacks, _maybe_cast_ice_barrier_pre_pull,
    add_point, advance_events, best_wand, effective_range,
    filter_policies_by_primary_school, forever_crafted_gear, ice_barrier_rank,
    latest, legal_add, mana_cost, normal_world_raw_dps, perform_am, perform_blink,
    perform_direct, perform_instant_damage, perform_move, perform_nova, player_stats,
    player_stats_for_config, solve_recovery, RECOVERY_SOLVER_ID, regen_fraction_in_5sr,
    representative_player_hp, roll_magic_resistance_multiplier, tree_points, wand_hit_chance,
    armor_reduction,
)

@dataclass(frozen=True)
class Policy:
    name:str
    primary:str='frostbolt'
    use_fireblast:bool=True
    fireblast_execute_frac:float=.18
    use_nova:bool=True
    nova_rank1:bool=True
    nova_melee_only:bool=True
    nova_move_yards:float=6.0
    use_blink:bool=True
    blink_min_hp_frac:float=.35
    # Ice Barrier is an optional pre-pull throughput/control action, not a
    # passive consequence of taking the talent.  Keeping the decision in the
    # policy lets MC/Fast compare 'use it' vs 'skip it' rather than making a
    # potentially mana-negative spell mandatory.
    use_ice_barrier:bool=False
    clearcast_am:bool=False
    use_proc_ice_lance:bool=False
    ice_lance_move_away:bool=True
    use_missile_barrage:bool=True
    # Arcane guide/search family: cast AB until this many stacks, then clear
    # with Arcane Missiles. 0 keeps the legacy AB-spam policy.
    arcane_blast_to_stacks:int=0
    # Fire guide/search family: cast Pyroblast once Hot Streak reaches this
    # many stacks. 0 disables reactive Hot Streak Pyro use.
    hot_streak_pyro_stacks:int=0
    # Fire cadence is intentionally independent of Improved Scorch rank.  This
    # avoids a search pathology where low Imp Scorch could be rewarded merely
    # because the old "cast until N stacks" policy happened to cast more Scorch.
    fireball_block:int=0
    scorch_block:int=0
    # Phase offset into the fixed Fireball/Scorch cadence.  This makes e.g.
    # FBa3/Sc3 capable of starting as FBa,FBa,Sc,Sc,Sc,FBa... (phase=1)
    # or Sc,Sc,Sc,FBa,FBa,FBa... (phase=3) without tying rotation
    # behavior to any talent rank.
    fire_cycle_phase:int=0
    # Optional conditional Frost Nova insertion *before* this logical cadence
    # position whenever Nova is ready and the target is in range. -1 keeps the
    # legacy/reactive melee Nova behavior. Nova does not consume a cadence slot.
    nova_cycle_pos:int=-1
    pyro_opener:bool=False
    # Deprecated legacy descriptor field. Kept only so old replay descriptors
    # can still be parsed; new search policies never use stack-driven behavior.
    scorch_to_stacks:int=0
    # Optional utility downrank: Rank 1 Frostbolt alongside a Fire rotation.
    # 'opener' = one cheap chill at pull start; 'maintain' = refresh chill when
    # it is about to expire and the mob is still outside melee.
    fbo_r1_mode:str='none'  # none | opener | maintain
    fbo_r1_refresh_s:float=.75
    # Observable-HP finisher policy. 0 disables it; N means switch to the best
    # available wand when the mob's current HP is within N expected full shots,
    # then attempt at most N shots once before resuming the normal spell policy.
    wand_finisher_max_hits:int=0


def policy_spell_usage(p:Policy, level:int) -> set[str]:
    """Conservative set of spells the policy can actually cast at this level.

    This is semantic metadata for diagnostics/search tie-breaking.  It mirrors
    choose_action rather than scraping the human-readable policy descriptor.
    """
    spells=set()
    primary_map={'frostbolt':'frostbolt','fireball':'fireball','scorch':'scorch','arcane_missiles':'arcane_missiles','arcane_blast':'arcane_blast'}
    pr=primary_map.get(p.primary)
    if pr:
        spells.add(pr)
    if p.fireball_block>0 and p.scorch_block>0:
        if latest(FIREBALL,level): spells.add('fireball')
        if latest(SCORCH,level): spells.add('scorch')
    if p.scorch_to_stacks>0:
        if latest(SCORCH,level): spells.add('scorch')
        if latest(FIREBALL,level): spells.add('fireball')
    if p.use_fireblast and latest(FIRE_BLAST,level): spells.add('fire_blast')
    if p.use_nova and latest(FROST_NOVA,level): spells.add('frost_nova')
    if p.clearcast_am and latest(ARCANE_MISSILES,level): spells.add('arcane_missiles')
    if p.use_proc_ice_lance and latest(ICE_LANCE,level): spells.add('ice_lance')
    if p.arcane_blast_to_stacks>0:
        if latest(ARCANE_BLAST,level): spells.add('arcane_blast')
        if latest(ARCANE_MISSILES,level): spells.add('arcane_missiles')
    if (p.pyro_opener or p.hot_streak_pyro_stacks>0) and latest(PYROBLAST,level): spells.add('pyroblast')
    if p.fbo_r1_mode!='none': spells.add('frostbolt')
    return spells


def talent_directly_affects_policy(name:str, p:Policy, level:int) -> bool:
    """Whether a modeled talent can change this level/policy's speed result.

    Prerequisite-only/defensive fillers deliberately return False.  The helper
    is used only for diagnostics and tie-breaking; the simulator remains the
    authority on the actual numeric effect.
    """
    spells=policy_spell_usage(p,level)
    frost=bool(spells & {'frostbolt','frost_nova'})
    fire=bool(spells & {'fireball','scorch','fire_blast','pyroblast'})
    arcane='arcane_missiles' in spells
    any_spell=bool(spells)
    if name=='arcane_subtlety': return any_spell
    if name=='elemental_precision': return frost or fire
    if name=='arcane_focus': return arcane
    if name=='imp_frostbolt': return 'frostbolt' in spells
    if name=='ice_shards': return frost
    if name=='frostbite': return 'frostbolt' in spells
    if name=='imp_frost_nova': return 'frost_nova' in spells
    if name=='permafrost': return 'frostbolt' in spells
    if name=='piercing_ice': return frost
    if name=='arctic_reach': return bool(spells & {'frostbolt','frost_nova'})
    if name=='frost_channeling': return frost
    if name=='shatter': return frost and 'frost_nova' in spells
    if name=='winters_chill': return 'frostbolt' in spells
    if name=='ice_lance': return 'ice_lance' in spells
    if name=='fingers_of_frost': return bool(p.use_proc_ice_lance and 'ice_lance' in spells and 'frostbolt' in spells)
    if name=='ice_barrier': return bool(p.use_ice_barrier and any_spell and ice_barrier_rank(level) is not None)
    if name=='imp_arcane_missiles': return arcane
    if name=='arcane_concentration': return any_spell
    if name=='arcane_meditation': return any_spell
    # Arcane Resilience is now only a prerequisite gate: player HP/armor are not
    # part of this leveling-speed scoreroute.
    if name=='arcane_resilience': return False
    if name=='arcane_mind': return any_spell
    if name=='arcane_instability': return any_spell
    if name=='arcane_blast': return 'arcane_blast' in spells
    if name=='missile_barrage': return bool(p.use_missile_barrage and 'arcane_blast' in spells and 'arcane_missiles' in spells)
    if name=='imp_fireball': return 'fireball' in spells
    if name=='impact': return fire
    if name=='imp_fire_blast': return 'fire_blast' in spells
    if name=='ignite': return fire
    if name=='flame_throwing': return fire
    if name=='burning_soul': return fire
    if name=='incinerate': return bool(spells & {'scorch','fire_blast'})
    if name=='pyroblast': return 'pyroblast' in spells
    if name=='hot_streak': return bool(p.hot_streak_pyro_stacks>0 and 'pyroblast' in spells and fire)
    if name=='imp_scorch': return 'scorch' in spells
    if name=='master_elements': return frost or fire
    if name=='critical_mass': return fire
    if name=='fire_power': return fire
    if name=='combustion': return fire
    # Explicit neutral/gating talents in this ST objective.
    if name in {'frost_warding','improved_blizzard','cold_snap','ice_block','improved_cone_of_cold',
                'arcane_filler','improved_flamestrike','fire_warding'}:
        return False
    return False


def _expected_wand_hit(level:int,mob:Mob,t:Talents,cfg:SimConfig)->float:
    """Expected full-shot wand damage for an observable-HP finisher decision."""
    wand=best_wand(level)
    raw=.5*(float(wand.dmin)+float(wand.dmax))
    # Shoot is a ranged weapon attack: physical/ranged hit table, not spell hit.
    raw *= wand_hit_chance(level, mob.level)
    if wand.school in ('fire','frost','arcane','nature','shadow'):
        neutral=replace(t, arcane_subtlety=0)
        # School resistance still applies to magic wand damage; spell-hit and
        # Arcane Subtlety do not apply to the ranged weapon attack.
        from .engine import effective_magic_resistance_percent
        pct=effective_magic_resistance_percent(level,mob.level,wand.school,neutral,cfg,binary=False)
        raw*=max(0.0,1.0-pct)
    return max(EPS,raw)


def _should_wand_finish(s:State,level:int,t:Talents,cfg:SimConfig,mob:Mob,p:Policy)->bool:
    hits=max(0,int(getattr(p,'wand_finisher_max_hits',0)))
    if hits<=0 or s.wand_finisher_committed or s.hp<=HP_EPS:
        return False
    return float(s.hp) <= hits*_expected_wand_hit(level,mob,t,cfg) + HP_EPS


def perform_wand_finisher(s:State,max_hits:int,level:int,t:Talents,stats:Stats,cfg:SimConfig,
                           mob:Mob,rng:random.Random,metrics:FightMetrics)->None:
    """Attempt a bounded HP-aware wand finish with the best available wand.

    The player can observe target HP, so entering the finisher window is a
    state-dependent decision.  The commitment is one-shot per mob: after at
    most ``max_hits`` completed wand autos, a survivor returns to the normal
    spell policy instead of re-entering an unbounded wand loop.
    """
    s.wand_finisher_committed=True
    wand=best_wand(level)
    if not s.engaged:
        s.engaged=True
    for _ in range(max(0,int(max_hits))):
        if s.hp<=HP_EPS:
            s.hp=0.0; break
        t0=s.t
        advance_events(s,wand.speed,level,t,stats,cfg,mob,rng,metrics)
        elapsed=max(0.0,s.t-t0)
        if elapsed<=EPS:
            elapsed=wand.speed; s.t+=elapsed
        metrics.wand_time+=elapsed
        # Existing projectile/DoT damage can kill during the wand period.
        if s.hp<=HP_EPS:
            s.hp=0.0; break
        if elapsed + TIME_EPS < wand.speed:
            break
        hp0=s.hp
        raw=rng.uniform(wand.dmin,wand.dmax)
        mult=_wand_attack_multiplier(level,mob,wand,t,cfg,rng)
        dmg=max(0.0,raw*mult)
        s.hp=max(0.0,s.hp-dmg)
        metrics.wand_shots+=1
        metrics.wand_damage+=min(hp0,dmg)
        metrics.casts['wand_finisher']=metrics.casts.get('wand_finisher',0)+1


def choose_action(s:State,level:int,t:Talents,stats:Stats,cfg:SimConfig,mob:Mob,p:Policy,initial_hp:float):
    hpfrac=max(0,s.hp/initial_hp)
    if _should_wand_finish(s,level,t,cfg,mob,p):
        return ('wand_finisher',best_wand(level))
    fb=latest(FIRE_BLAST,level)
    if p.use_fireblast and fb and s.t>=s.fireblast_ready and s.distance<=effective_range(fb,t)+EPS and hpfrac<=p.fireblast_execute_frac:
        return ('fire_blast',fb)
    # Reactive Nova is the default.  Cadence-scheduled Nova is handled below
    # so it can be inserted at an optimizer-selected point in the Fire cycle.
    if p.use_nova and p.nova_cycle_pos < 0 and s.in_melee and s.t>=s.nova_ready:
        nr=FROST_NOVA[0] if p.nova_rank1 else latest(FROST_NOVA,level)
        if nr and s.distance<=nr.radius*(1+.1*t.arctic_reach): return ('nova',nr)
    if p.use_blink and s.in_melee and level>=20 and s.t>=s.blink_ready and hpfrac>=p.blink_min_hp_frac:
        return ('blink',None)
    if getattr(p,'use_missile_barrage',False) and getattr(t,'missile_barrage',0) and s.t + TIME_EPS < s.missile_barrage_until:
        am=latest(ARCANE_MISSILES,level)
        if am:return ('am',am)
    if getattr(p,'use_proc_ice_lance',False) and getattr(t,'ice_lance',0):
        # A real Frozen/root state (Frostbite or Frost Nova) is just as valid
        # for Ice Lance as Fingers of Frost.  Previously the selector only
        # reacted to FoF charges even though damage/crit resolution already
        # understood ordinary roots, leaving Frostbite/Nova value on the table.
        frozen_now = s.t + TIME_EPS < s.root_until
        fof_now = s.fingers_of_frost_charges>0 and s.t + TIME_EPS < s.fingers_of_frost_until
        if frozen_now or fof_now:
            il=latest(ICE_LANCE,level)
            if il:return ('ice_lance',il)
    if p.clearcast_am and s.clearcasting:
        am=latest(ARCANE_MISSILES,level)
        if am:return ('am',am)

    # Hot Streak is a rotation-changing talent: once the configured stack
    # threshold is reached, reactive Pyro takes priority over the filler.
    if p.hot_streak_pyro_stacks>0 and t.hot_streak and t.pyroblast:
        if _hot_streak_active_stacks(s) >= p.hot_streak_pyro_stacks:
            py=latest(PYROBLAST,level)
            if py:return ('direct',py)

    # Arcane Blast policies are cyclic rather than AB spam.  At the selected
    # stack threshold, Arcane Missiles spends/clears the AB damage buff; below
    # the threshold, continue building stacks with AB.
    if p.arcane_blast_to_stacks>0 and p.primary=='arcane_blast' and t.arcane_blast:
        stacks=(s.arcane_blast_stacks if s.t + TIME_EPS < s.arcane_blast_until else 0)
        if stacks>=p.arcane_blast_to_stacks:
            am=latest(ARCANE_MISSILES,level)
            if am:return ('am',am)
        ab=latest(ARCANE_BLAST,level)
        if ab:return ('direct',ab)

    if p.pyro_opener and t.pyroblast and not s.pyro_opener_used:
        py=latest(PYROBLAST,level)
        if py:
            return ('direct',py)

    # Cheap utility Frostbolt R1 for Fire policies.
    if p.fbo_r1_mode != 'none' and p.primary in ('fireball','scorch'):
        r1=FROSTBOLT[0]
        if p.fbo_r1_mode == 'opener' and not s.engaged:
            return ('direct',r1)
        if (p.fbo_r1_mode == 'maintain' and not s.in_melee and s.t >= s.root_until
                and (not s.engaged or s.slow_until-s.t <= p.fbo_r1_refresh_s)):
            return ('direct',r1)

    if p.fireball_block>0 and p.scorch_block>0 and latest(FIREBALL,level) and latest(SCORCH,level):
        cycle=p.fireball_block+p.scorch_block
        pos=(s.fire_cycle_pos + p.fire_cycle_phase) % cycle
        # A scheduled Nova is a conditional insertion, not a cycle element:
        # cast it when ready/in range, then resume the same Fire cycle slot.
        if p.use_nova and p.nova_cycle_pos >= 0 and pos == (p.nova_cycle_pos % cycle) and s.t>=s.nova_ready:
            nr=FROST_NOVA[0] if p.nova_rank1 else latest(FROST_NOVA,level)
            if nr and s.distance<=nr.radius*(1+.1*t.arctic_reach) and s.mana+EPS>=mana_cost(nr,t,stats):
                return ('nova',nr)
        if pos < p.fireball_block:
            return ('direct',latest(FIREBALL,level))
        sc=latest(SCORCH,level)
        if s.distance<=effective_range(sc,t)+EPS:
            return ('direct',sc)
        return ('wait_range',sc)
    if p.primary=='frostbolt': return ('direct',latest(FROSTBOLT,level))
    if p.primary=='fireball': return ('direct',latest(FIREBALL,level))
    if p.primary=='scorch': return ('direct',latest(SCORCH,level))
    if p.primary=='arcane_missiles': return ('am',latest(ARCANE_MISSILES,level))
    if p.primary=='arcane_blast': return ('direct',latest(ARCANE_BLAST,level))
    raise ValueError(p.primary)



def _wand_resistance_multiplier(level:int,mob:Mob,wand:Wand,t:Talents,cfg:SimConfig,rng:random.Random)->float:
    """Magic-school mitigation for a wand shot.

    Wands are ranged weapon attacks, so spell-hit talents do not modify their
    hit chance here. School resistance still mitigates magic wand damage; Arcane
    Subtlety is intentionally not applied to wand shots because it modifies
    resistance to the mage's spells, not ranged weapon attacks.
    """
    school=wand.school
    if school not in ('fire','frost','arcane','nature','shadow'):
        return 1.0
    neutral=replace(t, arcane_subtlety=0)
    return roll_magic_resistance_multiplier(level,mob.level,school,'wand',neutral,cfg,rng)


def _wand_attack_multiplier(level:int,mob:Mob,wand:Wand,t:Talents,cfg:SimConfig,rng:random.Random)->float:
    """One Shoot attack-table roll followed by magic-school resistance."""
    if rng.random() > wand_hit_chance(level,mob.level):
        return 0.0
    return _wand_resistance_multiplier(level,mob,wand,t,cfg,rng)


def _mana_wait_seconds(s:State,need:float,level:int,t:Talents,stats:Stats,cfg:SimConfig)->float:
    """Continuous time until ``need`` mana is available under normal spirit regen."""
    deficit=max(0.0,float(need)-s.mana)
    if deficit<=EPS:
        return 0.0
    mps=(12.5+stats.spirit/4)/2 + stats.mp5/5.0
    f=regen_fraction_in_5sr(level,t,cfg)
    five=max(0.0,s.last_mana_spend+5.0-s.t)
    inside_rate=mps*f
    inside_gain=inside_rate*five
    if deficit<=inside_gain and inside_rate>EPS:
        return deficit/inside_rate
    return five + max(0.0,deficit-inside_gain)/max(mps,EPS)


def _required_mana(action:str,obj:Optional[Rank],t:Talents,stats:Stats)->float:
    if obj is not None and action in ('direct','fire_blast','ice_lance','nova'):
        if obj.spell=='arcane_blast':
            return stats.base_mana*wh.ARCANE_BLAST_BASE_MANA_PCT
        return mana_cost(obj,t,stats)
    if obj is not None and action=='am':
        return obj.mana
    if action=='blink':
        return .35*stats.base_mana
    return 0.0


def perform_wand_fallback(s:State,seconds:float,level:int,t:Talents,stats:Stats,cfg:SimConfig,
                          mob:Mob,rng:random.Random,metrics:FightMetrics)->None:
    """Use the best level-appropriate wand as a real ranged autoattack.

    One wand shot occurs per item-speed interval. Each shot rolls the item's
    actual damage range. Mana regenerates while wanding. If the requested spell
    becomes affordable before the next shot would complete, the mage cancels the
    wand cycle and resumes the policy immediately. No player-HP/death model is
    involved.
    """
    remaining=max(0.0,float(seconds))
    wand=best_wand(level)
    if 0.0 < s.hp <= HP_EPS:
        s.hp=0.0
        return
    if not s.engaged:
        s.engaged=True
    while remaining>EPS and s.hp>HP_EPS:
        # Do not invent a partial wand hit. If mana becomes available before a
        # full auto-shot finishes, simply regen for the remaining interval.
        if remaining + TIME_EPS < wand.speed:
            t0=s.t
            advance_events(s,remaining,level,t,stats,cfg,mob,rng,metrics)
            elapsed=max(0.0,s.t-t0)
            if elapsed<=EPS:
                elapsed=remaining; s.t+=elapsed
            metrics.wand_time+=elapsed
            remaining=max(0.0,remaining-elapsed)
            break

        shot_dt=min(wand.speed,remaining)
        t0=s.t
        advance_events(s,shot_dt,level,t,stats,cfg,mob,rng,metrics)
        elapsed=max(0.0,s.t-t0)
        if elapsed<=EPS:
            elapsed=shot_dt; s.t+=elapsed
        metrics.wand_time+=elapsed
        remaining=max(0.0,remaining-elapsed)
        if s.hp<=HP_EPS:
            s.hp=0.0; break
        # Only a completed wand period creates a shot. Existing projectiles/DoTs
        # may have killed the target during the period.
        if elapsed + TIME_EPS >= wand.speed:
            raw=rng.uniform(wand.dmin,wand.dmax)
            mult=_wand_attack_multiplier(level,mob,wand,t,cfg,rng)
            dmg=max(0.0,raw*mult)
            hp0=s.hp
            s.hp=max(0.0,s.hp-dmg)
            metrics.wand_shots+=1
            metrics.wand_damage+=min(hp0,dmg)
            metrics.casts['wand']=metrics.casts.get('wand',0)+1
        if 0.0 < s.hp <= HP_EPS:
            s.hp=0.0


def simulate_fight(level:int,tal:Talents,mob:Mob,policy:Policy,cfg:SimConfig,rng:random.Random,
                   cooldowns:Optional[Tuple[float,...]]=None, initial_mana:Optional[float]=None)->Tuple[FightMetrics,Tuple[float,...],float,float]:
    stats=player_stats(level,tal,cfg.owl_intensity)
    # Start each pull at the primary spell's max range (representing selecting a fresh target at pull distance).
    primary=latest(SPELLS.get(policy.primary,FROSTBOLT),level) if policy.primary in SPELLS else latest(FROSTBOLT,level)
    start_range=effective_range(primary,tal) if primary else 30
    if policy.fbo_r1_mode != 'none' and policy.primary in ('fireball','scorch'):
        start_range=min(start_range, effective_range(FROSTBOLT[0],tal))
    raw=list(cooldowns or ())
    raw += [0.0] * max(0, 10-len(raw))
    fbr,nr,br,cbr,cactive,ccrits,cbonus,ibar,ibabs,ibdur=raw[:10]
    carried_absorb=max(0.0,float(ibabs)) if ibdur>EPS else 0.0
    start_mana=stats.max_mana if initial_mana is None else max(0.0,min(stats.max_mana,float(initial_mana)))
    s=State(t=0,hp=mob.hp,mana=start_mana,max_mana=stats.max_mana,distance=start_range,
            engaged=False, fireblast_ready=fbr,nova_ready=nr,blink_ready=br,
            combustion_ready=cbr,combustion_active=bool(round(cactive)),
            combustion_crits=int(round(ccrits)),combustion_bonus=int(round(cbonus)),
            ice_barrier_ready=ibar,ice_barrier_absorb=carried_absorb,
            ice_barrier_until=(max(0.0,float(ibdur)) if ibdur>EPS else -1e9),
            min_distance=start_range)
    m=FightMetrics(); initial=mob.hp
    if policy.use_ice_barrier:
        _maybe_cast_ice_barrier_pre_pull(s,level,tal,stats,cfg,mob,rng,m)
    post_nova_move=False
    steps=0
    while s.hp>0:
        steps+=1
        action,obj=choose_action(s,level,tal,stats,cfg,mob,policy,initial)
        ok=False
        if action=='direct' and obj:
            ok=perform_direct(s,obj,level,tal,stats,cfg,mob,rng,m)
            if ok and obj.spell=='pyroblast':
                s.pyro_opener_used=True
            if ok and policy.fireball_block>0 and policy.scorch_block>0 and obj.spell in ('fireball','scorch'):
                s.fire_cycle_pos+=1
        elif action in ('fire_blast','ice_lance') and obj:
            ok=perform_instant_damage(s,obj,level,tal,stats,cfg,mob,rng,m,
                                      moving_away=(action=='ice_lance' and policy.ice_lance_move_away))
        elif action=='nova' and obj:
            ok=perform_nova(s,obj,level,tal,stats,cfg,mob,rng,m);post_nova_move=ok
        elif action=='blink': ok=perform_blink(s,level,tal,stats,cfg,mob,rng,m)
        elif action=='am' and obj: ok=perform_am(s,obj,level,tal,stats,cfg,mob,rng,m)
        elif action=='wand_finisher':
            perform_wand_finisher(s,policy.wand_finisher_max_hits,level,tal,stats,cfg,mob,rng,m); ok=True
        elif action=='wait_range' and obj:
            target=effective_range(obj,tal)
            if not s.in_melee and s.distance>target:
                if s.engaged:
                    # Once the target is active, simply let it close to the
                    # shorter spell's range.
                    slowed=s.t + TIME_EPS < s.slow_until
                    speed=mob.run_speed*((1-s.slow_frac) if slowed else 1.0)
                    dt=max(0.0,(s.distance-target)/max(speed,1e-9))
                    advance_events(s,dt,level,tal,stats,cfg,mob,rng,m)
                else:
                    # A missile spell can be in flight while the next cadence
                    # spell (typically Scorch) has shorter range. Before impact
                    # the mob is intentionally not aggroed, so waiting for mob
                    # movement would be a zero-time loop. Walk into range instead.
                    # Existing projectiles are still resolved during the move; if
                    # one lands, advance_events also starts target movement.
                    dt=max(0.0,(s.distance-target)/7.0)
                    advance_events(s,max(dt,1e-4),level,tal,stats,cfg,mob,rng,m,
                                   moving=True,player_speed_away=-7.0)
                    s.distance=max(target,s.distance)
                    s.in_melee=s.distance<=mob.melee_reach+cfg.moving_leeway
                    if not s.in_melee:
                        s.next_swing=math.inf
                ok=True
            else:
                ok=True
        if post_nova_move and s.hp>0:
            perform_move(s,policy.nova_move_yards,level,tal,stats,cfg,mob,rng,m);post_nova_move=False
        if not ok:
            need=_required_mana(action,obj,tal,stats)
            if need>s.mana+EPS:
                # OOM is not a death/failure state.  Wand until the requested
                # policy action becomes affordable (or the wand/ongoing effects
                # kill the mob), then resume the same policy.
                wait=max(.05,_mana_wait_seconds(s,need,level,tal,stats,cfg))
                perform_wand_fallback(s,wait,level,tal,stats,cfg,mob,rng,m)
            else:
                # A non-mana transient failure should be extremely rare; let
                # projectiles/contact/cooldowns advance rather than inventing a
                # penalty or silently changing the policy.
                advance_events(s,.05,level,tal,stats,cfg,mob,rng,m)
        # Damage rolls routinely land a few ulps either side of exact zero.
        # Treat sub-resolution residual HP as dead before the next policy choice.
        if 0.0 < s.hp <= HP_EPS:
            s.hp=0.0
        if steps >= 10000:
            raise RuntimeError(f'simulator stalled at level {level}: {policy_desc(policy, level)}')
    # Let already-launched killing missiles land instead of declaring the fight done early.
    while s.hp>0 and s.projectiles:
        nxt=min(p.impact for p in s.projectiles)
        advance_events(s,max(0,nxt-s.t),level,tal,stats,cfg,mob,rng,m)
    m.kill_time=s.t;m.pushback=s.total_pushback;m.swings=s.damage_taken_swings
    m.melee_contact=s.total_melee_contact; m.min_range=s.min_distance
    # Return cooldowns relative to end of fight; between-pull drink time will tick them down.
    barrier_duration=max(0.0,s.ice_barrier_until-s.t)
    barrier_absorb=max(0.0,s.ice_barrier_absorb) if barrier_duration>EPS else 0.0
    cds=(max(0,s.fireblast_ready-s.t),max(0,s.nova_ready-s.t),max(0,s.blink_ready-s.t),
         max(0,s.combustion_ready-s.t),1.0 if s.combustion_active else 0.0,
         float(s.combustion_crits),float(s.combustion_bonus),
         max(0,s.ice_barrier_ready-s.t),barrier_absorb,barrier_duration)
    mana_left=max(0,s.mana)
    five_sr=max(0.0,s.last_mana_spend+5.0-s.t)
    return m,cds,mana_left,five_sr


def _mage_player_hp_and_armor(level:int,tal:Talents,cfg:SimConfig)->tuple[float,float]:
    gear=forever_crafted_gear(level,cfg.owl_intensity)
    stamina=max(0.0,float(gear.get("stamina_floor",0.0))+float(getattr(cfg,"gear_bonus_stamina",0.0)))
    armor=max(0.0,float(gear.get("armor_floor",0.0))+float(getattr(cfg,"gear_bonus_armor",0.0)))
    return representative_player_hp(level,stamina),armor


def recovery_time(level:int,tal:Talents,mana_left:float,cfg:SimConfig,
                  five_sr_remaining:float=5.0,hp_missing:float=0.0)->float:
    """Shared cross-class recovery: return both HP and mana to 100%.

    The former Mage-only Spirit/drink timing remains useful as a sensitivity
    model, but the cross-class baseline now uses the same ordinary vendor food
    and water tiers as Paladin/Druid.  Mage has no direct self-heal option.
    """
    stats=player_stats_for_config(level,tal,cfg)
    mana_missing=max(0.0,stats.max_mana-mana_left)
    ooc_mps=ooc_mana_regen_per_s(stats)
    r=solve_recovery(level,max(0.0,hp_missing),mana_missing,
                     passive_mana_regen_per_s=ooc_mps,
                     water_override=best_mage_water(level,best_available=bool(cfg.use_best_water)))
    return r.total_s


def simulate_chain_incremental(level:int,tal:Talents,policy:Policy,cfg:SimConfig,target_n:int=100,seed:int=1,
                               hp_mult:float=1.0,continuation:Optional[dict]=None):
    """Run/extend one canonical pull chain and return (metrics, continuation).

    The continuation contains the RNG state, persistent cooldowns and cumulative
    sufficient statistics after exactly ``n`` mobs.  Extending a cached 32-mob
    chain to 64 therefore simulates only mobs 33..64 and is bit-for-bit the same
    stream as a fresh 64-mob run under the same simulator code/config.
    """
    if continuation:
        start_n=int(continuation.get('n',0))
        if start_n>target_n:
            raise ValueError('continuation is beyond requested target_n')
        rng=random.Random()
        rng.setstate(continuation['rng_state'])
        cds=tuple(continuation.get('cooldowns',(0.0,0.0,0.0)))
        total=float(continuation.get('total_s',0.0)); kill=float(continuation.get('kill_s',0.0))
        drink=float(continuation.get('recovery_s',0.0)); mana=float(continuation.get('mana',0.0))
        wand=float(continuation.get('wand_s',0.0)); pb=float(continuation.get('pushback_s',0.0)); sw=float(continuation.get('swings',0.0)); usw=float(continuation.get('unabsorbed_swings',0.0))
        contact=float(continuation.get('melee_contact_s',0.0)); min_range=float(continuation.get('min_range_yards',math.inf))
        damage=float(continuation.get('damage_done',0.0)); wand_damage=float(continuation.get('wand_damage',0.0)); wand_shots=float(continuation.get('wand_shots',0.0))
        total_sq=float(continuation.get('total_sq_s',0.0))
        casts=dict(continuation.get('casts',{}))
    else:
        start_n=0; rng=random.Random(seed); cds=(0.0,0.0,0.0)
        total=kill=drink=mana=wand=pb=sw=usw=damage=wand_damage=wand_shots=contact=0.0; min_range=math.inf; total_sq=0.0; casts={}

    # Sustained leveling baseline: same-level mobs and resource carry across
    # pulls.  A Mage keeps killing while the previous pull says the next one is
    # affordable; only then does the between-pull resource policy use a Mana Gem,
    # Evocation, or food+water.  This removes the old "full reset after every mob"
    # artifact from Int/Spirit/mp5 and policy rankings.
    stats=player_stats_for_config(level,tal,cfg)
    player_hp,player_armor=_mage_player_hp_and_armor(level,tal,cfg)
    current_mana=float(continuation.get('current_mana',stats.max_mana)) if continuation else float(stats.max_mana)
    hp_missing_pool=float(continuation.get('hp_missing_pool',0.0)) if continuation else 0.0
    gem_cd=float(continuation.get('mana_gem_cd_s',0.0)) if continuation else 0.0
    evo_cd=float(continuation.get('evocation_cd_s',0.0)) if continuation else 0.0
    gem_needs_restock=bool(continuation.get('mana_gem_needs_restock',False)) if continuation else False
    prev_spend=float(continuation.get('prev_pull_mana_spent',0.0)) if continuation else 0.0
    gem_uses=int(continuation.get('mana_gem_uses',0)) if continuation else 0
    evo_uses=int(continuation.get('evocation_uses',0)) if continuation else 0
    full_recoveries=int(continuation.get('full_recoveries',0)) if continuation else 0

    def tick_resources(dt:float):
        nonlocal gem_cd,evo_cd,cds
        gem_cd=max(0.0,gem_cd-dt); evo_cd=max(0.0,evo_cd-dt)
        tmp=list(cds)+[0.0]*max(0,10-len(cds))
        for j in (0,1,2,3,7): tmp[j]=max(0.0,tmp[j]-dt)
        tmp[9]=max(0.0,tmp[9]-dt)
        if tmp[9]<=EPS: tmp[8]=0.0
        cds=tuple(tmp[:10])

    def recover_between_pulls(force_full:bool=False)->float:
        nonlocal current_mana,hp_missing_pool,gem_cd,evo_cd,gem_needs_restock,gem_uses,evo_uses,full_recoveries
        if policy.primary == 'arcane_missiles':
            rr=latest(ARCANE_MISSILES,level); primary_floor=float(rr.mana if rr else 0.0)
        else:
            table=SPELLS.get(policy.primary,FROSTBOLT); rr=latest(table,level) if table else None
            if rr is None: primary_floor=0.0
            elif rr.spell == 'arcane_blast': primary_floor=float(stats.base_mana)*float(wh.ARCANE_BLAST_BASE_MANA_PCT)
            else: primary_floor=float(mana_cost(rr,tal,stats))
        need=max(primary_floor,0.80*max(0.0,prev_spend))
        need=min(stats.max_mana,max(0.0,need))
        if not force_full and hp_missing_pool < 0.55*player_hp and current_mana+EPS >= need:
            return 0.0
        profile=cfg.server_profile
        gem=mana_gem_tier(level) if profile.mana_gem_enabled else None
        if (not force_full and gem and gem_cd<=EPS and not gem_needs_restock
                and current_mana+EPS < need and current_mana <= stats.max_mana-0.55*gem.restore):
            current_mana=min(stats.max_mana,current_mana+gem.restore)
            gem_cd=float(profile.mana_gem_cooldown_s); gem_needs_restock=True; gem_uses+=1
            if current_mana+EPS >= need and hp_missing_pool < 0.55*player_hp:
                return 0.0
        if (not force_full and level>=20 and profile.evocation_enabled and evo_cd<=EPS and current_mana+EPS < need
                and hp_missing_pool < 0.55*player_hp):
            gain=stats.max_mana*max(0.0,float(profile.evocation_restore_fraction))
            evo_s=max(0.0,float(profile.evocation_channel_s))
            water=best_mage_water(level,best_available=bool(cfg.use_best_water))
            drink_to_need=max(0.0,need-current_mana)/max(1e-9,water.rate_per_s + ooc_mana_regen_per_s(stats))
            if gain>0 and evo_s <= drink_to_need+EPS:
                current_mana=min(stats.max_mana,current_mana+gain); evo_uses+=1
                evo_cd=max(0.0,float(profile.evocation_cooldown_s))
                tick_resources(evo_s)
                if current_mana+EPS >= need:
                    return evo_s
        ooc_mps=ooc_mana_regen_per_s(stats)
        r=solve_recovery(level,hp_missing_pool,max(0.0,stats.max_mana-current_mana),
                         passive_mana_regen_per_s=ooc_mps,
                         water_override=best_mage_water(level,best_available=bool(cfg.use_best_water)))
        rt=float(r.total_s)
        if gem_needs_restock and mana_gem_tier(level) is not None and profile.mana_gem_enabled:
            rt+=max(0.0,float(profile.mana_gem_restock_s)); gem_needs_restock=False
        current_mana=stats.max_mana; hp_missing_pool=0.0; full_recoveries+=1
        tick_resources(rt)
        return rt

    for i in range(start_n,target_n):
        pre_rt=recover_between_pulls(False) if i>start_n or start_n>0 else 0.0
        ml=level+int(getattr(cfg,"target_level_offset",0))
        swing=(cfg.mob_swing_mix[i%len(cfg.mob_swing_mix)] if cfg.mob_swing_mix else cfg.mob_swing)
        mob=Mob(ml,MOB_BASE_HP[ml]*hp_mult,cfg.mob_speed,swing,cfg.melee_reach)
        damage += mob.hp
        mana_before=current_mana
        fm,cds,mleft,five_sr=simulate_fight(level,tal,mob,policy,cfg,rng,cds,initial_mana=current_mana)
        current_mana=float(mleft)
        prev_spend=max(0.0,mana_before-current_mana)
        raw_hit=normal_world_raw_dps(mob.level)*mob.swing
        hit_after_armor=raw_hit*(1.0-armor_reduction(player_armor,mob.level))
        hp_missing_pool+=float(fm.unabsorbed_swings)*hit_after_armor
        pull_s=fm.kill_time+pre_rt
        total+=pull_s; total_sq+=pull_s*pull_s; kill+=fm.kill_time;drink+=pre_rt;mana+=fm.mana_spent;wand+=fm.wand_time;pb+=fm.pushback;sw+=fm.swings;usw+=fm.unabsorbed_swings
        contact+=fm.melee_contact; min_range=min(min_range,fm.min_range)
        wand_damage+=fm.wand_damage; wand_shots+=fm.wand_shots
        gem_cd=max(0.0,gem_cd-fm.kill_time); evo_cd=max(0.0,evo_cd-fm.kill_time)
        for k,v in fm.casts.items():casts[k]=casts.get(k,0)+v

    # Close the displayed measurement window at a full-resource boundary so
    # N-mob scores are steady-state comparable.  Continuation state itself is
    # saved *before* that synthetic tail, otherwise extending 32 -> 64 mobs
    # would double-count the 32-mob boundary recovery.
    raw_state=(total,drink,cds,current_mana,hp_missing_pool,gem_cd,evo_cd,gem_needs_restock,
               prev_spend,gem_uses,evo_uses,full_recoveries)
    if target_n>start_n:
        tail=recover_between_pulls(True)
        total+=tail; drink+=tail
    travel_total=between_pull_travel_s()*max(0,int(target_n))
    reported_total=total+travel_total
    mean=(reported_total/target_n) if target_n else 0.0
    if target_n>1:
        var=max(0.0,(total_sq-(total*total/target_n))/(target_n-1))
        stderr=math.sqrt(var/target_n)
    else:
        var=0.0; stderr=math.inf
    active_dps=(damage/kill) if kill>EPS else 0.0
    out={'total_s':reported_total,'kill_s':kill,'recovery_s':drink,'travel_s':travel_total,'mana':mana,'wand_s':wand,'wand_shots':wand_shots,'wand_damage':wand_damage,
         'damage_done':damage,'active_dps':active_dps,'pushback_s':pb,'swings':sw,'unabsorbed_swings':usw,
         'melee_contact_s':contact,'min_range_yards':min_range,
         'total_sq_s':total_sq,'mean_s_per_mob':mean,'stderr_s_per_mob':stderr,
         'mana_gem_uses':gem_uses,'evocation_uses':evo_uses,'full_recoveries':full_recoveries,
         'recovery_solver_id':RECOVERY_SOLVER_ID}
    for k,v in casts.items():out['casts_'+k]=v
    (raw_total,raw_drink,raw_cds,raw_mana,raw_hp,raw_gem_cd,raw_evo_cd,raw_restock,
     raw_prev_spend,raw_gem_uses,raw_evo_uses,raw_full_recoveries)=raw_state
    state={'n':int(target_n),'rng_state':rng.getstate(),'cooldowns':tuple(raw_cds),
           'total_s':raw_total,'kill_s':kill,'recovery_s':raw_drink,'mana':mana,'wand_s':wand,'wand_shots':wand_shots,'wand_damage':wand_damage,'damage_done':damage,
           'pushback_s':pb,'swings':sw,'unabsorbed_swings':usw,'melee_contact_s':contact,'min_range_yards':min_range,
           'total_sq_s':total_sq,'casts':casts,'current_mana':raw_mana,'hp_missing_pool':raw_hp,
           'mana_gem_cd_s':raw_gem_cd,'evocation_cd_s':raw_evo_cd,'mana_gem_needs_restock':raw_restock,'prev_pull_mana_spent':raw_prev_spend,
           'mana_gem_uses':raw_gem_uses,'evocation_uses':raw_evo_uses,'full_recoveries':raw_full_recoveries}
    return out,state

def simulate_chain(level:int,tal:Talents,policy:Policy,cfg:SimConfig,n:int=100,seed:int=1,
                   hp_mult:float=1.0)->Dict[str,float]:
    out,_=simulate_chain_incremental(level,tal,policy,cfg,target_n=n,seed=seed,hp_mult=hp_mult)
    return out



def with_ice_barrier_policy_variants(policies:Iterable[Policy], level:int, talents:Talents)->List[Policy]:
    """Return policy basis plus explicit Ice Barrier-use variants when legal.

    Taking the talent only grants the button.  It must never force every pull to
    spend mana/GCD on Barrier: search compares otherwise-identical policies with
    and without pre-pull Barrier and keeps whichever wins the objective.
    """
    base=list(policies)
    if not talents.ice_barrier or ice_barrier_rank(level) is None:
        return base
    out=[]
    for pol in base:
        out.append(pol)
        if not pol.use_ice_barrier:
            out.append(replace(pol,name=pol.name+'+Barrier',use_ice_barrier=True))
    seen=set(); dedup=[]
    for pol in out:
        key=tuple(getattr(pol,f) for f in pol.__dataclass_fields__ if f!='name')
        if key not in seen:
            seen.add(key); dedup.append(pol)
    return dedup

def candidate_policies(level:int)->List[Policy]:
    """Full policy grid for final per-level validation.

    Fire cadence is a talent-independent periodic policy.  Search covers both
    block lengths and phase offsets, so one FBa3/Sc3 cycle can represent starts
    such as FBa,FBa,Sc,Sc,Sc,FBa... or Sc,Sc,Sc,FBa,FBa,FBa....  Frost Nova
    can either stay reactive (melee utility) or be conditionally inserted at an
    optimizer-selected cadence position.  Pyroblast remains an opener choice.
    """
    base=[]
    scheduled_nova=[]
    for primary in ('frostbolt','fireball','arcane_missiles','arcane_blast'):
        if latest(SPELLS[primary],level) is None:
            continue
        base.append(Policy(primary.upper()+' pure',primary,use_fireblast=False,use_nova=False,use_blink=False))
        for ex in (.10,.18,.28):
            for cc in (False, True):
                p=Policy(
                    f'{primary}+execute/nova'+('+CCAM' if cc else ''),
                    primary=primary,
                    use_fireblast=True,
                    fireblast_execute_frac=ex,
                    use_nova=True,
                    nova_rank1=True,
                    nova_move_yards=6,
                    use_blink=True,
                    blink_min_hp_frac=.35,
                    clearcast_am=cc,
                )
                base.append(p)
                if primary=='fireball':
                    base.append(replace(p,name=p.name+'+FBoR1-open',fbo_r1_mode='opener'))
                    base.append(replace(p,name=p.name+'+FBoR1-maint',fbo_r1_mode='maintain'))

    if latest(SCORCH,level):
        p=Policy('Sc pure',primary='scorch',use_fireblast=True,use_nova=True,nova_rank1=True,
                 nova_move_yards=6,use_blink=True)
        base.append(p)
        for mode in ('opener','maintain'):
            base.append(replace(p,name=f'Sc+FBoR1-{mode}',fbo_r1_mode=mode))

        # Search the cadence itself, including phase.  Scorch blocks up to three
        # explicitly cover the previously-missing Sc,Sc,Sc examples.
        for fb_n in (1,2,3,4,6):
            for sc_n in (1,2,3):
                cycle=fb_n+sc_n
                for phase in range(cycle):
                    suffix=f'@{phase}' if phase else ''
                    p=Policy(f'FBa{fb_n}/Sc{sc_n}{suffix}',primary='fireball',
                             use_fireblast=True,use_nova=True,nova_rank1=True,
                             nova_move_yards=6,use_blink=True,
                             fireball_block=fb_n,scorch_block=sc_n,
                             fire_cycle_phase=phase)
                    base.append(p)
                    # Keep one utility-Frostbolt variant per cadence/phase.
                    base.append(replace(p,name=p.name+'+FBoR1-maint',fbo_r1_mode='maintain'))

                    # Scheduled-Nova variants deliberately stay on one fixed
                    # Nova rank/step configuration to avoid a combinatorial
                    # FN-rank x movement x position explosion. Reactive variants
                    # below still search those utility parameters independently.
                    for nova_pos in range(cycle):
                        scheduled_nova.append(replace(
                            p, name=p.name+f'+FN@{nova_pos}', nova_cycle_pos=nova_pos,
                            nova_rank1=True, nova_move_yards=6))

    # Pyroblast is an opener strategy. Add it to normal Fire policies and to
    # scheduled-Nova cadence policies; optimize_policy talent-gates it.
    if latest(PYROBLAST,level):
        fire_openers=[]
        for p in base:
            if p.primary in ('fireball','scorch'):
                fire_openers.append(replace(p,name=p.name+'+PyroOpen',pyro_opener=True))
        base.extend(fire_openers)
        scheduled_nova += [replace(p,name=p.name+'+PyroOpen',pyro_opener=True)
                           for p in list(scheduled_nova)]

    nova_variants=[]
    for p in base:
        if p.use_nova:
            nova_variants.append(p)
            maxr=latest(FROST_NOVA,level)
            if maxr and maxr.rank>1:
                nova_variants.append(replace(p,name=p.name+' FNmax',nova_rank1=False))
        else:
            nova_variants.append(p)

    out=[]
    for p in nova_variants:
        out.append(p)
        if p.use_nova:
            for y in (4,5,6,8,10):
                out.append(replace(p,name=p.name+f' step{y}',nova_move_yards=y))
    # Scheduled-Nova policies are already a broad positional search. Keep them
    # fixed at R1/step6 and append without the generic utility cross-product.
    out.extend(scheduled_nova)

    seen=set(); dedup=[]
    for p in out:
        key=tuple(getattr(p,f) for f in p.__dataclass_fields__ if f!='name')
        if key not in seen:
            seen.add(key); dedup.append(p)
    return dedup

def candidate_fire_cadence_policies(level:int)->List[Policy]:
    """Focused Fireball/Scorch cadence basis used by the live optimizer.

    This searches block lengths and every phase offset without depending on
    Improved Scorch rank. Nova/Pyro insertions are layered on adaptively by the
    cached policy optimizer so the common path does not pay the full cross-product.
    """
    if latest(FIREBALL,level) is None or latest(SCORCH,level) is None:
        return []
    out=[]
    for fb_n in (1,2,3,4):
        for sc_n in (1,2,3):
            cycle=fb_n+sc_n
            for phase in range(cycle):
                suffix=f'@{phase}' if phase else ''
                out.append(Policy(
                    f'FBa{fb_n}/Sc{sc_n}{suffix}', primary='fireball',
                    use_fireblast=True, fireblast_execute_frac=.22,
                    use_nova=True, nova_rank1=True, nova_move_yards=5,
                    use_blink=True, blink_min_hp_frac=.35,
                    fireball_block=fb_n, scorch_block=sc_n,
                    fire_cycle_phase=phase))
    return out


def candidate_policies_coarse(level:int)->List[Policy]:
    """Very small policy basis for the outer talent beam.

    The beam's job is to discover promising talent states, not to solve the
    final rotation. Finalists are re-optimized against candidate_policies().
    """
    ps=[]
    if latest(FROSTBOLT,level):
        ps += [
            Policy('FBo pure','frostbolt',use_fireblast=False,use_nova=False,use_blink=False),
            Policy('FBo ctl FN1','frostbolt',use_fireblast=True,fireblast_execute_frac=.22,
                   use_nova=True,nova_rank1=True,nova_move_yards=5,use_blink=True,blink_min_hp_frac=.35),
            Policy('FBo ctl FN1 CCAM','frostbolt',use_fireblast=True,fireblast_execute_frac=.22,
                   use_nova=True,nova_rank1=True,nova_move_yards=5,use_blink=True,blink_min_hp_frac=.35,
                   clearcast_am=True),
        ]
        mx=latest(FROST_NOVA,level)
        if mx and mx.rank>1:
            ps.append(Policy('FBo ctl FNmax','frostbolt',use_fireblast=True,fireblast_execute_frac=.22,
                             use_nova=True,nova_rank1=False,nova_move_yards=5,use_blink=True,blink_min_hp_frac=.35))
    if latest(FIREBALL,level):
        ps += [
            Policy('FBa pure','fireball',use_fireblast=False,use_nova=False,use_blink=False),
            Policy('FBa ctl','fireball',use_fireblast=True,fireblast_execute_frac=.22,
                   use_nova=True,nova_rank1=True,nova_move_yards=5,use_blink=True,blink_min_hp_frac=.35),
            Policy('FBa ctl +FBoR1','fireball',use_fireblast=True,fireblast_execute_frac=.22,
                   use_nova=True,nova_rank1=True,nova_move_yards=5,use_blink=True,blink_min_hp_frac=.35,
                   fbo_r1_mode='maintain'),
        ]
        if latest(PYROBLAST,level):
            ps.append(Policy('FBa ctl +PyroOpen','fireball',use_fireblast=True,fireblast_execute_frac=.22,
                             use_nova=True,nova_rank1=True,nova_move_yards=5,use_blink=True,
                             blink_min_hp_frac=.35,pyro_opener=True))
    if latest(ARCANE_MISSILES,level):
        ps.append(Policy('AM ctl','arcane_missiles',use_fireblast=True,fireblast_execute_frac=.22,
                         use_nova=True,nova_rank1=True,nova_move_yards=5,use_blink=True,blink_min_hp_frac=.35))
    if latest(ARCANE_BLAST,level):
        ps.append(Policy('AB proc ctl','arcane_blast',use_fireblast=True,fireblast_execute_frac=.22,
                         use_nova=True,nova_rank1=True,nova_move_yards=5,use_blink=True,blink_min_hp_frac=.35,
                         use_proc_ice_lance=True,use_missile_barrage=True))
    if latest(SCORCH,level):
        ps += [
            Policy('Sc ctl','scorch',use_fireblast=True,fireblast_execute_frac=.22,
                   use_nova=True,nova_rank1=True,nova_move_yards=5,use_blink=True),
            Policy('FBa3/Sc1','fireball',use_fireblast=True,fireblast_execute_frac=.22,
                   use_nova=True,nova_rank1=True,nova_move_yards=5,use_blink=True,
                   fireball_block=3,scorch_block=1),
            Policy('FBa2/Sc2','fireball',use_fireblast=True,fireblast_execute_frac=.22,
                   use_nova=True,nova_rank1=True,nova_move_yards=5,use_blink=True,
                   fireball_block=2,scorch_block=2),
        ]
    return ps


def policy_legal_for_talents(p:Policy, t:Talents, level:int) -> bool:
    """Whether every rotation-changing action in ``p`` is actually unlocked.

    The old search treated spell-rank availability as equivalent to talent
    availability.  Forever breaks that assumption: Arcane Blast and Ice Lance
    exist in the spell table before a build has bought their talent.  Keeping
    legality here makes policy generation, A/B tooling and the outer talent
    beam share one contract.
    """
    if p.primary == 'arcane_blast' and not t.arcane_blast:
        return False
    if p.use_proc_ice_lance and not t.ice_lance:
        return False
    if p.hot_streak_pyro_stacks > 0 and not (t.hot_streak and t.pyroblast):
        return False
    if p.pyro_opener and not t.pyroblast:
        return False
    if p.use_ice_barrier and not t.ice_barrier:
        return False
    # A stack cycle needs both the unlocked AB button and a learned AM rank.
    if p.arcane_blast_to_stacks > 0:
        if not t.arcane_blast or latest(ARCANE_MISSILES, level) is None:
            return False
    return True


def guide_meta_policy(level:int, t:Talents, school:str) -> Policy:
    """Named source-anchored leveling policy used as a prior, never a winner.

    These policies intentionally stay compact.  ``policy_search`` competes the
    prior against nearby legal variants, so a guide rotation can lose cleanly.
    """
    school=str(school).lower()
    if school == 'frost':
        if not t.ice_lance:
            return Policy('Frost guide baseline', 'frostbolt', use_fireblast=True,
                          fireblast_execute_frac=.22, use_nova=True, nova_rank1=True,
                          nova_move_yards=5, use_blink=True, blink_min_hp_frac=.35)
        return Policy('Frost guide meta: FoF/Frozen→IL', 'frostbolt',
                      use_fireblast=True, fireblast_execute_frac=.22,
                      use_nova=True, nova_rank1=True, nova_move_yards=5,
                      use_blink=True, blink_min_hp_frac=.35,
                      use_proc_ice_lance=True, ice_lance_move_away=True)
    if school == 'arcane':
        if not t.arcane_blast:
            return Policy('Arcane guide baseline: AM', 'arcane_missiles',
                          use_fireblast=True, fireblast_execute_frac=.22,
                          use_nova=True, nova_rank1=True, nova_move_yards=5,
                          use_blink=True, blink_min_hp_frac=.35)
        return Policy('Arcane guide meta: AB3→AM', 'arcane_blast',
                      use_fireblast=True, fireblast_execute_frac=.22,
                      use_nova=True, nova_rank1=True, nova_move_yards=5,
                      use_blink=True, blink_min_hp_frac=.35,
                      arcane_blast_to_stacks=3, use_missile_barrage=True)
    if school == 'fire':
        base=Policy('Fire guide baseline', 'fireball', use_fireblast=True,
                    fireblast_execute_frac=.22, use_nova=True, nova_rank1=True,
                    nova_move_yards=5, use_blink=True, blink_min_hp_frac=.35,
                    pyro_opener=bool(t.pyroblast))
        if t.hot_streak and t.pyroblast:
            return replace(base, name='Fire guide meta: HS3→Pyro', hot_streak_pyro_stacks=3)
        return base
    raise ValueError(f'unknown school {school!r}')


def _focused_policy_family(level:int, t:Talents, school:Optional[str]=None) -> List[Policy]:
    """Small build-gated family for structural talent valuation / quick search."""
    schools=(str(school).lower(),) if school else ('frost','arcane','fire')
    out=[]
    for sc in schools:
        if sc=='frost' and latest(FROSTBOLT,level):
            controls=[
                Policy('Frost control: FBo spam','frostbolt',use_fireblast=False,use_nova=False,use_blink=False),
                Policy('Frost control: FBo+control','frostbolt',use_fireblast=True,fireblast_execute_frac=.22,
                       use_nova=True,nova_rank1=True,nova_move_yards=5,use_blink=True,blink_min_hp_frac=.35),
            ]
            out.extend(controls)
            if t.ice_lance and latest(ICE_LANCE,level):
                for c in controls:
                    out.append(replace(c,name=c.name+' + Frozen/FoF→IL',use_proc_ice_lance=True,ice_lance_move_away=True))
                out.append(guide_meta_policy(level,t,'frost'))
        elif sc=='arcane' and latest(ARCANE_MISSILES,level):
            out.append(Policy('Arcane control: AM','arcane_missiles',use_fireblast=True,fireblast_execute_frac=.22,
                              use_nova=True,nova_rank1=True,nova_move_yards=5,use_blink=True,blink_min_hp_frac=.35))
            if t.arcane_blast and latest(ARCANE_BLAST,level):
                for stacks in (1,2,3,4):
                    out.append(Policy(f'Arcane AB{stacks}→AM','arcane_blast',use_fireblast=True,
                                      fireblast_execute_frac=.22,use_nova=True,nova_rank1=True,nova_move_yards=5,
                                      use_blink=True,blink_min_hp_frac=.35,arcane_blast_to_stacks=stacks,
                                      use_missile_barrage=True))
                out.append(guide_meta_policy(level,t,'arcane'))
        elif sc=='fire' and latest(FIREBALL,level):
            base=guide_meta_policy(level,t,'fire')
            out.append(replace(base,name='Fire control: FBa',hot_streak_pyro_stacks=0))
            if latest(SCORCH,level):
                out.extend([
                    Policy('Fire FBa3/Sc1','fireball',use_fireblast=True,fireblast_execute_frac=.22,
                           use_nova=True,nova_rank1=True,nova_move_yards=5,use_blink=True,blink_min_hp_frac=.35,
                           fireball_block=3,scorch_block=1,pyro_opener=bool(t.pyroblast)),
                    Policy('Fire FBa2/Sc2','fireball',use_fireblast=True,fireblast_execute_frac=.22,
                           use_nova=True,nova_rank1=True,nova_move_yards=5,use_blink=True,blink_min_hp_frac=.35,
                           fireball_block=2,scorch_block=2,pyro_opener=bool(t.pyroblast)),
                ])
            if t.hot_streak and t.pyroblast:
                for threshold in (1,2,3):
                    out.append(replace(base,name=f'Fire HS{threshold}→Pyro',hot_streak_pyro_stacks=threshold))
                out.append(guide_meta_policy(level,t,'fire'))
    # Apply legality and semantic deduplication.
    seen=set(); legal=[]
    for pol in out:
        if not policy_legal_for_talents(pol,t,level):
            continue
        key=tuple(getattr(pol,f) for f in pol.__dataclass_fields__ if f!='name')
        if key not in seen:
            seen.add(key); legal.append(pol)
    return legal


def candidate_policies_for_build(level:int, t:Talents, *, coarse:bool=False,
                                 focused:bool=False, school:Optional[str]=None) -> List[Policy]:
    """Build-aware policy set; structural rotations appear only after unlock."""
    if focused:
        policies=_focused_policy_family(level,t,school=school)
    else:
        policies=(candidate_policies_coarse(level) if coarse else candidate_policies(level))
        # Add bounded structural families without multiplying the legacy grid.
        policies=list(policies)+_focused_policy_family(level,t,school=school)
    policies=with_ice_barrier_policy_variants(policies,level,t)
    policies=filter_policies_by_primary_school(policies,school)
    policies=[p for p in policies if policy_legal_for_talents(p,t,level)]
    # M47 bounded finisher search: expand Frost policies only, avoiding a 4x
    # cross-product over every Fire/Arcane cadence. This is enough to make the
    # current Frost leveling winner compete on observable-HP wand finishing.
    if not coarse:
        frost=[p for p in policies if p.primary=='frostbolt']
        policies=list(policies)+[replace(p,name=p.name+f' + Wand≤{hits}',wand_finisher_max_hits=hits)
                                 for p in frost for hits in (1,2,3)]
    seen=set(); out=[]
    for pol in policies:
        key=tuple(getattr(pol,f) for f in pol.__dataclass_fields__ if f!='name')
        if key not in seen:
            seen.add(key); out.append(pol)
    return out


def _policy_result_summary(policy:Policy, result:Dict[str,float], n:int) -> Dict[str,object]:
    mean=float(result['total_s'])/max(1,int(n))
    return {
        'policy':policy.name,
        'rotation':policy_desc(policy,0),
        'mobs_per_hour':3600.0/mean if mean>0 else math.inf,
        'seconds_per_mob':mean,
        'kill_seconds_per_mob':float(result.get('kill_s',0.0))/max(1,int(n)),
        'recovery_seconds_per_mob':float(result.get('recovery_s',0.0))/max(1,int(n)),
        'travel_seconds_per_mob':float(result.get('travel_s',0.0))/max(1,int(n)),
        'pushback_seconds_per_mob':float(result.get('pushback_s',0.0))/max(1,int(n)),
        'melee_contact_seconds_per_mob':float(result.get('melee_contact_s',0.0))/max(1,int(n)),
        'swings_per_mob':float(result.get('swings',0.0))/max(1,int(n)),
        'min_range_yards':float(result.get('min_range_yards',math.inf)),
        'casts':{k[6:]:v for k,v in result.items() if k.startswith('casts_')},
        'recovery_solver_id':result.get('recovery_solver_id'),
    }


def policy_ab(level:int, t:Talents, cfg:SimConfig, school:str, *, n:int=32, seed:int=1) -> Dict[str,object]:
    """Fixed-build causal A/B: simple baseline rotation vs named guide meta."""
    school=str(school).lower()
    if school=='frost':
        baseline=Policy('Frostbolt spam','frostbolt',use_fireblast=False,use_nova=False,use_blink=False)
    elif school=='arcane':
        baseline=Policy('Arcane Missiles baseline','arcane_missiles',use_fireblast=False,use_nova=False,use_blink=False)
    elif school=='fire':
        baseline=Policy('Fireball baseline','fireball',use_fireblast=False,use_nova=False,use_blink=False,
                        pyro_opener=bool(t.pyroblast))
    else:
        raise ValueError(school)
    meta=guide_meta_policy(level,t,school)
    if not policy_legal_for_talents(meta,t,level):
        raise ValueError(f'guide meta policy is not legal for {school} build')
    rb=simulate_chain(level,t,baseline,cfg,n=n,seed=seed)
    rm=simulate_chain(level,t,meta,cfg,n=n,seed=seed)
    sb=_policy_result_summary(baseline,rb,n); sm=_policy_result_summary(meta,rm,n)
    return {'question':'policy_ab','school':school,'baseline':sb,'meta':sm,
            'delta_mobs_per_hour':float(sm['mobs_per_hour'])-float(sb['mobs_per_hour']),
            'delta_seconds_per_mob':float(sm['seconds_per_mob'])-float(sb['seconds_per_mob'])}


def policy_search(level:int, t:Talents, cfg:SimConfig, school:str, *, n:int=32, seed:int=1) -> Dict[str,object]:
    """Fixed-build comparison of the guide prior against best focused policy found."""
    meta=guide_meta_policy(level,t,school)
    rm=simulate_chain(level,t,meta,cfg,n=n,seed=seed)
    best=None
    for i,pol in enumerate(candidate_policies_for_build(level,t,focused=True,school=school)):
        r=simulate_chain(level,t,pol,cfg,n=n,seed=seed)
        if best is None or r['total_s']<best[1]['total_s']:
            best=(pol,r)
    if best is None:
        raise RuntimeError(f'no legal focused policies for {school}')
    sm=_policy_result_summary(meta,rm,n); sb=_policy_result_summary(best[0],best[1],n)
    return {'question':'policy_search','school':str(school).lower(),'meta':sm,'best_found':sb,
            'meta_regret_seconds_per_mob':float(sm['seconds_per_mob'])-float(sb['seconds_per_mob']),
            'meta_regret_mobs_per_hour':float(sb['mobs_per_hour'])-float(sm['mobs_per_hour'])}


def talent_value(level:int, without:Talents, with_unlock:Talents, cfg:SimConfig, *,
                 school:str, n:int=32, seed:int=1) -> Dict[str,object]:
    """Net value of a structural talent with each build using its own best policy."""
    def best_for(t:Talents):
        best=None
        for pol in candidate_policies_for_build(level,t,focused=True,school=school):
            r=simulate_chain(level,t,pol,cfg,n=n,seed=seed)
            if best is None or r['total_s'] < best[1]['total_s']:
                best=(pol,r)
        if best is None:
            raise RuntimeError(f'no focused policies for {school}')
        return best
    a=best_for(without); b=best_for(with_unlock)
    sa=_policy_result_summary(a[0],a[1],n); sb=_policy_result_summary(b[0],b[1],n)
    return {'question':'talent_value','school':str(school).lower(),'without':sa,'with':sb,
            'delta_mobs_per_hour':float(sb['mobs_per_hour'])-float(sa['mobs_per_hour']),
            'delta_seconds_per_mob':float(sb['seconds_per_mob'])-float(sa['seconds_per_mob'])}

def optimize_policy(level:int,tal:Talents,cfg:SimConfig,n:int=40,seed:int=1,coarse:bool=False)->Tuple[Policy,Dict[str,float]]:
    best=None
    policies=candidate_policies_for_build(level,tal,coarse=coarse)
    if coarse:
        # AM is a deliberately expensive channel to simulate when it is repeatedly
        # pushback/health limited.  For talent discovery, only test it once the path
        # has actually invested in AM/Arcane proc support; the first such point is
        # itself generated by the talent beam, so Arcane paths remain discoverable.
        policies=[p for p in policies
                  if p.primary!='arcane_missiles' or tal.imp_arcane_missiles>0 or tal.arcane_concentration>0]
    else:
        # Remove policies that are behaviorally identical for this talent state.
        policies=[p for p in policies
                  if (not p.clearcast_am or tal.arcane_concentration>0)
                  and (not p.pyro_opener or tal.pyroblast>0)]
    if coarse:
        policies=[p for p in policies if (not p.pyro_opener or tal.pyroblast>0)]
    for i,p in enumerate(policies):
        r=simulate_chain(level,tal,p,cfg,n=n,seed=seed)
        if best is None or r['total_s']<best[1]['total_s']:best=(p,r)
    return best

# -------------------------- talent optimizer -------------------------------

@dataclass
class PathState:
    talents:Talents
    cumulative_s:float
    path:List[Tuple[int,str,Policy,float]]


def talent_key(t:Talents):
    return tuple(getattr(t,f) for f in t.__dataclass_fields__)


def talent_preference_key(t:Talents):
    """Deterministic secondary ordering for mechanically tied allocations.

    This key only acts after the modeled speed score ties.  Prefer real optional
    utility/future payoff over synthetic or objective-neutral gate spend:

    * Arcane Subtlety weakly dominates synthetic Arcane filler on the baseline
      and can help against reducible resistance.
    * Ice Block is neutral in the current no-death ST objective but is the real
      prerequisite for Ice Barrier.  Keeping that tied branch alive prevents the
      structural beam from pruning Barrier one point before it unlocks.
    * Taking Ice Barrier grants an optional button; because policy search keeps
      both Barrier-OFF and Barrier-ON, the talent itself cannot make a tied build
      worse and should survive over a neutral filler point.
    """
    return (int(t.arcane_filler), -int(t.arcane_subtlety),
            -int(t.ice_barrier), -int(t.ice_block), talent_key(t))



# Talents that open a qualitatively different policy family.  The outer beam
# keeps one progression frontier toward each target so an unlock is not pruned
# merely because the incumbent rotation cannot use a future button yet.
STRUCTURAL_POLICY_UNLOCKS = {
    'ice_lance': 'frost',
    'fingers_of_frost': 'frost',
    'arcane_blast': 'arcane',
    'missile_barrage': 'arcane',
    'hot_streak': 'fire',
}


def _structural_progress_key(t:Talents, target:str) -> tuple:
    tree, _mx, need, pre = TALENT_RULES[target]
    pre_met = 1 if (pre is None or getattr(t,pre[0]) >= pre[1]) else 0
    unlocked = 1 if getattr(t,target) > 0 else 0
    # Once the target is unlocked, keep its rank first; before that, preserve
    # the prerequisite and deepest legal tree progression toward its row.
    return (unlocked, getattr(t,target), pre_met, min(tree_points(t,tree), need), tree_points(t,tree))


def _retain_structural_frontiers(ranked:List[PathState], beam_width:int) -> List[PathState]:
    if not ranked:
        return []
    chosen=list(ranked[:beam_width])
    seen={talent_key(x.talents) for x in chosen}
    for target in STRUCTURAL_POLICY_UNLOCKS:
        best=max(ranked, key=lambda st: (_structural_progress_key(st.talents,target), -st.cumulative_s))
        key=talent_key(best.talents)
        if key not in seen:
            chosen.append(best); seen.add(key)
    return chosen

def talent_candidates(t:Talents)->List[Tuple[str,Talents]]:
    out=[]
    for name in TALENT_RULES:
        if legal_add(t,name):
            out.append((name,add_point(t,name)))
    return out


def optimize_talent_path(start_level:int=11,end_level:int=60,cfg:SimConfig=SimConfig(),
                         beam_width:int=10,mobs_per_level:int=8,seed:int=11,
                         start_talents:Talents=Talents())->PathState:
    """Coarse joint talent/policy beam search.

    Level L is evaluated after spending the point earned at L (so a level-11
    run starting from an empty tree spends two points before its first scored
    level: one representing level 10, one level 11).  For speed this stage uses
    a short same-level mob chain; finalists should be revalidated with 100+ mobs.
    """
    states=[PathState(start_talents,0.0,[])]
    # spend points from 10 through end_level. If start_level > 10, points before
    # start_level still matter to legal structure but are scored only once the
    # requested window begins.
    for lvl in range(10,end_level+1):
        nxt={}
        score_cache={}
        for st in states:
            for name,nt in talent_candidates(st.talents):
                if nt.points()!=lvl-9:
                    continue
                if lvl < start_level:
                    cand=PathState(nt,st.cumulative_s,st.path+[(lvl,name,Policy('unscored'),0.0)])
                else:
                    tk=talent_key(nt)
                    cached=score_cache.get(tk)
                    if cached is None:
                        pol,res=optimize_policy(lvl,nt,cfg,n=mobs_per_level,seed=seed+lvl*7919,coarse=True)
                        score=res['total_s']*(100.0/mobs_per_level)
                        score_cache[tk]=(pol,score)
                    else:
                        pol,score=cached
                    cand=PathState(nt,st.cumulative_s+score,st.path+[(lvl,name,pol,score)])
                k=talent_key(nt)
                old=nxt.get(k)
                if old is None or cand.cumulative_s<old.cumulative_s:
                    nxt[k]=cand
        if lvl < start_level:
            states=list(nxt.values())
        else:
            ranked=sorted(nxt.values(),key=lambda x:x.cumulative_s)
            states=_retain_structural_frontiers(ranked,beam_width)
        if not states:
            raise RuntimeError(f'beam exhausted at level {lvl}')
    return min(states,key=lambda x:x.cumulative_s)



def optimize_talent_paths(start_level:int=11,end_level:int=60,cfg:SimConfig=SimConfig(),
                          beam_width:int=10,mobs_per_level:int=8,seed:int=11,
                          start_talents:Talents=Talents(),top_k:int=5)->List[PathState]:
    """Return the top-K final talent paths retained by the beam.

    Same search as optimize_talent_path(), but preserves the final ranking so
    the report can show runner-up builds rather than only the winner.
    """
    states=[PathState(start_talents,0.0,[])]
    for lvl in range(10,end_level+1):
        nxt={}
        score_cache={}
        for st in states:
            for name,nt in talent_candidates(st.talents):
                if nt.points()!=lvl-9:
                    continue
                if lvl < start_level:
                    cand=PathState(nt,st.cumulative_s,st.path+[(lvl,name,Policy('unscored'),0.0)])
                else:
                    tk=talent_key(nt)
                    cached=score_cache.get(tk)
                    if cached is None:
                        pol,res=optimize_policy(lvl,nt,cfg,n=mobs_per_level,seed=seed+lvl*7919,coarse=True)
                        score=res['total_s']*(100.0/mobs_per_level)
                        score_cache[tk]=(pol,score)
                    else:
                        pol,score=cached
                    cand=PathState(nt,st.cumulative_s+score,st.path+[(lvl,name,pol,score)])
                k=talent_key(nt)
                old=nxt.get(k)
                if old is None or cand.cumulative_s<old.cumulative_s:
                    nxt[k]=cand
        ranked=sorted(nxt.values(),key=lambda x:x.cumulative_s)
        states=ranked if lvl < start_level else _retain_structural_frontiers(ranked,beam_width)
        if not states:
            raise RuntimeError(f'beam exhausted at level {lvl}')
    return sorted(states,key=lambda x:x.cumulative_s)[:max(1,top_k)]

def final_allocation(t:Talents)->str:
    parts=[]
    for name in t.__dataclass_fields__:
        v=getattr(t,name)
        if v:
            parts.append(f'{name}={v}')
    return ', '.join(parts)

def policy_desc(p:Policy,level:int)->str:
    ab={'frostbolt':'FBo','fireball':'FBa','arcane_missiles':'AM','arcane_blast':'AB','scorch':'Sc'}
    bits=[ab.get(p.primary,p.primary)]
    if p.fireball_block and p.scorch_block:
        bits=[f'FBa{p.fireball_block}/Sc{p.scorch_block}']
        if p.fire_cycle_phase:
            bits.append(f'Phase={p.fire_cycle_phase}')
    elif p.scorch_to_stacks:
        # Legacy replay descriptor only; new search does not emit this policy.
        bits=[f'Sc×{p.scorch_to_stacks}→FBa']
    if p.pyro_opener:
        bits.append('PyroOpen')
    if p.fbo_r1_mode!='none':
        bits.append(f'FBoR1:{p.fbo_r1_mode}')
    if p.use_fireblast:
        bits.append(f'FBl≤{int(round(p.fireblast_execute_frac*100))}%')
    if p.use_nova:
        nr='R1' if p.nova_rank1 else 'max'
        bits.append(f'FN{nr}+step{p.nova_move_yards:g}')
        if p.nova_cycle_pos >= 0:
            bits.append(f'FNpos={p.nova_cycle_pos}')
    if p.use_blink and level>=20:
        bits.append(f'Blink≥{int(round(p.blink_min_hp_frac*100))}%')
    if p.use_ice_barrier and ice_barrier_rank(level) is not None:
        bits.append('IceBarrier')
    if p.clearcast_am:
        bits.append('CC→AM')
    if getattr(p,'use_proc_ice_lance',False):
        bits.append('Frozen/FoF→IL(move)' if getattr(p,'ice_lance_move_away',False) else 'Frozen/FoF→IL')
    if getattr(p,'arcane_blast_to_stacks',0)>0:
        bits.append(f'AB×{p.arcane_blast_to_stacks}→AM')
    if getattr(p,'hot_streak_pyro_stacks',0)>0:
        bits.append(f'HS×{p.hot_streak_pyro_stacks}→Pyro')
    if getattr(p,'wand_finisher_max_hits',0)>0:
        bits.append(f'HP→Wand≤{int(p.wand_finisher_max_hits)}')
    return ' | '.join(bits)

