#!/usr/bin/env python3
"""Generic 300s fixed-dimension talent optimizer over source-declared talent trees.

This is a native-Rust talent discovery diagnostic. It does not itself establish
live gsim 2D ↔ Rust causality or certify a PROCESS P7.3 gate.
"""
from __future__ import annotations
import argparse, copy, hashlib, json, math, os, random, subprocess, sys, tempfile, time
from pathlib import Path
from talent_schema_druid import TREES,LOOKUP,parse,encode,points,legal_add,validate

REFERENCE_DPS=728.1936126415858

def sha(obj): return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def player(req): return req['raid']['parties'][0]['players'][0]

def initial_ranks():return [[0]*len(t) for t in TREES]

def random_build(rng, target=None):
    """Source-legal random full allocation with independent tree split discovery.

    This macro operator samples all feasible tree budgets, then spends points
    within each tree by source tier/cap/prerequisite rules. Existing elites may
    bias but do not lock the sampled tree split. No saved reference allocation
    is used for sampling, elite initialization, or scoring.
    """
    if target is None or rng.random() < 0.35:
        balance_target = rng.randint(31, sum(t.maximum for t in TREES[0]))
        feral_target = rng.randint(0, 51-balance_target)
    else:
        old_balance=sum(target[0]);old_feral=sum(target[1])
        balance_target=max(31,min(sum(t.maximum for t in TREES[0]),old_balance+rng.randint(-9,9)))
        feral_target=max(0,min(51-balance_target,old_feral+rng.randint(-9,9)))
    resto_target=51-balance_target-feral_target
    targets=(balance_target,feral_target,resto_target)
    ranks=initial_ranks()
    for ti,total in enumerate(targets):
        for count in range(total):
            if ti==0 and count==15:
                assert legal_add(ranks,0,8)
                ranks[0][8]+=1
                continue
            if ti==0 and count==30:
                assert legal_add(ranks,0,15)
                ranks[0][15]+=1
                continue
            options=[]
            for i,t in enumerate(TREES[ti]):
                if ti==0 and i in (8,15):continue
                if not legal_add(ranks,ti,i):continue
                w=0.5+rng.random()**2*2.5
                if target is not None:
                    current=ranks[ti][i]
                    wanted=target[ti][i]
                    w*= (1+10*max(0,wanted-current)) if current<wanted else 0.25
                options.append((w,i))
            if not options:
                raise RuntimeError('No legal allocation step for tree '+str(ti))
            u=rng.random()*sum(w for w,_ in options)
            for w,i in options:
                u-=w
                if u<=0:break
            ranks[ti][i]+=1
    if not validate(ranks):
        raise RuntimeError('Illegal source-derived random build '+encode(ranks))
    return ranks

def edit_neighbors(elite,rng):
    """Source-legal 1-point donor→recipient moves, without reference seeding."""
    for _ in range(60):
        out=[row[:] for row in elite]
        donors=[(ti,i) for ti,t in enumerate(out) for i,n in enumerate(t) if n and (ti,i) not in ((0,8),(0,15))]
        if not donors:break
        ti,i=rng.choice(donors)
        out[ti][i]-=1
        options=[(tj,j) for tj,tree in enumerate(TREES) for j,_ in enumerate(tree) if legal_add(out,tj,j) and (tj,j) not in ((0,8),(0,15))]
        if not options:continue
        tj,j=rng.choice(options)
        out[tj][j]+=1
        if validate(out) and out!=elite:return out
    return random_build(rng,elite)

def dps(out):
    return float(out['result']['raidMetrics']['dps']['avg'])

def run(binary,req,iterations,seed,rng_mode,deadline):
    remaining=deadline-time.monotonic()
    if remaining<=0.05:raise TimeoutError('No remaining time before native execution')
    payload=copy.deepcopy(req)
    payload['simOptions']['iterations']=iterations
    payload['simOptions']['randomSeed']=str(seed)
    with tempfile.TemporaryDirectory() as d:
        inp=Path(d)/'req.json'; out=Path(d)/'out.json'
        inp.write_text(json.dumps(payload,separators=(',',':')))
        env=dict(os.environ,WOWSIM_RNG_MODE=rng_mode)
        st=time.monotonic()
        res=subprocess.run([str(binary),'sim','--request',str(inp),'--outfile',str(out),'--gate'],
                           stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True,
                           env=env,timeout=max(0.001,deadline-time.monotonic()))
        if res.returncode!=0 or not out.exists():
            raise RuntimeError('native Rust failed: '+res.stderr[-1400:])
        output=json.loads(out.read_text())
    return dps(output),output,round(time.monotonic()-st,6),sha(payload)

def main():
    pa=argparse.ArgumentParser()
    pa.add_argument('--binary',type=Path,required=True)
    pa.add_argument('--reference',type=Path,required=True)
    pa.add_argument('--outdir',type=Path,required=True)
    pa.add_argument('--seconds',type=float,default=300.0)
    pa.add_argument('--screen-iterations',type=int,default=100)
    pa.add_argument('--holdout-iterations',type=int,default=4000)
    pa.add_argument('--seed',type=int,default=647003)
    pa.add_argument('--rng-mode',choices=('stochastic','balanced'),default='balanced',
                    help='Balanced search (default) requires verified patched Rust; stochastic is an explicit fallback')
    a=pa.parse_args()
    if a.seconds<=0 or a.screen_iterations<=0 or a.holdout_iterations<1000:pa.error('Invalid budgets')
    a.outdir.mkdir(parents=True,exist_ok=True)
    reference=json.loads(a.reference.read_text())
    p=player(reference)
    assert p['talentsString']=='5532220115501351--505'
    assert validate(parse(p['talentsString']))
    assert len(p['equipment']['items'])==16 and len(p['rotation']['priorityList'])==10
    fixed_gear=sha(p['equipment']);fixed_apl=sha(p['rotation']);reference_hash=sha(reference)
    reference_talents=p['talentsString']
    rng=random.Random(a.seed)
    start=time.monotonic()
    deadline=start+a.seconds
    # Reserve a new-seed finalist tournament: 100-fight screens never select final winner.
    rerank_reserve=min(80.0,max(1.0,a.seconds*0.26))
    screening_end=deadline-rerank_reserve
    search_seed=int(reference['simOptions']['randomSeed'])
    if a.rng_mode == 'balanced':
        # A stock engine ignores WOWSIM_RNG_MODE. Refuse silently stochastic searches.
        probe_end=min(deadline,time.monotonic()+max(0.2,min(20.,a.seconds*0.1)))
        scores=[]
        for seed in (search_seed,search_seed+777):
            score,_,_,_=run(a.binary,reference,40,seed,'balanced',probe_end)
            scores.append(score)
        s_score,_,_,_=run(a.binary,reference,40,search_seed,'stochastic',probe_end)
        if scores[0] != scores[1] or scores[0] == s_score:
            raise RuntimeError('BALANCED_RNG_NOT_VERIFIED: different seeds must agree and balanced must differ from stochastic; refusing to mislabel Monte Carlo search')
    holdout_seed=a.seed+1300000007
    seen={reference_talents}
    elites=[]
    records=[]
    best=None
    attempts=0
    failures=0
    last_status=0
    while time.monotonic() < screening_end-0.05:
        q=rng.random()
        if elites and q<0.62:
            ranks=edit_neighbors(rng.choice(elites[:min(18,len(elites))])[1],rng)
        elif elites and q<0.89:
            ranks=random_build(rng,rng.choice(elites[:min(14,len(elites))])[1])
        else:
            ranks=random_build(rng)
        s=encode(ranks)
        attempts+=1
        if s in seen:continue
        seen.add(s)
        assert validate(parse(s)),s
        req=copy.deepcopy(reference)
        player(req)['talentsString']=s
        assert sha(player(req)['equipment'])==fixed_gear
        assert sha(player(req)['rotation'])==fixed_apl
        try:
            value,output,elapsed,reqsha=run(a.binary,req,a.screen_iterations,search_seed,a.rng_mode,screening_end)
        except (subprocess.TimeoutExpired,TimeoutError):break
        except Exception as exc:
            failures+=1
            records.append({'talents':s,'error':str(exc)[:450]})
            continue
        row={'talents':s,'dps':value,'elapsed_s':elapsed,'request_sha256':reqsha}
        records.append(row)
        elites.append((value,ranks))
        elites.sort(key=lambda x:-x[0])
        elites=elites[:22]
        if best is None or value>best['dps']:
            best=dict(row)
            best['talent_ranks']={t.name:ranks[ti][i] for ti,tree in enumerate(TREES) for i,t in enumerate(tree) if ranks[ti][i]}
            (a.outdir/'progress.json').write_text(json.dumps({'elapsed':time.monotonic()-start,'evaluations':len(records),'best':best},indent=2))
        if time.monotonic()-start-last_status>30:
            last_status=time.monotonic()-start
            print(json.dumps({'elapsed':round(last_status,1),'paid':len(records),'best_dps':best['dps'],'best_talents':best['talents']}),flush=True)
    if best is None:raise RuntimeError('No valid candidate paid')
    # Reference is not seeded. Independent high-precision evaluation of frozen top 40.
    top_screen=sorted((r for r in records if 'dps' in r),key=lambda r:-r['dps'])[:40]
    rerank_seed=search_seed + 987654321
    reranked=[]
    rerank_end=deadline-min(10.0,max(0.5,a.seconds*0.04))
    for candidate in top_screen:
        if time.monotonic()>=rerank_end-0.25:break
        requested=copy.deepcopy(reference)
        player(requested)['talentsString']=candidate['talents']
        try:
            score,_,duration,request_hash=run(a.binary,requested,10000,rerank_seed,'stochastic',rerank_end)
        except (TimeoutError,subprocess.TimeoutExpired):break
        reranked.append({'talents':candidate['talents'],'screen_dps':candidate['dps'],
                         'rerank_dps':score,'rerank_seed':rerank_seed,
                         'rerank_iterations':10000,'request_sha256':request_hash,'elapsed_s':duration})
    if not reranked:raise RuntimeError('No independently re-evaluated finalists')
    final_best=max(reranked,key=lambda r:r['rerank_dps'])
    (a.outdir/'reranked_finalists.json').write_text(json.dumps(reranked,indent=2))
    winner=copy.deepcopy(reference)
    player(winner)['talentsString']=final_best['talents']
    winner['simOptions']['iterations']=a.holdout_iterations
    winner['simOptions']['randomSeed']=str(holdout_seed)
    assert final_best['talents']!=reference_talents
    assert sha(player(winner)['equipment'])==fixed_gear
    assert sha(player(winner)['rotation'])==fixed_apl
    # Save the exact frozen winner *before* the independent holdout.
    (a.outdir/'frozen_winner_request.json').write_text(json.dumps(winner,indent=2))
    holdout_dps,holdout,holdout_s,holdout_hash=run(a.binary,winner,a.holdout_iterations,holdout_seed,'stochastic',deadline)
    (a.outdir/'frozen_holdout_result.json').write_text(json.dumps(holdout,indent=2))
    (a.outdir/'paid_candidates.json').write_text(json.dumps(records,separators=(',',':')))
    elapsed=time.monotonic()-start
    report={
      'status':'NATIVE_RUST_P73_DIAGNOSTIC_NOT_2D_CAUSAL_PASS',
      'source_rules':'mage-level-sim/src/rulesets/forever/classes/druid/talents.py schema=1.60.1.70170 + WF482 explicit Vengeance prerequisite',
      'reference_sha256':reference_hash,'frozen_gear_sha256':fixed_gear,'frozen_apl_sha256':fixed_apl,
      'reference_talents':reference_talents,'reference_dps':REFERENCE_DPS,'acceptance_floor_point_estimate':0.99*REFERENCE_DPS,
      'budget_s':a.seconds,'elapsed_s':elapsed,'candidate_generation_attempts':attempts,
      'paid_count':len(records),'failed_native':failures,'screen_iterations':a.screen_iterations,
      'screen_seed':search_seed,'screen_rng_mode':a.rng_mode,'holdout_iterations':a.holdout_iterations,'holdout_seed':holdout_seed,
      'best_screen':best,'rerank_seed':rerank_seed,'rerank_finalists':len(reranked),
      'best_reranked':final_best,'holdout_dps':holdout_dps,'holdout_request_sha256':holdout_hash,
      'holdout_duration_s':holdout_s,'point_estimate_ge_99pct_reference':holdout_dps>=0.99*REFERENCE_DPS,
      'winner_is_source_legal':validate(parse(best['talents'])),
      'native_rust_worked':True,'live_2d_causal_trace_exists':False,
      'limits':['No live 2D↔Rust controller/ACK causal evidence.','Rust talent schema adapted from source build 1.60.1.70170; runtime may use later talent updates.','Statistical confidence of holdout versus reference not computed.'],
    }
    (a.outdir/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:report[k] for k in ('status','elapsed_s','paid_count','failed_native','best_screen','best_reranked','holdout_dps','point_estimate_ge_99pct_reference')},indent=2),flush=True)
    if elapsed>a.seconds:raise TimeoutError('End-to-end 300s ceiling violated')

if __name__=='__main__':main()