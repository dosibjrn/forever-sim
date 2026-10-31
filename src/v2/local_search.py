from __future__ import annotations

"""Simple independent per-level talent search for v2.

This intentionally avoids v1's structural frontier / mutation / kNN / precision
scheduler stack.  A cheap deterministic pure-school proxy keeps a diverse beam;
only final allocations pay the richer deterministic policy search.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Iterable, Tuple
import math

from src.engine_registry import eng
from .expected_engine import score_policy, optimize_policy_expected


@dataclass
class LevelCandidate:
    talents: eng.Talents
    score_s_per_100: float
    policy: eng.Policy
    details: dict


def talent_key(t: eng.Talents) -> tuple[int, ...]:
    # Frozen dataclass field insertion order is identical to dataclass field order.
    # Avoid ~35 getattr/int calls in this extremely hot structural-search helper.
    return tuple(t.__dict__.values())


def _talent_tiebreak_key(t: eng.Talents) -> tuple:
    """Prefer weakly-dominating real utility over synthetic Arcane filler.

    Arcane Subtlety is true all-school spell penetration: it has no effect on a
    zero-inherent-resistance baseline mob, but it can only improve spell damage
    against mobs with reducible school resistance.  Therefore, when the speed
    proxy/scorer is exactly tied, spending the first two low-tier Arcane points
    in Subtlety weakly dominates spending them in ``arcane_filler``.

    This is deliberately only a secondary key.  It never overrides a measurable
    speed difference, and it does not pretend Subtlety can remove the unpenetrable
    level-difference resistance term.
    """
    return eng.talent_preference_key(t)


def tree_triplet(t: eng.Talents) -> tuple[int,int,int]:
    return tuple(eng.tree_points(t,x) for x in ('frost','arcane','fire'))


def family(t: eng.Talents) -> str:
    vals=dict(zip(('frost','arcane','fire'),tree_triplet(t)))
    m=max(vals.values())
    winners=[k for k,v in vals.items() if v==m]
    return winners[0] if len(winners)==1 else 'mixed'


def _proxy_policies(level: int) -> list[eng.Policy]:
    ps=[]
    if eng.latest(eng.FROSTBOLT,level):
        ps.append(eng.Policy('proxy FBo','frostbolt',use_fireblast=False,use_nova=False,use_blink=False))
    if eng.latest(eng.FIREBALL,level):
        ps.append(eng.Policy('proxy FBa','fireball',use_fireblast=False,use_nova=False,use_blink=False))
    if eng.latest(eng.SCORCH,level):
        ps.append(eng.Policy('proxy Sc','scorch',use_fireblast=False,use_nova=False,use_blink=False))
    if eng.latest(eng.ARCANE_MISSILES,level):
        ps.append(eng.Policy('proxy AM','arcane_missiles',use_fireblast=False,use_nova=False,use_blink=False))
    return ps


@lru_cache(maxsize=2048)
def _proxy_player_stats(level:int, arcane_mind:int, arcane_instability:int, owl_intensity:float):
    # player_stats depends on talents only through these two fields.
    t=eng.Talents(arcane_mind=int(arcane_mind), arcane_instability=int(arcane_instability))
    return eng.player_stats(int(level),t,float(owl_intensity))


def _spell_proxy(level:int, mob_level:int, t:eng.Talents, cfg:eng.SimConfig,
                 spell:str) -> float:
    """O(1) steady-state-ish cost proxy for structural talent beam ranking.

    This intentionally does *not* run the fight kernel.  It only needs to keep
    mechanically promising partial talent allocations alive until the rich
    analytical scorer is run on the final beam.  Lower is better and the unit is
    approximately seconds per representative mob.
    """
    from .expected_engine import ExpectedState, expected_direct_components, _expected_resist_multiplier
    stats=_proxy_player_stats(level,t.arcane_mind,t.arcane_instability,cfg.owl_intensity)
    hp=float(eng.MOB_BASE_HP[mob_level])
    state=ExpectedState(0.0,hp,stats.max_mana,stats.max_mana,30.0)

    if spell=='arcane_missiles':
        r=eng.latest(eng.ARCANE_MISSILES,level)
        if r is None: return math.inf
        hit=eng.spell_hit(level,mob_level,'arcane',t)
        resist=_expected_resist_multiplier(level,mob_level,r,t,cfg)
        dmg=max(1e-9,hit*resist*r.channel_ticks*r.channel_tick_damage*(1+.01*t.arcane_instability))
        cast=max(.5,float(r.channel_ticks))
        mana=float(r.mana)
    else:
        ranks={'frostbolt':eng.FROSTBOLT,'fireball':eng.FIREBALL,'scorch':eng.SCORCH}[spell]
        r=eng.latest(ranks,level)
        if r is None: return math.inf
        # Give the structural proxy a mild expected-debuff state so talents such
        # as Winter's Chill / Improved Scorch are not invisible to the beam.
        if spell=='frostbolt' and t.winters_chill:
            state.wc_stacks=min(5.0,0.40*float(t.winters_chill))
            state.wc_until=999.0
        if spell=='frostbolt' and t.frostbite and t.shatter:
            state.root_probability=min(.45,.08*float(t.frostbite))
        if spell=='scorch' and t.imp_scorch:
            proc=(1/3,2/3,1.0)[max(0,min(2,int(t.imp_scorch)-1))]
            state.scorch_stacks=min(5.0,1.5*proc)
            state.scorch_until=999.0
        c=expected_direct_components(level,mob_level,r,t,stats,cfg,state)
        dmg=max(1e-9,float(c['damage']))
        # Attached Fireball DoT is deliberately discounted: much of it is
        # refreshed or the mob dies before all ticks.  This is a beam heuristic,
        # not the authoritative scorer.
        if spell=='fireball' and r.dot_total:
            dmg += .45*float(r.dot_total)*(1+.02*t.fire_power)*(1+.01*t.arcane_instability)
        cast=float(r.cast or 1.5)
        if spell=='frostbolt': cast=max(.5,cast-.1*t.imp_frostbolt)
        elif spell=='fireball': cast=max(.5,cast-.1*t.imp_fireball)
        mana=float(eng.mana_cost(r,t,stats))
        # Expected Master of Elements refund and Clearcasting discount.
        mana=max(0.0,mana-float(c.get('mana_refund',0.0)))
        if t.arcane_concentration:
            pcc=min(.10,.02*float(t.arcane_concentration))*float(c.get('hit',1.0))
            mana*=1.0-pcc

    casts=hp/dmg
    active=casts*cast

    # O(1) control / pushback correction.  The rich scorer still owns exact
    # movement, projectile, Nova and root timing; this term merely prevents
    # range/slow talents from being invisible to the structural beam.
    #
    # v1/v2 start a pull at the primary spell's effective range.  Projectiles
    # do not aggro/move the mob until impact, so their first cast + travel time
    # is additional free time before the mob begins closing.  Frostbolt then
    # slows the closing speed; using hit-weighted slow keeps this expectation
    # smooth and deterministic.
    if spell=='arcane_missiles':
        start_range=float(r.range)
        engage_delay=0.0  # AM begins hostile work immediately in the model.
        school='arcane'
        hit_p=hit
        slow_frac=0.0
    else:
        start_range=float(eng.effective_range(r,t))
        school=str(r.school)
        hit_p=float(c.get('hit',1.0))
        if float(getattr(r,'missile_speed',0.0) or 0.0)>0.0:
            engage_delay=cast + max(5.0,start_range)/float(r.missile_speed)
        else:
            # Non-projectile direct spells engage at first cast completion.
            engage_delay=cast
        if spell=='frostbolt':
            pf=int(max(0,min(3,t.permafrost)))
            slow_frac=(0.40+[0.0,0.04,0.07,0.10][pf])*hit_p
        else:
            slow_frac=0.0

    closing_speed=max(1e-9,float(cfg.mob_speed)*(1.0-max(0.0,min(.95,slow_frac))))
    run_time=max(0.0,start_range-float(cfg.melee_reach))/closing_speed
    free_time=max(0.0,engage_delay+run_time)
    melee_exposure=max(0.0,active-free_time)
    swing_mix=tuple(float(x) for x in cfg.mob_swing_mix if float(x)>0) if cfg.mob_swing_mix else ()
    mean_swing=(sum(swing_mix)/len(swing_mix)) if swing_mix else max(1e-9,float(cfg.mob_swing))
    raw_swings=melee_exposure/max(1e-9,mean_swing)
    pb_resist=(0.35*float(t.burning_soul)) if school=='fire' else 0.0
    base_mps=(12.5+stats.spirit/4.0)/2.0
    regen=base_mps*eng.regen_fraction_in_5sr(level,t,cfg)
    water=eng.latest_pair(eng.WATER_USABLE if cfg.use_best_water else eng.WATER_SELF,level)
    if water:
        _,amount,duration=water
        drink_mps=max(1e-9,float(amount)/float(duration))
    else:
        drink_mps=max(1e-9,base_mps)

    def structural_total(*, use_barrier:bool)->float:
        expected_swings=raw_swings
        barrier_freq=0.0
        barrier_mana=0.0
        if use_barrier:
            br=eng.ice_barrier_rank(level)
            if br is not None:
                # Structural-only estimate of choosing the 30 s Barrier button.
                # It is an *option*: the talent score is min(skip,use) below.
                barrier_freq=min(1.0,max(0.0,active)/30.0)
                hit=max(1e-9,eng.generic_melee_hit_damage(eng.Mob(mob_level,hp,cfg.mob_speed,mean_swing,cfg.melee_reach),cfg))
                shield_swings=float(br.absorb)/hit
                protected=min(expected_swings,shield_swings)*barrier_freq
                expected_swings=max(0.0,expected_swings-protected)
                barrier_mana=eng.ice_barrier_mana_cost(level,t)*barrier_freq
        pushback=max(0.0,expected_swings*0.6*(1.0-max(0.0,min(1.0,pb_resist))))
        pushback=min(pushback,0.50*active)
        active_with_utility=active+pushback+eng.GCD*barrier_freq
        net=max(0.0,casts*mana+barrier_mana-active_with_utility*regen)
        return active_with_utility+net/drink_mps

    without=structural_total(use_barrier=False)
    if t.ice_barrier and eng.ice_barrier_rank(level) is not None:
        return min(without,structural_total(use_barrier=True))
    return without


def proxy_vector(level:int,t:eng.Talents,cfg:eng.SimConfig)->dict[str,float]:
    """Independent cheap rotation-archetype views used to preserve beam diversity."""
    accum={k:[] for k in ('frostbolt','fireball','scorch','arcane_missiles')}
    # Ice Lance is a talent-gated rotation lane, not a standalone spam spell.
    # Preserve one structural Ice-Lance-capable build through the beam so the
    # richer scorer/event validator can decide whether it actually wins.
    ice_lance_lane=[]
    for ml in (level+1,level+2):
        for spell in tuple(accum):
            try: v=_spell_proxy(level,ml,t,cfg,spell)
            except Exception: v=math.inf
            if math.isfinite(v): accum[spell].append(v)
    out={k:sum(v)/len(v) for k,v in accum.items() if v}
    if 'frostbolt' in out:
        # Dedicated control corridor: keep root/control-heavy Frost allocations
        # alive long enough to reach Ice Lance. This is a beam-diversity prior,
        # not reported throughput; the rich scorer/event backend decides value.
        fb=float(getattr(t,'frostbite',0)); nova=float(getattr(t,'imp_frost_nova',0)); pf=float(getattr(t,'permafrost',0)); hit=float(getattr(t,'elemental_precision',0))
        out['frost_control_corridor']=out['frostbolt']*(1.0-0.012*min(12.0,3.0*fb+1.5*nova+pf))
        out['frost_control_hit']=out['frostbolt']*(1.0-0.010*min(14.0,3.0*fb+1.2*hit+0.5*pf))
        out['frost_control_permafrost']=out['frostbolt']*(1.0-0.010*min(14.0,3.0*fb+2.0*pf+0.5*hit))
        out['frost_control_nova']=out['frostbolt']*(1.0-0.010*min(14.0,3.0*fb+2.0*nova+0.5*hit))
        if getattr(t,'ice_lance',0):
            out['frost_ice_lance']=min(out['frost_control_corridor'],out['frost_control_hit'],out['frost_control_permafrost'],out['frost_control_nova'])
    # Tiny mixed-Fire lane.  It is intentionally only a structural view: the rich
    # scorer owns projectile timing and exact Scorch cadence.  The expected
    # vulnerability credit prevents Improved Scorch builds from disappearing
    # before they can reach that scorer.
    if 'fireball' in out and 'scorch' in out and t.imp_scorch:
        proc=(1/3,2/3,1.0)[max(0,min(2,int(t.imp_scorch)-1))]
        vuln=1.0+0.03*min(5.0,2.0*proc)
        out['fire_mix']=(0.55*out['fireball']+0.45*out['scorch'])/vuln
    return out


def _school_proxy_lanes(school:str)->tuple[str,...]:
    school=eng.normalize_primary_school(school)
    if school=='frost': return ('frostbolt','frost_ice_lance')
    if school=='arcane': return ('arcane_missiles',)
    if school=='fire': return ('fireball','scorch','fire_mix')
    return ('frostbolt','fireball','scorch','fire_mix','arcane_missiles')

def _support_families(school:str)->tuple[str,...]:
    school=eng.normalize_primary_school(school)
    if school=='all': return ('frost','arcane','fire','mixed')
    vals=[school]
    if school!='arcane': vals.append('arcane')
    vals.append('mixed')
    return tuple(dict.fromkeys(vals))

def proxy_score(level: int, t: eng.Talents, cfg: eng.SimConfig, *, school:str='all') -> float:
    """Cheap mechanics-only structural proxy for the requested primary school."""
    v=proxy_vector(level,t,cfg)
    lanes=_school_proxy_lanes(school)
    vals=[v[k] for k in lanes if k in v]
    return min(vals) if vals else math.inf


def _retain_diverse(scored: list[tuple[float,eng.Talents]], width: int, family_keep: int,
                    lane_scores:Dict[tuple[int,...],dict[str,float]]|None=None, *,
                    school:str='all') -> list[eng.Talents]:
    scored.sort(key=lambda x:(x[0],_talent_tiebreak_key(x[1])))
    selected=[]; seen=set()
    # First preserve one mechanically good allocation for each dominant rotation
    # archetype.  This is more useful than assuming tree label == rotation.
    if lane_scores:
        allowed=set(_school_proxy_lanes(school))
        lanes=sorted({lane for d in lane_scores.values() for lane in d if lane in allowed})
        for lane in lanes:
            choices=[]
            for _,t in scored:
                k=talent_key(t); v=lane_scores.get(k,{}).get(lane,math.inf)
                if math.isfinite(v): choices.append((v,k,t))
            if choices:
                _,k,t=min(choices, key=lambda x:(x[0],_talent_tiebreak_key(x[2])))
                if k not in seen:
                    selected.append(t); seen.add(k)
                    if len(selected)>=width: return selected
    # Then keep tree-family lanes so neutral prerequisite spend cannot collapse a
    # deep tree before its payoff talents become legal.
    for fam in _support_families(school):
        n=0
        for _,t in scored:
            if family(t)!=fam: continue
            k=talent_key(t)
            if k in seen: continue
            selected.append(t); seen.add(k); n+=1
            if len(selected)>=width: return selected
            if n>=family_keep: break
    # Structural Ice Lance corridor. Keep this bounded so small historical beams
    # still preserve Arcane support/deep-Frost utility candidates (e.g. Barrier).
    # Wider production beams retain several distinct root/control prerequisite
    # shapes, which is enough for event reranking to discover Ice Lance builds.
    if eng.normalize_primary_school(school) in ('frost','all'):
        special_limit = 6 if width >= 20 else 0
        views=(
            lambda t:(-int(getattr(t,'imp_frostbolt',0)),-int(getattr(t,'frostbite',0)),-int(getattr(t,'elemental_precision',0)),-int(getattr(t,'permafrost',0)),-int(getattr(t,'imp_frost_nova',0))),
            lambda t:(-int(getattr(t,'imp_frostbolt',0)),-int(getattr(t,'frostbite',0)),-int(getattr(t,'permafrost',0)),-int(getattr(t,'elemental_precision',0)),-int(getattr(t,'imp_frost_nova',0))),
            lambda t:(-int(getattr(t,'imp_frostbolt',0)),-int(getattr(t,'frostbite',0)),abs(int(getattr(t,'elemental_precision',0))-int(getattr(t,'permafrost',0))),-(int(getattr(t,'elemental_precision',0))+int(getattr(t,'permafrost',0)))),
            lambda t:(-int(getattr(t,'frostbite',0)),-int(getattr(t,'elemental_precision',0)),-int(getattr(t,'permafrost',0)),-int(getattr(t,'imp_frost_nova',0))),
            lambda t:(-int(getattr(t,'frostbite',0)),-int(getattr(t,'permafrost',0)),-int(getattr(t,'elemental_precision',0)),-int(getattr(t,'imp_frost_nova',0))),
            lambda t:(-int(getattr(t,'frostbite',0)),-int(getattr(t,'imp_frost_nova',0)),-int(getattr(t,'elemental_precision',0)),-int(getattr(t,'permafrost',0))),
        )
        has_il=any(int(getattr(t,'ice_lance',0) or 0)>0 for _,t in scored)
        pool=[(v,t) for v,t in scored if (not has_il or int(getattr(t,'ice_lance',0) or 0)>0)]
        added=0
        for keyfn in views:
            if not pool or len(selected)>=width or added>=special_limit: break
            _v,t=min(pool,key=lambda vt:(keyfn(vt[1]),vt[0],_talent_tiebreak_key(vt[1])))
            k=talent_key(t)
            if k not in seen:
                selected.append(t); seen.add(k); added+=1
    for _,t in scored:
        if len(selected)>=width: break
        k=talent_key(t)
        if k not in seen:
            selected.append(t); seen.add(k)
    return selected[:width]


def search_level(level: int, cfg: eng.SimConfig, *, beam_width: int=32,
                 family_keep: int=6, final_k: int=16,
                 proposal_pulls: int=2, refine_pulls: int=6,
                 school:str='all') -> list[LevelCandidate]:
    """Independent allocation search for exactly ``level-9`` talent points."""
    points=int(level)-9
    if points<1: return []
    beam=[eng.Talents()]
    proxy_cache: Dict[tuple[int,...],float]={}
    lane_cache: Dict[tuple[int,...],dict[str,float]]={}
    for _depth in range(points):
        expanded={}
        for t in beam:
            for name in eng.TALENT_RULES:
                if eng.legal_add(t,name):
                    q=eng.add_point(t,name)
                    expanded.setdefault(talent_key(q),q)
        scored=[]
        for k,q in expanded.items():
            v=proxy_cache.get(k)
            if v is None:
                lanes=proxy_vector(level,q,cfg); lane_cache[k]=lanes
                allowed=_school_proxy_lanes(school)
                vals=[lanes[x] for x in allowed if x in lanes]
                v=min(vals) if vals else math.inf; proxy_cache[k]=v
            scored.append((v,q))
        if not scored: break
        beam=_retain_diverse(scored,max(4,int(beam_width)),max(1,int(family_keep)),lane_cache,school=school)

    # Rich deterministic policy search only on final proxy leaders.  Keep several
    # from every family so neutral prerequisite spend can still reach deep trees.
    finals=[]
    for t in beam:
        policies=eng.filter_policies_by_primary_school(__import__('src.v2.expected_engine',fromlist=['policy_candidates_expected']).policy_candidates_expected(level,t),school)
        p,r=optimize_policy_expected(level,t,cfg,proposal_pulls=proposal_pulls,refine_pulls=refine_pulls,policies=policies)
        finals.append(LevelCandidate(t,float(r['total_s']),p,r))
    finals.sort(key=lambda c:(c.score_s_per_100,_talent_tiebreak_key(c.talents),eng.final_allocation(c.talents),eng.policy_desc(c.policy,level)))

    # Final return is global top-K plus at least one leader per family.
    out=[]; seen=set()
    for fam in _support_families(school):
        c=next((x for x in finals if family(x.talents)==fam),None)
        if c is not None:
            k=talent_key(c.talents); out.append(c); seen.add(k)
    for c in finals:
        if len(out)>=max(1,int(final_k)): break
        k=talent_key(c.talents)
        if k not in seen: out.append(c); seen.add(k)
    out.sort(key=lambda c:c.score_s_per_100)
    return out[:max(1,int(final_k))]




def _mage_fixed_point_score(level:int,t,cfg,*,options,school:str):
    """Score one final Mage talent candidate at its own gear/stat fixed point.

    The coordinate loop uses fixed-policy finite differences after policy
    optimization; the final published stat weights still use the mature
    reoptimized-policy probe once at the settled gear state.
    """
    from dataclasses import replace
    from .analytic_scorer import optimize_policy_analytic, score_policy_analytic
    from .path_dp import LevelNode
    from .per_level_fixed_point import optimize_level_fixed_point
    from . import stat_weights as stat_weight_module
    from src.rulesets.forever.classes.mage import real_gear

    initial=real_gear.equipped_items(int(level))
    selected_holder=[initial]
    policy_holder=[None]

    def signature(items):
        return tuple(sorted((str(x.slot), int(x.item_id or 0), str(x.name)) for x in items))

    def score_with_gear(items):
        selected_holder[0]=tuple(items)
        with real_gear.gear_override(tuple(items)):
            p,r=optimize_policy_analytic(int(level),t,cfg,options=options,school=school)
            gear_stats=real_gear.snapshot(int(level))
        policy_holder[0]=p
        out=dict(r); out['gear_stats']=gear_stats; out['_fixed_point_policy']=p
        return out

    def derive_loop_weights(score):
        # Rotation was just optimized in score_with_gear.  For the coordinate
        # step we need the local value of stats around *that* optimum, not six
        # additional global policy searches.
        inc=stat_weight_module.probe_increment(int(level))
        baseline=float(score['total_s'])
        fields={'intellect':'gear_bonus_intellect','spirit':'gear_bonus_spirit','spell_power':'gear_bonus_spell_power'}
        stats={}
        with real_gear.gear_override(tuple(selected_holder[0])):
            for stat,field in fields.items():
                minus=replace(cfg,**{field:float(getattr(cfg,field))-inc})
                plus=replace(cfg,**{field:float(getattr(cfg,field))+inc})
                rm=score_policy_analytic(int(level),t,policy_holder[0],minus,options=options)
                rp=score_policy_analytic(int(level),t,policy_holder[0],plus,options=options)
                m=float(rm['total_s']); p=float(rp['total_s'])
                stats[stat]={'seconds_saved_per_100_per_point':(m-p)/(2.0*inc),
                             'forward_seconds_saved_per_100_per_point':(baseline-p)/inc,
                             'backward_seconds_saved_per_100_per_point':(m-baseline)/inc}
        return {'method':'fixed_policy_symmetric_difference_for_gear_loop','talents_fixed':True,
                'policy_fixed':True,'probe_increment':inc,'baseline_s_per_100':baseline,'stats':stats}

    def select_gear(_items,values):
        return real_gear.equipped_items(int(level),dict(values or {}))

    fp=optimize_level_fixed_point(initial_gear=initial,score_with_gear=score_with_gear,
        stat_weights=derive_loop_weights,select_gear=select_gear,gear_signature=signature,max_iters=4)
    out=dict(fp.score)
    final_policy=out.pop('_fixed_point_policy', policy_holder[0])
    policy_holder[0]=final_policy
    out['gear_fixed_point']=dict(out.get('gear_fixed_point') or {})
    out['gear_fixed_point'].update({'class':'mage','school':str(school),
        'weight_method':'fixed_policy_symmetric_difference_for_gear_loop'})

    # Publish the normal mature stat-weight contract exactly once around the
    # final gear state. This keeps listener semantics unchanged.
    final_items=real_gear._selection_from_snapshot(out.get('gear_stats') or {}) or tuple(selected_holder[0])
    selected_holder[0]=final_items
    node=LevelNode(int(level),t,float(out['total_s']),policy_holder[0],'analytic:gear-fp',dict(out))
    with real_gear.gear_override(final_items):
        probed=stat_weight_module._legacy_probe_node(node,cfg,options=options,school=school)
        out['gear_stats']=real_gear.snapshot(int(level))
    out['stat_weights']=dict((probed.details or {}).get('stat_weights') or {})
    return policy_holder[0],out


def search_level_analytic(level:int,cfg:eng.SimConfig,*,options=None,
                          beam_width:int=24,family_keep:int=4,final_k:int=12,
                          school:str='all'):
    """Independent analytical talent search for one level.

    The structural beam uses the very cheap pure-school deterministic proxy.
    Only final allocations pay the analytical steady-state policy search.  The
    returned objects are ``LevelNode`` instances so they can flow directly into
    continuity repair and the exact layered path DP.
    """
    from .analytic_scorer import AnalyticOptions,optimize_policy_analytic
    from .path_dp import LevelNode
    if options is None:
        options=AnalyticOptions()
    points=int(level)-9
    if points<1:
        return []
    width=max(4,int(beam_width)); fam_keep=max(1,int(family_keep)); out_k=max(1,int(final_k))
    beam=[eng.Talents()]
    proxy_cache:Dict[tuple[int,...],float]={}
    lane_cache:Dict[tuple[int,...],dict[str,float]]={}
    for _depth in range(points):
        expanded={}
        for t in beam:
            for name in eng.TALENT_RULES:
                if eng.legal_add(t,name):
                    q=eng.add_point(t,name)
                    expanded.setdefault(talent_key(q),q)
        scored=[]
        for k,q in expanded.items():
            v=proxy_cache.get(k)
            if v is None:
                try:
                    lanes=proxy_vector(level,q,cfg); lane_cache[k]=lanes
                    allowed=_school_proxy_lanes(school)
                    vals=[lanes[x] for x in allowed if x in lanes]
                    v=min(vals) if vals else float('inf')
                except Exception:
                    v=float('inf')
                proxy_cache[k]=v
            if v<float('inf'):
                scored.append((v,q))
        if not scored:
            break
        beam=_retain_diverse(scored,width,fam_keep,lane_cache,school=school)

    finals=[]
    use_mage_fp=(getattr(eng,'RULESET',None)=='forever' and getattr(eng,'CLASS_NAME',None)=='mage')
    for t in beam:
        try:
            if use_mage_fp:
                p,r=_mage_fixed_point_score(level,t,cfg,options=options,school=school)
            else:
                p,r=optimize_policy_analytic(level,t,cfg,options=options,school=school)
        except (ValueError,RuntimeError,OverflowError,RecursionError):
            continue
        d=dict(r); d['talent_search']='analytic_proxy_beam'; d['beam_width']=width
        source=f"analytic:{getattr(options,'kill_boundary_model','hard')}"
        finals.append(LevelNode(level,t,float(r['total_s']),p,source,d))
    finals.sort(key=lambda n:(n.score_s_per_100,_talent_tiebreak_key(n.talents),n.key))

    # Keep one allocation from every discovered tree family, then global leaders.
    out=[]; seen=set()
    for fam in _support_families(school):
        n=next((x for x in finals if family(x.talents)==fam),None)
        if n is not None and n.key not in seen:
            out.append(n); seen.add(n.key)
    for n in finals:
        if len(out)>=out_k: break
        if n.key not in seen:
            out.append(n); seen.add(n.key)
    out.sort(key=lambda n:(n.score_s_per_100,_talent_tiebreak_key(n.talents),n.key))
    return out[:out_k]
