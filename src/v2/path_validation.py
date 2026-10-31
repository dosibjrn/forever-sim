from __future__ import annotations

"""Stochastic validation for complete analytic talent paths.

A fixed path decomposes by level.  Each level can therefore be simulated in a
separate process, then the Classic Era XP weights combine means and variances.
This is the path-level counterpart of the analytic `build -> parallel levels ->
reduce` architecture.
"""

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
import math
import statistics
from typing import Sequence

from src.engine_registry import eng
from .objective import estimated_workload_mobs
from .path_dp import PathResult,PathStep


@dataclass(frozen=True)
class StochasticLevelEstimate:
    level:int
    mobs:int
    mean_s_per_mob:float
    stderr_s_per_mob:float
    estimated_level_mobs:float
    weighted_seconds:float
    weighted_se_seconds:float


@dataclass(frozen=True)
class StochasticPathEstimate:
    rows:tuple[StochasticLevelEstimate,...]
    total_seconds:float
    stderr_seconds:float
    mobs_simulated:int

    @property
    def hours(self)->float:return self.total_seconds/3600.0
    @property
    def stderr_hours(self)->float:return self.stderr_seconds/3600.0


@dataclass(frozen=True)
class PairedPathDelta:
    mean_delta_seconds:float
    stderr_delta_seconds:float
    block_deltas_seconds:tuple[float,...]
    mobs_per_level_per_block:int
    blocks:int

    @property
    def mean_delta_hours(self)->float:return self.mean_delta_seconds/3600.0
    @property
    def stderr_delta_hours(self)->float:return self.stderr_delta_seconds/3600.0


def _level_worker(args):
    step,cfg,mobs,seed=args
    if step.node.policy is None:
        raise ValueError(f'path level {step.node.level} has no frozen policy')
    r=eng.simulate_chain(step.node.level,step.node.talents,step.node.policy,cfg,n=int(mobs),seed=int(seed))
    nlevel=estimated_workload_mobs(step.node.level)
    mean=float(r['mean_s_per_mob']); se=float(r['stderr_s_per_mob'])
    return StochasticLevelEstimate(step.node.level,int(mobs),mean,se,nlevel,mean*nlevel,se*nlevel)


def _validated_positive_int(value:int, name:str)->int:
    value=int(value)
    if value <= 0:
        raise ValueError(f'{name} must be > 0')
    return value


def _path_levels(path:PathResult)->list[int]:
    levels=[int(step.node.level) for step in path.steps]
    if not levels:
        raise ValueError('path must contain at least one step')
    if len(set(levels)) != len(levels):
        raise ValueError('path contains duplicate levels')
    if any(b != a + 1 for a,b in zip(levels, levels[1:])):
        raise ValueError('path levels must be contiguous and increasing')
    return levels


def estimate_path_stochastic(path:PathResult,cfg:eng.SimConfig,*,mobs_per_level:int=500,
                             seed:int=1,max_workers:int|None=None)->StochasticPathEstimate:
    mobs_per_level=_validated_positive_int(mobs_per_level, 'mobs_per_level')
    _path_levels(path)
    jobs=[]
    for i,step in enumerate(path.steps):
        jobs.append((step,cfg,mobs_per_level,int(seed)+i*1_000_003))
    if max_workers==1 or len(jobs)<=1:
        rows=[_level_worker(j) for j in jobs]
    else:
        with ProcessPoolExecutor(max_workers=max_workers) as ex:
            rows=list(ex.map(_level_worker,jobs))
    total=sum(r.weighted_seconds for r in rows)
    se=math.sqrt(sum(r.weighted_se_seconds*r.weighted_se_seconds for r in rows))
    return StochasticPathEstimate(tuple(rows),total,se,sum(r.mobs for r in rows))


def _paired_block_worker(args):
    path_a,path_b,cfg,mobs,seed=args
    by_level_a={s.node.level:s for s in path_a.steps};by_level_b={s.node.level:s for s in path_b.steps}
    levels=sorted(set(by_level_a)&set(by_level_b))
    if levels!=sorted(by_level_a) or levels!=sorted(by_level_b):
        raise ValueError('paired path comparison requires identical level ranges')
    delta=0.0
    for j,lvl in enumerate(levels):
        sa=by_level_a[lvl];sb=by_level_b[lvl]
        sd=int(seed)+j*104729
        ra=eng.simulate_chain(lvl,sa.node.talents,sa.node.policy,cfg,n=int(mobs),seed=sd)
        rb=eng.simulate_chain(lvl,sb.node.talents,sb.node.policy,cfg,n=int(mobs),seed=sd)
        nlevel=estimated_workload_mobs(lvl)
        delta+=(float(ra['mean_s_per_mob'])-float(rb['mean_s_per_mob']))*nlevel
    return delta


def compare_paths_paired(path_a:PathResult,path_b:PathResult,cfg:eng.SimConfig,*,
                         mobs_per_level_per_block:int=200,blocks:int=8,seed:int=1,
                         max_workers:int|None=None)->PairedPathDelta:
    mobs_per_level_per_block=_validated_positive_int(mobs_per_level_per_block, 'mobs_per_level_per_block')
    blocks=_validated_positive_int(blocks, 'blocks')
    levels_a=_path_levels(path_a); levels_b=_path_levels(path_b)
    if levels_a != levels_b:
        raise ValueError('paired path comparison requires identical level ranges')
    jobs=[(path_a,path_b,cfg,mobs_per_level_per_block,int(seed)+b*10_000_019) for b in range(blocks)]
    if max_workers==1 or len(jobs)<=1:
        ds=[_paired_block_worker(j) for j in jobs]
    else:
        with ProcessPoolExecutor(max_workers=max_workers) as ex:
            ds=list(ex.map(_paired_block_worker,jobs))
    mean=statistics.mean(ds)
    se=statistics.stdev(ds)/math.sqrt(len(ds)) if len(ds)>1 else math.inf
    return PairedPathDelta(mean,se,tuple(ds),mobs_per_level_per_block,blocks)
