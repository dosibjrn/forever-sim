from __future__ import annotations

"""Talent allocation -> low-dimensional mechanics projection.

The combat scorer does not care about talent names.  It cares about the small
set of derived mechanics those talents produce: cast time, mana, damage/crit,
hit, range/control, regeneration and cooldown deltas.  This module makes that
quotient space explicit and measures its numerical rank with SVD/PCA.
"""

from dataclasses import dataclass
import random
from typing import Iterable, Sequence
import numpy as np

from src.engine_registry import eng
from .expected_engine import ExpectedState, expected_direct_components


FEATURE_NAMES=(
    'max_mana','regen_5sr','regen_out',
    'fbo_cast','fbo_mana','fbo_damage','fbo_range','frost_hit','frost_crit_mult','frost_root_p','frost_slow',
    'fba_cast','fba_mana','fba_damage','fba_range','fire_hit','fire_crit','ignite_frac',
    'scorch_crit','scorch_stack_p','master_elements_refund',
    'fireblast_cd','nova_cd','nova_range',
    'arcane_hit','am_mana','am_protection','clearcast_proc',
    'pyro_unlocked','combustion_unlocked',
    'ice_barrier_absorb','ice_barrier_mana',
)


def _regen_rates(level:int,t:eng.Talents,cfg:eng.SimConfig,stats:eng.Stats)->tuple[float,float]:
    base=(12.5+stats.spirit/4.0)/2.0
    return base*eng.regen_fraction_in_5sr(level,t,cfg),base


def mechanics_vector(level:int,t:eng.Talents,cfg:eng.SimConfig|None=None)->np.ndarray:
    cfg=cfg or eng.SimConfig()
    stats=eng.player_stats(level,t,cfg.owl_intensity)
    r5,rout=_regen_rates(level,t,cfg,stats)
    dummy=ExpectedState(0.0,1e9,stats.max_mana,stats.max_mana,30.0)
    vals=[stats.max_mana,r5,rout]

    fbo=eng.latest(eng.FROSTBOLT,level)
    if fbo:
        comp=expected_direct_components(level,level+1,fbo,t,stats,cfg,dummy)
        vals += [max(.5,fbo.cast-.1*t.imp_frostbolt),eng.mana_cost(fbo,t,stats),comp['damage'],eng.effective_range(fbo,t),
                 comp['hit'],eng.crit_mult(fbo,t),comp['hit']*.05*t.frostbite,
                 (0.40+[0,.04,.07,.10][int(max(0,min(3,t.permafrost)))])*comp['hit']]
    else: vals += [0.0]*8

    fba=eng.latest(eng.FIREBALL,level)
    if fba:
        comp=expected_direct_components(level,level+1,fba,t,stats,cfg,dummy)
        vals += [max(.5,fba.cast-.1*t.imp_fireball),eng.mana_cost(fba,t,stats),comp['damage'],eng.effective_range(fba,t),
                 comp['hit'],comp['crit_p'],.08*t.ignite]
    else: vals += [0.0]*7

    sc=eng.latest(eng.SCORCH,level)
    if sc:
        comp=expected_direct_components(level,level+1,sc,t,stats,cfg,dummy)
        proc=(0.0,1/3,2/3,1.0)[int(max(0,min(3,t.imp_scorch)))]
        vals += [comp['crit_p'],comp['hit']*proc,.10*t.master_elements]
    else: vals += [0.0]*3

    fb=eng.latest(eng.FIRE_BLAST,level)
    fbcd=max(1.0,fb.cooldown-.5*t.imp_fire_blast) if fb else 0.0
    nova=eng.latest(eng.FROST_NOVA,level)
    ncd=max(1.0,nova.cooldown-2*t.imp_frost_nova) if nova else 0.0
    nrange=nova.radius*(1+.1*t.arctic_reach) if nova else 0.0
    vals += [fbcd,ncd,nrange]

    am=eng.latest(eng.ARCANE_MISSILES,level)
    ahit=eng.spell_hit(level,level+1,'arcane',t)
    br=eng.ice_barrier_rank(level) if t.ice_barrier else None
    vals += [ahit,am.mana if am else 0.0,.20*t.imp_arcane_missiles,.02*t.arcane_concentration,
             1.0 if t.pyroblast else 0.0,1.0 if t.combustion else 0.0,
             float(br.absorb) if br else 0.0,
             eng.ice_barrier_mana_cost(level,t) if br else 0.0]
    out=np.asarray(vals,dtype=float)
    if len(out)!=len(FEATURE_NAMES):
        raise AssertionError((len(out),len(FEATURE_NAMES)))
    return out


def talent_key(t:eng.Talents)->tuple[int,...]:
    return tuple(int(round(getattr(t,n))) for n in t.__dataclass_fields__)


def sample_legal_builds(level:int,n:int=1000,seed:int=1)->list[eng.Talents]:
    """Cheap structural candidate pool; no combat scoring is performed."""
    points=max(0,int(level)-9)
    rng=random.Random(seed)
    names=list(eng.TALENT_RULES)
    trees={tr:[nm for nm,(tree,*_) in eng.TALENT_RULES.items() if tree==tr] for tr in ('frost','arcane','fire')}
    out={}

    def walk(bias:str|None=None)->eng.Talents|None:
        t=eng.Talents()
        for _ in range(points):
            legal=[nm for nm in names if eng.legal_add(t,nm)]
            if not legal: return None
            if bias:
                preferred=[nm for nm in legal if eng.TALENT_RULES[nm][0]==bias]
                # Mostly stay in the requested tree, but retain hybrids.
                if preferred and rng.random()<.82: legal=preferred
            # Mild value bias toward modeled talents over neutral gate fillers.
            weighted=[]
            for nm in legal:
                neutral=nm in {'frost_warding','improved_blizzard','cold_snap','ice_block','improved_cone_of_cold',
                               'arcane_filler','improved_flamestrike','fire_warding','arcane_resilience','impact'}
                weighted.extend([nm]*(1 if neutral else 3))
            t=eng.add_point(t,rng.choice(weighted))
        return t

    # Deterministic school-biased/random mix.
    modes=('frost','fire','arcane',None)
    attempts=max(n*20,200)
    for i in range(attempts):
        t=walk(modes[i%len(modes)])
        if t is not None and t.points()==points:
            out.setdefault(talent_key(t),t)
        if len(out)>=n: break
    return list(out.values())


@dataclass
class MechanicsProjection:
    level:int
    mean:np.ndarray
    scale:np.ndarray
    components:np.ndarray   # k x features
    singular_values:np.ndarray
    explained_ratio:np.ndarray
    feature_names:tuple[str,...]=FEATURE_NAMES

    @property
    def dims(self)->int: return int(self.components.shape[0])

    def transform_vectors(self,x:np.ndarray)->np.ndarray:
        xx=(np.asarray(x,float)-self.mean)/self.scale
        return xx@self.components.T

    def transform_builds(self,builds:Sequence[eng.Talents],cfg:eng.SimConfig|None=None)->np.ndarray:
        x=np.vstack([mechanics_vector(self.level,b,cfg) for b in builds])
        return self.transform_vectors(x)

    def reconstruct_vectors(self,z:np.ndarray)->np.ndarray:
        zz=np.asarray(z,float)
        return (zz@self.components)*self.scale+self.mean


def fit_mechanics_projection(level:int,builds:Sequence[eng.Talents],cfg:eng.SimConfig|None=None,
                             *,dims:int|None=None,variance_target:float=.995,max_dims:int=10)->MechanicsProjection:
    if len(builds)<2: raise ValueError('need at least two builds')
    x=np.vstack([mechanics_vector(level,b,cfg) for b in builds])
    mean=x.mean(axis=0)
    scale=x.std(axis=0)
    scale=np.where(scale<1e-12,1.0,scale)
    xs=(x-mean)/scale
    _,s,vt=np.linalg.svd(xs,full_matrices=False)
    var=s*s
    ratio=var/var.sum() if var.sum()>0 else np.zeros_like(var)
    if dims is None:
        cum=np.cumsum(ratio)
        dims=int(np.searchsorted(cum,variance_target)+1)
        dims=max(1,min(int(max_dims),dims,vt.shape[0]))
    else:
        dims=max(1,min(int(dims),vt.shape[0]))
    return MechanicsProjection(level,mean,scale,vt[:dims],s,ratio)


def projection_diagnostics(proj:MechanicsProjection)->dict:
    k=proj.dims
    return {
        'dims':k,
        'explained_variance':float(proj.explained_ratio[:k].sum()),
        'effective_rank_99':int(np.searchsorted(np.cumsum(proj.explained_ratio),.99)+1),
        'effective_rank_995':int(np.searchsorted(np.cumsum(proj.explained_ratio),.995)+1),
        'singular_values':proj.singular_values.tolist(),
    }
