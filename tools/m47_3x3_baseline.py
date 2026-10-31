from __future__ import annotations

import argparse, csv, dataclasses, json, math, re, sys
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

from src import game_context
from src.engine_registry import get_engine, reset_engine_cache
from src.v2.analytic_frontier import default_views
from src.v2.local_search import search_level_analytic
from src.v2.runner import _per_level_best_path
from src.v2.experimental_classes import _BeamRow, _candidate_json

LEVELS=(20,40,60)
CLASSES=("mage","paladin","druid")
SEED_FILE=ROOT/'MILESTONE_3X3_v0.11.16.json'
VERSION='v0.11.47.0'


def _key(t)->tuple[int,...]:
    return tuple(int(v) for v in dataclasses.asdict(t).values())


def _ranks(t)->dict[str,int]:
    return {k:int(v) for k,v in dataclasses.asdict(t).items() if int(v)>0}


def _reachable(engine, ranks:dict[str,int]):
    t=engine.Talents()
    want={k:int(v) for k,v in ranks.items() if int(v)>0}
    for _ in range(sum(want.values())):
        choices=[name for name in sorted(want) if int(getattr(t,name,0))<want[name] and engine.legal_add(t,name)]
        if not choices:
            return None
        t=engine.add_point(t,choices[0])
    return t if _ranks(t)==want else None


def _family_corridor(engine, level:int, family:str):
    t=engine.Talents()
    for _ in range(level-9):
        legal=[n for n in engine.TALENT_RULES if engine.legal_add(t,n)]
        if not legal: return None
        legal.sort(key=lambda n:(engine.TALENT_RULES[n][0]!=family, engine.TALENT_RULES[n][2], n))
        t=engine.add_point(t,legal[0])
    return t


def _neighbors(engine,t,cap:int=72):
    base=_ranks(t); out={}
    invested=sorted(base)
    names=sorted(engine.TALENT_RULES)
    for drop in invested:
        if base[drop]<=0: continue
        partial=dict(base); partial[drop]-=1
        if partial[drop]<=0: partial.pop(drop,None)
        for add in names:
            max_rank=int(engine.TALENT_RULES[add][1])
            if partial.get(add,0)>=max_rank: continue
            cand=dict(partial); cand[add]=cand.get(add,0)+1
            ct=_reachable(engine,cand)
            if ct is not None and _key(ct)!=_key(t): out[_key(ct)]=ct
    # Deterministic bounded neighborhood. Prefer same dominant family moves, then key.
    fam=max(engine.TREE_NAMES,key=lambda tr: engine.tree_points(t,tr))
    vals=list(out.values())
    vals.sort(key=lambda x:(-engine.tree_points(x,fam),_key(x)))
    return vals[:max(0,int(cap))]


def _seed_rows():
    rows=json.loads(SEED_FILE.read_text(encoding='utf-8'))
    return {(str(r['class']),int(r['level'])):r for r in rows}


def _score_experimental(cls:str,level:int,seed:dict,neighbor_cap:int=72,rounds:int=2):
    game_context.configure('forever',cls); reset_engine_cache(); e=get_engine()
    seed_t=_reachable(e,seed.get('talent_ranks') or {})
    if seed_t is None:
        raise RuntimeError(f'{cls} L{level}: historic seed is no longer legal')
    candidate_sources={_key(seed_t):(seed_t,'historic_v0.11.16_seed')}
    for family in e.TREE_NAMES:
        t=_family_corridor(e,level,family)
        if t is not None: candidate_sources.setdefault(_key(t),(t,f'family_corridor:{family}'))
    cache={}
    def score(t):
        k=_key(t)
        if k not in cache: cache[k]=e.experimental_level_score(level,t,'all')
        return cache[k]
    best_t=seed_t; best_s=score(seed_t); searched=0
    round_summaries=[]
    for rnd in range(max(1,int(rounds))):
        pool=list(candidate_sources.values())
        for nt in _neighbors(e,best_t,neighbor_cap):
            candidate_sources.setdefault(_key(nt),(nt,f'local_swap_r{rnd+1}'))
        pool=list(candidate_sources.values())
        ranked=[]
        for t,src in pool:
            s=score(t); searched+=1
            ranked.append((float(s['total_s']),_key(t),t,src,s))
        ranked.sort(key=lambda x:(x[0],x[1]))
        prev=float(best_s['total_s']); _,_,best_t,best_src,best_s=ranked[0]
        round_summaries.append({'round':rnd+1,'candidate_pool':len(ranked),'best_s_per_100':float(best_s['total_s']),'improvement_s_per_100':prev-float(best_s['total_s'])})
        if prev-float(best_s['total_s']) < 1e-9: break
    row=_candidate_json(_BeamRow(best_t,0.0,best_s,tuple()),level,include_stat_weights=True)
    row['class']=cls; row['selection_authority']='bounded_target_level_local_search'
    row['selection_source']=candidate_sources[_key(best_t)][1]
    row['search']={'seed':'MILESTONE_3X3_v0.11.16','neighbor_cap':neighbor_cap,'rounds_requested':rounds,'rounds':round_summaries,'unique_scored':len(cache),'not_exhaustive':True}
    return row


def _score_mage(level:int):
    game_context.configure('forever','mage'); reset_engine_cache(); e=get_engine()
    cfg=e.SimConfig(use_best_water=True)
    smooth={v.name:v for v in default_views()}['smooth']
    bw,fk,ok=(24,4,24) if int(level)==20 else (10,2,12)
    rows=search_level_analytic(level,cfg,options=smooth.options,beam_width=bw,family_keep=fk,final_k=ok,school='all')
    # Reuse the production per-level-best bounded event rerank, including Ice Lance challengers.
    path=_per_level_best_path({level:rows},cfg,start_level=level,end_level=level,respec_seconds=1.0)
    row=dict(path['steps'][0])
    # Ensure winner has the common stat-weight/named-gear contract by taking the matching node when possible.
    alloc=row.get('allocation')
    node=next((n for n in rows if getattr(n,'allocation',None)==alloc),None)
    # Node allocation is normally rendered, not an attr; match via renderer fallback.
    if row.get('stat_weights') is None:
        from src.v2 import stat_weights
        for n in rows:
            try:
                from src.v2.view_models import node_json
                if node_json(n).get('allocation')==alloc:
                    ann=stat_weights.annotate_top_nodes([n],cfg,options=smooth.options,school='all',top_k=1)[0]
                    richer=node_json(ann)
                    for k in ('stat_weights','gear_stats','gear','combat_profile','talent_family','talent_ranks','tree_points'):
                        if richer.get(k) is not None: row[k]=richer.get(k)
                    break
            except Exception:
                pass
    row['class']='mage'; row['level']=level
    row['selection_authority']='production_analytic_search_plus_bounded_event_rerank'
    row['search']={'beam_width':bw,'family_keep':fk,'final_k':ok,'event_rerank':row.get('selection_validation'),'not_exhaustive':True}
    return row


def _normalize_row(row:dict)->dict:
    out=dict(row)
    mph=out.get('mobs_per_hour')
    if mph is None:
        s=float(out.get('score_s_per_100') or 0.0); mph=360000.0/s if s>0 else None; out['mobs_per_hour']=mph
    if out.get('seconds_per_mob') is None and mph:
        out['seconds_per_mob']=3600.0/float(mph)
    return out


def build(neighbor_cap:int=72,rounds:int=2)->dict:
    seeds=_seed_rows(); rows=[]
    prior=game_context.current()
    try:
        for level in LEVELS: rows.append(_normalize_row(_score_mage(level)))
        for cls in ('paladin','druid'):
            for level in LEVELS: rows.append(_normalize_row(_score_experimental(cls,level,seeds[(cls,level)],neighbor_cap,rounds)))
    finally:
        game_context.configure(prior.ruleset,prior.class_name); reset_engine_cache()
    rows.sort(key=lambda r:(CLASSES.index(r['class']),LEVELS.index(int(r['level']))))
    return {
      'schema_version':1,'version':VERSION,'milestone':'M47','status':'BASELINE_IN_PROGRESS',
      'contract':{'primary_mode':'per_level_fastest','respec_seconds':1.0,'target':'same_level_world_mob','recovery':'sustained_chain_best_level_usable_food_water','levels':list(LEVELS),'classes':list(CLASSES)},
      'optimization_scope':'Mage production analytic search + bounded event rerank; Paladin/Druid historic-seed target-level local swap search. Reproducible baseline, not M47 Gate-A exhaustive/adversarial closure.',
      'rows':rows,
    }


def write(payload:dict,out_prefix:Path):
    out_prefix.parent.mkdir(parents=True,exist_ok=True)
    jp=Path(str(out_prefix)+'.json'); cp=Path(str(out_prefix)+'.csv'); mp=Path(str(out_prefix)+'.md')
    jp.write_text(json.dumps(payload,indent=2,sort_keys=True),encoding='utf-8')
    fields=['class','level','mobs_per_hour','seconds_per_mob','talent_family','combat_profile','gear','pull_size','rotation','allocation','selection_authority','selection_source']
    with cp.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in payload['rows']: w.writerow({k:r.get(k) for k in fields})
    lines=[f"# M47 optimized 3×3 baseline — {payload['version']}",'',
           '**State:** BASELINE / M47 still IN_PROGRESS. This is reproducible bounded optimization evidence, not final Gate-A closure.','',
           '| Class | L | mobs/h | sec/mob | profile | gear / pull | rotation | allocation |',
           '|---|---:|---:|---:|---|---|---|---|']
    for r in payload['rows']:
        lines.append(f"| {r['class'].title()} | {r['level']} | {float(r.get('mobs_per_hour') or 0):.1f} | {float(r.get('seconds_per_mob') or 0):.2f} | {r.get('combat_profile') or r.get('profile')} | {r.get('gear')} / {r.get('pull_size')} | {str(r.get('rotation') or r.get('policy') or '—').replace('|','/')} | `{str(r.get('allocation') or '—').replace('|','/')}` |")
    lines += ['', '## Search authority','', payload['optimization_scope'],'',
              'Default workload is the M46-closed contract: same-level world mob, sustained recovery chain, and best level-usable recovery resources. Cheap (~1 s) respec makes the per-level winner the primary answer.','',
              'Next M47 step: adversarial/expanded finalist search around surprising cells and explicit Gate-A classification; do not treat this baseline as final cross-class ranking evidence.']
    mp.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return jp,cp,mp


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--neighbor-cap',type=int,default=72); ap.add_argument('--rounds',type=int,default=2); ap.add_argument('--out-prefix',default=f'M47_3X3_BASELINE_{VERSION}')
    a=ap.parse_args(); p=build(a.neighbor_cap,a.rounds); paths=write(p,ROOT/a.out_prefix); print(json.dumps({'ok':True,'files':[str(x) for x in paths],'rows':len(p['rows'])},indent=2))
if __name__=='__main__': main()
