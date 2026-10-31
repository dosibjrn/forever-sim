from __future__ import annotations

"""Embarrassingly-parallel level scoring for a fixed talent path.

A path is represented as ``{level: Talents}``.  Each level is independent and
can be scored in a separate process; only the final weighted reduction couples
levels.  Respec/path legality belongs in the outer DP, not in this scorer.
"""

from dataclasses import dataclass
from concurrent.futures import ProcessPoolExecutor
from typing import Mapping

from src.engine_registry import eng
from .analytic_scorer import optimize_policy_analytic


@dataclass(frozen=True)
class LevelScore:
    level:int
    talents:eng.Talents
    policy:eng.Policy
    seconds_per_100:float
    details:dict


@dataclass(frozen=True)
class PathScore:
    levels:tuple[LevelScore,...]
    weighted_score:float


def _score_one(args):
    level,talents,cfg=args
    p,r=optimize_policy_analytic(level,talents,cfg)
    return LevelScore(level,talents,p,float(r['total_s']),r)


def score_path_levels(allocations:Mapping[int,eng.Talents],cfg:eng.SimConfig,*,
                      weights:Mapping[int,float]|None=None,max_workers:int|None=None)->PathScore:
    items=sorted((int(l),t,cfg) for l,t in allocations.items())
    if max_workers==1 or len(items)<=1:
        rows=[_score_one(x) for x in items]
    else:
        with ProcessPoolExecutor(max_workers=max_workers) as ex:
            rows=list(ex.map(_score_one,items))
    w=weights or {r.level:1.0 for r in rows}
    total=sum(float(w.get(r.level,0.0))*r.seconds_per_100 for r in rows)
    return PathScore(tuple(rows),total)
