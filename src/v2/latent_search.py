from __future__ import annotations

"""Low-dimensional proposal search over the mechanics manifold.

This is deliberately optional.  The exact answer always comes from scoring a
legal talent build.  Nelder-Mead only proposes locations in a PCA mechanics
space; those locations are projected back to nearby legal builds and rescored.
"""

from dataclasses import dataclass
from typing import Callable, Sequence
import math
import numpy as np
from scipy.optimize import minimize

from src.engine_registry import eng
from .mechanics_projection import MechanicsProjection, fit_mechanics_projection


@dataclass
class LatentSearchResult:
    talents:eng.Talents
    score:float
    exact_evaluations:int
    anchor_indices:list[int]
    finalist_indices:list[int]
    latent_optima:list[np.ndarray]
    projection:MechanicsProjection


def _farthest_indices(z:np.ndarray,n:int,seed_index:int=0)->list[int]:
    n=min(max(1,int(n)),len(z))
    chosen=[int(seed_index)%len(z)]
    d2=np.sum((z-z[chosen[0]])**2,axis=1)
    while len(chosen)<n:
        i=int(np.argmax(d2))
        chosen.append(i)
        nd=np.sum((z-z[i])**2,axis=1)
        d2=np.minimum(d2,nd)
    return chosen


def _poly_design(z:np.ndarray)->np.ndarray:
    z=np.asarray(z,float)
    if z.ndim==1:z=z[None,:]
    cols=[np.ones(len(z))]
    for i in range(z.shape[1]): cols.append(z[:,i])
    for i in range(z.shape[1]): cols.append(z[:,i]**2)
    for i in range(z.shape[1]):
        for j in range(i+1,z.shape[1]): cols.append(z[:,i]*z[:,j])
    return np.column_stack(cols)


def _fit_ridge_quadratic(z:np.ndarray,y:np.ndarray,lam:float=1e-5)->np.ndarray:
    a=_poly_design(z)
    scale=max(1.0,float(np.median(np.abs(y))))
    yy=y/scale
    gram=a.T@a
    reg=np.eye(gram.shape[0])*lam
    reg[0,0]=0.0
    beta=np.linalg.solve(gram+reg,a.T@yy)
    return beta*scale


def _predict(beta:np.ndarray,z:np.ndarray)->np.ndarray:
    return _poly_design(np.asarray(z,float))@beta


def search_latent(candidates:Sequence[eng.Talents],level:int,score_fn:Callable[[eng.Talents],float],*,
                  dims:int=4,anchors:int=48,finalists:int=48,starts:int=5,
                  projection:MechanicsProjection|None=None)->LatentSearchResult:
    if not candidates: raise ValueError('empty candidate set')
    proj=projection or fit_mechanics_projection(level,candidates,dims=dims)
    z=proj.transform_builds(candidates)
    # Farthest-point anchors give broad coverage without combat scoring the pool.
    centroid=z.mean(axis=0)
    seed=int(np.argmin(np.sum((z-centroid)**2,axis=1)))
    anchor_idx=_farthest_indices(z,anchors,seed)
    y=np.asarray([float(score_fn(candidates[i])) for i in anchor_idx])
    beta=_fit_ridge_quadratic(z[anchor_idx],y)

    lo=z.min(axis=0); hi=z.max(axis=0)
    span=np.maximum(hi-lo,1e-9)
    def objective(x):
        x=np.asarray(x,float)
        clipped=np.clip(x,lo,hi)
        outside=np.sum(((x-clipped)/span)**2)
        return float(_predict(beta,clipped)[0] + outside*max(1.0,float(np.std(y)))*100.0)

    order=np.argsort(y)[:max(1,min(starts,len(anchor_idx)))]
    optima=[]
    for j in order:
        x0=z[anchor_idx[int(j)]]
        res=minimize(objective,x0,method='Nelder-Mead',options={'maxiter':400,'xatol':1e-5,'fatol':1e-5})
        optima.append(np.clip(np.asarray(res.x,float),lo,hi))

    # Candidate priorities: close to any continuous optimum, then low surrogate.
    mind=np.full(len(candidates),np.inf)
    for x in optima:
        d=np.sum(((z-x)/span)**2,axis=1)
        mind=np.minimum(mind,d)
    pred=_predict(beta,z)
    # Union of geometry-nearest and surrogate-best, deduplicated.
    want=max(1,int(finalists))
    idx=[]; seen=set()
    for arr in (np.argsort(mind)[:want],np.argsort(pred)[:want]):
        for i in arr:
            i=int(i)
            if i not in seen:
                seen.add(i); idx.append(i)
            if len(idx)>=2*want: break
    # Anchors are already exact-scored; reuse them rather than recompute.
    scores={i:float(v) for i,v in zip(anchor_idx,y)}
    for i in idx:
        if i not in scores: scores[i]=float(score_fn(candidates[i]))
    best_i=min(scores,key=lambda i:(scores[i],i))
    return LatentSearchResult(candidates[best_i],scores[best_i],len(scores),anchor_idx,idx,optima,proj)
