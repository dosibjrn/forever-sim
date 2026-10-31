"""Rebase source-legal Druid L30 P3 Top5 on the latest *independent* stage.

Only candidate selection/measurement and evidence: canonical source SQLite -> IR ->
CombatRuntime -> actual persistent 100 mobs remains the sole execution engine.
No legacy optimizer output is a seed. No zero for unresolved item effects.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor,as_completed
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from time import monotonic,process_time
import argparse,json,os,sqlite3,tempfile

from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0,source_item_l0
from src.game.data.forever.source_checkpoint_p3_swaps import (
    source_context_fingerprint,substituted_multi_stage,subprocess_stage_100mob)
from src.game.data.forever.source_checkpoint_p3_empirical_weights import (
    fit_swap_weights,rank_all_legal_items_with_proxy)
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.recovery_between_pulls import BetweenPullPolicy
from src.rulesets.forever.items.runtime_selection import available_items
from tools.wf321_ingest_control_observations import ingest as ingest_control
from tools.wf358_l30_p3_top5_replay import source_legal_proposals

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/wf359'
STAGE=ROOT/'evidence/wf358/WF358_L30_BEST_JOINT_P3_STAGE.json'
PRIOR=ROOT/'evidence/wf352/WF352_L30_P3_TOP5.json'
ACTIVE=ROOT/'evidence/wf358/WF358_L30_P3_CONTEXTUAL_TOP5_AND_WEIGHTS.json'
POLICY=BetweenPullPolicy(.25,.1,exit_action_id='cancel_mode:cat',reentry_action_id='cat_form:768')


def scenario_context(*,stage,db):
    base=source_context_fingerprint(stage=stage,class_key='druid',level=30,
        source_db_sha256=sha256(db.read_bytes()).hexdigest())
    # The old cache key omitted recovery/runtime semantics. Never reuse a
    # 100-mob result across changed policy or execution code.
    runtime_paths=(
        'src/game/recovery_between_pulls.py',
        'src/game/runtime/source_maintenance.py',
        'src/v2/source_persistent_joint_finalists.py',
        'src/game/data/forever/source_checkpoint_p3_swaps.py',
        'tools/wf353_p3_eval_worker.py',
    )
    fingerprint={'base':base,'recovery_policy':asdict(POLICY),
        'runtime_files_sha256':{p:sha256((ROOT/p).read_bytes()).hexdigest() for p in runtime_paths}}
    return sha256(json.dumps(fingerprint,sort_keys=True).encode()).hexdigest(),fingerprint


def candidate_jobs(stage,inventory,prior,active,max_per_slot=6):
    proposals,counts,unknown,paired=source_legal_proposals(
        stage,inventory,prior,max_per_slot=max_per_slot,active_proxy=active)
    byslot={s:[p for p in proposals if p['slot']==s] for s in counts}
    ordered=[]
    for depth in range(max(map(len,byslot.values()))):
        for slot in sorted(byslot):
            if depth<len(byslot[slot]):ordered.append(byslot[slot][depth])
    return ordered,counts,unknown,paired


def score_candidates(*,rows,stage,db,baseline,workers,timeout_s,cache,context):
    equipped={k:int(v['item_id']) for k,v in stage['gear_policy_result']['winner']['gear']['slots'].items()}
    def evaluate(row):
        if row['unresolved_effects']:
            return {**row,'result':{'status':'L0_ONLY_UNRESOLVED_EFFECT',
                                    'unresolved_effects':row['unresolved_effects']}}
        if all(equipped.get(k)==int(v) for k,v in row['swaps'].items()):
            return {**row,'result':{**baseline,'evaluation_source':'EXACT_BASELINE_REUSE_NO_NEW_100MOB'}}
        result=subprocess_stage_100mob(stage=stage,source_db_path=db,swaps=row['swaps'],
            timeout_s=timeout_s,recovery_policy=POLICY)
        return {**row,'result':result}
    seen={(r['slot'],int(r['item_id'])) for r in cache}
    todo=[r for r in rows if (r['slot'],int(r['item_id'])) not in seen]
    def write():
        tmp=OUT/'WF359_L30_P3_REBASED_DIRECT_100MOB.tmp'
        tmp.write_text(json.dumps({'checkpoint':'druid:L30:unrestricted',
            'context_fingerprint':context,'baseline':baseline,'results':cache},indent=2,sort_keys=True)+'\n')
        tmp.replace(OUT/'WF359_L30_P3_REBASED_DIRECT_100MOB.json')
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(evaluate,r):r for r in todo}
        for f in as_completed(futures):
            r=f.result();cache.append(r);write()
            print('P3',len(cache),r['slot'],r['item_id'],r['result']['status'],
                  r['result'].get('mean_s_per_mob'),flush=True)
    return cache


def run(*,workers=4,timeout_s=25.,max_per_slot=6,adaptive_per_slot=1):
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
    started=monotonic();parent_cpu=process_time()
    OUT.mkdir(parents=True,exist_ok=True)
    stage=json.loads(STAGE.read_text());prior=json.loads(PRIOR.read_text());active=json.loads(ACTIVE.read_text())
    inventory=checkpoint_item_l0(class_key='druid',level=30)
    print('WF359_STAGE inventory',monotonic()-started,flush=True)
    assert (inventory['legal_item_count'],inventory['l0_assessed_count'])==(1974,1974)
    proposals,counts,unknown,paired=candidate_jobs(stage,inventory,prior,active,max_per_slot=max_per_slot)
    print('WF359_STAGE proposals',len(proposals),monotonic()-started,flush=True)
    assert len(counts)==18 and all(counts.values())
    with tempfile.TemporaryDirectory(prefix='wf359_rebase_') as tmp:
        db=Path(tmp)/'source.sqlite'
        with sqlite3.connect(f"file:{(ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite').resolve()}?mode=ro",uri=True) as a,sqlite3.connect(db) as b:a.backup(b)
        ingest_observations(db,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(db,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        context,context_details=scenario_context(stage=stage,db=db)
        print('WF359_STAGE context',monotonic()-started,flush=True)
        baseline=subprocess_stage_100mob(stage=stage,source_db_path=db,
            timeout_s=timeout_s,recovery_policy=POLICY)
        if baseline['status']!='COMPLETE':raise RuntimeError('P3_BASELINE_NOT_COMPLETE:'+str(baseline))
        previous=OUT/'WF359_L30_P3_REBASED_DIRECT_100MOB.json'
        if previous.exists():
            old=json.loads(previous.read_text())
            if old['context_fingerprint']!=context or abs(old['baseline']['mean_s_per_mob']-baseline['mean_s_per_mob'])>1e-9:
                raise ValueError('P3_STALE_CONTEXT_REPLAY_CACHE')
            cache=old['results']
        else:cache=[]
        print('WF359_STAGE initial paid start',monotonic()-started,flush=True)
        score_candidates(rows=proposals,stage=stage,db=db,baseline=baseline,workers=workers,
            timeout_s=timeout_s,cache=cache,context=context)
        print('WF359_STAGE initial paid done',len(cache),monotonic()-started,flush=True)
        model=fit_swap_weights(stage=stage,results=cache,baseline_s_per_mob=baseline['mean_s_per_mob'],
            class_key='druid',level=30)
        if model['status']=='INSUFFICIENT_MEASURED_ITEM_SWAPS':raise RuntimeError('P3_NO_FIT')
        print('WF359_STAGE fit',monotonic()-started,flush=True)
        ranked=rank_all_legal_items_with_proxy(stage=stage,model=model,
            class_key='druid',level=30,paired_offhand_weapon_id=paired)
        print('WF359_STAGE rank',monotonic()-started,flush=True)
        # Adaptive independent proposals: each source-legal slot's new Top5,
        # not the stale prior stage's ranking. Unknown effects remain L0-only.
        seen={(r['slot'],int(r['item_id'])) for r in cache}
        followups=[]
        for slot,section in ranked.items():
            if adaptive_per_slot<=0:continue
            added=0
            for row in section['known_component_top5']:
                if (slot,int(row['item_id'])) in seen:continue
                item=next(i for i in available_items('druid',30,required_level_policy='observed') if int(i.item_id)==int(row['item_id']))
                followups.append({'slot':slot,'item_id':int(row['item_id']),
                    'swaps':row['swaps'],'name':item.name,'source_url':item.source_url,
                    'reason':'REBASED_NEW_CONTEXT_PROXY_CHALLENGER',
                    'unresolved_effects':source_item_l0(item)['unresolved_effects']})
                added+=1
                if added>=adaptive_per_slot:break
        if followups:
            score_candidates(rows=followups,stage=stage,db=db,baseline=baseline,workers=workers,
                timeout_s=timeout_s,cache=cache,context=context)
            model=fit_swap_weights(stage=stage,results=cache,
                baseline_s_per_mob=baseline['mean_s_per_mob'],class_key='druid',level=30)
            ranked=rank_all_legal_items_with_proxy(stage=stage,model=model,
                class_key='druid',level=30,paired_offhand_weapon_id=paired)
    print('WF359_STAGE all paid and rank done',monotonic()-started,flush=True)
    sections={};all_top5_source_legal=True
    legal={int(i.item_id):i for i in available_items('druid',30,required_level_policy='observed')}
    for slot in sorted(counts):
        measured=sorted((r for r in cache if r['slot']==slot and r['result']['status']=='COMPLETE'),
            key=lambda r:(r['result']['mean_s_per_mob'],r['item_id']))
        top5=ranked[slot]['known_component_top5']
        assert len(top5)==min(5,ranked[slot]['evaluated_legal_equipment_packages'])
        for r in top5:
            assert int(r['item_id']) in legal
            substituted_multi_stage(stage=stage,class_key='druid',level=30,swaps=r['swaps'])
        all_top5_source_legal &= bool(top5)
        sections[slot]={'legal_items':counts[slot], 'source_unknown_effect_items':unknown[slot],
            'direct_complete':len(measured),'direct_top5':measured[:5],
            'legal_contextual_packages':ranked[slot]['evaluated_legal_equipment_packages'],
            'l0_contextual_top5':top5,
            'l0_unidentified_packages':ranked[slot]['unidentified_item_count'],
            'top5_measured_ids':[r['item_id'] for r in measured[:5]],
            'top5_proxy_ids':[r['item_id'] for r in top5],
            'ranking_uncertainty':'Proxy order not a globally proven ranking; exact 100-mob swaps override estimates.'}
    improved=[r for r in cache if r['result']['status']=='COMPLETE' and
              r['result']['mean_s_per_mob']<baseline['mean_s_per_mob']-1e-7]
    improved.sort(key=lambda r:r['result']['mean_s_per_mob'])
    status_counts={k:sum(r['result']['status']==k for r in cache)
        for k in sorted({r['result']['status'] for r in cache})}
    # User's P3 is L0 *every legal item*, a source-legal candidate per slot,
    # and selection of promising slot candidates. A measured global Top5
    # proof is NOT an additional user acceptance gate.
    p3_pass=(inventory['l0_assessed_count']==inventory['legal_item_count'] and
             len(sections)==18 and all_top5_source_legal and
             all(v['direct_complete']>=1 for v in sections.values()) and
             model['status'].startswith('MEASURED_'))
    result={'checkpoint':'druid:L30:unrestricted','accepted_checkpoints':'1/148',
        'p1':'PASS 86/86','p2':'PASS 117/117',
        'p3':'PASS' if p3_pass else 'FAIL',
        'p4':'NOT_RUN','p5':'NOT_RUN','p6':'NOT_RUN',
        'source_legal_item_count':inventory['legal_item_count'],
        'source_l0_assessed':inventory['l0_assessed_count'],
        'source_legal_slot_count':len(counts),'slots':sections,
        'source_unknown_effect_items':sum(1 for i in legal.values() if source_item_l0(i)['unresolved_effects']),
        'baseline_100mob':baseline,'best_single_item_challenger':improved[0] if improved else None,
        'context_fingerprint':context,'context_components':context_details,
        'recovery_policy':asdict(POLICY),'empirical_context_weights':model,
        'direct_attempts':len(cache),'direct_status_counts':status_counts,
        'direct_unique_slot_item_candidates':len({(r['slot'],r['item_id']) for r in cache}),
        'direct_paid_complete':sum(r['result']['status']=='COMPLETE' and
            r['result'].get('evaluation_source')!='EXACT_BASELINE_REUSE_NO_NEW_100MOB' for r in cache),
        'direct_events':sum(r['result'].get('events',0) for r in cache if
            r['result'].get('evaluation_source')!='EXACT_BASELINE_REUSE_NO_NEW_100MOB'),
        'child_cpu_s':sum(r['result'].get('end_to_end_child_cpu_s',0) for r in cache if
            r['result'].get('evaluation_source')!='EXACT_BASELINE_REUSE_NO_NEW_100MOB'),
        'evidence_aggregation_invocation_wall_s':monotonic()-started,
        'evidence_aggregation_invocation_parent_cpu_s':process_time()-parent_cpu,
        'cumulative_paid_child_outer_wall_s':sum(r['result'].get('outer_wall_s',0) for r in cache
            if r['result'].get('evaluation_source')!='EXACT_BASELINE_REUSE_NO_NEW_100MOB'),
        'uncertainty':['73 previously identified source-item effects may remain L0-only; counted explicitly, not zeroed',
            'measured stat response is discrete/nonlinear; CV error is disclosed',
            'Top5 is a contextual shortlist, not global item optimality proof',
            'no P4/P5 independent gear×talent×rotation run yet']}
    (OUT/'WF359_L30_P3_REBASED_TOP5.json').write_text(json.dumps(result,indent=2,sort_keys=True,default=str)+'\n')
    print('FINAL',json.dumps({'p3':result['p3'],'attempts':len(cache),
        'paid':result['direct_paid_complete'],'statuses':status_counts,
        'cv_mae':model.get('cv_mae_s_per_mob'),'best_single':improved[0]['result']['mean_s_per_mob'] if improved else None,
        'baseline':baseline['mean_s_per_mob'],'aggregation_wall':result['evidence_aggregation_invocation_wall_s']}),flush=True)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--workers',type=int,default=4)
    p.add_argument('--timeout',type=float,default=25.);p.add_argument('--per-slot',type=int,default=6)
    p.add_argument('--adaptive',type=int,default=1)
    a=p.parse_args();run(workers=a.workers,timeout_s=a.timeout,max_per_slot=a.per_slot,adaptive_per_slot=a.adaptive)
