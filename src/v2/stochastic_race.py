from __future__ import annotations

"""Variance-aware final validation for a frozen shortlist.

This is not used for broad search.  It is a conservative stochastic adjudicator
for analytic finalists: start every candidate at a small sample, retain only
candidates whose confidence intervals still overlap the best plausible score,
and extend survivors using v1's exact continuation state.
"""

from dataclasses import dataclass
import math
from statistics import NormalDist
from typing import Sequence

from src.engine_registry import eng
from .stochastic_diagnostics import Candidate

EPS=1e-12


@dataclass
class RaceRow:
    candidate_index:int
    mobs:int
    mean_s_per_mob:float
    stderr_s_per_mob:float
    lower_s_per_mob:float
    upper_s_per_mob:float
    eliminated:bool=False


@dataclass
class RaceResult:
    winner_index:int
    survivor_indices:tuple[int,...]
    resolved:bool
    rows:tuple[RaceRow,...]
    rounds:int
    total_mobs_simulated:int
    critical_z:float


def _z_bonferroni(alpha:float,n:int)->float:
    # Two-sided family-wise interval across n candidates.
    tail=max(1e-15,min(.25,float(alpha)/(2.0*max(1,n))))
    return NormalDist().inv_cdf(1.0-tail)


def race_candidates(level:int,candidates:Sequence[Candidate],cfg:eng.SimConfig,*,
                    start_mobs:int=100,max_mobs:int=3200,growth:int=2,
                    alpha:float=.05,seed:int=1)->RaceResult:
    if not candidates: raise ValueError('no candidates')
    if start_mobs<2 or max_mobs<start_mobs: raise ValueError('invalid mob limits')
    if growth<2: raise ValueError('growth must be >=2')
    z=_z_bonferroni(alpha,len(candidates))
    alive=set(range(len(candidates)))
    cont=[None]*len(candidates)
    metrics=[None]*len(candidates)
    mobs=[0]*len(candidates)
    total_sim=0; rounds=0; target=int(start_mobs)

    while alive:
        rounds+=1
        for i in sorted(alive):
            prev=mobs[i]
            out,state=eng.simulate_chain_incremental(
                level,candidates[i].talents,candidates[i].policy,cfg,
                target_n=target,seed=seed+i*1_000_003,continuation=cont[i],
            )
            metrics[i]=out; cont[i]=state; mobs[i]=target
            total_sim+=target-prev

        # Candidate is safely eliminable when even its optimistic lower bound is
        # slower than another candidate's pessimistic upper bound.
        intervals={}
        for i in alive:
            m=float(metrics[i]['mean_s_per_mob']); se=float(metrics[i]['stderr_s_per_mob'])
            intervals[i]=(m-z*se,m+z*se)
        best_upper=min(u for _,u in intervals.values())
        drop={i for i,(l,u) in intervals.items() if l>best_upper+1e-12}
        if len(drop)>=len(alive):
            drop.clear()
        alive-=drop
        if len(alive)<=1 or target>=max_mobs:
            break
        target=min(max_mobs,target*growth)

    # Winner is the lowest current sample mean among survivors; all rows are
    # reported for diagnostics, including earlier eliminations.
    valid=[i for i,m in enumerate(metrics) if m is not None]
    winner=min(alive if alive else valid,key=lambda i:float(metrics[i]['mean_s_per_mob']))
    rows=[]
    for i in valid:
        m=float(metrics[i]['mean_s_per_mob']); se=float(metrics[i]['stderr_s_per_mob'])
        rows.append(RaceRow(i,mobs[i],m,se,m-z*se,m+z*se,i not in alive))
    rows.sort(key=lambda r:r.mean_s_per_mob)
    survivors=tuple(sorted(alive))
    return RaceResult(winner,survivors,len(survivors)==1,tuple(rows),rounds,total_sim,z)
