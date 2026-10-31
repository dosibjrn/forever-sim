from __future__ import annotations

"""Analytical steady-state wrapper around the deterministic fight kernel.

This is intentionally the opposite extreme from the v1 Monte-Carlo chain:

* ordinary RNG is already reduced to expectations by ``expected_engine``;
* +1/+2 mobs are two deterministic workload classes, not samples;
* cooldown availability is solved as a small fixed point over ready fractions;
* Clearcasting is a probability/mana expectation carried inside one fight;
* Combustion is reduced to a long-run expected crit contribution and solved by
  a tiny outer fixed point.

For a fixed level/build/policy the expensive objects are therefore only the
2^k ready/down fight outcomes for the k cooldowns that can change decisions.
The steady-state itself is algebraic blending; there is no pull-chain loop.
"""

from dataclasses import dataclass, replace
from functools import lru_cache
import itertools
import math
from typing import Dict, Iterable, Mapping, Sequence

from src.engine_registry import eng
from src.shared.leveling.timing import between_pull_travel_s
from .expected_engine import CooldownState, ExpectedState, expected_direct_components, simulate_fight_expected, score_policy as score_policy_expected

EPS=1e-12


@dataclass(frozen=True)
class AnalyticOptions:
    mob_offsets: tuple[int,...]=(1,2)
    workload_weights: tuple[float,...]=(0.5,0.5)
    representative_swing: float=2.0
    cooldown_max_iter: int=24
    cooldown_tol: float=1e-7
    cooldown_damping: float=0.55
    combustion_max_iter: int=4
    combustion_tol: float=2e-4
    # 'marginal': baseline + one ready-delta per cooldown (<= 1+k states).
    # 'joint': full 2^k ready/down table, retained as a validation mode.
    cooldown_model: str='marginal'
    # Smooth discrete kill thresholds analytically. 'normal2' estimates the
    # cumulative direct-damage variance and evaluates two deterministic effective
    # HP thresholds at +/- one sigma; no random samples are drawn.
    kill_boundary_model: str='hard'  # hard | normal2 | normal5q
    kill_boundary_sigma_scale: float=1.0
    kill_boundary_sigma_cap: float=0.22


@dataclass(frozen=True)
class _CDSpec:
    name: str
    cooldown_s: float
    cast_key: str


def _active_cooldowns(level:int, talents:eng.Talents, policy:eng.Policy)->tuple[_CDSpec,...]:
    out=[]
    if policy.use_fireblast:
        r=eng.latest(eng.FIRE_BLAST,level)
        if r is not None:
            out.append(_CDSpec('fire_blast',max(1.0,r.cooldown-0.5*talents.imp_fire_blast),'fire_blast'))
    if policy.use_nova:
        r=eng.latest(eng.FROST_NOVA,level)
        if r is not None:
            out.append(_CDSpec('nova',max(1.0,r.cooldown-2.0*talents.imp_frost_nova),'frost_nova'))
    if policy.use_blink and level>=20:
        out.append(_CDSpec('blink',15.0,'blink'))
    if policy.use_ice_barrier and talents.ice_barrier and eng.ice_barrier_rank(level) is not None:
        out.append(_CDSpec('ice_barrier',30.0,'ice_barrier'))
    return tuple(out)


def _state_for_mask(specs:Sequence[_CDSpec], mask:int)->CooldownState:
    # A very large remaining cooldown means unavailable throughout this one
    # deterministic fight.  Ready states begin at exactly zero.
    vals={'fire_blast':0.0,'nova':0.0,'blink':0.0,'combustion':0.0,'ice_barrier':0.0}
    active={s.name for s in specs}
    for name in ('fire_blast','nova','blink','ice_barrier'):
        if name not in active:
            vals[name]=1e6
    for i,s in enumerate(specs):
        vals[s.name]=0.0 if (mask>>i)&1 else 1e6
    return CooldownState(**vals)


def _mask_weight(mask:int, ready:Sequence[float])->float:
    w=1.0
    for i,p in enumerate(ready):
        p=max(0.0,min(1.0,p))
        w*=p if (mask>>i)&1 else (1.0-p)
    return w


def _blend_outcomes(outcomes:Mapping[int,Sequence[object]], ready:Sequence[float], workload_weights:Sequence[float])->dict:
    # outcomes[mask] contains one FightOutcome per deterministic workload class.
    total=kill=recovery=mana=0.0
    casts:Dict[str,float]={}
    mask_uses=[0.0 for _ in ready]
    for mask,rows in outcomes.items():
        mw=_mask_weight(mask,ready)
        if mw<=EPS: continue
        for ww,out in zip(workload_weights,rows):
            w=mw*ww
            total+=w*out.total_s; kill+=w*out.kill_s; recovery+=w*out.recovery_s; mana+=w*out.mana_spent
            for k,v in out.casts.items(): casts[k]=casts.get(k,0.0)+w*float(v)
    return {'total':total,'kill':kill,'recovery':recovery,'mana':mana,'casts':casts}


def _solve_ready_fractions(specs:Sequence[_CDSpec], outcomes:Mapping[int,Sequence[object]],
                           workload_weights:Sequence[float], options:AnalyticOptions)->tuple[list[float],dict,int]:
    if not specs:
        b=_blend_outcomes(outcomes,[],workload_weights)
        return [],b,0
    ready=[1.0 for _ in specs]
    last=None
    for it in range(1,max(1,options.cooldown_max_iter)+1):
        b=_blend_outcomes(outcomes,ready,workload_weights)
        cycle=max(EPS,b['total'])
        new=[]
        for i,spec in enumerate(specs):
            uses=max(0.0,b['casts'].get(spec.cast_key,0.0))
            # Demand conditional on readiness.  This turns the long-run cooldown
            # rate constraint uses/sec <= 1/CD into a ready fraction.  If a ready
            # spell is never actually requested by the policy, it remains ready.
            if ready[i]>1e-9:
                demand=min(1.0,uses/ready[i])
            else:
                # Recover demand from the masks in which this cooldown alone is
                # allowed to be ready, avoiding a zero fixed point.
                probe=list(ready); probe[i]=1.0
                pb=_blend_outcomes(outcomes,probe,workload_weights)
                demand=min(1.0,max(0.0,pb['casts'].get(spec.cast_key,0.0)))
            if demand<=1e-10:
                target=1.0
            else:
                target=min(1.0,cycle/(spec.cooldown_s*demand))
            damp=max(0.0,min(1.0,options.cooldown_damping))
            new.append((1.0-damp)*ready[i]+damp*target)
        delta=max(abs(a-b) for a,b in zip(new,ready))
        ready=new; last=b
        if delta<options.cooldown_tol:
            break
    final=_blend_outcomes(outcomes,ready,workload_weights)
    return ready,final,it


def _blend_marginals(outcomes:Mapping[int,Sequence[object]], ready:Sequence[float], workload_weights:Sequence[float])->dict:
    """First-order cooldown decomposition: base + sum_i u_i * delta_i.

    This is the simple analytical extreme.  It deliberately ignores interaction
    terms between simultaneous cooldown readiness; the joint 2^k solver remains
    available as a validation mode.
    """
    def avg(mask:int):
        total=kill=recovery=mana=0.0; casts:Dict[str,float]={}
        for ww,out in zip(workload_weights,outcomes[mask]):
            total+=ww*out.total_s; kill+=ww*out.kill_s; recovery+=ww*out.recovery_s; mana+=ww*out.mana_spent
            for k,v in out.casts.items(): casts[k]=casts.get(k,0.0)+ww*float(v)
        return {'total':total,'kill':kill,'recovery':recovery,'mana':mana,'casts':casts}
    base=avg(0)
    out={'total':base['total'],'kill':base['kill'],'recovery':base['recovery'],'mana':base['mana'],'casts':dict(base['casts'])}
    for i,u in enumerate(ready):
        one=avg(1<<i); u=max(0.0,min(1.0,u))
        for k in ('total','kill','recovery','mana'): out[k]+=u*(one[k]-base[k])
        keys=set(base['casts'])|set(one['casts'])
        for k in keys: out['casts'][k]=out['casts'].get(k,0.0)+u*(one['casts'].get(k,0.0)-base['casts'].get(k,0.0))
    for k in ('total','kill','recovery','mana'): out[k]=max(0.0,out[k])
    for k in list(out['casts']): out['casts'][k]=max(0.0,out['casts'][k])
    return out


def _solve_ready_marginals(specs:Sequence[_CDSpec], outcomes:Mapping[int,Sequence[object]],
                            workload_weights:Sequence[float], options:AnalyticOptions)->tuple[list[float],dict,int]:
    if not specs:
        return [],_blend_marginals(outcomes,[],workload_weights),0
    # Conditional demand when this cooldown is ready and all other cooldowns are
    # down.  Usually 0 or 1 use/pull for these leveling policies.
    demand=[]
    for i,spec in enumerate(specs):
        q=0.0
        for ww,out in zip(workload_weights,outcomes[1<<i]): q+=ww*float(out.casts.get(spec.cast_key,0.0))
        demand.append(max(0.0,q))
    ready=[1.0]*len(specs)
    for it in range(1,max(1,options.cooldown_max_iter)+1):
        b=_blend_marginals(outcomes,ready,workload_weights); cycle=max(EPS,b['total']); new=[]
        for spec,q,old in zip(specs,demand,ready):
            target=1.0 if q<=1e-10 else min(1.0,cycle/(spec.cooldown_s*q))
            d=max(0.0,min(1.0,options.cooldown_damping))
            new.append((1-d)*old+d*target)
        delta=max(abs(a-b) for a,b in zip(new,ready)); ready=new
        if delta<options.cooldown_tol: break
    return ready,_blend_marginals(outcomes,ready,workload_weights),it


def _combustion_extra_crits_per_activation(base_crit:float)->float:
    """Expected *additional* crits from one Classic Combustion activation.

    Work on landed Fire spells, because misses neither crit nor increase the
    Combustion bonus in v1.  The state is (crits_so_far, bonus_index).  Bonus
    starts at +10 percentage points and increments after every landed Fire hit.
    This tiny DP is exact for the simplified homogeneous-base-crit assumption.
    """
    base=max(0.0,min(0.99,float(base_crit)))
    from functools import lru_cache
    @lru_cache(None)
    def rec(crits:int, bonus:int)->float:
        if crits>=3: return 0.0
        # At bonus>=10 the cap is effectively reached for any realistic base.
        b=min(int(bonus),12)
        p=min(0.99,base+0.10*b)
        extra=p-base
        if crits+1>=3:
            oncrit=0.0
        else:
            oncrit=rec(crits+1,min(12,b+1))
        if b>=12:
            # At the cap a non-crit returns to the same state.  Solve the
            # one-state geometric equation rather than recursing into itself.
            return (extra + p*oncrit)/max(p,EPS)
        onmiss=rec(crits,b+1)
        return extra + p*oncrit + (1.0-p)*onmiss
    return max(0.0,rec(0,1))


def _fire_base_crit(level:int,talents:eng.Talents,policy:eng.Policy,cfg:eng.SimConfig,
                    cast_mix:Mapping[str,float])->float:
    stats=eng.player_stats_for_config(level,talents,cfg)
    dummy=ExpectedState(0.0,1.0,stats.max_mana,stats.max_mana,30.0)
    tables={
        'fireball':eng.FIREBALL,'scorch':eng.SCORCH,'fire_blast':eng.FIRE_BLAST,'pyroblast':eng.PYROBLAST,
    }
    num=den=0.0
    for spell,n in cast_mix.items():
        if n<=0 or spell not in tables: continue
        r=eng.latest(tables[spell],level)
        if r is None: continue
        c=expected_direct_components(level,level+1,r,talents,stats,cfg,dummy)['crit_p']
        num+=n*c; den+=n
    return num/den if den>EPS else 0.0





def _spell_power_direct_coeff(rank, cfg) -> float:
    profile = getattr(cfg, "server_profile", None)
    if profile is not None:
        try:
            return float(eng.spell_power_direct_coeff(rank, profile))
        except TypeError:
            pass
    return float(eng.spell_power_direct_coeff(rank))

def _primary_damage_sigma_rel(level:int,talents:eng.Talents,policy:eng.Policy,cfg:eng.SimConfig,mob_level:int)->float:
    """Approximate sigma(cumulative direct damage)/mob_hp for terminal-boundary smoothing.

    The moment model keeps hit/crit and tooltip damage-range variance, while
    treating the expected resistance multiplier as deterministic.  This is not
    a stochastic simulation: it supplies a width for two-point Gaussian
    quadrature around the deterministic kill threshold.
    """
    stats=eng.player_stats_for_config(level,talents,cfg)
    dummy=ExpectedState(0.0,1e9,stats.max_mana,stats.max_mana,30.0)
    seq=[]
    if policy.fireball_block>0 and policy.scorch_block>0:
        fb=eng.latest(eng.FIREBALL,level); sc=eng.latest(eng.SCORCH,level)
        if fb: seq.append((fb,float(policy.fireball_block)))
        if sc: seq.append((sc,float(policy.scorch_block)))
    else:
        table={'frostbolt':eng.FROSTBOLT,'fireball':eng.FIREBALL,'scorch':eng.SCORCH}
        arr=table.get(policy.primary)
        r=eng.latest(arr,level) if arr else None
        if r: seq.append((r,1.0))
    if not seq:
        return 0.0
    wsum=sum(w for _,w in seq) or 1.0
    mean=var=0.0
    for rank,w in seq:
        comp=expected_direct_components(level,mob_level,rank,talents,stats,cfg,dummy)
        hit=max(0.0,min(1.0,float(comp['hit'])))
        crit=max(0.0,min(0.99,float(comp['crit_p'])))
        cm=float(eng.crit_mult(rank,talents))
        mod=1.0
        if rank.school=='frost': mod*=1.0+0.02*talents.piercing_ice
        if rank.school=='fire': mod*=1.0+0.02*talents.fire_power
        mod*=1.0+0.01*talents.arcane_instability
        resist=max(0.0,float(comp['resist']))
        sp_add=stats.spell_power*_spell_power_direct_coeff(rank, cfg)
        base_mean=0.5*(rank.dmin+rank.dmax)+sp_add
        base_second=(rank.dmin*rank.dmin+rank.dmin*rank.dmax+rank.dmax*rank.dmax)/3.0 + 2.0*sp_add*0.5*(rank.dmin+rank.dmax) + sp_add*sp_add
        ebase=base_mean*mod*resist
        ebase2=base_second*mod*mod*resist*resist
        ec=1.0+crit*(cm-1.0); ec2=1.0+crit*(cm*cm-1.0)
        mu=hit*ebase*ec
        e2=hit*ebase2*ec2
        mean += w*mu/wsum
        var += w*max(0.0,e2-mu*mu)/wsum
    hp=float(eng.MOB_BASE_HP[mob_level])
    if mean<=EPS or hp<=EPS:
        return 0.0
    expected_casts=max(1.0,hp/mean)
    return math.sqrt(expected_casts*max(0.0,var))/hp


def _workload_scenarios(level:int,talents:eng.Talents,policy:eng.Policy,cfg:eng.SimConfig,options:AnalyticOptions):
    if len(options.mob_offsets)!=len(options.workload_weights):
        raise ValueError('mob_offsets and workload_weights must have equal length')
    if not options.workload_weights or any((not math.isfinite(float(w))) or float(w)<0.0 for w in options.workload_weights):
        raise ValueError('workload weights must be finite and nonnegative')
    raw=[]
    for off,ww in zip(options.mob_offsets,options.workload_weights):
        ml=level+int(off)
        if options.kill_boundary_model=='hard':
            raw.append((int(off),1.0,float(ww)))
        elif options.kill_boundary_model in ('normal2','normal5q'):
            rel=_primary_damage_sigma_rel(level,talents,policy,cfg,ml)
            rel=min(max(0.0,rel*max(0.0,options.kill_boundary_sigma_scale)),max(0.0,options.kill_boundary_sigma_cap))
            if rel<=1e-8:
                raw.append((int(off),1.0,float(ww)))
            elif options.kill_boundary_model=='normal2':
                # Historical two-point rule retained for differential tests.
                raw.append((int(off),max(0.05,1.0-rel),0.5*float(ww)))
                raw.append((int(off),1.0+rel,0.5*float(ww)))
            else:
                # Five equal-probability midpoint quantiles of N(0,1).  This
                # samples the CDF more uniformly than sparse Gauss-Hermite
                # support and is less phase-sensitive at integer cast-count
                # thresholds.  z = Phi^-1({0.1,0.3,0.5,0.7,0.9}).
                for zz in (-1.2815515655446004,-0.5244005127080409,0.0,
                           0.5244005127080409,1.2815515655446004):
                    raw.append((int(off),max(0.05,1.0+zz*rel),0.2*float(ww)))
        else:
            raise ValueError(f'unknown kill_boundary_model {options.kill_boundary_model!r}')
    sw=sum(w for _,_,w in raw)
    if sw<=0: raise ValueError('workload weights must sum positive')
    return [(off,hp,w/sw) for off,hp,w in raw]

def _build_outcome_table(level:int,talents:eng.Talents,policy:eng.Policy,cfg:eng.SimConfig,
                         specs:Sequence[_CDSpec],combustion_extra_crit:float,
                         options:AnalyticOptions,scenarios:Sequence[tuple[int,float,float]])->dict[int,list[object]]:
    table={}
    if options.cooldown_model=='joint':
        masks=range(1<<len(specs))
    elif options.cooldown_model=='marginal':
        masks=[0]+[1<<i for i in range(len(specs))]
    else:
        raise ValueError(f'unknown cooldown_model {options.cooldown_model!r}')
    for mask in masks:
        cd=_state_for_mask(specs,mask)
        rows=[]
        for off,hp_mult,_w in scenarios:
            rows.append(simulate_fight_expected(
                level,talents,policy,cfg,mob_level=level+int(off),hp_mult=float(hp_mult),
                mob_swing=options.representative_swing,cooldowns=cd,
                combustion_extra_crit=combustion_extra_crit,
            ))
        table[mask]=rows
    return table




def _weighted_scenario_cycle(scenarios:Sequence[tuple[int,float,float]], length:int)->list[tuple[int,float,float]]:
    """Deterministic smooth weighted round-robin cycle for stateful cooldowns.

    Barrier carry makes adjacent pulls matter.  The ordinary analytic scorer can
    blend independent workload classes algebraically, but a surviving shield is
    genuine state.  This scheduler realizes the same scenario weights as a short
    deterministic pull stream without introducing RNG or clustering equal-weight
    classes into long runs.
    """
    n=max(1,int(length))
    if not scenarios:
        return []
    weights=[max(0.0,float(x[2])) for x in scenarios]
    sw=sum(weights)
    if sw<=EPS:
        raise ValueError('scenario weights must sum positive')
    weights=[w/sw for w in weights]
    counts=[0]*len(scenarios)
    out=[]
    for step in range(n):
        target_step=step+1
        # Largest cumulative deficit first; stable index tie-break keeps this
        # fully deterministic across Python versions/processes.
        i=max(range(len(scenarios)),key=lambda j:(target_step*weights[j]-counts[j],-j))
        counts[i]+=1
        out.append(scenarios[i])
    return out


def _score_stateful_barrier_chain(level:int,talents:eng.Talents,policy:eng.Policy,cfg:eng.SimConfig,
                                    specs:Sequence[_CDSpec],options:AnalyticOptions,
                                    scenarios:Sequence[tuple[int,float,float]])->dict:
    """Deterministic steady-cycle scorer for the one cooldown with persistent absorb.

    Ice Barrier is not just a ready/down cooldown: unused absorb can survive into
    the next pull for up to 60 seconds.  A small warmup + measurement cycle keeps
    that state exactly in the expected fight kernel while retaining deterministic
    normal5q workload smoothing.  Other policies stay on the faster algebraic
    fixed-point path.
    """
    cycle_len=max(12,2*len(scenarios))
    cycle=_weighted_scenario_cycle(scenarios,cycle_len)
    cd=CooldownState()
    # One complete cycle is enough to remove the artificial all-cooldowns-ready
    # startup for 15/25/30 s leveling cooldowns and the 60 s Barrier aura.
    for off,hp_mult,_w in cycle:
        out=simulate_fight_expected(level,talents,policy,cfg,mob_level=level+int(off),
                                    hp_mult=float(hp_mult),mob_swing=options.representative_swing,
                                    cooldowns=cd)
        cd=out.end_cooldowns

    total=kill=recovery=mana=0.0
    casts:Dict[str,float]={}
    ready_counts={sp.name:0.0 for sp in specs}
    attr={'fire_blast':'fire_blast','nova':'nova','blink':'blink','combustion':'combustion','ice_barrier':'ice_barrier'}
    for off,hp_mult,_w in cycle:
        for sp in specs:
            if float(getattr(cd,attr[sp.name]))<=EPS:
                ready_counts[sp.name]+=1.0
        out=simulate_fight_expected(level,talents,policy,cfg,mob_level=level+int(off),
                                    hp_mult=float(hp_mult),mob_swing=options.representative_swing,
                                    cooldowns=cd)
        cd=out.end_cooldowns
        total+=out.total_s; kill+=out.kill_s; recovery+=out.recovery_s; mana+=out.mana_spent
        for k,v in out.casts.items(): casts[k]=casts.get(k,0.0)+float(v)
    n=float(len(cycle))
    scale=100.0/n
    travel_per_mob=between_pull_travel_s()
    result={
        'total_s':total*scale + 100.0*travel_per_mob,'kill_s':kill*scale,'recovery_s':recovery*scale,
        'travel_s':100.0*travel_per_mob,'mana':mana*scale,
        'mean_s_per_mob':total/n + travel_per_mob,'deterministic':True,'analytic_steady_state':True,
        'stateful_barrier_chain':True,'state_evaluations':2*len(cycle),
        'cooldown_fixed_point_iters':0,'combustion_fixed_point_iters':1,'combustion_extra_crit':0.0,
        'kill_boundary_model':options.kill_boundary_model,
        'cooldown_ready':{sp.name:ready_counts[sp.name]/n for sp in specs},
    }
    for k,v in casts.items(): result['casts_'+k]=v*scale
    return result

def score_policy_analytic(level:int,talents:eng.Talents,policy:eng.Policy,cfg:eng.SimConfig,
                          *,options:AnalyticOptions=AnalyticOptions())->dict:
    """Algebraic steady-state score for one fixed level/build/policy.

    Returns seconds/100 mobs for compatibility with v1/v2 scorers.  No stochastic
    samples and no sequential pull chain are used.
    """
    # Forever's default scorer must use the same sustained resource loop as the
    # deterministic/event paths: carry mana across same-level pulls, use gems /
    # Evocation when they beat sitting, and drink only when continuation loses.
    # Explicit workload sensitivities still use the algebraic kernel below.
    forever_default=(hasattr(cfg,"server_profile") and options.mob_offsets==(1,2)
                     and options.workload_weights==(0.5,0.5)
                     and options.kill_boundary_model=='hard')
    if forever_default:
        r=score_policy_expected(level,talents,policy,cfg,cycle_pulls=6)
        r=dict(r)
        r['analytic_steady_state']=False
        r['deterministic_resource_chain']=True
        r['approximation_flags']=tuple(sorted(set(r.get('approximation_flags',()))|{
            'forever_default_same_level_resource_chain',
            'event_hp_recovery_authority',
        }))
        r.setdefault('state_evaluations',6)
        r.setdefault('cooldown_fixed_point_iters',0)
        r.setdefault('combustion_fixed_point_iters',0)
        r.setdefault('combustion_extra_crit',0.0)
        r.setdefault('kill_boundary_model','hard')
        r.setdefault('cooldown_ready',{})
        return r
    if hasattr(cfg,"server_profile") and options.mob_offsets==(1,2) and options.workload_weights==(0.5,0.5):
        options=replace(options,mob_offsets=(int(getattr(cfg,"target_level_offset",0)),),
                        workload_weights=(1.0,))
    scenarios=_workload_scenarios(level,talents,policy,cfg,options)
    weights=tuple(w for _off,_hp,w in scenarios)
    specs=_active_cooldowns(level,talents,policy)
    # Barrier absorb/duration is persistent state, not just cooldown readiness.
    # Use a short deterministic pull cycle so a surviving shield can protect the
    # next mob instead of being discarded by the algebraic ready/down blend.
    if policy.use_ice_barrier and talents.ice_barrier and not talents.combustion:
        return _score_stateful_barrier_chain(level,talents,policy,cfg,specs,options,scenarios)
    comb_extra=0.0
    comb_iters=0
    table=None; ready=[]; blended=None; cd_iters=0
    for ci in range(max(1,options.combustion_max_iter if talents.combustion else 1)):
        comb_iters=ci+1
        table=_build_outcome_table(level,talents,policy,cfg,specs,comb_extra,options,scenarios)
        ready,blended,cd_iters=(_solve_ready_marginals(specs,table,weights,options) if options.cooldown_model=='marginal' else _solve_ready_fractions(specs,table,weights,options))
        if not talents.combustion:
            break
        casts=blended['casts']
        fire_casts=sum(casts.get(k,0.0) for k in ('fireball','scorch','fire_blast','pyroblast'))
        if fire_casts<=EPS:
            new_extra=0.0
        else:
            base=_fire_base_crit(level,talents,policy,cfg,casts)
            extra_per_activation=_combustion_extra_crits_per_activation(base)
            activations_per_pull=min(1.0,max(EPS,blended['total'])/180.0)
            new_extra=min(0.50,extra_per_activation*activations_per_pull/fire_casts)
        if abs(new_extra-comb_extra)<options.combustion_tol:
            comb_extra=new_extra
            break
        comb_extra=0.5*comb_extra+0.5*new_extra
    # One final table at the converged combustion value if the last iteration moved.
    if talents.combustion:
        table=_build_outcome_table(level,talents,policy,cfg,specs,comb_extra,options,scenarios)
        ready,blended,cd_iters=(_solve_ready_marginals(specs,table,weights,options) if options.cooldown_model=='marginal' else _solve_ready_fractions(specs,table,weights,options))
    assert blended is not None
    casts=blended['casts']
    travel_per_mob=between_pull_travel_s()
    result={
        'total_s':(blended['total']+travel_per_mob)*100.0,
        'kill_s':blended['kill']*100.0,
        'recovery_s':blended['recovery']*100.0,
        'travel_s':travel_per_mob*100.0,
        'mana':blended['mana']*100.0,
        'mean_s_per_mob':blended['total']+travel_per_mob,
        'deterministic':True,
        'analytic_steady_state':True,
        # Combustion always rebuilds one final outcome table at the converged
        # extra-crit value after the fixed-point loop. Count that work too so
        # this diagnostic reflects actual deterministic fight-kernel calls.
        'state_evaluations':((1+len(specs)) if options.cooldown_model=='marginal' else (1<<len(specs)))*len(scenarios)*(comb_iters+(1 if talents.combustion else 0)),
        'cooldown_fixed_point_iters':cd_iters,
        'combustion_fixed_point_iters':comb_iters,
        'combustion_extra_crit':comb_extra,
        'kill_boundary_model':options.kill_boundary_model,
        'cooldown_ready':{s.name:p for s,p in zip(specs,ready)},
    }
    for k,v in casts.items(): result['casts_'+k]=v*100.0
    return result




def _policy_family(policy:eng.Policy)->str:
    """Mechanical family used only to gate *expensive expansion*.

    This is deliberately not a hard statement that a Frost build may never cast
    Fire spells.  Every available family gets an anchor score first; a family is
    expanded whenever its anchor is competitive, even with zero points in that
    tree.  This preserves spell-rank breakpoint surprises while avoiding dozens
    of obviously irrelevant cadence evaluations.
    """
    if getattr(policy,'fireball_block',0) and getattr(policy,'scorch_block',0):
        return 'fire'
    primary=getattr(policy,'primary','')
    if primary=='frostbolt': return 'frost'
    if primary in ('fireball','scorch'): return 'fire'
    if primary=='arcane_missiles': return 'arcane'
    return 'other'


def _policy_anchor_basis(level:int, school:str="all")->list[eng.Policy]:
    """One cheap representative per mechanically distinct spell family."""
    out=[]
    if eng.latest(eng.FROSTBOLT,level):
        out.append(eng.Policy('analytic anchor FBo','frostbolt',use_fireblast=False,use_nova=False,use_blink=False))
    if eng.latest(eng.FIREBALL,level):
        out.append(eng.Policy('analytic anchor FBa','fireball',use_fireblast=False,use_nova=False,use_blink=False))
    if eng.latest(eng.SCORCH,level):
        out.append(eng.Policy('analytic anchor Sc','scorch',use_fireblast=False,use_nova=False,use_blink=False))
    if eng.latest(eng.ARCANE_MISSILES,level):
        out.append(eng.Policy('analytic anchor AM','arcane_missiles',use_fireblast=False,use_nova=False,use_blink=False))
    return eng.filter_policies_by_primary_school(out, school)


def _talent_tree_points(talents:eng.Talents)->dict[str,int]:
    return {fam:int(eng.tree_points(talents,fam)) for fam in ('frost','arcane','fire')}


def _score_policy_set(level:int,talents:eng.Talents,cfg:eng.SimConfig,ps:Iterable[eng.Policy],
                      options:AnalyticOptions):
    scored=[]; skipped=0
    for p in ps:
        if getattr(p,'clearcast_am',False):
            continue
        try:
            r=score_policy_analytic(level,talents,p,cfg,options=options)
        except (RuntimeError,ValueError,OverflowError,RecursionError):
            skipped+=1; continue
        scored.append((float(r['total_s']),eng.policy_desc(p,level),p,r))
    scored.sort(key=lambda x:(x[0],x[1]))
    return scored,skipped


def optimize_policy_analytic_exhaustive(level:int,talents:eng.Talents,cfg:eng.SimConfig,*,
                                          policies:Iterable[eng.Policy]|None=None,
                                          options:AnalyticOptions=AnalyticOptions(),
                                          school:str="all")->tuple[eng.Policy,dict]:
    """Reference implementation: score anchors plus the full 54-policy Fire cadence basis."""
    from .expected_engine import policy_candidates_expected_exhaustive
    ps=list(policy_candidates_expected_exhaustive(level,talents) if policies is None else policies)
    ps=eng.filter_policies_by_primary_school(ps,school)
    scored,skipped=_score_policy_set(level,talents,cfg,ps,options)
    if not scored: raise ValueError(f'no analytical policies available at level {level}')
    best=scored[0]
    best[3]['policy_count']=len(ps)
    best[3]['policy_scored_count']=len(scored)
    best[3]['policy_search']='exhaustive'
    best[3]['skipped_invalid_policies']=skipped
    return best[2],best[3]


def optimize_policy_analytic(level:int,talents:eng.Talents,cfg:eng.SimConfig,*,
                             policies:Iterable[eng.Policy]|None=None,
                             options:AnalyticOptions=AnalyticOptions(),
                             family_margin:float=0.10,
                             family_talent_trigger:int=10,
                             school:str="all")->tuple[eng.Policy,dict]:
    """Family-aware staged analytical policy search.

    Stage 1 scores one anchor rotation from every available spell family.  Stage
    2 expands a family only when either:
      * its anchor is within ``family_margin`` of the best anchor, or
      * the build has at least ``family_talent_trigger`` points in that tree.

    Therefore deep Frost still tests a Fireball/Scorch anchor (and can open the
    Fire search if a spell-rank breakpoint makes it competitive), but normally
    does not pay for ~50 Fireball/Scorch cadence policies.  Explicit ``policies``
    bypass gating so callers can request an exact/reference comparison.
    """
    from .expected_engine import policy_candidates_expected

    if policies is not None:
        return optimize_policy_analytic_exhaustive(level,talents,cfg,policies=policies,options=options,school=school)

    full=eng.filter_policies_by_primary_school(policy_candidates_expected(level,talents),school)
    anchors=_policy_anchor_basis(level,school)
    anchor_scored,skipped=_score_policy_set(level,talents,cfg,anchors,options)
    if not anchor_scored:
        raise ValueError(f'no analytical policy anchors available at level {level}')

    best_anchor=float(anchor_scored[0][0])
    family_anchor_best:dict[str,float]={}
    for score,_desc,p,_r in anchor_scored:
        fam=_policy_family(p)
        family_anchor_best[fam]=min(score,family_anchor_best.get(fam,float('inf')))

    pts=_talent_tree_points(talents)
    active=set()
    margin=max(0.0,float(family_margin))
    trigger=max(0,int(family_talent_trigger))
    requested=eng.normalize_primary_school(school)
    expansion_families=('frost','arcane','fire') if requested=='all' else (requested,)
    for fam in expansion_families:
        a=family_anchor_best.get(fam,float('inf'))
        if a <= best_anchor*(1.0+margin)+1e-12 or pts.get(fam,0)>=trigger:
            active.add(fam)

    # Anchors have already been scored.  Only score non-anchor full candidates
    # whose family earned expansion.  Deduplicate semantically, because the full
    # basis contains pure policies equivalent to anchors but with different names.
    def semantic_key(p:eng.Policy):
        return tuple(getattr(p,f) for f in p.__dataclass_fields__ if f!='name')
    anchor_keys={semantic_key(p) for p in anchors}
    expanded=[]; seen=set(anchor_keys)
    for p in full:
        k=semantic_key(p)
        if k in seen: continue
        fam=_policy_family(p)
        if fam in active:
            expanded.append(p); seen.add(k)

    expanded_scored,skipped2=_score_policy_set(level,talents,cfg,expanded,options)
    all_scored=anchor_scored+expanded_scored
    all_scored.sort(key=lambda x:(x[0],x[1]))
    best=all_scored[0]
    best[3]['policy_count']=len(full)
    best[3]['policy_anchor_count']=len(anchor_scored)
    best[3]['policy_expanded_count']=len(expanded_scored)
    best[3]['policy_scored_count']=len(all_scored)
    best[3]['policy_active_families']=tuple(sorted(active))
    best[3]['policy_family_anchor_s_per_100']={k:float(v) for k,v in family_anchor_best.items()}
    best[3]['policy_family_margin']=margin
    best[3]['policy_family_talent_trigger']=trigger
    best[3]['policy_tree_points']=pts
    best[3]['policy_search']='family_staged'
    best[3]['skipped_invalid_policies']=skipped+skipped2
    return best[2],best[3]
