from __future__ import annotations

"""Bounded, user-triggered Forever Mage structural validation probes.

This is deliberately not a full optimizer run. It reuses the current per-level
candidate search, then scores the retained candidates with the event backend so
listener controls can answer concrete questions such as "Ice Lance at L20 vs
best current-level build" in the same mobs/hour unit.
"""

import argparse, json
from src.engine_registry import eng
from .local_search import search_level_analytic


def _event_row(level:int, node, cfg, *, n:int=32, seed:int=7) -> dict:
    school='frost'
    result=eng.policy_search(level,node.talents,cfg,school,n=n,seed=seed)
    best=dict(result.get('best_found') or {})
    return {
        'allocation':eng.final_allocation(node.talents),
        'talent_ranks':{k:int(getattr(node.talents,k)) for k in node.talents.__dataclass_fields__ if int(getattr(node.talents,k))},
        'rotation':best.get('rotation'),
        'policy':best.get('policy'),
        'mobs_per_hour':float(best.get('mobs_per_hour') or 0.0),
        'seconds_per_mob':float(best.get('seconds_per_mob') or 0.0),
        'kill_seconds_per_mob':float(best.get('kill_seconds_per_mob') or 0.0),
        'recovery_seconds_per_mob':float(best.get('recovery_seconds_per_mob') or 0.0),
        'ice_lance':bool(getattr(node.talents,'ice_lance',0)),
        'analytic_score_s_per_100':float(node.score_s_per_100),
    }


def validate_ice_lance(level:int=20, *, n:int=32, seed:int=7) -> dict:
    level=int(level)
    cfg=eng.SimConfig()
    rows=search_level_analytic(level,cfg,beam_width=24,family_keep=4,final_k=24,school='frost')
    if not rows:
        raise RuntimeError(f'no Mage candidates at L{level}')
    # Compare every retained candidate with the same event scorer. This makes
    # "Ice Lance vs optimum" a like-for-like event comparison, not analytic vs MC.
    scored=[_event_row(level,row,cfg,n=n,seed=seed) for row in rows]
    scored.sort(key=lambda x:(-x['mobs_per_hour'],x['allocation']))
    optimum=scored[0]
    il_rows=[x for x in scored if x['ice_lance']]
    best_il=il_rows[0] if il_rows else None
    delta=None
    if best_il is not None:
        delta=float(best_il['mobs_per_hour'])-float(optimum['mobs_per_hour'])
    return {
        'schema_version':1,
        'question':'ice_lance_vs_current_level_optimum',
        'level':level,
        'target_level':level,
        'target_contract':'same-level mob; current best-food/water and sustained-resource config',
        'event_samples':int(n),
        'seed':int(seed),
        'candidate_count':len(scored),
        'ice_lance_candidate_count':len(il_rows),
        'optimum':optimum,
        'best_ice_lance':best_il,
        'delta_mobs_per_hour':delta,
        'ice_lance_is_optimum':bool(best_il is not None and abs(delta or 0.0)<1e-9),
        'authority':'bounded event comparison over retained current-level candidate pool; not exhaustive proof',
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--level',type=int,default=20)
    ap.add_argument('--n',type=int,default=32)
    ap.add_argument('--seed',type=int,default=7)
    a=ap.parse_args()
    print(json.dumps(validate_ice_lance(a.level,n=a.n,seed=a.seed),ensure_ascii=False,separators=(',',':')))

if __name__=='__main__':
    main()
