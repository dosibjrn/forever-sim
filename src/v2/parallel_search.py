from __future__ import annotations

"""Embarrassingly-parallel independent level pool generation."""

from concurrent.futures import ProcessPoolExecutor
import multiprocessing as mp
from typing import Iterable

from src.engine_registry import eng
from .analytic_scorer import AnalyticOptions
from .local_search import search_level_analytic


def _worker(args):
    level,cfg,options,beam_width,family_keep,final_k=args
    return level,search_level_analytic(level,cfg,options=options,beam_width=beam_width,
                                       family_keep=family_keep,final_k=final_k)


def search_levels_parallel(levels:Iterable[int],cfg:eng.SimConfig,*,options:AnalyticOptions=AnalyticOptions(),
                           beam_width:int=32,family_keep:int=6,final_k:int=20,
                           max_workers:int|None=None)->dict[int,list]:
    jobs=[(int(l),cfg,options,int(beam_width),int(family_keep),int(final_k)) for l in sorted(set(levels))]
    if max_workers==1 or len(jobs)<=1:
        return dict(_worker(j) for j in jobs)
    with ProcessPoolExecutor(max_workers=max_workers, mp_context=mp.get_context('spawn')) as ex:
        return dict(ex.map(_worker,jobs))
