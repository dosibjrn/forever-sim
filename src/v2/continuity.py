from __future__ import annotations

"""Bounded forward continuity repair for independent per-level analytic pools.

Independent level search is intentionally embarrassingly parallel, so its top-K
allocations need not form legal +1-talent paths.  The repair layer must add just
enough structure for exact path DP without reconstructing the full talent subset
lattice.

Strategy
--------
* Three guaranteed legal greedy spines (Frost / Arcane / Fire) exist through the
  full level range.  Therefore a 0-respec path is always available.
* A small number of independent leaders at every level are treated as possible
  respec landing points.
* From those leaders plus a bounded set of already-propagated trails, keep only
  ``parent_k`` best legal children by the O(1) structural proxy.
* Rich analytic scoring is performed only for the missing nodes that survive
  this bounded structural repair.

The function name ``close_pools_backward`` is retained as an API compatibility
alias for older runner/tests; the implementation is forward and bounded.
"""

from concurrent.futures import ProcessPoolExecutor
import math
from typing import Mapping, Sequence

from src.engine_registry import eng
from .analytic_frontier import AnalyticView, score_builds_view
from .local_search import proxy_score, talent_key, family
from .path_dp import LevelNode


def legal_children(parent:eng.Talents)->list[eng.Talents]:
    out=[]
    for name in eng.TALENT_RULES:
        try:
            if eng.legal_add(parent,name):
                out.append(eng.add_point(parent,name))
        except Exception:
            continue
    return out


def _proxy_rank(level:int,t:eng.Talents,cfg:eng.SimConfig,school:str="all")->tuple:
    try:
        s=float(proxy_score(level,t,cfg) if eng.normalize_primary_school(school)=='all' else proxy_score(level,t,cfg,school=school))
    except Exception: s=math.inf
    return s,eng.talent_preference_key(t)


def _added_tree(parent:eng.Talents,child:eng.Talents)->str|None:
    found=None
    for name,rule in eng.TALENT_RULES.items():
        d=int(getattr(child,name))-int(getattr(parent,name))
        if d==0:
            continue
        if d!=1 or found is not None:
            return None
        found=str(rule[0])
    return found


def _future_unlock_steps(t:eng.Talents,tree:str)->int|None:
    """Minimum *future* points needed to gain a currently gated talent.

    Tier/prerequisite setup can be locally neutral for several levels.  This is
    only a retention hint; it does not contribute to the objective score.
    """
    pts=int(eng.tree_points(t,tree))
    best=None
    for name,rule in eng.TALENT_RULES.items():
        rtree,max_rank,required,prereq=rule
        if rtree!=tree or int(getattr(t,name))>=int(max_rank):
            continue
        missing_tier=max(0,int(required)-pts)
        missing_prereq=0
        if prereq:
            pname,prank=prereq
            missing_prereq=max(0,int(prank)-int(getattr(t,pname)))
        # Only talents that are structurally gated create future-option value.
        # If the child has *just* satisfied the gate, the payoff is one point
        # away and must remain alive for the next level.
        if int(required)<=0 and not prereq:
            continue
        steps=max(missing_tier,missing_prereq)+1  # setup points + first rank
        best=steps if best is None else min(best,steps)
    return best


def _family_greedy_spines(start_level:int,end_level:int,cfg:eng.SimConfig,school:str="all")->dict[str,dict[int,eng.Talents]]:
    """Construct one legal no-respec path per tree, deterministically."""
    out={}
    requested=eng.normalize_primary_school(school)
    fams=('frost','arcane','fire') if requested=='all' else tuple(dict.fromkeys((requested,'arcane')))
    for fam in fams:
        t=eng.Talents(); rows={}
        for points in range(1,end_level-8):  # points 1 .. end_level-9 inclusive
            level=points+9
            children=legal_children(t)
            same=[q for q in children if any(
                int(getattr(q,n))>int(getattr(t,n)) and eng.TALENT_RULES[n][0]==fam
                for n in eng.TALENT_RULES
            )]
            cand=same or children
            if not cand:
                break
            # Proxy is secondary to staying in the requested tree.
            cand.sort(key=lambda q:_proxy_rank(level,q,cfg,school))
            t=cand[0]
            if start_level<=level<=end_level:
                rows[level]=t
        out[fam]=rows
    return out


def _score_missing_worker(args):
    if len(args)==4:
        level,builds,cfg,view=args; school='all'
    else:
        level,builds,cfg,view,school=args
    if eng.normalize_primary_school(school)=='all':
        return level,score_builds_view(level,builds,cfg,view)
    return level,score_builds_view(level,builds,cfg,view,school=school)


def close_pools_forward(pools:Mapping[int,Sequence[LevelNode]],cfg:eng.SimConfig,view:AnalyticView,*,
                        parent_k:int=1,start_level:int|None=None,end_level:int|None=None,
                        max_workers:int|None=None,leader_seeds:int=4,trail_cap:int=12,
                        school:str='all')->dict[int,list[LevelNode]]:
    if not pools: raise ValueError('no pools')
    all_levels=sorted(int(x) for x in pools)
    lo=all_levels[0] if start_level is None else int(start_level)
    hi=all_levels[-1] if end_level is None else int(end_level)
    levels=[l for l in all_levels if lo<=l<=hi]
    if not levels or any(b!=a+1 for a,b in zip(levels,levels[1:])):
        raise ValueError('continuity repair requires contiguous level pools')
    pk=max(1,int(parent_k)); seed_k=max(1,int(leader_seeds)); cap=max(3,int(trail_cap))

    node_maps={l:{n.key:n for n in pools[l]} for l in levels}
    original_keys={l:[n.key for n in sorted(pools[l],key=lambda n:(n.score_s_per_100,eng.talent_preference_key(n.talents),n.key))] for l in levels}
    talent_maps={l:{n.key:n.talents for n in pools[l]} for l in levels}

    # Guaranteed legal no-respec backbones.  These are structural only for now;
    # missing nodes are rich-scored in one batch below.
    spines=_family_greedy_spines(lo,hi,cfg,school)
    spine_keys={l:set() for l in levels}
    for rows in spines.values():
        for l,t in rows.items():
            if l not in talent_maps: continue
            k=talent_key(t); talent_maps[l][k]=t; spine_keys[l].add(k)

    # Active trails are generated children selected to continue forward.  At
    # every level, a few independent leaders are also allowed to start a new
    # trail because a respec may land there.
    active=set(spine_keys[lo])
    for idx,l in enumerate(levels[:-1]):
        nl=levels[idx+1]
        parent_keys=[]
        parent_keys.extend(original_keys[l][:seed_k])
        parent_keys.extend(sorted(active))
        parent_keys.extend(sorted(spine_keys[l]))
        seen=set(); parents=[]
        for k in parent_keys:
            if k in seen: continue
            t=talent_maps[l].get(k)
            if t is not None:
                parents.append(t); seen.add(k)

        generated={}
        future_lanes={}  # (parent dominant family, destination tree) -> (steps,rank,child)
        remaining=max(0,hi-nl)
        for p in parents:
            kids=legal_children(p)
            kids.sort(key=lambda q:_proxy_rank(nl,q,cfg,school))
            for q in kids[:pk]:
                generated.setdefault(talent_key(q),q)

            # Local score alone cannot distinguish a prerequisite investment
            # from a dead-end filler. Preserve only a bounded representative
            # for each cross-tree future-unlock lane; do not expand all kids.
            pfam=family(p)
            for q in kids:
                dst=_added_tree(p,q)
                if dst is None:
                    continue
                steps=_future_unlock_steps(q,dst)
                if steps is None or steps>remaining:
                    continue
                lane=(pfam,dst)
                rank=(_proxy_rank(nl,q,cfg,school),talent_key(q))
                old=future_lanes.get(lane)
                cand=(steps,rank,q)
                if old is None or (steps,rank)<(old[0],old[1]):
                    future_lanes[lane]=cand

        future_nodes=[x[2] for x in future_lanes.values()]
        for q in future_nodes:
            generated.setdefault(talent_key(q),q)

        # Always insert generated children into the next candidate graph. Only
        # a bounded best subset remains active for another propagation step.
        talent_maps[nl].update(generated)
        ranked=sorted(generated.values(),key=lambda q:_proxy_rank(nl,q,cfg,school))
        chosen=[]; chosen_keys=set()

        # Keep bounded future-setup lanes active. The lane key includes the
        # parent's dominant family because Fire->Arcane and pure Arcane->Arcane
        # have very different downstream states even if their current score is
        # identical. There are at most 4*3 lane keys, bounded by trail_cap.
        ordered_future=sorted(future_lanes.values(),key=lambda x:(x[0],x[1]))
        for _steps,_rank,q in ordered_future:
            if len(chosen)>=cap:
                break
            k=talent_key(q)
            if k not in chosen_keys:
                chosen.append(q); chosen_keys.add(k)

        # Preserve at least one trail per current family when available.
        requested=eng.normalize_primary_school(school)
        preserve=('frost','arcane','fire','mixed') if requested=='all' else tuple(dict.fromkeys((requested,'arcane','mixed')))
        for fam in preserve:
            q=next((x for x in ranked if family(x)==fam),None)
            if q is not None:
                k=talent_key(q)
                if k not in chosen_keys and len(chosen)<cap:
                    chosen.append(q); chosen_keys.add(k)
        for q in ranked:
            if len(chosen)>=cap: break
            k=talent_key(q)
            if k not in chosen_keys:
                chosen.append(q); chosen_keys.add(k)
        active={talent_key(q) for q in chosen} | set(spine_keys[nl])

    # Rich-score exactly the structural additions, independently per level.
    jobs=[]
    for l in levels:
        missing=[t for k,t in talent_maps[l].items() if k not in node_maps[l]]
        if missing:
            jobs.append((l,missing,cfg,view) if eng.normalize_primary_school(school)=='all' else (l,missing,cfg,view,school))
    if jobs:
        if max_workers in (None,1) or len(jobs)<=1:
            scored=dict(_score_missing_worker(j) for j in jobs)
        else:
            with ProcessPoolExecutor(max_workers=max_workers) as ex:
                scored=dict(ex.map(_score_missing_worker,jobs))
        for l,rows in scored.items():
            for n in rows: node_maps[l][n.key]=n

    out={}
    for l in levels:
        rows=list(node_maps[l].values())
        rows.sort(key=lambda n:(n.score_s_per_100,eng.talent_preference_key(n.talents),n.key))
        out[l]=rows
    return out


def close_pools_backward(pools:Mapping[int,Sequence[LevelNode]],cfg:eng.SimConfig,view:AnalyticView,**kwargs):
    """Compatibility alias; repair is now bounded forward propagation."""
    return close_pools_forward(pools,cfg,view,**kwargs)
