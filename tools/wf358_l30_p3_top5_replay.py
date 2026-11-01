"""Contextual P3 candidate replay, using the existing source->IR->CombatRuntime.

This is a *measured challenger frontier*, not a global Top5 proof. The entire
source-legal universe retains its L0 assessment, including unresolved effects.
"""
from __future__ import annotations
import json,os,sqlite3,tempfile,hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
from time import monotonic,process_time
from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0,source_item_l0
from src.game.data.forever.source_checkpoint_p3_swaps import (subprocess_stage_100mob,
    substituted_multi_stage,source_context_fingerprint)
from src.game.data.forever.source_checkpoint_p3_weights import _features
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.rulesets.forever.items.runtime_selection import available_items
from src.game.recovery_between_pulls import BetweenPullPolicy
from tools.wf321_ingest_control_observations import ingest as ingest_control

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/wf358'
STAGE=ROOT/'evidence/wf357/WF357_L30_BEST_P3_STAGE.json'
PRIOR=ROOT/'evidence/wf352/WF352_L30_P3_TOP5.json'
ACTIVE_PROXY=ROOT/'evidence/wf358/WF358_L30_P3_CONTEXTUAL_TOP5_AND_WEIGHTS.json'
AXES=('strength','agility','weapon_dps','health_regeneration_per_5s','stamina',
      'attack_power','spirit','mp5','intellect','armor','spell_power','crit','hit')
POLICY=BetweenPullPolicy(.25,.1,exit_action_id='cancel_mode:cat',reentry_action_id='cat_form:768')

def source_legal_proposals(stage, inventory, prior, *, max_per_slot=8, active_proxy=None):
    """Old proxy is a discovery prior ONLY; real ranking uses paid 100mob.

    Build the entire slot-specific legal universe first. Include source-stat
    maxima to challenge stale linear scores. Include equipped items and an
    explicitly marked offhand+onehand pair when a 2H weapon is equipped.
    """
    items={int(i.item_id):i for i in available_items('druid',30,required_level_policy='observed')}
    equipped={k:int(v['item_id']) for k,v in stage['gear_policy_result']['winner']['gear']['slots'].items()}
    output=[];slot_counts={};unresolved={};slots=inventory['slot_frontiers']
    onehands=sorted((i for i in items.values() if i.slot in ('one_hand','main_hand') and i.weapon_hands!=2),
        key=lambda i:(-_features(i).get('weapon_dps',0),-i.item_level,i.item_id))
    if not onehands:raise ValueError('P3_NO_SOURCE_LEGAL_ONE_HAND_WEAPON')
    # Do not use the legacy optimizer winner as a seed. These are source-item
    # legality alternatives in the *already independently found* stage.
    paired_weapon=int(onehands[0].item_id)
    for slot,section in sorted(slots.items()):
        eligible=[items[int(r['item_id'])] for r in inventory['source_items'] if slot in r['slots']]
        slot_counts[slot]=len(eligible)
        unresolved[slot]=sum(bool(source_item_l0(i)['unresolved_effects']) for i in eligible)
        candidates=[]
        def offer(iid,reason):
            if iid not in items or iid in {x['item_id'] for x in candidates}:return
            sw={slot:int(iid)}
            if slot=='offhand' and slot not in equipped:sw={'weapon':paired_weapon,'offhand':int(iid)}
            try:substituted_multi_stage(stage=stage,class_key='druid',level=30,swaps=sw)
            except ValueError:return
            item=items[iid];l0=source_item_l0(item)
            candidates.append({'slot':slot,'item_id':int(iid),'swaps':sw,
                'name':item.name,'source_url':item.source_url,'reason':reason,
                'unresolved_effects':l0['unresolved_effects'],
                'source_stat_domains':l0['numeric_source_domains']})
        if slot in equipped:offer(equipped[slot],'equipped_context_anchor')
        if active_proxy is not None:
            for row in active_proxy['slots'].get(slot,{}).get('all_source_legal_proxy',{}).get('known_component_top5',[]):
                offer(int(row['item_id']),'active_paid_100mob_trained_proxy_challenger')
        for row in prior['slots'].get(slot,{}).get('weighted_top',[]):
            offer(int(row['item_id']),'historical_proxy_proposal_not_ranking')
        for axis in AXES:
            ranked=sorted(eligible,key=lambda i:(-float(_features(i).get(axis,0)),i.item_id))
            if ranked and _features(ranked[0]).get(axis,0):offer(int(ranked[0].item_id),'source_stat_axis_max_'+axis)
        # Prefer direct L2 replays of known effects, but retain unknown-effect
        # candidates in evidence rather than treating them as zero.
        # Diverse *source-legal* proposals, not five copies of the previous
        # build's proxy preference.  A prior proxy is only a candidate generator.
        # Round-robin the contextual anchor, source-axis extrema, measured-proxy
        # suggestions and historical proposals before filling spare places.
        # This keeps newly discovered nonlinear/threshold winners reachable.
        known=[r for r in candidates if not r['unresolved_effects']]
        unknown=[r for r in candidates if r['unresolved_effects']]
        def category(row):
            reason=row['reason']
            if reason=='equipped_context_anchor':return 'anchor'
            if reason.startswith('source_stat_axis_max_'):return 'source_axis'
            if reason.startswith('active_paid_'):return 'measured_proxy'
            return 'historical'
        buckets={k:[r for r in known if category(r)==k]
                 for k in ('anchor','source_axis','measured_proxy','historical')}
        selected=[]
        while len(selected)<max_per_slot and any(buckets.values()):
            for kind in ('anchor','source_axis','measured_proxy','historical'):
                if buckets[kind] and len(selected)<max_per_slot:
                    selected.append(buckets[kind].pop(0))
        if len(selected)<max_per_slot: selected+=unknown[:max_per_slot-len(selected)]
        # For small slots, record all legal items, including contextual-zero shirts.
        if len(eligible)<=max_per_slot:
            for item in eligible:offer(int(item.item_id),'complete_small_slot')
            selected=candidates
        output.extend(selected)
    return output,slot_counts,unresolved,paired_weapon


def run(*,max_jobs=60,workers=2,timeout_s=23.):
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
    stage=json.loads(STAGE.read_text());prior=json.loads(PRIOR.read_text())
    inv=checkpoint_item_l0(class_key='druid',level=30)
    if inv['legal_item_count']!=1974 or inv['l0_assessed_count']!=1974:raise ValueError('P3_SOURCE_SCOPE_DRIFT')
    active=json.loads(ACTIVE_PROXY.read_text()) if ACTIVE_PROXY.exists() else None
    jobs,counts,unknown,paired=source_legal_proposals(stage,inv,prior,active_proxy=active)
    # Breadth-first across slots, then within-slot candidate depth.
    byslot={s:[j for j in jobs if j['slot']==s] for s in counts}
    ordered=[]
    for depth in range(max(len(v) for v in byslot.values())):
        for slot in sorted(byslot):
            if depth<len(byslot[slot]):ordered.append(byslot[slot][depth])
    started=monotonic();cpu=process_time();OUT.mkdir(parents=True,exist_ok=True)
    evidence=OUT/'WF358_L30_P3_TOP5_DIRECT_REPLAYS.json'
    with tempfile.TemporaryDirectory(prefix='wf358_l30_') as tmp:
        db=Path(tmp)/'source.sqlite'
        with sqlite3.connect(f"file:{(ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite').resolve()}?mode=ro",uri=True) as a,sqlite3.connect(db) as b:a.backup(b)
        ingest_observations(db,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(db,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        fingerprint=source_context_fingerprint(stage=stage,class_key='druid',level=30,
            source_db_sha256=hashlib.sha256(db.read_bytes()).hexdigest())
        baseline=subprocess_stage_100mob(stage=stage,source_db_path=db,timeout_s=timeout_s,recovery_policy=POLICY)
        if baseline.get('status')!='COMPLETE':raise RuntimeError('P3_BASELINE_FAILED:'+str(baseline))
        old=json.loads(evidence.read_text()) if evidence.exists() else None
        if old and (old['context_fingerprint']!=fingerprint or abs(old['baseline']['mean_s_per_mob']-baseline['mean_s_per_mob'])>1e-7):
            raise ValueError('P3_STALE_REPLAY_EVIDENCE')
        results=list(old['results']) if old else []
        done={(r['slot'],r['item_id']) for r in results}
        remaining=[r for r in ordered if (r['slot'],r['item_id']) not in done][:max(0,max_jobs-len(results))]
        equipped={k:int(v['item_id']) for k,v in stage['gear_policy_result']['winner']['gear']['slots'].items()}
        def evaluate(row):
            if all(equipped.get(k)==int(v) for k,v in row['swaps'].items()):
                return {**row,'result':{**baseline,'evaluation_source':'EXACT_BASELINE_REUSE_NO_NEW_100MOB'}}
            if row['unresolved_effects']:
                return {**row,'result':{'status':'L0_ONLY_UNRESOLVED_EFFECT','unresolved_effects':row['unresolved_effects']}}
            r=subprocess_stage_100mob(stage=stage,source_db_path=db,swaps=row['swaps'],
                timeout_s=timeout_s,recovery_policy=POLICY)
            return {**row,'result':r}
        def write():
            slots={}
            for slot in counts:
                measured=[r for r in results if r['slot']==slot and r['result']['status']=='COMPLETE']
                measured.sort(key=lambda r:(r['result']['mean_s_per_mob'],r['item_id']))
                slots[slot]={'source_legal_count':counts[slot],
                    'unresolved_source_item_count':unknown[slot],
                    'direct_completed':len(measured),'top5_measured_challengers':measured[:5],
                    'not_global_top5_proof':True}
            payload=json.dumps({'checkpoint':'druid:L30:unrestricted',
                'accepted_checkpoints':'1/148','p1':'PASS 86/86','p2':'PASS 117/117',
                'p3':'FAIL_PENDING_FULL_CONTEXTUAL_TOP5',
                'source_legal_items':inv['legal_item_count'],'l0_assessed':inv['l0_assessed_count'],
                'source_legal_slots':counts,'source_unresolved_by_slot':unknown,
                'paired_offhand_weapon_id':paired,'context_fingerprint':fingerprint,
                'recovery_policy':vars(POLICY),'baseline':baseline,
                'proposed':len(ordered),'tested':len(results),
                'completed':sum(r['result']['status']=='COMPLETE' for r in results),
                'wall_s':monotonic()-started,'parent_cpu_s':process_time()-cpu,
                'slots':slots,'results':results},indent=2,sort_keys=True,default=str)+'\n'
            temp=evidence.with_suffix('.tmp')
            temp.write_text(payload)
            temp.replace(evidence)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures={pool.submit(evaluate,r):r for r in remaining}
            for f in as_completed(futures):
                r=f.result();results.append(r);write()
                print('REPLAY',len(results),r['slot'],r['item_id'],r['result']['status'],r['result'].get('mean_s_per_mob'),flush=True)
        write()
    return json.loads(evidence.read_text())

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--max-jobs',type=int,default=60);p.add_argument('--workers',type=int,default=2);p.add_argument('--timeout',type=float,default=23.)
    a=p.parse_args();r=run(max_jobs=a.max_jobs,workers=a.workers,timeout_s=a.timeout)
    print(json.dumps({'tested':r['tested'],'completed':r['completed'],'wall_s':r['wall_s'],'baseline':r['baseline']['mean_s_per_mob']}))
