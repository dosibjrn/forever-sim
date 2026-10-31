from __future__ import annotations
import dataclasses, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from src import game_context
from src.engine_registry import reset_engine_cache,get_engine
from src.v2.analytic_frontier import default_views
from src.v2.local_search import search_level_analytic
from src.v2.runner import _per_level_best_path
from src.v2.view_models import node_json
from tools.m47_3x3_baseline import _neighbors,_family_corridor,_key,_ranks

VERSION='v0.11.47.11'; LEVEL=20

def _best_event(e, level, t, cfg, n=8, seed=7):
    best=None
    for school in ('frost','arcane','fire'):
        policies=e.candidate_policies_for_build(level,t,focused=True,school=school)
        for p in policies:
            r=e.simulate_chain(level,t,p,cfg,n=n,seed=seed)
            total=float(r['total_s'])
            cand=(total, school, p, r)
            if best is None or (total,school,p.name)<(best[0],best[1],best[2].name):
                best=cand
    if best is None: return None
    total,school,p,r=best
    return {'mobs_per_hour':3600.0/(total/n),'seconds_per_mob':total/n,'school':school,
            'policy':p.name,'rotation':e.policy_desc(p,0),'wand_shots_per_mob':float(r.get('wand_shots',0.0))/n}

def build():
    prior=game_context.current(); game_context.configure('forever','mage'); reset_engine_cache(); e=get_engine(); cfg=e.SimConfig(use_best_water=True)
    try:
        smooth={v.name:v for v in default_views()}['smooth']
        rows=search_level_analytic(LEVEL,cfg,options=smooth.options,beam_width=24,family_keep=4,final_k=24,school='all')
        path=_per_level_best_path({LEVEL:rows},cfg,start_level=LEVEL,end_level=LEVEL,respec_seconds=1.0)
        prod=path['steps'][0]; prod_alloc=prod['allocation']
        winner_node=next(n for n in rows if node_json(n).get('allocation')==prod_alloc)
        pool={}
        for n in rows[:12]: pool[_key(n.talents)]=(n.talents,'production_top12')
        seenfam=set()
        for n in rows:
            fam=node_json(n).get('talent_family') or 'unknown'
            if fam not in seenfam:
                pool.setdefault(_key(n.talents),(n.talents,f'production_family_leader:{fam}')); seenfam.add(fam)
        for t in _neighbors(e,winner_node.talents,cap=32): pool.setdefault(_key(t),(t,'winner_one_swap'))
        for fam in e.TREE_NAMES:
            t=_family_corridor(e,LEVEL,fam)
            if t is not None: pool.setdefault(_key(t),(t,f'family_corridor:{fam}'))
        cheap=[]
        for t,source in pool.values():
            ev=_best_event(e,LEVEL,t,cfg,n=8,seed=7)
            if ev is None: continue
            cheap.append({'source':source,'allocation':', '.join(f'{k}={v}' for k,v in _ranks(t).items()),'talent_ranks':_ranks(t),**ev})
        cheap.sort(key=lambda x:(-x['mobs_per_hour'],x['allocation']))
        finalist_allocs={r['allocation'] for r in cheap[:8]}
        finalist_allocs.add(prod_alloc)
        # Always carry explicit family leaders/corridors into authority replay even if noisy cheap rank is poor.
        finalist_allocs.update(r['allocation'] for r in cheap if r['source'].startswith('production_family_leader:') or r['source'].startswith('family_corridor:'))
        auth=[]
        byalloc={r['allocation']:r for r in cheap}
        for alloc in sorted(finalist_allocs):
            r0=byalloc[alloc]; t=e.Talents(**r0['talent_ranks'])
            ev=_best_event(e,LEVEL,t,cfg,n=32,seed=7)
            auth.append({'source':r0['source'],'allocation':alloc,'talent_ranks':r0['talent_ranks'],**ev})
        auth.sort(key=lambda x:(-x['mobs_per_hour'],x['allocation']))
        pub=next((x for x in auth if x['allocation']==prod_alloc),None); winner=auth[0]
        regret=None if pub is None else winner['mobs_per_hour']-pub['mobs_per_hour']
        return {'version':VERSION,'level':LEVEL,'screen_samples':8,'authority_samples':32,'seed':7,'candidate_count':len(cheap),'authority_finalist_count':len(auth),
                'scope':'production top finalists + production family leaders + published-winner legal one-swap neighbors + pure-family legal corridors; each candidate gets best focused Frost/Arcane/Fire event policy; n=8 screens, n=32 decides',
                'production_published':{'allocation':prod_alloc,'mobs_per_hour':prod.get('mobs_per_hour'),'rotation':prod.get('rotation')},
                'published_authority_replay':pub,'adversarial_winner':winner,
                'winner_matches_published_allocation':winner['allocation']==prod_alloc,
                'published_regret_mobs_per_hour':regret,
                'classification':'closed_bounded' if winner['allocation']==prod_alloc else 'selection_gap',
                'screen_top':cheap[:12],'authority_top':auth[:12]}
    finally:
        game_context.configure(prior.ruleset,prior.class_name); reset_engine_cache()

def write(p):
    jp=ROOT/f'M47_MAGE_L20_ADVERSARIAL_{VERSION}.json'; mp=ROOT/f'M47_MAGE_L20_ADVERSARIAL_{VERSION}.md'
    jp.write_text(json.dumps(p,indent=2,sort_keys=True),encoding='utf-8')
    lines=[f'# M47 Mage L20 adversarial — {VERSION}','',f"Screen candidates: **{p['candidate_count']}** · authority finalists: **{p['authority_finalist_count']}** · n=**{p['authority_samples']}** · seed **{p['seed']}**",'',p['scope'],'',
           f"Production published: **{p['production_published']['mobs_per_hour']:.2f} mobs/h** · `{p['production_published']['allocation']}`",'',
           f"Authority winner: **{p['adversarial_winner']['mobs_per_hour']:.2f} mobs/h** · {p['adversarial_winner']['school']} · `{p['adversarial_winner']['allocation']}`",'',
           f"Classification: **{p['classification']}**",'', '| # | mobs/h | school | source | allocation | rotation |','|---:|---:|---|---|---|---|']
    for i,r in enumerate(p['authority_top'],1): lines.append(f"| {i} | {r['mobs_per_hour']:.2f} | {r['school']} | {r['source']} | `{r['allocation']}` | {r['rotation'].replace('|','/')} |")
    mp.write_text('\n'.join(lines)+'\n',encoding='utf-8'); return jp,mp

if __name__=='__main__':
    p=build(); files=write(p); print(json.dumps({'ok':True,'files':[str(x) for x in files],'winner':p['adversarial_winner'],'classification':p['classification'],'matches':p['winner_matches_published_allocation'],'regret':p['published_regret_mobs_per_hour']},indent=2))
