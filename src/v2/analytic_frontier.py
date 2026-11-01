from __future__ import annotations

"""Two-view analytical candidate generation.

The hard discrete kill boundary and a variance-smoothed boundary have different
model biases.  They are kept as separate coherent views; scores are never mixed
inside one path.  Candidate selection may take the union of their leaders.
"""

from dataclasses import dataclass
from typing import Iterable,Sequence

from src.engine_registry import eng
from .analytic_scorer import AnalyticOptions,optimize_policy_analytic
from .local_search import family,talent_key
from .path_dp import LevelNode


@dataclass(frozen=True)
class AnalyticView:
    name:str
    options:AnalyticOptions


def default_views()->tuple[AnalyticView,...]:
    return (
        AnalyticView('hard',AnalyticOptions(kill_boundary_model='hard')),
        AnalyticView('smooth',AnalyticOptions(kill_boundary_model='normal5q',kill_boundary_sigma_scale=1.0)),
    )


def score_build_view(level:int,talents:eng.Talents,cfg:eng.SimConfig,view:AnalyticView,*,school:str="all")->LevelNode:
    if eng.normalize_primary_school(school)=='all':
        p,r=optimize_policy_analytic(level,talents,cfg,options=view.options)
    else:
        p,r=optimize_policy_analytic(level,talents,cfg,options=view.options,school=school)
    d=dict(r); d['analytic_view']=view.name
    return LevelNode(level,talents,float(r['total_s']),p,view.name,d)


def score_builds_view(level:int,builds:Iterable[eng.Talents],cfg:eng.SimConfig,view:AnalyticView,*,school:str="all")->list[LevelNode]:
    out=[]
    for t in builds:
        try:
            if eng.normalize_primary_school(school)=='all':
                out.append(score_build_view(level,t,cfg,view))
            else:
                out.append(score_build_view(level,t,cfg,view,school=school))
        except (ValueError,RuntimeError,OverflowError,RecursionError):
            continue
    out.sort(key=lambda n:(n.score_s_per_100,eng.talent_preference_key(n.talents),n.key))
    return out


def union_view_leaders(scored_by_view:Sequence[Sequence[LevelNode]],*,top_k_per_view:int=8,
                       family_keep:int=1)->list[LevelNode]:
    """Union leaders without comparing score magnitudes across analytic views."""
    out=[]; seen=set()
    for rows in scored_by_view:
        rows=list(rows)
        # Family leaders protect against approximation collapse.
        for fam in ('frost','arcane','fire','mixed'):
            n=0
            for row in rows:
                if family(row.talents)!=fam: continue
                k=(row.key,row.source)
                if k not in seen:
                    out.append(row); seen.add(k); n+=1
                if n>=max(0,int(family_keep)): break
        for row in rows[:max(1,int(top_k_per_view))]:
            k=(row.key,row.source)
            if k not in seen:
                out.append(row); seen.add(k)
    return out
